"""Async engine against a real tmux server, and parity with the classic engine.

Uses :func:`asyncio.run` to drive :func:`arun` so the async transport is
exercised end to end without a pytest-asyncio dependency.
"""

from __future__ import annotations

import asyncio
import typing as t

from libtmux.experimental.engines import AsyncSubprocessEngine, SubprocessEngine
from libtmux.experimental.ops import SplitWindow, arun, run
from libtmux.experimental.ops._types import WindowId
from libtmux.experimental.ops.results import SplitWindowResult

if t.TYPE_CHECKING:
    from libtmux.session import Session


def test_async_split_creates_real_pane(session: Session) -> None:
    """An async split returns a typed result whose new pane really exists."""
    server = session.server
    window = session.active_window
    assert window.window_id is not None
    engine = AsyncSubprocessEngine.for_server(server)

    result = asyncio.run(arun(SplitWindow(target=WindowId(window.window_id)), engine))

    assert isinstance(result, SplitWindowResult)
    assert result.ok
    assert result.new_pane_id is not None
    assert server.panes.get(pane_id=result.new_pane_id) is not None


def test_async_sync_parity(session: Session) -> None:
    """The async and sync classic engines agree on result type and argv."""
    server = session.server
    window = session.active_window
    assert window.window_id is not None
    operation = SplitWindow(target=WindowId(window.window_id))

    sync_result = run(operation, SubprocessEngine.for_server(server))
    async_result = asyncio.run(
        arun(operation, AsyncSubprocessEngine.for_server(server)),
    )

    assert type(sync_result) is type(async_result) is SplitWindowResult
    assert sync_result.argv == async_result.argv == operation.render()
    assert sync_result.ok and async_result.ok
