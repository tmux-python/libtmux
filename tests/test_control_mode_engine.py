"""Tests for ControlModeEngine."""

from __future__ import annotations

import io
import pathlib
import subprocess
import time
import typing as t

import pytest

from libtmux import exc
from libtmux._internal.engines.control_mode import ControlModeEngine
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
    # ControlModeEngine creates a bootstrap session "libtmux_control_mode", so we
    # expect 2 sessions
    sessions = server.sessions
    assert len(sessions) >= 1
    session_names = [s.name for s in sessions]
    assert "test_sess" in session_names
    assert "libtmux_control_mode" in session_names

    # run a command that returns output
    output = server.cmd("display-message", "-p", "hello").stdout
    assert output == ["hello"]

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
        def readline(self) -> str:
            time.sleep(0.05)
            return ""

    class FakeProcess:
        def __init__(self) -> None:
            self.stdin = io.StringIO()
            self.stdout = BlockingStdout()
            self._terminated = False

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            self._terminated = True

        def wait(self, timeout: float | None = None) -> None:
            return None

    engine = ControlModeEngine(command_timeout=0.01)

    fake_process = FakeProcess()

    def fake_start(
        server_args: t.Sequence[str | int] | None,
    ) -> None:  # pragma: no cover - simple stub
        engine.process = t.cast(subprocess.Popen[str], fake_process)
        engine._server_args = tuple(server_args or ())

    monkeypatch.setattr(engine, "_start_process", fake_start)

    with pytest.raises(exc.ControlModeTimeout):
        engine.run("list-sessions")

    assert engine.process is None
