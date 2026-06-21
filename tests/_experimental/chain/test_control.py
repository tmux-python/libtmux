"""Tests for the experimental chain control-mode runner."""

from __future__ import annotations

import typing as t

import pytest

from libtmux._experimental.chain.control import (
    ControlModeBlock,
    ControlModeParser,
    ControlModeRunner,
)
from libtmux._experimental.chain.ir import CommandCall

if t.TYPE_CHECKING:
    from libtmux.session import Session


class ParserCase(t.NamedTuple):
    """A control-mode wire payload and expected blocks."""

    test_id: str
    wire: bytes
    expected: tuple[ControlModeBlock, ...]


PARSER_CASES = (
    ParserCase(
        test_id="success-block",
        wire=b"%begin 1 7 1\nhello\n%end 1 7 1\n",
        expected=(
            ControlModeBlock(
                number=7,
                flags=1,
                is_error=False,
                body=(b"hello",),
            ),
        ),
    ),
    ParserCase(
        test_id="error-block",
        wire=b"%begin 1 8 1\nbad command\n%error 1 8 1\n",
        expected=(
            ControlModeBlock(
                number=8,
                flags=1,
                is_error=True,
                body=(b"bad command",),
            ),
        ),
    ),
    ParserCase(
        test_id="pane-id-output",
        wire=b"%begin 1 9 1\n%42\n%end 1 9 1\n",
        expected=(
            ControlModeBlock(
                number=9,
                flags=1,
                is_error=False,
                body=(b"%42",),
            ),
        ),
    ),
)


@pytest.mark.parametrize(
    "case",
    PARSER_CASES,
    ids=[case.test_id for case in PARSER_CASES],
)
def test_control_mode_parser_emits_blocks(case: ParserCase) -> None:
    """The parser preserves block bodies and error status."""
    parser = ControlModeParser()

    parser.feed(case.wire)

    assert tuple(parser.blocks()) == case.expected


def test_control_mode_runner_empty_batch_does_not_spawn(session: Session) -> None:
    """An empty control-mode batch is a no-op."""
    runner = ControlModeRunner(session.server)
    try:
        assert runner.run_argvs([]) == []
        assert runner._proc is None
    finally:
        runner.close()


def test_control_mode_runner_batch_returns_per_command_stdout(
    session: Session,
) -> None:
    """A control-mode batch returns one output result per command."""
    with ControlModeRunner(session.server) as runner:
        results = runner.run_argvs(
            [
                ("display-message", "-p", "first"),
                ("display-message", "-p", "second"),
            ],
        )

    assert [result.returncode for result in results] == [0, 0]
    assert [result.stdout for result in results] == [["first"], ["second"]]
    assert [result.stderr for result in results] == [[], []]


def test_control_mode_runner_chain_returns_per_call_stdout(
    session: Session,
) -> None:
    """A ``CommandChain`` can run over control mode without merged output."""
    chain = CommandCall("display-message", ("-p", "left")).then(
        CommandCall("display-message", ("-p", "right")),
    )

    with ControlModeRunner(session.server) as runner:
        results = runner.run_chain(chain)

    assert [result.stdout for result in results] == [["left"], ["right"]]


def test_control_mode_runner_mid_batch_error_keeps_later_results(
    session: Session,
) -> None:
    """A bad command in a control-mode batch does not consume later results."""
    with ControlModeRunner(session.server) as runner:
        before, bad, after = runner.run_argvs(
            [
                ("display-message", "-p", "before"),
                ("no-such-command",),
                ("display-message", "-p", "after"),
            ],
        )

    assert before.returncode == 0
    assert before.stdout == ["before"]
    assert bad.returncode == 1
    assert bad.stdout == []
    assert bad.stderr
    assert after.returncode == 0
    assert after.stdout == ["after"]
