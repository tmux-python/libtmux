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
from libtmux.experimental.engines.base import CommandSeparator
from libtmux.experimental.ops import (
    BatchingPlanner,
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
    r"""An ``%output`` line exposes decoded bytes and keeps raw wire text."""
    notif = ControlNotification.parse(b"%output %1 hello\\012world\\134")
    assert notif.kind == "output"
    assert notif.args == ("%1", r"hello\012world\134")
    assert notif.pane_id == "%1"
    assert notif.payload == b"hello\nworld\\"
    assert notif.raw == r"%output %1 hello\012world\134"
    assert notif.raw_bytes == b"%output %1 hello\\012world\\134"


def test_notification_parse_requires_three_octal_digits() -> None:
    r"""Short octal-looking text stays literal; tmux frames exactly three."""
    notif = ControlNotification.parse(b"%output %1 \\1 \\12 \\123")
    assert notif.payload == b"\\1 \\12 S"


def test_notification_parse_extended_output_payload() -> None:
    r"""``%extended-output`` skips metadata and decodes its pane bytes."""
    notif = ControlNotification.parse(b"%extended-output %2 17 future : a\\011b")
    assert notif.kind == "extended-output"
    assert notif.pane_id == "%2"
    assert notif.payload == b"a\tb"
    assert notif.raw == r"%extended-output %2 17 future : a\011b"


def test_notification_parse_preserves_non_utf8_wire_bytes() -> None:
    r"""Raw diagnostics and decoded payloads retain bytes tmux passes through."""
    wire = b"%output %3 \xff\\033"
    notif = ControlNotification.parse(wire)
    assert notif.raw_bytes == wire
    assert notif.payload == b"\xff\x1b"


def test_notification_parse_line_without_percent() -> None:
    """A line lacking the ``%`` prefix still parses to a kind and args."""
    notif = ControlNotification.parse(b"window-renamed @1 new")
    assert notif.kind == "window-renamed"
    assert notif.args == ("@1", "new")
    assert notif.pane_id is None
    assert notif.payload is None


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


def test_async_control_batch_continues_after_failure(session: Session) -> None:
    """Three pipelined requests retain success, failure, success attribution."""
    server = session.server
    window_id = session.active_window.window_id
    assert window_id is not None
    plan = LazyPlan()
    plan.add(RenameWindow(target=WindowId(window_id), name="first"))
    plan.add(RenameWindow(target=WindowId("@999999"), name="missing"))
    plan.add(RenameWindow(target=WindowId(window_id), name="continued"))

    async def main() -> PlanResult:
        async with AsyncControlModeEngine.for_server(server) as engine:
            return await plan.aexecute(engine, planner=BatchingPlanner())

    outcome = asyncio.run(main())
    assert [result.status for result in outcome.results] == [
        "complete",
        "failed",
        "complete",
    ]
    renamed = server.windows.get(window_id=window_id)
    assert renamed is not None
    assert renamed.window_name == "continued"


def test_async_control_correlates_semicolon_command_group(session: Session) -> None:
    """One intentional command group waits for both control-mode blocks."""
    server = session.server
    window_id = session.active_window.window_id
    assert window_id is not None
    request = CommandRequest(
        args=(
            "rename-window",
            "-t",
            window_id,
            "first",
            CommandSeparator(";"),
            "rename-window",
            "-t",
            window_id,
            "grouped",
        ),
    )

    async def main() -> CommandResult:
        async with AsyncControlModeEngine.for_server(server) as engine:
            return await engine.run(request)

    result = asyncio.run(main())
    assert result.returncode == 0
    renamed = server.windows.get(window_id=window_id)
    assert renamed is not None
    assert renamed.window_name == "grouped"


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
