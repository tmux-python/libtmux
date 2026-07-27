"""Classic engine against a real tmux server, and parity with mock.

These use the libtmux pytest fixtures (a live tmux server), so they exercise the
classic :class:`~libtmux.experimental.engines.subprocess.SubprocessEngine` path
end to end and assert it returns the *same typed result shape* the mock
engine does.
"""

from __future__ import annotations

import typing as t

from libtmux.experimental.engines import MockEngine, SubprocessEngine
from libtmux.experimental.ops import (
    CapturePane,
    SelectLayout,
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


def test_classic_split_creates_real_pane(session: Session) -> None:
    """A classic split returns a typed result whose new pane really exists."""
    server = session.server
    window = session.active_window
    assert window.window_id is not None
    engine = SubprocessEngine.for_server(server)

    result = run(SplitWindow(target=WindowId(window.window_id)), engine)

    assert isinstance(result, SplitWindowResult)
    assert result.ok
    assert result.new_pane_id is not None
    assert result.new_pane_id.startswith("%")
    assert server.panes.get(pane_id=result.new_pane_id) is not None


def test_classic_send_keys_and_select_layout(session: Session) -> None:
    """Classic send-keys and select-layout return successful typed results."""
    server = session.server
    pane = session.active_pane
    window = session.active_window
    assert pane is not None
    assert pane.pane_id is not None
    assert window.window_id is not None
    engine = SubprocessEngine.for_server(server)

    sent = run(SendKeys(target=PaneId(pane.pane_id), keys="echo hi"), engine)
    assert type(sent) is AckResult
    assert sent.ok

    laid_out = run(
        SelectLayout(target=WindowId(window.window_id), layout="even-horizontal"),
        engine,
    )
    assert laid_out.ok


def test_classic_capture_returns_lines(session: Session) -> None:
    """Classic capture-pane returns a typed result carrying line data."""
    server = session.server
    pane = session.active_pane
    assert pane is not None
    assert pane.pane_id is not None
    engine = SubprocessEngine.for_server(server)

    result = run(CapturePane(target=PaneId(pane.pane_id)), engine)

    assert isinstance(result, CapturePaneResult)
    assert result.ok
    assert isinstance(result.lines, tuple)


def test_classic_mock_parity(session: Session) -> None:
    """Classic and mock engines agree on result type and argv (not payload)."""
    server = session.server
    window = session.active_window
    assert window.window_id is not None
    operation = SplitWindow(target=WindowId(window.window_id))

    classic = run(operation, SubprocessEngine.for_server(server))
    mock = run(operation, MockEngine())

    assert type(classic) is type(mock) is SplitWindowResult
    assert classic.argv == mock.argv == operation.render()
    assert classic.ok and mock.ok
