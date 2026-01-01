"""Control Mode engine for libtmux."""

from __future__ import annotations

import contextlib
import io
import logging
import shlex
import shutil
import subprocess
import threading
import typing as t
import uuid

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


class _ControlProcess(t.Protocol):
    """Protocol for control-mode process handle (real or test fake)."""

    stdin: t.TextIO | None
    stdout: t.Iterable[str] | None
    stderr: t.Iterable[str] | None
    pid: int | None

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> t.Any: ...

    def poll(self) -> int | None: ...


class _ProcessFactory(t.Protocol):
    """Protocol for constructing a control-mode process."""

    def __call__(
        self,
        cmd: list[str],
        *,
        stdin: t.Any,
        stdout: t.Any,
        stderr: t.Any,
        text: bool,
        bufsize: int,
        errors: str,
    ) -> _ControlProcess: ...


class ControlModeEngine(Engine):
    """Engine that runs tmux commands via a persistent Control Mode process.

    By default, creates an internal session for connection management.
    This session is hidden from user-facing APIs like Server.sessions.

    Error Handling
    --------------
    Connection errors (BrokenPipeError, EOF) raise
    :class:`~libtmux.exc.ControlModeConnectionError` and are automatically
    retried up to ``max_retries`` times (default: 1).

    Timeouts raise :class:`~libtmux.exc.ControlModeTimeout` and are NOT retried.
    If operations frequently timeout, increase ``command_timeout``.

    Notifications
    -------------
    A bounded notification queue (default 4096) records out-of-band events with
    drop counting when consumers fall behind. Use :meth:`iter_notifications` to
    consume events or :meth:`drain_notifications` to wait for idle state.
    """

    def __init__(
        self,
        command_timeout: float | None = 10.0,
        notification_queue_size: int = 4096,
        internal_session_name: str | None = None,
        control_session: str | None = None,
        process_factory: _ProcessFactory | None = None,
        max_retries: int = 1,
        start_threads: bool = True,
        shutdown_timeout: float = 2.0,
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
            Default: Auto-generated unique name (libtmux_ctrl_XXXXXXXX)

            The internal session is used for connection management and is
            automatically filtered from user-facing APIs. A unique name is
            generated automatically to avoid collisions with user sessions.
        control_session : str, optional
            Attach to existing session instead of creating internal one.
            When set, control mode attaches to this session for its connection.

            .. warning::
               Attaching to user sessions can cause notification spam from
               pane output. Use for advanced scenarios only.
        process_factory : _ProcessFactory, optional
            Test hook to override how the tmux control-mode process is created.
            When provided, it receives the argv list and must return an object
            compatible with ``subprocess.Popen`` (stdin/stdout/stderr streams).
        max_retries : int, optional
            Number of times to retry a command after a BrokenPipeError while
            writing to the control-mode process. Default: 1.
        start_threads : bool, optional
            Internal/testing hook to skip spawning reader/stderr threads when
            using a fake process that feeds the protocol directly. Default: True.
        shutdown_timeout : float, optional
            Time in seconds to wait for the control-mode process and threads
            to shut down during :meth:`close`. Default: 2.0.
        """
        self.process: _ControlProcess | None = None
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
        self._internal_session_name = (
            internal_session_name or f"libtmux_ctrl_{uuid.uuid4().hex[:8]}"
        )
        self._control_session = control_session
        self._process_factory = process_factory
        self._max_retries = max(0, max_retries)
        self._start_threads = start_threads
        self._shutdown_timeout = shutdown_timeout

    # Lifecycle ---------------------------------------------------------
    def close(self) -> None:
        """Terminate the tmux control mode process and clean up threads.

        Terminates the subprocess and waits for reader/stderr threads to
        finish. Non-daemon threads ensure clean shutdown without races.
        """
        proc = self.process
        if proc is None:
            return

        try:
            proc.terminate()
            proc.wait(timeout=self._shutdown_timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=self._shutdown_timeout)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "Control Mode process did not exit within %.2fs",
                    self._shutdown_timeout,
                )
        finally:
            # Join threads to ensure clean shutdown (non-daemon threads).
            # Skip join if called from within the thread itself (e.g., during GC).
            current = threading.current_thread()
            if (
                self._reader_thread is not None
                and self._reader_thread.is_alive()
                and self._reader_thread is not current
            ):
                self._reader_thread.join(timeout=self._shutdown_timeout)
                if self._reader_thread.is_alive():
                    logger.warning(
                        "Control Mode reader thread did not exit within %.2fs",
                        self._shutdown_timeout,
                    )
            if (
                self._stderr_thread is not None
                and self._stderr_thread.is_alive()
                and self._stderr_thread is not current
            ):
                self._stderr_thread.join(timeout=self._shutdown_timeout)
                if self._stderr_thread.is_alive():
                    logger.warning(
                        "Control Mode stderr thread did not exit within %.2fs",
                        self._shutdown_timeout,
                    )

            # Close pipes to avoid unraisable BrokenPipe errors on GC.
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if isinstance(stream, io.IOBase):
                    with contextlib.suppress(Exception):
                        stream.close()

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
                    if attempts > self._max_retries:
                        raise
                    # retry the full cycle with a fresh process/context
                    continue

            # Wait outside the lock so multiple callers can run concurrently
            if not ctx.wait(timeout=effective_timeout):
                self.close()
                self._restarts += 1
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

    def drain_notifications(
        self,
        *,
        idle_duration: float = 0.1,
        timeout: float = 8.0,
    ) -> list[Notification]:
        """Drain notifications until the queue is idle.

        This helper is useful when you need to wait for notification activity
        to settle after an operation that may generate multiple notifications
        (e.g., attach-session in control_session mode).

        Parameters
        ----------
        idle_duration : float, optional
            Consider the queue idle after this many seconds of silence.
            Default: 0.1 (100ms)
        timeout : float, optional
            Maximum time to wait for idle state. Default: 8.0
            Matches RETRY_TIMEOUT_SECONDS from libtmux.test.retry.

        Returns
        -------
        list[Notification]
            All notifications received before idle state.

        Raises
        ------
        TimeoutError
            If timeout is reached before idle state.
        """
        import time

        collected: list[Notification] = []
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            notif = self._protocol.get_notification(timeout=idle_duration)
            if notif is None:
                # Queue was idle for idle_duration - we're done
                return collected
            if notif.kind.name == "EXIT":
                return collected
            collected.append(notif)

        msg = f"Notification queue did not become idle within {timeout}s"
        raise TimeoutError(msg)

    def set_client_flags(
        self,
        *,
        no_output: bool | None = None,
        pause_after: int | None = None,
        wait_exit: bool | None = None,
        ignore_size: bool | None = None,
        active_pane: bool | None = None,
        read_only: bool | None = None,
        no_detach_on_destroy: bool | None = None,
    ) -> None:
        """Set control client flags via ``refresh-client -f``.

        These are runtime flags on the connected client. Boolean flags are
        toggled using tmux's ``!flag`` negation semantics and are left unchanged
        when passed ``None``.

        Parameters
        ----------
        no_output : bool, optional
            Filter ``%output`` notifications. ``False`` clears the flag.
        pause_after : int, optional
            Pause after N seconds of buffering; 0 clears the flag.
        wait_exit : bool, optional
            Keep control connection alive until tmux exit is reported.
        ignore_size : bool, optional
            Ignore size updates from the client.
        active_pane : bool, optional
            Mark client as active-pane.
        read_only : bool, optional
            Prevent modifications from this client.
        no_detach_on_destroy : bool, optional
            Mirror tmux's ``no-detach-on-destroy`` client flag.

        Examples
        --------
        >>> engine.set_client_flags(no_output=True)  # doctest: +SKIP
        >>> engine.set_client_flags(pause_after=5)   # doctest: +SKIP
        >>> engine.set_client_flags(wait_exit=True)  # doctest: +SKIP
        >>> engine.set_client_flags(no_output=False) # doctest: +SKIP
        """

        def _bool_flag(name: str, value: bool | None) -> str | None:
            if value is None:
                return None
            return name if value else f"!{name}"

        flags: list[str] = []

        maybe_flag = _bool_flag("no-output", no_output)
        if maybe_flag:
            flags.append(maybe_flag)

        if pause_after is not None:
            if pause_after < 0:
                msg = "pause_after must be >= 0"
                raise ValueError(msg)
            if pause_after == 0:
                flags.append("!pause-after")
            else:
                flags.append(f"pause-after={pause_after}")

        maybe_flag = _bool_flag("wait-exit", wait_exit)
        if maybe_flag:
            flags.append(maybe_flag)

        for name, value in (
            ("ignore-size", ignore_size),
            ("active-pane", active_pane),
            ("read-only", read_only),
            ("no-detach-on-destroy", no_detach_on_destroy),
        ):
            maybe_flag = _bool_flag(name, value)
            if maybe_flag:
                flags.append(maybe_flag)

        if flags:
            server_args = self._server_context.to_args() if self._server_context else ()
            self.run(
                "refresh-client",
                cmd_args=("-f", ",".join(flags)),
                server_args=server_args,
            )

    def set_pane_flow(self, pane_id: str | int, state: str = "continue") -> None:
        """Set per-pane flow control for the control client.

        This maps to ``refresh-client -A pane:state`` where ``state`` is one of
        ``on``, ``off``, ``pause``, or ``continue``. The default resumes a
        paused pane.
        """
        if state not in {"on", "off", "pause", "continue"}:
            msg = "state must be one of on|off|pause|continue"
            raise ValueError(msg)

        server_args = self._server_context.to_args() if self._server_context else ()
        self.run(
            "refresh-client",
            cmd_args=("-A", f"{pane_id}:{state}"),
            server_args=server_args,
        )

    def subscribe(
        self,
        name: str,
        *,
        what: str | None = None,
        fmt: str | None = None,
    ) -> None:
        """Manage control-mode subscriptions.

        Subscriptions emit ``%subscription-changed`` notifications when the
        provided format changes. Passing ``format=None`` removes the
        subscription by name.
        """
        server_args = self._server_context.to_args() if self._server_context else ()

        if fmt is None:
            # Remove subscription
            self.run(
                "refresh-client",
                cmd_args=("-B", name),
                server_args=server_args,
            )
            return

        target = what or ""
        payload = f"{name}:{target}:{fmt}"
        self.run(
            "refresh-client",
            cmd_args=("-B", payload),
            server_args=server_args,
        )

    def get_stats(self) -> EngineStats:
        """Return diagnostic statistics for the engine."""
        return self._protocol.get_stats(restarts=self._restarts)

    @property
    def internal_session_names(self) -> set[str]:
        """Session names reserved for the engine's control connection."""
        if self._control_session:
            return set()
        return {self._internal_session_name}

    def probe_server_alive(self) -> bool | None:
        """Check if tmux server is alive without starting control mode.

        Performs a direct subprocess check to avoid bootstrapping the control
        mode connection just to probe server liveness.

        Returns
        -------
        bool
            True if server is alive (list-sessions returns 0), False otherwise.
        """
        tmux_bin = shutil.which("tmux")
        if tmux_bin is None:
            return None

        server_args = self._server_context.to_args() if self._server_context else ()
        result = subprocess.run(
            [tmux_bin, *server_args, "list-sessions"],
            check=False,
            capture_output=True,
        )
        return result.returncode == 0

    def filter_sessions(
        self,
        sessions: list[Session],
    ) -> list[Session]:
        """Hide sessions that are only attached via the control-mode client."""
        if self.process is None or self.process.pid is None:
            return sessions

        ctrl_pid = str(self.process.pid)
        server_args = self._server_context.to_args() if self._server_context else ()

        proc = self.run(
            "list-clients",
            cmd_args=(
                "-F",
                "#{client_pid}\t#{client_flags}\t#{session_name}",
            ),
            server_args=server_args,
        )
        pid_map: dict[str, list[tuple[str, str]]] = {}
        for line in proc.stdout:
            parts = line.split("\t", 2)
            if len(parts) >= 3:
                pid, flags, sess_name = parts
                pid_map.setdefault(sess_name, []).append((pid, flags))

        filtered: list[Session] = []
        for sess_obj in sessions:
            sess_name = sess_obj.session_name or ""

            # Never expose the internal control session we create to hold the
            # control client when control_session is unset.
            if not self._control_session and sess_name == self._internal_session_name:
                continue

            clients = pid_map.get(sess_name, [])
            non_control_clients = [
                (pid, flags)
                for pid, flags in clients
                if "control-mode" not in flags and pid != ctrl_pid
            ]

            if non_control_clients:
                filtered.append(sess_obj)

        return filtered

    def can_switch_client(self) -> bool:
        """Return True if there is at least one non-control client attached."""
        server_args = self._server_context.to_args() if self._server_context else ()
        if self.process is None or self.process.pid is None:
            with self._lock:
                self._ensure_process(tuple(server_args))

        if self.process is None or self.process.pid is None:
            return False

        ctrl_pid = str(self.process.pid)

        proc = self.run(
            "list-clients",
            cmd_args=("-F", "#{client_pid}\t#{client_flags}"),
            server_args=server_args,
        )
        for line in proc.stdout:
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            pid, flags = parts
            if "control-mode" not in flags and pid != ctrl_pid:
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
        if self._control_session:
            # Fail fast if attach target is missing before starting control mode.
            has_session_cmd = [
                tmux_bin,
                *[str(a) for a in server_args],
                "has-session",
                "-t",
                self._control_session,
            ]
            probe = subprocess.run(
                has_session_cmd,
                capture_output=True,
                text=True,
            )
            if probe.returncode != 0:
                msg = f"control_session not found: {self._control_session}"
                raise exc.ControlModeConnectionError(msg)

            # Attach to existing session (advanced mode)
            cmd = [
                tmux_bin,
                *[str(a) for a in server_args],
                "-C",
                "attach-session",
                "-t",
                self._control_session,
            ]
            bootstrap_argv = [
                tmux_bin,
                *[str(a) for a in server_args],
                "attach-session",
                "-t",
                self._control_session,
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
        popen_factory: _ProcessFactory = (
            self._process_factory or subprocess.Popen  # type: ignore[assignment]
        )
        self.process = popen_factory(
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
        # Non-daemon threads ensure clean shutdown via join() in close().
        if self._start_threads:
            self._reader_thread = threading.Thread(
                target=self._reader,
                args=(self.process,),
                daemon=False,
            )
            self._reader_thread.start()

            self._stderr_thread = threading.Thread(
                target=self._drain_stderr,
                args=(self.process,),
                daemon=False,
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

    def _reader(self, process: _ControlProcess) -> None:
        assert process.stdout is not None
        try:
            for raw in process.stdout:
                self._protocol.feed_line(raw.rstrip("\n"))
        except Exception:  # pragma: no cover - defensive
            logger.exception("Control Mode reader thread crashed")
        finally:
            self._protocol.mark_dead("EOF from tmux")

    def _drain_stderr(self, process: _ControlProcess) -> None:
        if process.stderr is None:
            return
        for err_line in process.stderr:
            logger.debug("Control Mode stderr: %s", err_line.rstrip("\n"))
