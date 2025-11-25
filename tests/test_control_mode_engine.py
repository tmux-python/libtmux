"""Tests for ControlModeEngine."""

from __future__ import annotations

import io
import pathlib
import queue
import threading
import time
import typing as t
from collections import deque
from dataclasses import dataclass

import pytest

from libtmux import exc
from libtmux._internal.engines.base import ExitStatus
from libtmux._internal.engines.control_mode import ControlModeEngine, _ControlProcess
from libtmux._internal.engines.control_protocol import ControlProtocol
from libtmux.server import Server


def test_control_mode_engine_basic(tmp_path: pathlib.Path) -> None:
    """Test basic functionality of ControlModeEngine."""
    socket_path = tmp_path / "tmux-control-mode-test"
    engine = ControlModeEngine()

    # Server should auto-start engine on first cmd
    server = Server(socket_path=socket_path, engine=engine)

    # kill server if exists (cleanup from previous runs if any)
    if server.is_alive():
        server.kill()

    # new session
    session = server.new_session(session_name="test_sess", kill_session=True)
    assert session.name == "test_sess"

    # check engine process is running
    assert engine.process is not None
    assert engine.process.poll() is None

    # list sessions
    # Control mode bootstrap session is now filtered from server.sessions
    sessions = server.sessions
    assert len(sessions) == 1
    session_names = [s.name for s in sessions]
    assert "test_sess" in session_names

    # Verify bootstrap session exists but is filtered (use internal method)
    all_sessions = server._sessions_all()
    all_session_names = [s.name for s in all_sessions]
    # Internal session now uses UUID-based name: libtmux_ctrl_XXXXXXXX
    assert any(
        name is not None and name.startswith("libtmux_ctrl_")
        for name in all_session_names
    )
    assert len(all_sessions) == 2  # test_sess + libtmux_ctrl_*

    # run a command that returns output
    output_cmd = server.cmd("display-message", "-p", "hello")
    assert output_cmd.stdout == ["hello"]
    assert getattr(output_cmd, "exit_status", ExitStatus.OK) in (
        ExitStatus.OK,
        0,
    )

    # cleanup
    server.kill()
    # Engine process should terminate eventually (ControlModeEngine.close is called
    # manually or via weakref/del)
    # Server.kill() kills the tmux SERVER. The control mode client process should
    # exit as a result.

    engine.process.wait(timeout=2)
    assert engine.process.poll() is not None


def test_control_mode_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """ControlModeEngine should surface timeouts and clean up the process."""

    class BlockingStdout:
        def __iter__(self) -> BlockingStdout:
            return self

        def __next__(self) -> str:  # pragma: no cover - simple block
            time.sleep(0.05)
            raise StopIteration

    class FakeProcess:
        def __init__(self) -> None:
            self.stdin: t.TextIO | None = io.StringIO()
            self.stdout: t.Iterable[str] | None = BlockingStdout()
            self.stderr: t.Iterable[str] | None = iter([])
            self._terminated: bool = False
            self.pid: int | None = 1234

        def terminate(self) -> None:  # pragma: no cover - simple stub
            self._terminated = True

        def kill(self) -> None:  # pragma: no cover - simple stub
            self._terminated = True

        def wait(self, timeout: float | None = None) -> int | None:  # pragma: no cover
            return 0

        def poll(self) -> int | None:  # pragma: no cover - simple stub
            return 0

    engine = ControlModeEngine(command_timeout=0.01, start_threads=False)

    fake_process: _ControlProcess = FakeProcess()

    def fake_start(server_args: t.Sequence[str | int] | None) -> None:
        engine.tmux_bin = "tmux"
        engine._server_args = tuple(server_args or ())
        engine.process = fake_process

    monkeypatch.setattr(engine, "_start_process", fake_start)

    with pytest.raises(exc.ControlModeTimeout):
        engine.run("list-sessions")

    assert engine.process is None


def test_control_mode_per_command_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-call timeout should close process and raise ControlModeTimeout."""

    class FakeProcess:
        def __init__(self) -> None:
            self.stdin: t.TextIO | None = io.StringIO()
            self.stdout: t.Iterable[str] | None = iter([])  # no output
            self.stderr: t.Iterable[str] | None = iter([])
            self._terminated: bool = False
            self.pid: int | None = 5678

        def terminate(self) -> None:
            self._terminated = True

        def kill(self) -> None:
            self._terminated = True

        def wait(self, timeout: float | None = None) -> int | None:
            return 0

        def poll(self) -> int | None:
            return 0

    engine = ControlModeEngine(command_timeout=5.0, start_threads=False)

    def fake_start(server_args: t.Sequence[str | int] | None) -> None:
        engine.tmux_bin = "tmux"
        engine._server_args = tuple(server_args or ())
        fake_proc: _ControlProcess = FakeProcess()
        engine.process = fake_proc

    monkeypatch.setattr(engine, "_start_process", fake_start)

    with pytest.raises(exc.ControlModeTimeout):
        engine.run("list-sessions", timeout=0.01)

    assert engine.process is None


def test_control_mode_custom_session_name(tmp_path: pathlib.Path) -> None:
    """Control mode engine can use custom internal session name."""
    socket_path = tmp_path / "tmux-custom-session-test"
    engine = ControlModeEngine(internal_session_name="my_control_session")
    server = Server(socket_path=socket_path, engine=engine)

    # Cleanup if exists
    if server.is_alive():
        server.kill()

    # Create user session
    server.new_session(session_name="user_app")

    # Only user session visible via public API
    assert len(server.sessions) == 1
    assert server.sessions[0].name == "user_app"

    # Custom internal session exists but is filtered
    all_sessions = server._sessions_all()
    all_names = [s.name for s in all_sessions]
    assert "my_control_session" in all_names
    assert "user_app" in all_names
    assert len(all_sessions) == 2

    # Cleanup
    server.kill()
    assert engine.process is not None
    engine.process.wait(timeout=2)


def test_control_mode_attach_to_existing(tmp_path: pathlib.Path) -> None:
    """Control mode can attach to existing session (advanced opt-in)."""
    socket_path = tmp_path / "tmux-attach-test"

    # Create session first with subprocess engine
    from libtmux._internal.engines.subprocess_engine import SubprocessEngine

    subprocess_engine = SubprocessEngine()
    server1 = Server(socket_path=socket_path, engine=subprocess_engine)

    if server1.is_alive():
        server1.kill()

    server1.new_session(session_name="shared_session")

    # Control mode attaches to existing session (no internal session created)
    control_engine = ControlModeEngine(attach_to="shared_session")
    server2 = Server(socket_path=socket_path, engine=control_engine)

    # Should see the shared session
    assert len(server2.sessions) == 1
    assert server2.sessions[0].name == "shared_session"

    # No internal session was created
    all_sessions = server2._sessions_all()
    assert len(all_sessions) == 1  # Only shared_session

    # Cleanup
    server2.kill()
    assert control_engine.process is not None
    control_engine.process.wait(timeout=2)


class RestartFixture(t.NamedTuple):
    """Fixture for restart/broken-pipe handling."""

    test_id: str
    should_raise: type[BaseException]


@pytest.mark.parametrize(
    "case",
    [
        RestartFixture(
            test_id="broken_pipe_increments_restart",
            should_raise=exc.ControlModeConnectionError,
        ),
    ],
    ids=lambda c: c.test_id,
)
def test_write_line_broken_pipe_increments_restart(
    case: RestartFixture,
) -> None:
    """Broken pipe should raise ControlModeConnectionError and bump restarts."""

    class FakeStdin(io.StringIO):
        def write(self, _: str) -> int:  # pragma: no cover - simple stub
            raise BrokenPipeError

        def flush(self) -> None:  # pragma: no cover - not reached
            return None

    class FakeProcess:
        def __init__(self) -> None:
            self.stdin: t.TextIO | None = FakeStdin()
            self.stdout: t.Iterable[str] | None = iter([])
            self.stderr: t.Iterable[str] | None = iter([])
            self._terminated: bool = False
            self.pid: int | None = 9999

        def terminate(self) -> None:
            self._terminated = True

        def kill(self) -> None:  # pragma: no cover - simple stub
            self._terminated = True

        def wait(self, timeout: float | None = None) -> int | None:
            return 0

        def poll(self) -> int | None:
            return 0

    engine = ControlModeEngine()
    fake_proc: _ControlProcess = FakeProcess()
    engine.process = fake_proc

    with pytest.raises(case.should_raise):
        engine._write_line("list-sessions", server_args=())
    assert engine._restarts == 1
    assert engine.process is None


class NotificationOverflowFixture(t.NamedTuple):
    """Fixture for notification overflow handling."""

    test_id: str
    queue_size: int
    overflow: int


@pytest.mark.parametrize(
    "case",
    [
        NotificationOverflowFixture(
            test_id="iter_notifications_after_drop",
            queue_size=1,
            overflow=3,
        ),
    ],
    ids=lambda c: c.test_id,
)
def test_iter_notifications_survives_overflow(
    case: NotificationOverflowFixture,
) -> None:
    """iter_notifications should continue yielding after queue drops."""
    engine = ControlModeEngine()
    engine._protocol = ControlProtocol(notification_queue_size=case.queue_size)

    for _ in range(case.overflow):
        engine._protocol.feed_line("%sessions-changed")

    stats = engine.get_stats()
    assert stats.dropped_notifications >= case.overflow - case.queue_size

    notif_iter = engine.iter_notifications(timeout=0.01)
    first = next(notif_iter, None)
    assert first is not None
    assert first.kind.name == "SESSIONS_CHANGED"


class ScriptedStdin:
    """Fake stdin that can optionally raise BrokenPipeError on write."""

    def __init__(self, broken: bool = False) -> None:
        """Initialize stdin.

        Parameters
        ----------
        broken : bool
            If True, write() and flush() raise BrokenPipeError.
        """
        self._broken = broken
        self._buf: list[str] = []

    def write(self, data: str) -> int:
        """Write data or raise BrokenPipeError if broken."""
        if self._broken:
            raise BrokenPipeError
        self._buf.append(data)
        return len(data)

    def flush(self) -> None:
        """Flush or raise BrokenPipeError if broken."""
        if self._broken:
            raise BrokenPipeError


class ScriptedStdout:
    """Queue-backed stdout that blocks like real subprocess I/O.

    Lines are fed from a background thread, simulating the pacing of real
    process output. The iterator blocks on __next__ until a line is available
    or EOF.
    """

    def __init__(self, lines: list[str], delay: float = 0.0) -> None:
        """Initialize stdout iterator.

        Parameters
        ----------
        lines : list[str]
            Lines to emit (without trailing newlines).
        delay : float
            Optional delay between lines in seconds.
        """
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._delay = delay
        self._closed = threading.Event()
        self._lines_fed = threading.Event()

        # Start feeder thread that pushes lines with optional delay
        self._feeder = threading.Thread(
            target=self._feed,
            args=(lines,),
            daemon=True,
        )
        self._feeder.start()

    def _feed(self, lines: list[str]) -> None:
        """Feed lines into the queue from a background thread."""
        for line in lines:
            if self._delay > 0:
                time.sleep(self._delay)
            self._queue.put(line)
        # Sentinel signals EOF
        self._queue.put(None)
        self._lines_fed.set()

    def __iter__(self) -> ScriptedStdout:
        """Return iterator (self)."""
        return self

    def __next__(self) -> str:
        """Block until next line or raise StopIteration at EOF."""
        item = self._queue.get()  # Blocks until available
        if item is None:
            self._closed.set()
            raise StopIteration
        return item

    def wait_until_fed(self, timeout: float | None = None) -> bool:
        """Wait until all lines have been put into the queue."""
        return self._lines_fed.wait(timeout=timeout)

    def wait_until_consumed(self, timeout: float | None = None) -> bool:
        """Wait until the iterator has reached EOF."""
        return self._closed.wait(timeout=timeout)


@dataclass
class ScriptedProcess:
    """Fake control-mode process that plays back scripted stdout and errors.

    Uses ScriptedStdout (queue-backed iterator) instead of a tuple to match
    real subprocess I/O semantics where reads are blocking/async.
    """

    stdin: t.TextIO | None
    stdout: t.Iterable[str] | None
    stderr: t.Iterable[str] | None
    pid: int | None = 4242
    broken_on_write: bool = False
    writes: list[str] | None = None
    _stdin_impl: ScriptedStdin | None = None
    _stdout_impl: ScriptedStdout | None = None

    def __init__(
        self,
        stdout_lines: list[str],
        *,
        broken_on_write: bool = False,
        pid: int | None = 4242,
        line_delay: float = 0.0,
    ) -> None:
        """Initialize scripted process.

        Parameters
        ----------
        stdout_lines : list[str]
            Lines to emit on stdout (without trailing newlines).
        broken_on_write : bool
            If True, writes to stdin raise BrokenPipeError.
        pid : int | None
            Process ID to report.
        line_delay : float
            Delay between stdout lines in seconds. Use for timeout tests.
        """
        self._stdin_impl = ScriptedStdin(broken=broken_on_write)
        self.stdin = t.cast(t.TextIO, self._stdin_impl)
        self._stdout_impl = ScriptedStdout(stdout_lines, delay=line_delay)
        self.stdout: t.Iterable[str] | None = self._stdout_impl
        self.stderr: t.Iterable[str] | None = iter(())
        self.pid = pid
        self.broken_on_write = broken_on_write
        self.writes = []

    def terminate(self) -> None:
        """Stub terminate."""
        return None

    def kill(self) -> None:
        """Stub kill."""
        return None

    def wait(self, timeout: float | None = None) -> int | None:
        """Stub wait."""
        return 0

    def poll(self) -> int | None:
        """Stub poll."""
        return 0

    def write_line(self, line: str) -> None:
        """Record a write or raise BrokenPipe."""
        if self.broken_on_write:
            raise BrokenPipeError
        assert self.writes is not None
        self.writes.append(line)

    def wait_stdout_fed(self, timeout: float | None = None) -> bool:
        """Wait until all stdout lines have been queued."""
        if self._stdout_impl is None:
            return True
        return self._stdout_impl.wait_until_fed(timeout)

    def wait_stdout_consumed(self, timeout: float | None = None) -> bool:
        """Wait until stdout iteration has reached EOF."""
        if self._stdout_impl is None:
            return True
        return self._stdout_impl.wait_until_consumed(timeout)


class ProcessFactory:
    """Scriptable process factory for control-mode tests."""

    def __init__(self, procs: deque[ScriptedProcess]) -> None:
        self.procs = procs
        self.calls = 0

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
    ) -> _ControlProcess:
        """Return the next scripted process."""
        self.calls += 1
        return self.procs.popleft()


class RetryOutcome(t.NamedTuple):
    """Fixture for restart/timeout retry behavior."""

    test_id: str
    broken_once: bool
    expect_timeout: bool


@pytest.mark.parametrize(
    "case",
    [
        RetryOutcome(
            test_id="retry_after_broken_pipe_succeeds",
            broken_once=True,
            expect_timeout=False,
        ),
        RetryOutcome(
            test_id="timeout_then_retry_succeeds",
            broken_once=False,
            expect_timeout=True,
        ),
    ],
    ids=lambda c: c.test_id,
)
def test_run_result_retries_with_process_factory(
    case: RetryOutcome,
) -> None:
    """run_result should restart and succeed after broken pipe or timeout.

    This test verifies that after a failure (broken pipe or timeout) on the
    first attempt, a subsequent call to run_result() succeeds with a fresh
    process.

    Uses max_retries=0 so errors surface immediately on the first call.
    """
    # First process: either breaks on write or hangs (timeout path).
    if case.expect_timeout:
        first_stdout: list[str] = []  # no output triggers timeout
        broken = False
    else:
        first_stdout = []
        broken = True

    first = ScriptedProcess(first_stdout, broken_on_write=broken, pid=1111)

    # Second process: successful %begin/%end for bootstrap AND list-sessions.
    # The reader will consume all lines, so we need output for:
    # 1. Bootstrap command (new-session): %begin/%end
    # 2. list-sessions command: %begin/%end
    # Small delay allows command registration before response is parsed.
    second = ScriptedProcess(
        [
            "%begin 1 1 0",  # bootstrap begin
            "%end 1 1 0",  # bootstrap end
            "%begin 2 1 0",  # list-sessions begin
            "%end 2 1 0",  # list-sessions end
        ],
        pid=2222,
        line_delay=0.01,  # 10ms between lines for proper sequencing
    )

    factory = ProcessFactory(deque([first, second]))

    engine = ControlModeEngine(
        command_timeout=0.05 if case.expect_timeout else 5.0,
        process_factory=factory,
        start_threads=True,
        max_retries=0,  # No internal retries - error surfaces immediately
    )

    if case.expect_timeout:
        with pytest.raises(exc.ControlModeTimeout):
            engine.run("list-sessions", timeout=0.02)
    else:
        with pytest.raises(exc.ControlModeConnectionError):
            engine.run("list-sessions")

    # After failure, _restarts should be incremented
    assert engine._restarts == 1
    assert factory.calls == 1

    # Second attempt should succeed with fresh process.
    res = engine.run_result("list-sessions")
    assert res.exit_status is ExitStatus.OK
    assert engine._restarts >= 1
    assert factory.calls == 2


class BackpressureFixture(t.NamedTuple):
    """Fixture for notification backpressure integration."""

    test_id: str
    queue_size: int
    overflow: int
    expect_iter: bool


@pytest.mark.parametrize(
    "case",
    [
        BackpressureFixture(
            test_id="notif_overflow_iter",
            queue_size=1,
            overflow=5,
            expect_iter=True,
        ),
    ],
    ids=lambda c: c.test_id,
)
def test_notifications_overflow_then_iter(case: BackpressureFixture) -> None:
    """Flood notif queue then ensure iter_notifications still yields."""
    # Build scripted process that emits:
    # 1. Bootstrap command response (%begin/%end)
    # 2. Many notifications (to overflow the queue)
    # 3. A command response for list-sessions
    bootstrap_block = ["%begin 1 1 0", "%end 1 1 0"]
    notif_lines = ["%sessions-changed"] * case.overflow
    command_block = ["%begin 99 1 0", "%end 99 1 0"]
    script = [*bootstrap_block, *notif_lines, *command_block, "%exit"]
    factory = ProcessFactory(
        deque([ScriptedProcess(script, pid=3333, line_delay=0.01)])
    )

    engine = ControlModeEngine(
        process_factory=factory,
        start_threads=True,
        notification_queue_size=case.queue_size,
    )

    # Run a dummy command to consume the %begin/%end.
    res = engine.run_result("list-sessions")
    assert res.exit_status is ExitStatus.OK

    stats = engine.get_stats()
    assert stats.dropped_notifications >= case.overflow - case.queue_size

    if case.expect_iter:
        notif = next(engine.iter_notifications(timeout=0.1), None)
        assert notif is not None
        assert notif.kind.name == "SESSIONS_CHANGED"


class TimeoutRestartFixture(t.NamedTuple):
    """Fixture for per-command timeout restart behavior."""

    test_id: str


@pytest.mark.xfail(
    reason="per-command timeout restart needs injectable control-mode transport",
    strict=False,
)
@pytest.mark.parametrize(
    "case",
    [
        TimeoutRestartFixture(test_id="timeout_triggers_restart_then_succeeds"),
    ],
    ids=lambda c: c.test_id,
)
def test_run_result_timeout_triggers_restart(case: TimeoutRestartFixture) -> None:
    """Placeholder: timeout should restart control process and allow next command."""
    _ = ControlModeEngine(command_timeout=0.0001)
    pytest.xfail(
        "control-mode needs injectable process to simulate per-call timeout",
    )
