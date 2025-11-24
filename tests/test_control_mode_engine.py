"""Tests for ControlModeEngine."""

from __future__ import annotations

import io
import pathlib
import time
import typing as t

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
    assert "libtmux_control_mode" in all_session_names
    assert len(all_sessions) == 2  # test_sess + libtmux_control_mode

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


class RestartRetryFixture(t.NamedTuple):
    """Fixture for restart + retry behavior."""

    test_id: str
    raise_once: bool
    expect_xfail: bool


@pytest.mark.xfail(reason="Engine retry path not covered yet", strict=False)
@pytest.mark.parametrize(
    "case",
    [
        RestartRetryFixture(
            test_id="retry_after_broken_pipe",
            raise_once=True,
            expect_xfail=True,
        ),
        RestartRetryFixture(
            test_id="retry_after_timeout",
            raise_once=False,
            expect_xfail=True,
        ),
    ],
    ids=lambda c: c.test_id,
)
def test_run_result_retries_after_broken_pipe(
    case: RestartRetryFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Placeholder: run_result should retry after broken pipe and succeed."""
    engine = ControlModeEngine()
    # TODO: Implement retry simulation when engine supports injectable I/O.
    with pytest.raises(exc.ControlModeConnectionError):
        engine.run("list-sessions")


class BackpressureFixture(t.NamedTuple):
    """Fixture for notification backpressure integration."""

    test_id: str
    queue_size: int
    overflow: int
    expect_iter: bool


@pytest.mark.xfail(
    reason="control-mode notification backpressure integration not stable yet",
    strict=False,
)
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
    engine = ControlModeEngine()
    engine._protocol = ControlProtocol(notification_queue_size=case.queue_size)
    for _ in range(case.overflow):
        engine._protocol.feed_line("%sessions-changed")
    if case.expect_iter:
        notif = next(engine.iter_notifications(timeout=0.05), None)
        assert notif is not None


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
