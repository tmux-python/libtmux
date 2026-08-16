"""Async control-mode engine against a real tmux server.

Drives the persistent async ``tmux -C`` engine end to end via :func:`asyncio.run`
and asserts it returns the same typed result the other engines do, plus that its
notification stream works.
"""

from __future__ import annotations

import asyncio
import typing as t

from libtmux.experimental.engines import (
    AsyncControlModeEngine,
    AsyncMockEngine,
    CommandRequest,
    ControlNotification,
)
from libtmux.experimental.ops import (
    FoldingPlanner,
    LazyPlan,
    RenameWindow,
    SplitWindow,
    arun,
)
from libtmux.experimental.ops._types import WindowId
from libtmux.experimental.ops.results import SplitWindowResult

if t.TYPE_CHECKING:
    from libtmux.experimental.engines import CommandResult
    from libtmux.experimental.ops.plan import PlanResult
    from libtmux.experimental.ops.results import AckResult
    from libtmux.server import Server
    from libtmux.session import Session


def test_notification_parse() -> None:
    """A raw notification line parses into a typed notification (no tmux)."""
    notif = ControlNotification.parse(b"%window-add @3")
    assert notif.kind == "window-add"
    assert notif.args == ("@3",)


def test_notification_parse_output_keeps_payload() -> None:
    """An ``%output`` line keeps the pane id and the whole payload as args."""
    notif = ControlNotification.parse(b"%output %1 hello world")
    assert notif.kind == "output"
    assert notif.args == ("%1", "hello", "world")
    assert notif.raw == "%output %1 hello world"


def test_notification_parse_line_without_percent() -> None:
    """A line lacking the ``%`` prefix still parses to a kind and args."""
    notif = ControlNotification.parse(b"window-renamed @1 new")
    assert notif.kind == "window-renamed"
    assert notif.args == ("@1", "new")


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


def test_async_control_mock_parity(session: Session) -> None:
    """Async control-mode and mock engines agree on result type and argv."""
    server = session.server
    window_id = session.active_window.window_id
    assert window_id is not None
    operation = SplitWindow(target=WindowId(window_id))

    async def main() -> SplitWindowResult:
        async with AsyncControlModeEngine.for_server(server) as engine:
            return await arun(operation, engine)

    control = asyncio.run(main())
    mock = asyncio.run(arun(operation, AsyncMockEngine()))
    assert type(control) is type(mock) is SplitWindowResult
    assert control.argv == mock.argv == operation.render()


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


def test_async_control_empty_batch_short_circuits() -> None:
    """``run_batch([])`` returns ``[]`` without ever spawning a tmux process."""
    engine = AsyncControlModeEngine()
    assert asyncio.run(engine.run_batch([])) == []


def test_async_control_aclose_without_start_is_safe() -> None:
    """Closing an engine that was never started is a no-op, not an error."""
    engine = AsyncControlModeEngine()
    asyncio.run(engine.aclose())
    assert engine.dropped_notifications == 0


def test_async_control_for_server_carries_socket(server: Server) -> None:
    """``for_server`` threads the live server's socket into the connection flags."""
    engine = AsyncControlModeEngine.for_server(server)
    assert any(arg.startswith(("-L", "-S")) for arg in engine.server_args)
    assert engine.tmux_bin == server.tmux_bin


def test_async_control_run_batch_pipelines_one_call(session: Session) -> None:
    """One ``run_batch`` call dispatches several requests, one result each, in order."""
    server = session.server
    window_id = session.active_window.window_id
    assert window_id is not None
    request = CommandRequest.from_args(
        *SplitWindow(target=WindowId(window_id)).render()
    )

    async def main() -> list[CommandResult]:
        async with AsyncControlModeEngine.for_server(server) as engine:
            return await engine.run_batch([request, request])

    results = asyncio.run(main())
    assert len(results) == 2
    assert all(result.returncode == 0 for result in results)
    # Each split captured a distinct new pane id on its own block.
    assert results[0].stdout and results[1].stdout
    assert results[0].stdout[0] != results[1].stdout[0]


def test_async_control_folds_chain_over_one_dispatch(session: Session) -> None:
    """A folded ``;`` chain dispatches as one multi-block command; each op completes.

    The other tests dispatch only single-command operations, so the reader's
    "wait for ``expected`` blocks" correlation (``command_count`` > 1) is never
    exercised. A ``FoldingPlanner`` chain of two renames sends one ``a ; b`` line
    that tmux answers with two blocks, proving block accumulation and per-op
    attribution over the async connection.
    """
    server = session.server
    window_id = session.active_window.window_id
    assert window_id is not None
    plan = LazyPlan()
    plan.add_chain(
        RenameWindow(target=WindowId(window_id), name="first")
        >> RenameWindow(target=WindowId(window_id), name="folded"),
    )

    async def main() -> PlanResult:
        async with AsyncControlModeEngine.for_server(server) as engine:
            return await plan.aexecute(engine, planner=FoldingPlanner())

    outcome = asyncio.run(main())
    assert outcome.ok
    assert [result.status for result in outcome.results] == ["complete", "complete"]
    # The last rename in the folded line won, proving both sub-commands ran.
    renamed = server.windows.get(window_id=window_id)
    assert renamed is not None
    assert renamed.window_name == "folded"


def test_async_control_failure_is_data_not_raised(session: Session) -> None:
    """A tmux-rejected command yields a failed result; the engine does not raise."""
    server = session.server

    async def main() -> AckResult:
        async with AsyncControlModeEngine.for_server(server) as engine:
            return await arun(
                RenameWindow(target=WindowId("@999999"), name="nope"),
                engine,
            )

    result = asyncio.run(main())
    assert result.ok is False
    assert result.returncode != 0
