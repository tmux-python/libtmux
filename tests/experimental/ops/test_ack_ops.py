"""Tests for no-output operations and the AckResult type."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.engines import MockEngine
from libtmux.experimental.ops import (
    KillPane,
    KillWindow,
    RenameWindow,
    SelectLayout,
    SendKeys,
    run,
)
from libtmux.experimental.ops._types import PaneId, WindowId
from libtmux.experimental.ops.exc import TmuxCommandError
from libtmux.experimental.ops.results import AckResult

if t.TYPE_CHECKING:
    from libtmux.experimental.ops.operation import Operation


@pytest.mark.parametrize(
    ("operation", "expected_argv"),
    [
        pytest.param(
            RenameWindow(target=WindowId("@1"), name="build"),
            ("rename-window", "-t", "@1", "build"),
            id="rename_window",
        ),
        pytest.param(
            KillWindow(target=WindowId("@1")),
            ("kill-window", "-t", "@1"),
            id="kill_window",
        ),
        pytest.param(
            KillPane(target=PaneId("%1")),
            ("kill-pane", "-t", "%1"),
            id="kill_pane",
        ),
        pytest.param(
            SendKeys(target=PaneId("%1"), keys="x"),
            ("send-keys", "-t", "%1", "x"),
            id="send_keys",
        ),
        pytest.param(
            SelectLayout(target=WindowId("@1"), layout="tiled"),
            ("select-layout", "-t", "@1", "tiled"),
            id="select_layout",
        ),
    ],
)
def test_no_output_ops_return_ack(
    operation: Operation[AckResult],
    expected_argv: tuple[str, ...],
) -> None:
    """No-output operations render correctly and yield an AckResult."""
    result = run(operation, MockEngine())
    assert type(result) is AckResult
    assert result.argv == expected_argv
    assert result.ok


def test_ack_success_has_no_payload() -> None:
    """A successful ack carries only status -- no extra fields beyond the base."""
    result = RenameWindow(target=WindowId("@1"), name="x").build_result(returncode=0)
    assert isinstance(result, AckResult)
    assert result.ok
    assert result.stdout == ()


def test_ack_failure_raises_on_demand() -> None:
    """A no-output command can still fail; raise_for_status surfaces it."""
    result = KillWindow(target=WindowId("@9")).build_result(
        returncode=1,
        stderr=("can't find window @9",),
    )
    assert result.failed
    with pytest.raises(TmuxCommandError):
        result.raise_for_status()


def test_destructive_safety_metadata() -> None:
    """Kill operations are tagged destructive in the registry/catalog."""
    from libtmux.experimental.ops import catalog

    safety = {entry.kind: entry.safety for entry in catalog()}
    assert safety["kill_window"] == "destructive"
    assert safety["kill_pane"] == "destructive"
    assert safety["rename_window"] == "mutating"


class SendKeysGuardCase(t.NamedTuple):
    """A literal/enter combination and whether SendKeys rejects it."""

    test_id: str
    literal: bool
    enter: bool
    raises: bool


SEND_KEYS_GUARD_CASES = (
    SendKeysGuardCase("plain", literal=False, enter=False, raises=False),
    SendKeysGuardCase("enter_only", literal=False, enter=True, raises=False),
    SendKeysGuardCase("literal_only", literal=True, enter=False, raises=False),
    SendKeysGuardCase("literal_and_enter", literal=True, enter=True, raises=True),
)


@pytest.mark.parametrize(
    list(SendKeysGuardCase._fields),
    SEND_KEYS_GUARD_CASES,
    ids=[c.test_id for c in SEND_KEYS_GUARD_CASES],
)
def test_send_keys_literal_enter_guard(
    test_id: str,
    literal: bool,
    enter: bool,
    raises: bool,
) -> None:
    """literal=True with enter=True is rejected (tmux -l would type 'Enter')."""
    if raises:
        with pytest.raises(ValueError, match="literal"):
            SendKeys(target=PaneId("%1"), keys="x", literal=literal, enter=enter)
    else:
        op = SendKeys(target=PaneId("%1"), keys="x", literal=literal, enter=enter)
        assert op.render()[0] == "send-keys"
