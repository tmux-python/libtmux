"""Async control-mode engine against a real tmux server.

Drives the persistent async ``tmux -C`` engine end to end via :func:`asyncio.run`
and asserts it returns the same typed result the other engines do, plus that its
notification stream works.
"""

from __future__ import annotations

import asyncio
import typing as t

from libtmux.experimental.engines import (
    AsyncConcreteEngine,
    AsyncControlModeEngine,
    ControlNotification,
)
from libtmux.experimental.ops import SplitWindow, arun
from libtmux.experimental.ops._types import WindowId
from libtmux.experimental.ops.results import SplitWindowResult

if t.TYPE_CHECKING:
    from libtmux.session import Session


def test_notification_parse() -> None:
    """A raw notification line parses into a typed notification (no tmux)."""
    notif = ControlNotification.parse(b"%window-add @3")
    assert notif.kind == "window-add"
    assert notif.args == ("@3",)


def test_async_control_split_creates_real_pane(session: Session) -> None:
    """An async control-mode split returns a typed result; the pane exists."""
    server = session.server
    window_id = session.active_window.window_id
    assert window_id is not None

    async def main() -> SplitWindowResult:
        async with AsyncControlModeEngine.for_server(server) as engine:
            return await arun(SplitWindow(target=WindowId(window_id)), engine)

    result = asyncio.run(main())
    assert result.ok
    assert result.new_pane_id is not None
    assert server.panes.get(pane_id=result.new_pane_id) is not None


def test_async_control_batches_pipelined(session: Session) -> None:
    """run_batch pipelines several splits over one connection, one result each."""
    server = session.server
    window_id = session.active_window.window_id
    assert window_id is not None

    async def main() -> tuple[str | None, str | None]:
        async with AsyncControlModeEngine.for_server(server) as engine:
            r1 = await arun(SplitWindow(target=WindowId(window_id)), engine)
            r2 = await arun(SplitWindow(target=WindowId(window_id)), engine)
            return r1.new_pane_id, r2.new_pane_id

    first, second = asyncio.run(main())
    assert first is not None
    assert second is not None
    assert first != second


def test_async_control_concrete_parity(session: Session) -> None:
    """Async control-mode and concrete engines agree on result type and argv."""
    server = session.server
    window_id = session.active_window.window_id
    assert window_id is not None
    operation = SplitWindow(target=WindowId(window_id))

    async def main() -> SplitWindowResult:
        async with AsyncControlModeEngine.for_server(server) as engine:
            return await arun(operation, engine)

    control = asyncio.run(main())
    concrete = asyncio.run(arun(operation, AsyncConcreteEngine()))
    assert type(control) is type(concrete) is SplitWindowResult
    assert control.argv == concrete.argv == operation.render()


def test_async_control_event_stream(session: Session) -> None:
    """A command that changes server state surfaces a notification on the stream."""
    server = session.server
    window_id = session.active_window.window_id
    assert window_id is not None

    async def main() -> ControlNotification:
        async with AsyncControlModeEngine.for_server(server) as engine:
            events = engine.subscribe()
            await arun(SplitWindow(target=WindowId(window_id)), engine)
            return await asyncio.wait_for(anext(events), timeout=10.0)

    notif = asyncio.run(main())
    assert notif.kind
    assert notif.raw.startswith("%")
