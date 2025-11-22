"""Control mode protocol parsing and bookkeeping."""

from __future__ import annotations

import collections
import dataclasses
import enum
import logging
import queue
import threading
import time
import typing as t

from libtmux import exc
from libtmux._internal.engines.base import (
    CommandResult,
    EngineStats,
    ExitStatus,
    Notification,
    NotificationKind,
)

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class CommandContext:
    """Tracks state for a single in-flight control-mode command."""

    argv: list[str]
    cmd_id: int | None = None
    tmux_time: int | None = None
    flags: int | None = None
    stdout: list[str] = dataclasses.field(default_factory=list)
    stderr: list[str] = dataclasses.field(default_factory=list)
    exit_status: ExitStatus | None = None
    start_time: float | None = None
    end_time: float | None = None
    done: threading.Event = dataclasses.field(default_factory=threading.Event)
    error: BaseException | None = None

    def signal_done(self) -> None:
        """Mark the context as complete."""
        self.done.set()

    def wait(self, timeout: float | None) -> bool:
        """Wait for completion; returns False on timeout."""
        return self.done.wait(timeout=timeout)


class ParserState(enum.Enum):
    """Minimal state machine for control-mode parsing."""

    IDLE = enum.auto()
    IN_COMMAND = enum.auto()
    DEAD = enum.auto()


def _parse_notification(line: str, parts: list[str]) -> Notification:
    """Map raw notification lines into structured :class:`Notification`.

    The mapping is intentionally conservative; unknown tags fall back to RAW.
    """
    tag = parts[0]
    now = time.monotonic()
    data: dict[str, t.Any] = {}
    kind = NotificationKind.RAW

    if tag == "%output" and len(parts) >= 3:
        kind = NotificationKind.PANE_OUTPUT
        data = {"pane_id": parts[1], "payload": " ".join(parts[2:])}
    elif tag == "%extended-output" and len(parts) >= 4:
        kind = NotificationKind.PANE_EXTENDED_OUTPUT
        data = {
            "pane_id": parts[1],
            "behind_ms": parts[2],
            "payload": " ".join(parts[3:]),
        }
    elif tag == "%pane-mode-changed" and len(parts) >= 2:
        kind = NotificationKind.PANE_MODE_CHANGED
        data = {"pane_id": parts[1], "mode": parts[2:]}
    elif tag == "%window-add" and len(parts) >= 2:
        kind = NotificationKind.WINDOW_ADD
        data = {"window_id": parts[1], "rest": parts[2:]}
    elif tag == "%window-close" and len(parts) >= 2:
        kind = NotificationKind.WINDOW_CLOSE
        data = {"window_id": parts[1]}
    elif tag == "%window-renamed" and len(parts) >= 3:
        kind = NotificationKind.WINDOW_RENAMED
        data = {"window_id": parts[1], "name": " ".join(parts[2:])}
    elif tag == "%window-pane-changed" and len(parts) >= 3:
        kind = NotificationKind.WINDOW_PANE_CHANGED
        data = {"window_id": parts[1], "pane_id": parts[2]}
    elif tag == "%session-changed" and len(parts) >= 2:
        kind = NotificationKind.SESSION_CHANGED
        data = {"session_id": parts[1]}
    elif tag == "%sessions-changed":
        kind = NotificationKind.SESSIONS_CHANGED
    elif tag == "%session-window-changed" and len(parts) >= 3:
        kind = NotificationKind.SESSION_WINDOW_CHANGED
        data = {"session_id": parts[1], "window_id": parts[2]}
    elif tag == "%pause" and len(parts) >= 2:
        kind = NotificationKind.PAUSE
        data = {"pane_id": parts[1]}
    elif tag == "%continue" and len(parts) >= 2:
        kind = NotificationKind.CONTINUE
        data = {"pane_id": parts[1]}
    elif tag == "%subscription-changed" and len(parts) >= 4:
        kind = NotificationKind.SUBSCRIPTION_CHANGED
        data = {"name": parts[1], "type": parts[2], "value": " ".join(parts[3:])}
    elif tag == "%exit":
        kind = NotificationKind.EXIT

    return Notification(kind=kind, when=now, raw=line, data=data)


class ControlProtocol:
    """Parse the tmux control-mode stream into commands and notifications."""

    def __init__(self, *, notification_queue_size: int = 4096) -> None:
        self.state = ParserState.IDLE
        self._pending: collections.deque[CommandContext] = collections.deque()
        self._current: CommandContext | None = None
        self._notif_queue: queue.Queue[Notification] = queue.Queue(
            maxsize=notification_queue_size,
        )
        self._dropped_notifications = 0
        self._last_error: str | None = None
        self._last_activity: float | None = None

    # Command lifecycle -------------------------------------------------
    def register_command(self, ctx: CommandContext) -> None:
        """Queue a command context awaiting %begin/%end."""
        self._pending.append(ctx)

    def feed_line(self, line: str) -> None:
        """Feed a raw line from tmux into the parser."""
        self._last_activity = time.monotonic()
        if self.state is ParserState.DEAD:
            return

        if line.startswith("%"):
            self._handle_percent_line(line)
        else:
            self._handle_plain_line(line)

    def _handle_percent_line(self, line: str) -> None:
        parts = line.split()
        tag = parts[0]

        if tag == "%begin":
            self._on_begin(parts)
        elif tag in ("%end", "%error"):
            self._on_end_or_error(tag, parts)
        else:
            self._on_notification(line, parts)

    def _handle_plain_line(self, line: str) -> None:
        if self.state is ParserState.IN_COMMAND and self._current:
            self._current.stdout.append(line)
        else:
            logger.debug("Unexpected plain line outside command: %r", line)

    def _on_begin(self, parts: list[str]) -> None:
        if self.state is not ParserState.IDLE:
            self._protocol_error("nested %begin")
            return

        try:
            tmux_time = int(parts[1])
            cmd_id = int(parts[2])
            flags = int(parts[3]) if len(parts) > 3 else 0
        except (IndexError, ValueError):
            self._protocol_error(f"malformed %begin: {parts}")
            return

        try:
            ctx = self._pending.popleft()
        except IndexError:
            self._protocol_error(f"no pending command for %begin id={cmd_id}")
            return

        ctx.cmd_id = cmd_id
        ctx.tmux_time = tmux_time
        ctx.flags = flags
        ctx.start_time = time.monotonic()
        self._current = ctx
        self.state = ParserState.IN_COMMAND

    def _on_end_or_error(self, tag: str, parts: list[str]) -> None:
        if self.state is not ParserState.IN_COMMAND or self._current is None:
            self._protocol_error(f"unexpected {tag}")
            return

        ctx = self._current
        ctx.exit_status = ExitStatus.OK if tag == "%end" else ExitStatus.ERROR
        ctx.end_time = time.monotonic()

        # Copy tmux_time/flags if provided on the closing tag
        try:
            if len(parts) > 1:
                ctx.tmux_time = int(parts[1])
            if len(parts) > 3:
                ctx.flags = int(parts[3])
        except ValueError:
            pass

        if ctx.exit_status is ExitStatus.ERROR and ctx.stdout and not ctx.stderr:
            ctx.stderr, ctx.stdout = ctx.stdout, []

        ctx.signal_done()
        self._current = None
        self.state = ParserState.IDLE

    def _on_notification(self, line: str, parts: list[str]) -> None:
        notif = _parse_notification(line, parts)
        try:
            self._notif_queue.put_nowait(notif)
        except queue.Full:
            self._dropped_notifications += 1
            if self._dropped_notifications & (self._dropped_notifications - 1) == 0:
                logger.warning(
                    "Control Mode notification queue full; dropped=%d",
                    self._dropped_notifications,
                )

    def mark_dead(self, reason: str) -> None:
        """Mark protocol as unusable and fail pending commands."""
        self.state = ParserState.DEAD
        self._last_error = reason
        err = exc.ControlModeConnectionError(reason)

        if self._current:
            self._current.error = err
            self._current.signal_done()
            self._current = None

        while self._pending:
            ctx = self._pending.popleft()
            ctx.error = err
            ctx.signal_done()

    def _protocol_error(self, reason: str) -> None:
        logger.error("Control Mode protocol error: %s", reason)
        self.mark_dead(reason)

    # Accessors ---------------------------------------------------------
    def get_notification(self, timeout: float | None = None) -> Notification | None:
        """Return the next notification or ``None`` if none available."""
        try:
            return self._notif_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def get_stats(self, *, restarts: int) -> EngineStats:
        """Return diagnostic counters for the protocol."""
        in_flight = (1 if self._current else 0) + len(self._pending)
        return EngineStats(
            in_flight=in_flight,
            notif_queue_depth=self._notif_queue.qsize(),
            dropped_notifications=self._dropped_notifications,
            restarts=restarts,
            last_error=self._last_error,
            last_activity=self._last_activity,
        )

    def build_result(self, ctx: CommandContext) -> CommandResult:
        """Convert a completed context into a :class:`CommandResult`."""
        exit_status = ctx.exit_status or ExitStatus.OK
        return CommandResult(
            argv=ctx.argv,
            stdout=ctx.stdout,
            stderr=ctx.stderr,
            exit_status=exit_status,
            cmd_id=ctx.cmd_id,
            start_time=ctx.start_time,
            end_time=ctx.end_time,
            tmux_time=ctx.tmux_time,
            flags=ctx.flags,
        )
