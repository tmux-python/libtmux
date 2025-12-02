"""Engine abstractions and shared types for libtmux."""

from __future__ import annotations

import dataclasses
import enum
import typing as t
from abc import ABC, abstractmethod

from libtmux.common import tmux_cmd

if t.TYPE_CHECKING:
    from libtmux.session import Session


@dataclasses.dataclass(frozen=True)
class ServerContext:
    """Immutable server connection context.

    Passed to :meth:`Engine.bind` so engines can execute commands
    without requiring `server_args` on every hook call.
    """

    socket_name: str | None = None
    socket_path: str | None = None
    config_file: str | None = None

    def to_args(self) -> tuple[str, ...]:
        """Convert context to tmux server argument tuple.

        Returns args in concatenated form (e.g., ``-Lsocket_name``) to match
        the format used by ``Server._build_server_args()``.
        """
        args: list[str] = []
        if self.socket_name:
            args.append(f"-L{self.socket_name}")
        if self.socket_path:
            args.append(f"-S{self.socket_path}")
        if self.config_file:
            args.append(f"-f{self.config_file}")
        return tuple(args)


class ExitStatus(enum.Enum):
    """Exit status returned by tmux control mode commands."""

    OK = 0
    ERROR = 1


@dataclasses.dataclass
class CommandResult:
    """Canonical result shape produced by engines.

    This is the internal representation used by engines. Public-facing APIs
    still return :class:`libtmux.common.tmux_cmd` for compatibility; see
    :func:`command_result_to_tmux_cmd`.
    """

    argv: list[str]
    stdout: list[str]
    stderr: list[str]
    exit_status: ExitStatus
    cmd_id: int | None = None
    start_time: float | None = None
    end_time: float | None = None
    tmux_time: int | None = None
    flags: int | None = None

    @property
    def returncode(self) -> int:
        """Return a POSIX-style return code matching tmux expectations."""
        return 0 if self.exit_status is ExitStatus.OK else 1


class NotificationKind(enum.Enum):
    """High-level categories for tmux control-mode notifications."""

    PANE_OUTPUT = enum.auto()
    PANE_EXTENDED_OUTPUT = enum.auto()
    PANE_MODE_CHANGED = enum.auto()
    WINDOW_LAYOUT_CHANGED = enum.auto()
    WINDOW_ADD = enum.auto()
    WINDOW_CLOSE = enum.auto()
    UNLINKED_WINDOW_ADD = enum.auto()
    UNLINKED_WINDOW_CLOSE = enum.auto()
    UNLINKED_WINDOW_RENAMED = enum.auto()
    WINDOW_RENAMED = enum.auto()
    WINDOW_PANE_CHANGED = enum.auto()
    SESSION_CHANGED = enum.auto()
    CLIENT_SESSION_CHANGED = enum.auto()
    CLIENT_DETACHED = enum.auto()
    SESSION_RENAMED = enum.auto()
    SESSIONS_CHANGED = enum.auto()
    SESSION_WINDOW_CHANGED = enum.auto()
    PASTE_BUFFER_CHANGED = enum.auto()
    PASTE_BUFFER_DELETED = enum.auto()
    PAUSE = enum.auto()
    CONTINUE = enum.auto()
    SUBSCRIPTION_CHANGED = enum.auto()
    EXIT = enum.auto()
    MESSAGE = enum.auto()
    CONFIG_ERROR = enum.auto()
    RAW = enum.auto()


@dataclasses.dataclass
class Notification:
    """Parsed notification emitted by tmux control mode."""

    kind: NotificationKind
    when: float
    raw: str
    data: dict[str, t.Any]


@dataclasses.dataclass
class EngineStats:
    """Light-weight diagnostics about engine state."""

    in_flight: int
    notif_queue_depth: int
    dropped_notifications: int
    restarts: int
    last_error: str | None
    last_activity: float | None


def command_result_to_tmux_cmd(result: CommandResult) -> tmux_cmd:
    """Adapt :class:`CommandResult` into the legacy ``tmux_cmd`` wrapper."""
    proc = tmux_cmd(
        cmd=result.argv,
        stdout=result.stdout,
        stderr=result.stderr,
        returncode=result.returncode,
    )
    # Preserve extra metadata for consumers that know about it.
    proc.exit_status = result.exit_status  # type: ignore[attr-defined]
    proc.cmd_id = result.cmd_id  # type: ignore[attr-defined]
    proc.tmux_time = result.tmux_time  # type: ignore[attr-defined]
    proc.flags = result.flags  # type: ignore[attr-defined]
    proc.start_time = result.start_time  # type: ignore[attr-defined]
    proc.end_time = result.end_time  # type: ignore[attr-defined]
    return proc


class Engine(ABC):
    """Abstract base class for tmux execution engines.

    Engines produce :class:`CommandResult` internally but surface ``tmux_cmd``
    to the existing libtmux public surface. Subclasses should implement
    :meth:`run_result` and rely on the base :meth:`run` adapter unless they have
    a strong reason to override both.
    """

    _server_context: ServerContext | None = None

    def bind(self, context: ServerContext) -> None:
        """Bind engine to server context.

        Called by :class:`Server.__init__` to provide connection details.
        Engines can use this to run commands without requiring ``server_args``
        on every hook call.

        Parameters
        ----------
        context : ServerContext
            Immutable server connection context.
        """
        self._server_context = context

    def run(
        self,
        cmd: str,
        cmd_args: t.Sequence[str | int] | None = None,
        server_args: t.Sequence[str | int] | None = None,
        timeout: float | None = None,
    ) -> tmux_cmd:
        """Run a tmux command and return a ``tmux_cmd`` wrapper."""
        return command_result_to_tmux_cmd(
            self.run_result(
                cmd=cmd,
                cmd_args=cmd_args,
                server_args=server_args,
                timeout=timeout,
            ),
        )

    @abstractmethod
    def run_result(
        self,
        cmd: str,
        cmd_args: t.Sequence[str | int] | None = None,
        server_args: t.Sequence[str | int] | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        """Run a tmux command and return a :class:`CommandResult`."""

    def iter_notifications(
        self,
        *,
        timeout: float | None = None,
    ) -> t.Iterator[Notification]:  # pragma: no cover - default noop
        """Yield control-mode notifications if supported by the engine."""
        if False:  # keeps the function a generator for typing
            yield timeout
        return

    # Optional hooks ---------------------------------------------------
    def probe_server_alive(self) -> bool | None:
        """Probe if tmux server is alive without starting the engine.

        Uses the bound :attr:`_server_context` for connection details.

        Returns
        -------
        bool | None
            True if server is alive, False if dead, None to use default check.
            Return None to fall back to running ``list-sessions`` via the engine.

        Notes
        -----
        Override in engines that shouldn't start on probe (e.g., ControlModeEngine).
        """
        return None

    def can_switch_client(self) -> bool:
        """Check if switch-client is meaningful for this engine.

        Uses the bound :attr:`_server_context` for connection details.

        Returns
        -------
        bool
            True if there is at least one client that can be switched.
            Default implementation returns True (assumes switching is allowed).
        """
        return True

    @property
    def internal_session_names(self) -> set[str]:
        """Names of sessions reserved for engine internals."""
        return set()

    def filter_sessions(
        self,
        sessions: list[Session],
    ) -> list[Session]:
        """Filter sessions, hiding any internal/management sessions.

        Uses the bound :attr:`_server_context` for connection details.

        Parameters
        ----------
        sessions : list[Session]
            All sessions from the server.

        Returns
        -------
        list[Session]
            Sessions after filtering out any engine-internal ones.
        """
        return sessions

    def get_stats(self) -> EngineStats:  # pragma: no cover - default noop
        """Return engine diagnostic stats."""
        return EngineStats(
            in_flight=0,
            notif_queue_depth=0,
            dropped_notifications=0,
            restarts=0,
            last_error=None,
            last_activity=None,
        )

    def close(self) -> None:  # pragma: no cover - default noop
        """Clean up any engine resources."""
        return None
