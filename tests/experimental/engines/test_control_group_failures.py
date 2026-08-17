"""Control-mode group failures and guard correlation."""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.experimental.engines import AsyncControlModeEngine, ControlModeEngine
from libtmux.experimental.engines.base import CommandRequest, CommandSeparator
from libtmux.experimental.engines.control_mode import (
    ControlModeBlock,
    ControlModeError,
    ControlModeParser,
)

if t.TYPE_CHECKING:
    from libtmux.session import Session


def test_parser_preserves_guard_shaped_command_output() -> None:
    """Only the exact close tuple frames unescaped command output."""
    parser = ControlModeParser()
    body = (
        b"%begin 101 8 1",
        b"%end 101 7 1",
        b"%end 100 8 1",
        b"%end 100 7 0",
        b"%error broken guard",
    )

    parser.feed(b"%begin 100 7 1\n" + b"\n".join(body) + b"\n%end 100 7 1\n")

    assert parser.blocks()[0].body == body


def test_parser_preserves_the_matching_guard_timestamp() -> None:
    """A valid exact guard pair produces one correlated block."""
    parser = ControlModeParser()

    parser.feed(b"%begin 100 7 1\nbody\n%end 100 7 1\n")

    block = parser.blocks()[0]
    assert (block.timestamp, block.number, block.flags) == (100, 7, 1)


def test_parser_fails_closed_on_an_identical_guard_collision() -> None:
    """Two identical closes cannot be disambiguated as output plus framing."""
    parser = ControlModeParser()

    with pytest.raises(ControlModeError, match="without %begin"):
        parser.feed(b"%begin 100 7 1\n%end 100 7 1\n%end 100 7 1\n")


@pytest.mark.parametrize(
    "payload",
    [
        b"%begin broken\n",
        b"%end 100 7 1\n",
    ],
    ids=["invalid-begin", "orphan-close"],
)
def test_parser_rejects_impossible_guard_state(payload: bytes) -> None:
    """Malformed framing outside a command block poisons the parser."""
    parser = ControlModeParser()

    with pytest.raises(ControlModeError):
        parser.feed(payload)


def test_async_engine_rejects_a_solicited_block_without_a_request() -> None:
    """An impossible extra reply poisons correlation instead of being dropped."""
    engine = AsyncControlModeEngine()
    block = ControlModeBlock(
        number=7,
        flags=1,
        is_error=False,
        body=(),
        timestamp=100,
    )

    with pytest.raises(ControlModeError, match="no pending request"):
        engine._dispatch_block(block)


def _failure_then_independent(
    first_window_id: str,
    second_window_id: str,
) -> tuple[CommandRequest, CommandRequest]:
    """Build one fail-stop group followed by an independent request."""
    group = CommandRequest(
        args=(
            "rename-window",
            "-t",
            first_window_id,
            "--",
            "group-succeeded",
            CommandSeparator(";"),
            "rename-window",
            "-t",
            "@999999999",
            "--",
            "group-failed",
            CommandSeparator(";"),
            "rename-window",
            "-t",
            first_window_id,
            "--",
            "must-not-run",
        ),
    )
    independent = CommandRequest.from_args(
        "rename-window",
        "-t",
        second_window_id,
        "--",
        "independent-ran",
    )
    return group, independent


def test_sync_failed_group_does_not_consume_the_next_request(
    session: Session,
) -> None:
    """A fail-stop group's absent tail neither times out nor shifts attribution."""
    first = session.active_window
    second = session.new_window(window_name="independent-before")
    assert first.window_id is not None and second.window_id is not None
    requests = _failure_then_independent(first.window_id, second.window_id)

    with ControlModeEngine.for_server(session.server, timeout=0.5) as engine:
        results = engine.run_batch(requests)

    first.refresh()
    second.refresh()
    assert [result.returncode for result in results] == [1, 0]
    assert first.window_name == "group-succeeded"
    assert second.window_name == "independent-ran"


@pytest.mark.parametrize(
    "body",
    ["%begin 100 7 1", "%end 100 7 1", "%error broken guard"],
    ids=["begin", "end", "error"],
)
def test_sync_guard_shaped_output_is_not_protocol_framing(
    session: Session,
    body: str,
) -> None:
    """The sync engine returns raw output that resembles control guards."""
    # ``%%`` produces one literal percent on the tmux 3.2a compatibility floor;
    # newer ``display-message -l`` cannot be used by this matrix test.
    request = CommandRequest.from_args("display-message", "-p", f"%{body}")

    with ControlModeEngine.for_server(session.server) as engine:
        result = engine.run(request)

    assert result.stdout == (body,)


def test_async_failed_group_does_not_consume_the_next_request(
    session: Session,
) -> None:
    """Async FIFO correlation advances immediately on the group's ``%error``."""
    first = session.active_window
    second = session.new_window(window_name="async-independent-before")
    assert first.window_id is not None and second.window_id is not None
    requests = _failure_then_independent(first.window_id, second.window_id)

    async def run_requests() -> list[t.Any]:
        async with AsyncControlModeEngine.for_server(
            session.server,
            timeout=0.5,
        ) as engine:
            return await engine.run_batch(requests)

    results = asyncio.run(run_requests())
    first.refresh()
    second.refresh()
    assert [result.returncode for result in results] == [1, 0]
    assert first.window_name == "group-succeeded"
    assert second.window_name == "independent-ran"


@pytest.mark.parametrize(
    "body",
    ["%begin 100 7 1", "%end 100 7 1", "%error broken guard"],
    ids=["begin", "end", "error"],
)
def test_async_guard_shaped_output_is_not_protocol_framing(
    session: Session,
    body: str,
) -> None:
    """The async engine returns raw output that resembles control guards."""
    request = CommandRequest.from_args("display-message", "-p", f"%{body}")

    async def run_request() -> t.Any:
        async with AsyncControlModeEngine.for_server(session.server) as engine:
            return await engine.run(request)

    result = asyncio.run(run_request())

    assert result.stdout == (body,)
