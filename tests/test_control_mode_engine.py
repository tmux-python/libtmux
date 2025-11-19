"""Tests for ControlModeEngine."""

from __future__ import annotations

import pathlib

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
