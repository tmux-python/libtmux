"""Tests for the object matrix (scope x mode) over the shared spine."""

from __future__ import annotations

import asyncio
import typing as t

from libtmux.experimental.engines import AsyncMockEngine, MockEngine
from libtmux.experimental.objects import (
    AsyncPane,
    AsyncWindow,
    EagerPane,
    EagerServer,
    EagerWindow,
    LazyWindow,
)
from libtmux.experimental.ops import LazyPlan
from libtmux.experimental.ops._types import WindowId

if t.TYPE_CHECKING:
    from libtmux.session import Session


def test_eager_full_navigation_offline() -> None:
    """Eager Server->Session->Window->Pane navigation via the mock engine."""
    server = EagerServer(MockEngine())
    session = server.new_session(name="work")
    assert session.session_id == "$1"
    window = session.new_window(name="build")
    assert window.window_id == "@1"
    pane = window.split(horizontal=True)
    assert isinstance(pane, EagerPane)
    assert pane.pane_id == "%1"


def test_eager_window_methods() -> None:
    """EagerWindow rename/select_layout/kill return successful results."""
    window = EagerWindow(MockEngine(), "@1")
    assert window.rename("x").ok
    assert window.select_layout("tiled").ok
    assert window.kill().ok


def test_lazy_window_records_and_executes() -> None:
    """LazyWindow records ops and resolves the new pane on execute."""
    plan = LazyPlan()
    window = LazyWindow(plan, WindowId("@1"))
    window.split()
    window.rename("build")
    assert len(plan) == 2

    outcome = plan.execute(MockEngine())
    assert outcome.ok
    assert outcome.results[0].created_id == "%1"


def test_async_window_and_pane() -> None:
    """Async objects mirror the eager ones via await."""

    async def main() -> tuple[str, bool, bool]:
        window = AsyncWindow(AsyncMockEngine(), "@1")
        pane = await window.split()
        assert isinstance(pane, AsyncPane)
        sent = await pane.send_keys("echo hi", enter=True)
        laid_out = await window.select_layout("tiled")  # parity with eager/lazy
        return pane.pane_id, sent.ok, laid_out.ok

    pane_id, ok, laid_out = asyncio.run(main())
    assert pane_id == "%1"
    assert ok
    assert laid_out


def test_eager_navigation_live(session: Session) -> None:
    """Eager object builds a real session/window/pane against tmux, then cleans up."""
    server = session.server
    server_obj = EagerServer.for_server(server)

    created = server_obj.new_session(name="object-matrix-test")
    try:
        assert created.session_id.startswith("$")
        assert server.sessions.get(session_id=created.session_id) is not None

        window = created.new_window(name="built")
        assert window.window_id.startswith("@")
        assert server.windows.get(window_id=window.window_id) is not None

        pane = window.split(horizontal=True)
        assert pane.pane_id.startswith("%")
        assert server.panes.get(pane_id=pane.pane_id) is not None
    finally:
        created.kill()
