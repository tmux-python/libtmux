"""Tests for ControlModeEngine."""

from __future__ import annotations

import io
import pathlib
import subprocess
import time
import typing as t

import pytest

from libtmux import exc
from libtmux._internal.engines.base import ExitStatus
from libtmux._internal.engines.control_mode import ControlModeEngine
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
            self.stdin = io.StringIO()
            self.stdout = BlockingStdout()
            self.stderr = None
            self._terminated = False

        def terminate(self) -> None:  # pragma: no cover - simple stub
            self._terminated = True

        def kill(self) -> None:  # pragma: no cover - simple stub
            self._terminated = True

        def wait(self, timeout: float | None = None) -> None:  # pragma: no cover
            return None

    engine = ControlModeEngine(command_timeout=0.01)

    fake_process = FakeProcess()

    def fake_start(server_args: t.Sequence[str | int] | None) -> None:
        engine.tmux_bin = "tmux"
        engine._server_args = tuple(server_args or ())
        engine.process = t.cast(subprocess.Popen[str], fake_process)

    monkeypatch.setattr(engine, "_start_process", fake_start)

    with pytest.raises(exc.ControlModeTimeout):
        engine.run("list-sessions")

    assert engine.process is None


def test_control_mode_per_command_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-call timeout should close process and raise ControlModeTimeout."""

    class FakeProcess:
        def __init__(self) -> None:
            self.stdin = io.StringIO()
            self.stdout: t.Iterator[str] = iter([])  # no output
            self.stderr = None
            self._terminated = False

        def terminate(self) -> None:
            self._terminated = True

        def kill(self) -> None:
            self._terminated = True

        def wait(self, timeout: float | None = None) -> None:
            return None

    engine = ControlModeEngine(command_timeout=5.0)

    def fake_start(server_args: t.Sequence[str | int] | None) -> None:
        engine.tmux_bin = "tmux"
        engine._server_args = tuple(server_args or ())
        engine.process = t.cast(subprocess.Popen[str], FakeProcess())

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

    class FakeStdin:
        def write(self, _: str) -> None:
            raise BrokenPipeError

        def flush(self) -> None:  # pragma: no cover - not reached
            return None

    class FakeProcess:
        def __init__(self) -> None:
            self.stdin = FakeStdin()

    engine = ControlModeEngine()
    engine.process = FakeProcess()  # type: ignore[assignment]

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
