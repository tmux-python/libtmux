"""The live event stream tools -- push, pull, and the registration gate.

Driven offline against a fake engine that yields a fixed notification sequence,
so the push/pull mechanics are exercised without a real tmux ``-C`` connection.
"""

from __future__ import annotations

import asyncio
import contextlib
import typing as t

import pytest

from libtmux.experimental.engines.async_control_mode import ControlNotification
from libtmux.experimental.engines.base import CommandResult

fastmcp = pytest.importorskip("fastmcp")

if t.TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from libtmux.experimental.engines.base import CommandRequest


class FakeStreamEngine:
    """An async engine that replays a fixed notification stream."""

    def __init__(self, raw: tuple[bytes, ...]) -> None:
        self._raw = raw

    async def run(self, request: CommandRequest) -> CommandResult:
        """Acknowledge any command."""
        return CommandResult(cmd=("tmux", *request.args), returncode=0)

    async def run_batch(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Acknowledge a batch of commands."""
        return [await self.run(r) for r in requests]

    async def subscribe(self) -> AsyncIterator[ControlNotification]:
        """Yield the fixed notification sequence."""
        for raw in self._raw:
            yield ControlNotification.parse(raw)


_STREAM = (b"%window-add @3", b"%output %1 hi", b"%window-close @3")
_MON_STREAM = (b"%output %1 a  b", b"%output %1 c", b"%window-add @9")


class _BlockingStreamEngine:
    """An async engine whose ``subscribe()`` never ends (a live stream)."""

    _attached_session: str | None = None

    async def run(self, request: CommandRequest) -> CommandResult:
        """Acknowledge any command."""
        return CommandResult(cmd=("tmux", *request.args), returncode=0)

    async def run_batch(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Acknowledge a batch of commands."""
        return [await self.run(r) for r in requests]

    async def subscribe(self) -> AsyncIterator[ControlNotification]:
        """Block forever (a never-ending stream)."""
        await asyncio.Event().wait()
        yield ControlNotification.parse(b"%unreachable")  # present so this is a gen


class _RestartCase(t.NamedTuple):
    """An EventRing drain state and whether _ensure_started should restart it."""

    test_id: str
    stream_ends: bool  # True: prior drain completes; False: still running
    expect_restart: bool


_RESTART_CASES = (
    _RestartCase("done_drain_restarts", stream_ends=True, expect_restart=True),
    _RestartCase("running_drain_kept", stream_ends=False, expect_restart=False),
)


@pytest.mark.parametrize(
    list(_RestartCase._fields),
    _RESTART_CASES,
    ids=[c.test_id for c in _RESTART_CASES],
)
def test_event_ring_restarts_completed_drain(
    test_id: str,
    stream_ends: bool,
    expect_restart: bool,
) -> None:
    """_ensure_started restarts a *completed* drain (post-reconnect), not a live one."""
    from libtmux.experimental.mcp.events import _EventRing

    async def main() -> bool:
        engine = FakeStreamEngine(()) if stream_ends else _BlockingStreamEngine()
        ring = _EventRing(engine)
        ring.since(0)  # starts the drain task
        first = ring._task
        assert first is not None
        if stream_ends:
            await first  # the empty stream ends, so the drain completes
            assert first.done()
        ring.since(0)  # _ensure_started: restart only if the prior task is done
        second = ring._task
        restarted = second is not first
        for task in {first, second}:
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        return restarted

    assert asyncio.run(main()) is expect_restart


class _RaisingStreamEngine:
    """An async engine whose ``subscribe()`` raises, so the drain records it."""

    _attached_session: str | None = None

    async def run(self, request: CommandRequest) -> CommandResult:
        """Acknowledge any command."""
        return CommandResult(cmd=("tmux", *request.args), returncode=0)

    async def run_batch(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Acknowledge a batch of commands."""
        return [await self.run(r) for r in requests]

    async def subscribe(self) -> AsyncIterator[ControlNotification]:
        """Fail on first iteration (a permanently dead stream)."""
        msg = "engine permanently dead"
        raise RuntimeError(msg)
        yield ControlNotification.parse(b"%unreachable")  # marks this a generator


class _DrainErrorCase(t.NamedTuple):
    """Whether a drain errored and whether since() must surface an ``error`` key."""

    test_id: str
    raises: bool  # True: the drain fails; False: it ends cleanly
    expect_error_key: bool


_DRAIN_ERROR_CASES = (
    _DrainErrorCase("persistent_error_surfaces", raises=True, expect_error_key=True),
    _DrainErrorCase("clean_drain_no_error", raises=False, expect_error_key=False),
)


@pytest.mark.parametrize(
    list(_DrainErrorCase._fields),
    _DRAIN_ERROR_CASES,
    ids=[c.test_id for c in _DRAIN_ERROR_CASES],
)
def test_since_surfaces_persistent_drain_error(
    test_id: str,
    raises: bool,
    expect_error_key: bool,
) -> None:
    """A failed drain must surface via since(), not be masked by the restart.

    Regression: clearing the error inside _ensure_started wiped it before since()
    read it, so a permanently dead stream reported as empty-but-healthy forever.
    """
    from libtmux.experimental.mcp.events import _EventRing

    async def main() -> bool:
        engine = _RaisingStreamEngine() if raises else FakeStreamEngine(())
        ring = _EventRing(engine)
        ring.since(0)  # start the first drain
        if ring._task is not None:
            await ring._task  # let it run to completion (error or clean end)
        out = ring.since(0)  # restarts the drain; a prior error must still show
        if ring._task is not None and not ring._task.done():
            ring._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await ring._task
        return "error" in out

    assert asyncio.run(main()) is expect_error_key


class InstrumentedEngine:
    """A fake stream engine that records commands and scripts a few responses.

    Records every ``run`` argv in ``calls`` (so attach idempotence is assertable),
    exposes a settable ``dropped_notifications`` counter, can inject an
    ``attach-session`` failure, and can return a canned ``display-message`` line
    for the done-heuristics format.
    """

    def __init__(
        self,
        raw: tuple[bytes, ...] = (),
        *,
        attach_returncode: int = 0,
        done_line: str | None = None,
        dropped_after: int = 0,
    ) -> None:
        self._raw = raw
        self.calls: list[tuple[str, ...]] = []
        self.dropped_notifications = 0
        self._attached_session: str | None = None
        self._attach_returncode = attach_returncode
        self._done_line = done_line
        self._dropped_after = dropped_after

    async def run(self, request: CommandRequest) -> CommandResult:
        """Record the command and return a scripted result."""
        args = tuple(request.args)
        self.calls.append(args)
        if args and args[0] == "attach-session":
            stderr = () if self._attach_returncode == 0 else ("can't find session",)
            return CommandResult(
                cmd=("tmux", *args),
                returncode=self._attach_returncode,
                stderr=stderr,
            )
        if args and args[0] == "display-message":
            fmt = args[-1]
            if "pane_dead" in fmt and self._done_line is not None:
                return CommandResult(
                    cmd=("tmux", *args),
                    returncode=0,
                    stdout=(self._done_line,),
                )
            if "session_id" in fmt:
                return CommandResult(cmd=("tmux", *args), returncode=0, stdout=("$1",))
        return CommandResult(cmd=("tmux", *args), returncode=0)

    async def run_batch(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Acknowledge a batch of commands."""
        return [await self.run(r) for r in requests]

    async def subscribe(self) -> AsyncIterator[ControlNotification]:
        """Yield the fixed notification sequence, then bump the drop counter."""
        for raw in self._raw:
            yield ControlNotification.parse(raw)
        self.dropped_notifications += self._dropped_after


def _tool_names(server: t.Any) -> set[str]:
    """Return the visible tool names of *server* (via an in-process client)."""

    async def main() -> set[str]:
        async with fastmcp.Client(server) as client:
            return {tool.name for tool in await client.list_tools()}

    return asyncio.run(main())


def test_push_collects_filtered_events() -> None:
    """watch_events streams and returns only the requested notification kinds."""
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server

    server = build_async_server(
        FakeStreamEngine(_STREAM),
        events="push",
        include_operations=False,
        include_plan_tools=False,
    )

    async def main() -> dict[str, t.Any]:
        async with fastmcp.Client(server) as client:
            result = await client.call_tool(
                "watch_events",
                {
                    "kinds": ["window-add", "window-close"],
                    "max_events": 2,
                    "timeout": 2.0,
                },
            )
            return t.cast("dict[str, t.Any]", result.data)

    data = asyncio.run(main())
    assert data["count"] == 2
    assert [event["kind"] for event in data["events"]] == ["window-add", "window-close"]


def test_pull_buffers_events() -> None:
    """poll_events drains the background ring buffer with a cursor."""
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server

    server = build_async_server(
        FakeStreamEngine(_STREAM),
        events="pull",
        include_operations=False,
        include_plan_tools=False,
    )

    async def main() -> dict[str, t.Any]:
        async with fastmcp.Client(server) as client:
            await client.call_tool("poll_events", {"since": 0})  # start the drainer
            await asyncio.sleep(0.05)
            result = await client.call_tool("poll_events", {"since": 0})
            return t.cast("dict[str, t.Any]", result.data)

    data = asyncio.run(main())
    assert len(data["events"]) == 3
    assert data["cursor"] == 3


def test_both_registers_push_and_pull() -> None:
    """events='both' exposes both mechanisms."""
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server

    server = build_async_server(
        FakeStreamEngine(_STREAM),
        events="both",
        include_operations=False,
        include_plan_tools=False,
    )
    names = _tool_names(server)
    assert {"watch_events", "poll_events"} <= names


def test_monitor_registered_when_streaming() -> None:
    """wait_for_output is exposed whenever the engine streams, in any event mode."""
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server

    server = build_async_server(
        FakeStreamEngine(_STREAM),
        events="pull",
        include_operations=False,
        include_plan_tools=False,
    )
    assert "wait_for_output" in _tool_names(server)


def test_monitor_settles_on_stream_end() -> None:
    """wait_for_output folds per-pane output and returns when the stream ends.

    The decoded chunks preserve internal whitespace (``a  b`` + ``c`` -> ``a  bc``),
    locking out the ``" ".join`` reconstruction bug; the non-output frame is
    filtered.
    """
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server

    server = build_async_server(
        FakeStreamEngine(_MON_STREAM),
        events="push",
        include_operations=False,
        include_plan_tools=False,
    )

    async def main() -> t.Any:
        async with fastmcp.Client(server) as client:
            result = await client.call_tool("wait_for_output", {"target": "%1"})
            return result.data

    data = asyncio.run(main())
    assert data.pane_id == "%1"
    assert data.reason == "stream_end"
    assert data.captured_text == "a  bc"
    assert data.frame_count == 2
    assert data.truncated is False
    assert data.snapshot_lines == []
    # The fake's pane id is unverifiable post-settle, so liveness reads unknown.
    assert data.done.pane_dead is None


def test_monitor_snapshot_false_omits_grid() -> None:
    """snapshot=False leaves snapshot_lines None and skips the capture."""
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server

    server = build_async_server(
        InstrumentedEngine(_MON_STREAM),
        events="push",
        include_operations=False,
        include_plan_tools=False,
    )

    async def main() -> t.Any:
        async with fastmcp.Client(server) as client:
            result = await client.call_tool(
                "wait_for_output",
                {"target": "%1", "snapshot": False},
            )
            return result.data

    data = asyncio.run(main())
    assert data.snapshot_lines is None
    assert data.reason == "stream_end"


def test_monitor_reports_dropped_delta() -> None:
    """The dropped field is the engine's overflow-counter delta during the watch."""
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server

    server = build_async_server(
        InstrumentedEngine(_MON_STREAM, dropped_after=5),
        events="push",
        include_operations=False,
        include_plan_tools=False,
    )

    async def main() -> t.Any:
        async with fastmcp.Client(server) as client:
            result = await client.call_tool("wait_for_output", {"target": "%1"})
            return result.data

    data = asyncio.run(main())
    assert data.dropped == 5


def test_monitor_stream_partials_pushes_each_chunk() -> None:
    """stream_partials=True pushes each decoded chunk as an MCP log message."""
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server

    logged: list[t.Any] = []

    async def log_handler(message: t.Any) -> None:
        # ctx.info wraps the payload as {"msg": ..., "extra": ...}.
        data = message.data
        logged.append(data["msg"] if isinstance(data, dict) else data)

    server = build_async_server(
        InstrumentedEngine(_MON_STREAM),
        events="push",
        include_operations=False,
        include_plan_tools=False,
    )

    async def main() -> None:
        async with fastmcp.Client(server, log_handler=log_handler) as client:
            await client.call_tool(
                "wait_for_output",
                {"target": "%1", "stream_partials": True},
            )

    asyncio.run(main())
    assert "a  b" in logged
    assert "c" in logged


def test_ensure_attached_raises_on_failed_attach() -> None:
    """A failed attach raises and does not poison the per-engine cache."""
    from libtmux.experimental.mcp.events import _ensure_attached

    engine = InstrumentedEngine(attach_returncode=1)
    with pytest.raises(RuntimeError, match="cannot watch"):
        asyncio.run(_ensure_attached(engine, "$dead"))
    assert getattr(engine, "_attached_session", None) is None


def test_ensure_attached_is_idempotent_per_session() -> None:
    """Re-watching the same session attaches exactly once (no repeated redraw)."""
    from libtmux.experimental.mcp.events import _ensure_attached

    engine = InstrumentedEngine()

    async def main() -> None:
        await _ensure_attached(engine, "$1")
        await _ensure_attached(engine, "$1")

    asyncio.run(main())
    attaches = [c for c in engine.calls if c and c[0] == "attach-session"]
    assert len(attaches) == 1
    assert engine._attached_session == "$1"


def test_read_done_parses_display_message_fields() -> None:
    """_read_done maps the tab-joined display-message into DoneMetadata."""
    from libtmux.experimental.mcp.events import _read_done

    done_line = "%1\t1\t137\tHUP\tbash\t3\t50\t1"  # pane_id first
    engine = InstrumentedEngine(done_line=done_line)
    done = asyncio.run(_read_done(engine, "%1"))
    assert done.pane_dead is True
    assert done.pane_dead_status == 137
    assert done.pane_dead_signal == "HUP"
    assert done.pane_current_command == "bash"
    assert done.cursor_y == 3
    assert done.history_size == 50
    assert done.pane_in_mode is True


def test_subscribe_broadcasts_to_every_consumer() -> None:
    """Concurrent subscribers each receive every notification (no frame stealing).

    A regression for the competing-consumer bug: a single shared queue handed each
    item to exactly one waiter, so wait_for_output and watch_events/poll_events
    stole each other's %output and the monitor could falsely report 'settled'.
    """
    from libtmux.experimental.engines.async_control_mode import AsyncControlModeEngine

    engine = AsyncControlModeEngine()

    async def main() -> tuple[str, str]:
        stream_a, stream_b = engine.subscribe(), engine.subscribe()
        first = asyncio.ensure_future(stream_a.__anext__())
        second = asyncio.ensure_future(stream_b.__anext__())
        await asyncio.sleep(0)  # let both register their queues at the first await
        await asyncio.sleep(0)
        engine._publish(b"%window-add @3")
        notif_a, notif_b = await first, await second
        # asyncio.run finalizes the suspended generators via shutdown_asyncgens.
        return notif_a.raw, notif_b.raw

    raw_a, raw_b = asyncio.run(main())
    assert raw_a == "%window-add @3"
    assert raw_b == "%window-add @3"  # both, not split across consumers


def test_instructions_surface_wait_for_output() -> None:
    """The server instructions name the run-a-command-and-wait workflow.

    If this fails, the discoverable wording drifted -- update BOTH the instruction
    text in fastmcp_adapter.py AND these assertions intentionally.
    """
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server

    server = build_async_server(
        FakeStreamEngine(_STREAM),
        events="push",
        include_operations=False,
        include_plan_tools=False,
    )
    text = server.instructions or ""
    assert "wait_for_output" in text  # the tool by name
    assert "send_input" in text  # the workflow pair
    assert "completion" in text  # the run-a-command-and-wait intent
    assert "pytest" in text  # the long-running / test use case
    assert "sleep + capture_pane" in text  # the anti-polling steer
    assert "Settled" in text  # settled-is-not-success caveat


def test_instructions_omit_wait_for_output_without_streaming() -> None:
    """events='off' (no wait_for_output tool) drops the live-output guidance.

    The instructions must not name a tool the server did not register.
    """
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server

    server = build_async_server(
        FakeStreamEngine(_STREAM),
        events="off",
        include_operations=False,
        include_plan_tools=False,
    )
    text = server.instructions or ""
    assert "wait_for_output" not in text
    assert "watch_events" not in text


def test_wait_for_output_metadata_is_discoverable() -> None:
    """wait_for_output's description + per-param schema carry the search vocabulary.

    If this fails, the discoverable wording drifted -- update BOTH the description /
    docstring in events.py AND these assertions intentionally. The per-param
    descriptions also prove FastMCP parsed the NumPy ``Parameters`` section.
    """
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server

    server = build_async_server(
        FakeStreamEngine(_STREAM),
        events="push",
        include_operations=False,
        include_plan_tools=False,
    )

    async def main() -> t.Any:
        async with fastmcp.Client(server) as client:
            return {tool.name: tool for tool in await client.list_tools()}

    by_name = asyncio.run(main())
    tool = by_name["wait_for_output"]
    description = tool.description or ""
    assert "wait" in description
    assert "finish" in description
    assert "completion" in description
    assert "sleep + capture_pane" in description

    props = tool.inputSchema["properties"]
    for param in ("target", "settle_ms", "timeout", "max_bytes", "stream_partials"):
        assert props[param].get("description"), f"{param} missing param description"
    assert "idle" in props["settle_ms"]["description"].lower()


def test_no_event_tools_without_a_stream() -> None:
    """A non-streaming engine registers no event tools, even when asked."""
    from libtmux.experimental.engines import MockEngine
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server
    from libtmux.experimental.mcp.vocabulary._bridge import SyncToAsyncEngine

    server = build_async_server(
        SyncToAsyncEngine(MockEngine()),
        events="both",
        include_operations=False,
        include_plan_tools=False,
    )
    names = _tool_names(server)
    assert "watch_events" not in names
    assert "poll_events" not in names
    assert "wait_for_output" not in names
