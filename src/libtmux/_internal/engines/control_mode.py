"""Control Mode engine for libtmux."""

from __future__ import annotations

import logging
import shlex
import shutil
import subprocess
import threading
import typing as t

from libtmux import exc
from libtmux._internal.engines.base import (
    CommandResult,
    Engine,
    EngineStats,
    ExitStatus,
    Notification,
)
from libtmux._internal.engines.control_protocol import (
    CommandContext,
    ControlProtocol,
)

if t.TYPE_CHECKING:
    from libtmux.session import Session

logger = logging.getLogger(__name__)


class ControlModeEngine(Engine):
    """Engine that runs tmux commands via a persistent Control Mode process.

    By default, creates an internal session for connection management.
    This session is hidden from user-facing APIs like Server.sessions.

    Commands raise :class:`~libtmux.exc.ControlModeTimeout` or
    :class:`~libtmux.exc.ControlModeConnectionError` on stalls/disconnects; a
    bounded notification queue (default 4096) records out-of-band events with
    drop counting when consumers fall behind.
    """

    def __init__(
        self,
        command_timeout: float | None = 10.0,
        notification_queue_size: int = 4096,
        internal_session_name: str | None = None,
        attach_to: str | None = None,
    ) -> None:
        """Initialize control mode engine.

        Parameters
        ----------
        command_timeout : float, optional
            Timeout for tmux commands in seconds. Default: 10.0
        notification_queue_size : int
            Size of notification queue. Default: 4096
        internal_session_name : str, optional
            Custom name for internal control session.
            Default: "libtmux_control_mode"

            The internal session is used for connection management and is
            automatically filtered from user-facing APIs.
        attach_to : str, optional
            Attach to existing session instead of creating internal one.
            When set, control mode attaches to this session for its connection.

            .. warning::
               Attaching to user sessions can cause notification spam from
               pane output. Use for advanced scenarios only.
        """
        self.process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._server_args: tuple[str | int, ...] | None = None
        self.command_timeout = command_timeout
        self.tmux_bin: str | None = None
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._notification_queue_size = notification_queue_size
        self._protocol = ControlProtocol(
            notification_queue_size=notification_queue_size,
        )
        self._restarts = 0
        self._internal_session_name = internal_session_name or "libtmux_control_mode"
        self._attach_to = attach_to

    # Lifecycle ---------------------------------------------------------
    def close(self) -> None:
        """Terminate the tmux control mode process and clean up threads."""
        proc = self.process
        if proc is None:
            return

        try:
            proc.terminate()
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        finally:
            self.process = None
            self._server_args = None
            self._protocol.mark_dead("engine closed")

    def __del__(self) -> None:  # pragma: no cover - best effort cleanup
        """Ensure subprocess is terminated on GC."""
        self.close()

    # Engine API --------------------------------------------------------
    def run_result(
        self,
        cmd: str,
        cmd_args: t.Sequence[str | int] | None = None,
        server_args: t.Sequence[str | int] | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        """Run a tmux command and return a :class:`CommandResult`."""
        incoming_server_args = tuple(server_args or ())
        effective_timeout = timeout if timeout is not None else self.command_timeout
        attempts = 0

        while True:
            attempts += 1
            with self._lock:
                self._ensure_process(incoming_server_args)
                assert self.process is not None
                full_argv: list[str] = [
                    self.tmux_bin or "tmux",
                    *[str(x) for x in incoming_server_args],
                    cmd,
                ]
                if cmd_args:
                    full_argv.extend(str(a) for a in cmd_args)

                ctx = CommandContext(argv=full_argv)
                self._protocol.register_command(ctx)

                command_line = shlex.join([cmd, *(str(a) for a in cmd_args or [])])
                try:
                    self._write_line(command_line, server_args=incoming_server_args)
                except exc.ControlModeConnectionError:
                    if attempts >= 2:
                        raise
                    # retry the full cycle with a fresh process/context
                    continue

            # Wait outside the lock so multiple callers can run concurrently
            if not ctx.wait(timeout=effective_timeout):
                self.close()
                msg = "tmux control mode command timed out"
                raise exc.ControlModeTimeout(msg)

            if ctx.error is not None:
                # Treat EOF after kill-* as success: tmux closes control socket.
                if isinstance(ctx.error, exc.ControlModeConnectionError) and (
                    cmd in {"kill-server", "kill-session"}
                ):
                    ctx.exit_status = ExitStatus.OK
                    ctx.error = None
                else:
                    raise ctx.error

            if ctx.exit_status is None:
                ctx.exit_status = ExitStatus.OK

            return self._protocol.build_result(ctx)

    def iter_notifications(
        self,
        *,
        timeout: float | None = None,
    ) -> t.Iterator[Notification]:
        """Yield control-mode notifications until the stream ends."""
        while True:
            notif = self._protocol.get_notification(timeout=timeout)
            if notif is None:
                return
            if notif.kind.name == "EXIT":
                return
            yield notif

    def get_stats(self) -> EngineStats:
        """Return diagnostic statistics for the engine."""
        return self._protocol.get_stats(restarts=self._restarts)

    @property
    def internal_session_names(self) -> set[str]:
        """Session names reserved for the engine's control connection."""
        if self._attach_to:
            return set()
        return {self._internal_session_name}

    def exclude_internal_sessions(
        self,
        sessions: list[Session],
        *,
        server_args: tuple[str | int, ...] | None = None,
    ) -> list[Session]:
        """Hide sessions that are only attached via the control-mode client."""
        if self.process is None or self.process.pid is None:
            return sessions

        ctrl_pid = str(self.process.pid)
        effective_server_args = server_args or self._server_args or ()

        proc = self.run(
            "list-clients",
            cmd_args=(
                "-F",
                "#{client_pid} #{client_flags} #{session_name}",
            ),
            server_args=effective_server_args,
        )
        pid_map: dict[str, list[tuple[str, str]]] = {}
        for line in proc.stdout:
            parts = line.split()
            if len(parts) >= 3:
                pid, flags, sess_name = parts[0], parts[1], parts[2]
                pid_map.setdefault(sess_name, []).append((pid, flags))

        filtered: list[Session] = []
        for sess_obj in sessions:
            sess_name = sess_obj.session_name or ""

            # Never expose the internal control session we create to hold the
            # control client when attach_to is unset.
            if not self._attach_to and sess_name == self._internal_session_name:
                continue

            clients = pid_map.get(sess_name, [])
            non_control_clients = [
                (pid, flags)
                for pid, flags in clients
                if "C" not in flags and pid != ctrl_pid
            ]

            if non_control_clients:
                filtered.append(sess_obj)

        return filtered

    def can_switch_client(
        self,
        *,
        server_args: tuple[str | int, ...] | None = None,
    ) -> bool:
        """Return True if there is at least one non-control client attached."""
        if self.process is None or self.process.pid is None:
            return False

        ctrl_pid = str(self.process.pid)
        effective_server_args = server_args or self._server_args or ()

        proc = self.run(
            "list-clients",
            cmd_args=("-F", "#{client_pid} #{client_flags}"),
            server_args=effective_server_args,
        )
        for line in proc.stdout:
            parts = line.split()
            if len(parts) >= 2:
                pid, flags = parts[0], parts[1]
                if "C" not in flags and pid != ctrl_pid:
                    return True

        return False

    # Internals ---------------------------------------------------------
    def _ensure_process(self, server_args: tuple[str | int, ...]) -> None:
        if self.process is None:
            self._start_process(server_args)
            return

        if server_args != self._server_args:
            logger.warning(
                (
                    "Server args changed; restarting Control Mode process. "
                    "Old: %s, New: %s"
                ),
                self._server_args,
                server_args,
            )
            self.close()
            self._start_process(server_args)

    def _start_process(self, server_args: tuple[str | int, ...]) -> None:
        tmux_bin = shutil.which("tmux")
        if not tmux_bin:
            raise exc.TmuxCommandNotFound

        self.tmux_bin = tmux_bin
        self._server_args = server_args
        self._protocol = ControlProtocol(
            notification_queue_size=self._notification_queue_size,
        )

        # Build command based on configuration
        if self._attach_to:
            # Fail fast if attach target is missing before starting control mode.
            has_session_cmd = [
                tmux_bin,
                *[str(a) for a in server_args],
                "has-session",
                "-t",
                self._attach_to,
            ]
            probe = subprocess.run(
                has_session_cmd,
                capture_output=True,
                text=True,
            )
            if probe.returncode != 0:
                msg = f"attach_to session not found: {self._attach_to}"
                raise exc.ControlModeConnectionError(msg)

            # Attach to existing session (advanced mode)
            cmd = [
                tmux_bin,
                *[str(a) for a in server_args],
                "-C",
                "attach-session",
                "-t",
                self._attach_to,
            ]
            bootstrap_argv = [
                tmux_bin,
                *[str(a) for a in server_args],
                "attach-session",
                "-t",
                self._attach_to,
            ]
        else:
            # Create or attach to internal session (default)
            cmd = [
                tmux_bin,
                *[str(a) for a in server_args],
                "-C",
                "new-session",
                "-A",
                "-s",
                self._internal_session_name,
            ]
            bootstrap_argv = [
                tmux_bin,
                *[str(a) for a in server_args],
                "new-session",
                "-A",
                "-s",
                self._internal_session_name,
            ]

        logger.debug("Starting Control Mode process: %s", cmd)
        self.process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=0,
            errors="backslashreplace",
        )

        # The initial command (new-session or attach-session) emits an output
        # block; register a context so the protocol can consume it.
        bootstrap_ctx = CommandContext(argv=bootstrap_argv)
        self._protocol.register_command(bootstrap_ctx)

        # Start IO threads after registration to avoid early protocol errors.
        self._reader_thread = threading.Thread(
            target=self._reader,
            args=(self.process,),
            daemon=True,
        )
        self._reader_thread.start()

        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            args=(self.process,),
            daemon=True,
        )
        self._stderr_thread.start()

        if not bootstrap_ctx.wait(timeout=self.command_timeout):
            self.close()
            msg = "Control Mode bootstrap command timed out"
            raise exc.ControlModeTimeout(msg)

    def _write_line(
        self,
        command_line: str,
        *,
        server_args: tuple[str | int, ...],
    ) -> None:
        assert self.process is not None
        assert self.process.stdin is not None

        try:
            self.process.stdin.write(command_line + "\n")
            self.process.stdin.flush()
        except BrokenPipeError:
            logger.exception("Control Mode process died, restarting...")
            self.close()
            self._restarts += 1
            msg = "control mode process unavailable"
            raise exc.ControlModeConnectionError(msg) from None

    def _reader(self, process: subprocess.Popen[str]) -> None:
        assert process.stdout is not None
        try:
            for raw in process.stdout:
                self._protocol.feed_line(raw.rstrip("\n"))
        except Exception:  # pragma: no cover - defensive
            logger.exception("Control Mode reader thread crashed")
        finally:
            self._protocol.mark_dead("EOF from tmux")

    def _drain_stderr(self, process: subprocess.Popen[str]) -> None:
        if process.stderr is None:
            return
        for err_line in process.stderr:
            logger.debug("Control Mode stderr: %s", err_line.rstrip("\n"))
