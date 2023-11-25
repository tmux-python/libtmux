"""Test for libtmux Server object."""
import logging
import subprocess

import pytest

from libtmux.common import has_gte_version
from libtmux.server import Server
from libtmux.session import Session

logger = logging.getLogger(__name__)


def test_has_session(server: Server, session: Session) -> None:
    """Server.has_session() returns True if session exists."""
    session_name = session.get("session_name")
    assert session_name is not None
    assert server.has_session(session_name)
    assert not server.has_session("asdf2314324321")


def test_socket_name(server: Server) -> None:
    """``-L`` socket_name.

    ``-L`` socket_name  file name of socket. which will be stored in
            env TMUX_TMPDIR or /tmp if unset.)

    """
    myserver = Server(socket_name="test")

    assert myserver.socket_name == "test"


def test_socket_path(server: Server) -> None:
    """``-S`` socket_path  (alternative path for server socket)."""
    myserver = Server(socket_path="test")

    assert myserver.socket_path == "test"


def test_config(server: Server) -> None:
    """``-f`` file for tmux(1) configuration."""
    myserver = Server(config_file="test")
    assert myserver.config_file == "test"


def test_256_colors(server: Server) -> None:
    """Assert Server respects ``colors=256``."""
    myserver = Server(colors=256)
    assert myserver.colors == 256

    proc = myserver.cmd("list-sessions")

    assert "-2" in proc.cmd
    assert "-8" not in proc.cmd


def test_88_colors(server: Server) -> None:
    """Assert Server respects ``colors=88``."""
    myserver = Server(colors=88)
    assert myserver.colors == 88

    proc = myserver.cmd("list-sessions")

    assert "-8" in proc.cmd
    assert "-2" not in proc.cmd


def test_show_environment(server: Server) -> None:
    """Server.show_environment() returns dict."""
    _vars = server.show_environment()
    assert isinstance(_vars, dict)


def test_getenv(server: Server, session: Session) -> None:
    """Set environment then Server.show_environment(key)."""
    server.set_environment("FOO", "BAR")
    assert server.getenv("FOO") == "BAR"

    server.set_environment("FOO", "DAR")
    assert server.getenv("FOO") == "DAR"

    assert server.show_environment()["FOO"] == "DAR"


def test_show_environment_not_set(server: Server) -> None:
    """Unset environment variable returns None."""
    assert server.getenv("BAR") is None


def test_new_session(server: Server) -> None:
    """Server.new_session creates and returns valid session."""
    mysession = server.new_session("test_new_session")
    assert mysession.get("session_name") == "test_new_session"
    assert server.has_session("test_new_session")


def test_new_session_no_name(server: Server) -> None:
    """Server.new_session works with no name."""
    first_session = server.new_session()
    first_session_name = first_session.get("session_name")
    assert first_session_name is not None
    assert server.has_session(first_session_name)

    expected_session_name = str(int(first_session_name) + 1)

    # When a new session is created, it should enumerate
    second_session = server.new_session()
    second_session_name = second_session.get("session_name")
    assert expected_session_name == second_session_name
    assert second_session_name is not None
    assert server.has_session(second_session_name)


def test_new_session_shell(server: Server) -> None:
    """Verify ``Server.new_session`` creates valid session running w/ command."""
    cmd = "sleep 1m"
    mysession = server.new_session("test_new_session", window_command=cmd)
    window = mysession.list_windows()[0]
    pane = window.list_panes()[0]
    assert mysession.get("session_name") == "test_new_session"
    assert server.has_session("test_new_session")

    pane_start_command = pane.get("pane_start_command")
    assert pane_start_command is not None

    if has_gte_version("3.2"):
        assert pane_start_command.replace('"', "") == cmd
    else:
        assert pane_start_command == cmd


def test_no_server_sessions() -> None:
    """Verify ``Server.sessions`` returns empty list without tmux server."""
    server = Server(socket_name="test_attached_session_no_server")
    assert server.sessions == []


def test_no_server_attached_sessions() -> None:
    """Verify ``Server.attached_sessions`` returns empty list without tmux server."""
    server = Server(socket_name="test_no_server_attached_sessions")
    assert server.attached_sessions == []


def test_no_server_is_alive() -> None:
    """Verify is_alive() returns False without tmux server."""
    dead_server = Server(socket_name="test_no_server_is_alive")
    assert not dead_server.is_alive()


def test_with_server_is_alive(server: Server) -> None:
    """Verify is_alive() returns True when tmux server is alive."""
    server.new_session()
    assert server.is_alive()


def test_raise_if_dead_no_server_raises() -> None:
    """Verify new_session() raises if tmux server is dead."""
    dead_server = Server(socket_name="test_attached_session_no_server")
    with pytest.raises(subprocess.SubprocessError):
        dead_server.raise_if_dead()


def test_raise_if_dead_does_not_raise_if_alive(server: Server) -> None:
    """Verify new_session() does not raise if tmux server is alive."""
    server.new_session()
    server.raise_if_dead()
