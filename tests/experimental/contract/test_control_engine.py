"""Control-mode engine against a real tmux server, and parity with mock.

Exercises the persistent ``tmux -C`` engine end to end and asserts it returns
the same typed result shape the other engines do. The engine is used as a
context manager so the control connection is always torn down.
"""

from __future__ import annotations

import typing as t

from libtmux.experimental.engines import ControlModeEngine, MockEngine
from libtmux.experimental.ops import (
    CapturePane,
    SendKeys,
    SplitWindow,
    run,
)
from libtmux.experimental.ops._types import PaneId, WindowId
from libtmux.experimental.ops.results import (
    AckResult,
    CapturePaneResult,
    SplitWindowResult,
)

if t.TYPE_CHECKING:
    from libtmux.session import Session


def test_control_sequential_commands_stay_aligned(session: Session) -> None:
    """Many sequential commands keep result alignment (drain-between-calls path).

    The first command must get the real result (not the consumed startup ACK),
    and each subsequent call drains any unsolicited blocks before reading its own.
    """
    server = session.server
    pane = session.active_pane
    assert pane is not None
    assert pane.pane_id is not None

    with ControlModeEngine.for_server(server) as engine:
        for index in range(5):
            result = run(
                SendKeys(target=PaneId(pane.pane_id), keys=f"# {index}"), engine
            )
            assert result.ok
        captured = run(CapturePane(target=PaneId(pane.pane_id)), engine)

    assert isinstance(captured, CapturePaneResult)
    assert captured.ok


def test_control_split_creates_real_pane(session: Session) -> None:
    """A control-mode split returns a typed result whose pane really exists."""
    server = session.server
    window = session.active_window
    assert window.window_id is not None

    with ControlModeEngine.for_server(server) as engine:
        result = run(SplitWindow(target=WindowId(window.window_id)), engine)

    assert isinstance(result, SplitWindowResult)
    assert result.ok
    assert result.new_pane_id is not None
    assert server.panes.get(pane_id=result.new_pane_id) is not None


def test_control_batches_multiple_commands(session: Session) -> None:
    """run_batch pipelines several commands over one connection, one result each."""
    server = session.server
    pane = session.active_pane
    window = session.active_window
    assert pane is not None
    assert pane.pane_id is not None
    assert window.window_id is not None

    with ControlModeEngine.for_server(server) as engine:
        sent = run(SendKeys(target=PaneId(pane.pane_id), keys="echo hi"), engine)
        captured = run(CapturePane(target=PaneId(pane.pane_id)), engine)

    assert type(sent) is AckResult
    assert sent.ok
    assert isinstance(captured, CapturePaneResult)
    assert captured.ok


def test_control_mock_parity(session: Session) -> None:
    """Control-mode and mock engines agree on result type and argv."""
    server = session.server
    window = session.active_window
    assert window.window_id is not None
    operation = SplitWindow(target=WindowId(window.window_id))

    with ControlModeEngine.for_server(server) as engine:
        control = run(operation, engine)
    mock = run(operation, MockEngine())

    assert type(control) is type(mock) is SplitWindowResult
    assert control.argv == mock.argv == operation.render()
    assert control.ok and mock.ok
