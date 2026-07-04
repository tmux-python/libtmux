"""Live tmux event stream over MCP -- two interchangeable mechanisms (A/B).

A control-mode engine exposes tmux's asynchronous notifications (``%output``,
``%window-add``, ``%session-changed``, ...) as an ``async for`` stream via
``subscribe()``. FastMCP 3.x has no resource-subscription handshake and buffers a
tool's async generator into one list, so a live stream must be surfaced as
either:

- **push** -- a long-running ``watch_events`` tool that holds a ``Context`` and
  pushes each event as an MCP notification (real-time; best over streamable-http).
- **pull** -- a ``tmux://events`` resource backed by a ring buffer a background
  task fills, plus a ``poll_events`` tool; clients poll (stdio-friendly).

Which is registered is chosen by :func:`register_events` (driven by the
``LIBTMUX_MCP_EVENTS`` env var at the entrypoint). Both consume the engine's
single notification queue, so run one *or* the other per process when comparing.

The ``source`` axis selects the substrate: ``"output"`` streams raw
notifications; ``"subscription"`` first installs ``refresh-client -B`` format
subscriptions, tmux's debounced, server-side change detection.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import time
import typing as t
from dataclasses import dataclass

from fastmcp import Context

from libtmux.experimental.engines.base import CommandRequest
from libtmux.experimental.mcp._settle import (
    SettleReason,
    accumulate_until_settle,
    output_payload,
)
from libtmux.experimental.ops import TmuxCommandError

if t.TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator, Sequence

    from fastmcp import FastMCP

    from libtmux.experimental.engines.base import AsyncTmuxEngine, CommandResult

EventMode = t.Literal["off", "push", "pull", "both"]
EventSource = t.Literal["subscription", "output"]

_RING_SIZE = 1024

# tmux format read once at settle to fill DoneMetadata (tab-joined, one round-trip).
_DONE_FORMAT = "\t".join(
    (
        "#{pane_id}",
        "#{pane_dead}",
        "#{pane_dead_status}",
        "#{pane_dead_signal}",
        "#{pane_current_command}",
        "#{cursor_y}",
        "#{history_size}",
        "#{pane_in_mode}",
    ),
)


@dataclass(frozen=True)
class DoneMetadata:
    """Needle-free done-heuristics, read once at settle for the agent to interpret.

    A ``pane_dead`` pane with a ``pane_dead_status`` is a *hard* "process exited"
    signal; ``pane_current_command`` reverting to a shell is a *soft* "command
    finished" signal. The screen-state fields add context without claiming intent.
    ``pane_dead`` is ``None`` when the pane is gone or its liveness could not be
    read (the command exited and took the pane with it).
    """

    pane_dead: bool | None
    pane_dead_status: int | None
    pane_dead_signal: str | None
    pane_current_command: str | None
    cursor_y: int | None
    history_size: int | None
    pane_in_mode: bool


@dataclass(frozen=True)
class MonitorResult:
    """What ``wait_for_output`` returns; auto-serialized to structured content.

    ``reason`` is itself a signal: ``settled`` (the pane went quiet -- finished
    *or* blocked on input; ``done`` disambiguates), ``time_cap`` (still producing
    when the budget ran out; a partial chunk is returned), ``byte_cap`` (flooded,
    ``truncated``), ``stream_end`` (the notification stream ended).
    ``idle_ms_observed`` is only meaningful when ``reason == "settled"``;
    ``snapshot_lines`` is ``None`` when the call passed ``snapshot=False``.
    ``exit_code`` is the process exit code when the watched process is known to
    have exited (``done.pane_dead`` is true), else ``None``.
    """

    pane_id: str
    reason: SettleReason
    captured_text: str
    byte_count: int
    frame_count: int
    idle_ms_observed: int
    elapsed_ms: int
    truncated: bool
    dropped: int
    done: DoneMetadata
    exit_code: int | None
    snapshot_lines: tuple[str, ...] | None


class _StreamEngine(t.Protocol):
    """An async engine that also exposes a ``subscribe()`` notification stream.

    The general :class:`~..engines.base.AsyncTmuxEngine` protocol does not declare
    ``subscribe`` (only the control-mode engine has it), so the event tools type
    against this narrower protocol after the :func:`_supports_stream` guard.
    """

    _attached_session: str | None

    async def run(self, request: CommandRequest) -> CommandResult:
        """Execute one tmux command."""
        ...

    async def run_batch(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Execute a batch of tmux commands."""
        ...

    def subscribe(self) -> AsyncIterator[t.Any]:
        """Yield tmux notifications as they arrive."""
        ...


def _supports_stream(engine: AsyncTmuxEngine) -> bool:
    """Whether *engine* exposes a ``subscribe()`` notification stream."""
    return callable(getattr(engine, "subscribe", None))


def _event_dict(notification: t.Any) -> dict[str, t.Any]:
    """Project a ``ControlNotification`` to a JSON-friendly dict."""
    return {
        "kind": notification.kind,
        "args": list(notification.args),
        "raw": notification.raw,
    }


async def _install_subscriptions(
    engine: _StreamEngine,
    specs: list[str] | None,
) -> None:
    """Install ``refresh-client -B`` format subscriptions (``name:what:format``)."""
    for spec in specs or []:
        await engine.run(CommandRequest.from_args("refresh-client", "-B", spec))


class _EventRing:
    """A bounded ring buffer fed by a single background ``subscribe()`` reader.

    Each event gets a monotonic sequence number so a ``poll_events`` caller can
    ask for "everything since N" without re-reading the whole buffer.
    """

    def __init__(self, engine: _StreamEngine, maxlen: int = _RING_SIZE) -> None:
        self._engine = engine
        self._buffer: collections.deque[tuple[int, dict[str, t.Any]]] = (
            collections.deque(maxlen=maxlen)
        )
        self._seq = 0
        self._task: asyncio.Task[None] | None = None
        self._error: str | None = None

    def _ensure_started(self) -> None:
        """Start the drainer task, lazily, on the running loop.

        Also restarts it after it has *completed* -- the engine's
        ``_broadcast_stream_end`` ends the subscribe stream on a disconnect, so
        the drain task finishes; a bare ``is None`` guard would never re-subscribe
        after a reconnect, silently freezing the cursor.
        """
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._drain(), name="libtmux-mcp-events")

    async def _drain(self) -> None:
        """Copy every notification into the ring buffer (supervised, fail-safe).

        A reader failure is recorded and surfaced on the next :meth:`since` call,
        rather than silently freezing the cursor or raising at garbage-collection
        time. The subscription is closed deterministically via ``aclosing``. The
        prior error is cleared here, as this fresh attempt begins -- not in
        :meth:`_ensure_started`, so a restart cannot wipe a still-unread failure
        before :meth:`since` surfaces it (which would mask a persistently dead
        stream as empty-but-healthy).
        """
        self._error = None
        stream = t.cast("AsyncGenerator[t.Any, None]", self._engine.subscribe())
        try:
            async with contextlib.aclosing(stream) as managed:
                async for notification in managed:
                    self._seq += 1
                    self._buffer.append((self._seq, _event_dict(notification)))
        except Exception as error:  # capture: the drainer must never crash
            self._error = repr(error)

    def since(self, seq: int) -> dict[str, t.Any]:
        """Return buffered events with sequence number greater than *seq*."""
        self._ensure_started()
        events = [event for n, event in self._buffer if n > seq]
        out: dict[str, t.Any] = {"events": events, "cursor": self._seq}
        if self._error is not None:
            out["error"] = self._error
        return out


def register_events(
    mcp: FastMCP,
    engine: AsyncTmuxEngine,
    *,
    mode: EventMode = "push",
    source: EventSource = "subscription",
) -> None:
    """Register the event stream tools/resource on *mcp* per *mode*.

    Does nothing when *mode* is ``"off"`` or *engine* has no ``subscribe()``
    stream (e.g. a subprocess engine) -- the live stream is a control-mode
    feature.
    """
    if mode == "off" or not _supports_stream(engine):
        return
    stream = t.cast("_StreamEngine", engine)
    if mode in ("push", "both"):
        _register_push(mcp, stream, source=source)
    if mode in ("pull", "both"):
        _register_pull(mcp, stream)
    _register_monitor(mcp, stream)


def _register_push(
    mcp: FastMCP,
    engine: _StreamEngine,
    *,
    source: EventSource,
) -> None:
    """Register the long-running ``watch_events`` push tool."""
    from fastmcp.tools import FunctionTool
    from mcp.types import ToolAnnotations

    async def watch_events(
        ctx: Context,
        kinds: list[str] | None = None,
        max_events: int = 20,
        timeout: float = 30.0,
        subscriptions: list[str] | None = None,
    ) -> dict[str, t.Any]:
        """Stream live tmux notifications, pushing each as an MCP log message.

        Returns after *max_events* notifications or *timeout* seconds, whichever
        comes first. ``kinds`` filters by notification kind (e.g. ``window-add``,
        ``output``). With ``source="subscription"``, pass ``subscriptions`` as
        ``name:what:format`` specs to install ``refresh-client -B`` watches first.
        """
        if source == "subscription":
            await _install_subscriptions(engine, subscriptions)
        collected: list[dict[str, t.Any]] = []

        async def _collect() -> None:
            async for notification in engine.subscribe():
                if kinds and notification.kind not in kinds:
                    continue
                await ctx.info(notification.raw)
                collected.append(_event_dict(notification))
                if max_events and len(collected) >= max_events:
                    return

        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(_collect(), timeout=timeout)
        return {"events": collected, "count": len(collected)}

    tool = FunctionTool.from_function(
        watch_events,
        name="watch_events",
        description="Stream live tmux notifications as MCP messages",
        tags={"readonly", "events"},
        annotations=ToolAnnotations(title="watch_events", readOnlyHint=True),
    )
    mcp.add_tool(tool)


def _register_pull(mcp: FastMCP, engine: _StreamEngine) -> None:
    """Register the ``tmux://events`` resource + ``poll_events`` pull tool."""
    from fastmcp.tools import FunctionTool
    from mcp.types import ToolAnnotations

    ring = _EventRing(engine)

    async def read_events() -> dict[str, t.Any]:
        """Return all buffered tmux events (starts the reader on first read)."""
        return ring.since(0)

    mcp.resource(
        "tmux://events",
        name="tmux-events",
        description="Buffered tmux control-mode notifications",
    )(read_events)

    async def poll_events(since: int = 0) -> dict[str, t.Any]:
        """Return tmux events with sequence number greater than *since*.

        The response ``cursor`` is the latest sequence number; pass it back as
        ``since`` next call to receive only newer events.
        """
        return ring.since(since)

    tool = FunctionTool.from_function(
        poll_events,
        name="poll_events",
        description="Poll buffered tmux events since a cursor",
        tags={"readonly", "events"},
        annotations=ToolAnnotations(title="poll_events", readOnlyHint=True),
    )
    mcp.add_tool(tool)


def _gone_done() -> DoneMetadata:
    """``DoneMetadata`` for a pane that is gone or whose liveness can't be read."""
    return DoneMetadata(
        pane_dead=None,
        pane_dead_status=None,
        pane_dead_signal=None,
        pane_current_command=None,
        cursor_y=None,
        history_size=None,
        pane_in_mode=False,
    )


async def _read_done(engine: _StreamEngine, pane_id: str) -> DoneMetadata:
    """Fill :class:`DoneMetadata` for *pane_id* in one ``display-message`` read.

    Fail-safe: when the pane is gone -- the probe errors, returns blank, or tmux
    resolves a *different* (fallback) pane -- liveness is reported as unknown
    (``pane_dead=None``) rather than raising or fabricating ``pane_dead=False``,
    so a command that exited and took its pane still yields a result.
    """
    from libtmux.experimental.mcp.vocabulary.server import adisplay_message

    try:
        text = (await adisplay_message(engine, pane_id, _DONE_FORMAT)).text
    except TmuxCommandError:
        return _gone_done()
    fields = (text.split("\t") + [""] * 8)[:8]
    if not fields[0].strip() or fields[0].strip() != pane_id:
        return _gone_done()  # blank probe, or tmux resolved a fallback pane

    def _as_int(value: str) -> int | None:
        value = value.strip()
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def _as_str(value: str) -> str | None:
        return value.strip() or None

    return DoneMetadata(
        pane_dead=fields[1].strip() == "1",
        pane_dead_status=_as_int(fields[2]),
        pane_dead_signal=_as_str(fields[3]),
        pane_current_command=_as_str(fields[4]),
        cursor_y=_as_int(fields[5]),
        history_size=_as_int(fields[6]),
        pane_in_mode=fields[7].strip() == "1",
    )


async def _ensure_attached(engine: _StreamEngine, session_id: str) -> None:
    """Attach the control client to *session_id* so its panes emit ``%output``.

    A bare ``tmux -C`` control client receives **no** ``%output`` until it
    attaches to a session (a server-global notification like ``%window-add``
    arrives without attaching, but per-pane output does not). Attaching also
    triggers a one-time screen redraw, so a *successful* attachment is tracked
    per engine: re-watching the same session does not re-attach or redraw again.

    Raises on a failed attach (stale or killed session) instead of caching, so
    the caller gets a clear error rather than a silently empty capture and a
    later call can retry.
    """
    if getattr(engine, "_attached_session", None) == session_id:
        return
    result = await engine.run(
        CommandRequest.from_args("attach-session", "-t", session_id),
    )
    if result.returncode != 0:
        detail = " ".join(result.stderr) or "attach-session failed"
        msg = f"cannot watch {session_id}: {detail}"
        raise RuntimeError(msg)
    engine._attached_session = session_id


async def await_pane_output(
    engine: _StreamEngine,
    target: str,
    *,
    ctx: Context | None = None,
    settle_ms: int = 750,
    timeout: float = 30.0,
    max_bytes: int = 131072,
    needle: str | None = None,
    stream_partials: bool = False,
    snapshot: bool = True,
) -> MonitorResult:
    """Watch one pane's live output until it settles or reaches a cap."""
    from libtmux.experimental.mcp.target_resolver import resolve_target
    from libtmux.experimental.mcp.vocabulary._resolve import (
        pane_id as resolve_pane_id,
        reject_relative_special,
        session_id_of,
    )
    from libtmux.experimental.mcp.vocabulary.pane import acapture_pane

    reject_relative_special(resolve_target(target))
    pane = await resolve_pane_id(engine, target, None)
    await _ensure_attached(engine, await session_id_of(engine, target, None))

    dropped_before = getattr(engine, "dropped_notifications", 0)
    started = time.monotonic()

    async def _frames() -> AsyncGenerator[str, None]:
        async for notification in engine.subscribe():
            payload = output_payload(notification.raw, pane)
            if payload is None:
                continue
            if stream_partials and ctx is not None:
                await ctx.info(payload)
            yield payload

    outcome = await accumulate_until_settle(
        _frames(),
        settle_ms=settle_ms,
        timeout_ms=int(timeout * 1000),
        max_bytes=max_bytes,
        needle=needle,
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    dropped = getattr(engine, "dropped_notifications", 0) - dropped_before

    done = await _read_done(engine, pane)
    snapshot_lines: tuple[str, ...] | None = None
    if snapshot:
        # A pane that died at settle cannot be captured -- keep the result.
        with contextlib.suppress(TmuxCommandError):
            captured = await acapture_pane(
                engine,
                pane,
                join_wrapped=True,
                trim_trailing=True,
            )
            snapshot_lines = tuple(captured.lines)

    return MonitorResult(
        pane_id=pane,
        reason=outcome.reason,
        captured_text=outcome.text,
        byte_count=outcome.byte_count,
        frame_count=outcome.frame_count,
        idle_ms_observed=outcome.idle_ms_observed,
        elapsed_ms=elapsed_ms,
        truncated=outcome.truncated,
        dropped=dropped,
        done=done,
        exit_code=done.pane_dead_status if done.pane_dead else None,
        snapshot_lines=snapshot_lines,
    )


def _register_monitor(mcp: FastMCP, engine: _StreamEngine) -> None:
    """Register the ``wait_for_output`` needle-free settle monitor tool."""
    from fastmcp.tools import FunctionTool
    from mcp.types import ToolAnnotations

    async def wait_for_output(
        ctx: Context,
        target: str,
        settle_ms: int = 750,
        timeout: float = 30.0,
        max_bytes: int = 131072,
        needle: str | None = None,
        stream_partials: bool = False,
        snapshot: bool = True,
    ) -> MonitorResult:
        """Run a command and wait for it to finish; watch a pane until it settles.

        Use this to run a long-running command -- a test run (``uv run pytest``), a
        build, an install, a server coming up -- and wait for the result instead of
        polling with sleep + capture_pane. Typical flow: ``send_input`` the command
        to a pane (``enter=True``), then call ``wait_for_output`` on that same pane.
        It folds the bytes the pane *produces* and returns the instant it stays idle
        for ``settle_ms`` -- or ``timeout`` / ``max_bytes`` fires, or the stream
        ends. Needle-free: no regex, no sentinel injection.

        **Settled is not success.** ``reason='settled'`` means the pane stopped
        producing output -- it cannot, on its own, tell "finished, back to the
        shell" from "blocked waiting on stdin". To confirm the command exited, read
        ``done.pane_dead`` with ``done.pane_dead_status`` (the process exit code; 0
        is success) and ``done.pane_current_command`` (a shell name means idle).
        ``dropped`` / ``truncated`` warn the captured chunk may be incomplete.

        While it runs it shares tmux's single ``%output`` stream with
        ``watch_events`` / ``poll_events``; it is bounded by the caps and
        short-lived, and each call runs in its own task so it does not block other
        tools. The first watch on a session attaches the control client (so its
        panes emit ``%output``), which draws the current screen once into
        ``captured_text`` -- the clean rendered grid, when requested, is in
        ``snapshot_lines``.

        Parameters
        ----------
        target : str
            The pane to watch: a tmux id (``%pane``, ``@window``, ``$session``), a
            name, or ``session:window.pane``. Resolve directional specials to a
            concrete ``%N`` first.
        settle_ms : int
            Idle time in milliseconds with no new output before the pane is treated
            as done (default 750). Lower returns sooner but risks a false settle
            while a command pauses; raise it for chatty or bursty commands.
        timeout : float
            Wall-clock seconds to wait before giving up (default 30.0). Raise it for
            slow test suites or heavy builds; on expiry ``reason`` reports the cap.
        max_bytes : int
            Cap on captured output bytes (default 131072). On overflow the watch
            returns early with ``truncated`` set; raise it to keep more output.
        needle : str or None
            When set, return ``reason='matched'`` the instant the pane's output
            contains this substring (e.g. wait until a server prints ``READY``)
            instead of waiting for the idle settle. Default ``None`` (needle-free).
        stream_partials : bool
            When ``True``, also push each output chunk live as an MCP log message
            for real-time progress on long runs (default ``False``).
        snapshot : bool
            When ``True`` (default), capture the rendered pane grid into
            ``snapshot_lines`` at settle; ``False`` skips that extra capture and
            leaves ``snapshot_lines`` ``None``.
        """
        return await await_pane_output(
            engine,
            target,
            ctx=ctx,
            settle_ms=settle_ms,
            timeout=timeout,
            max_bytes=max_bytes,
            needle=needle,
            stream_partials=stream_partials,
            snapshot=snapshot,
        )

    tool = FunctionTool.from_function(
        wait_for_output,
        name="wait_for_output",
        description=(
            "Run a command and wait for it to finish (command completion): watch "
            "one pane's live output and return when it goes quiet (settles). Use "
            "after send_input to wait for long-running tests/builds/installs "
            "instead of sleep + capture_pane polling. Needle-free (no "
            "regex/sentinel); read captured_text and the done metadata (pane_dead, "
            "pane_dead_status = exit / return code, 0 is success) to tell whether "
            "it finished or failed."
        ),
        tags={"readonly", "events", "monitor"},
        annotations=ToolAnnotations(title="wait_for_output", readOnlyHint=True),
    )
    mcp.add_tool(tool)
