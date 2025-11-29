"""Test for libtmux Server object."""

from __future__ import annotations

import logging
import os
import pathlib
import subprocess
import time
import typing as t

import pytest

from libtmux.server import Server

if t.TYPE_CHECKING:
    from libtmux._internal.types import StrPath
    from libtmux.session import Session

logger = logging.getLogger(__name__)


def test_has_session(server: Server, session: Session) -> None:
    """Server.has_session() returns True if session exists."""
    session_name = session.session_name
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
    vars_ = server.show_environment()
    assert isinstance(vars_, dict)


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
    assert mysession.session_name == "test_new_session"
    assert server.has_session("test_new_session")


def test_new_session_no_name(server: Server) -> None:
    """Server.new_session works with no name."""
    first_session = server.new_session()
    first_session_name = first_session.session_name
    assert first_session_name is not None
    assert server.has_session(first_session_name)

    expected_session_name = str(int(first_session_name) + 1)

    # When a new session is created, it should enumerate
    second_session = server.new_session()
    second_session_name = second_session.session_name
    assert expected_session_name == second_session_name
    assert second_session_name is not None
    assert server.has_session(second_session_name)


def test_new_session_shell(server: Server) -> None:
    """Verify ``Server.new_session`` creates valid session running w/ command."""
    cmd = "sleep 1m"
    mysession = server.new_session("test_new_session", window_command=cmd)
    window = mysession.windows[0]
    pane = window.panes[0]
    assert mysession.session_name == "test_new_session"
    assert server.has_session("test_new_session")

    pane_start_command = pane.pane_start_command
    assert pane_start_command is not None

    assert pane_start_command.replace('"', "") == cmd


def test_new_session_shell_env(server: Server) -> None:
    """Verify ``Server.new_session`` creates valid session running w/ command (#553)."""
    cmd = "sleep 1m"
    env = dict(os.environ)
    mysession = server.new_session(
        "test_new_session_env",
        window_command=cmd,
        environment=env,
    )
    time.sleep(0.1)
    window = mysession.windows[0]
    pane = window.panes[0]
    assert mysession.session_name == "test_new_session_env"
    assert server.has_session("test_new_session_env")

    pane_start_command = pane.pane_start_command
    assert pane_start_command is not None

    assert pane_start_command.replace('"', "") == cmd


@pytest.mark.skipif(True, reason="tmux 3.2 returns wrong width - test needs rework")
def test_new_session_width_height(server: Server) -> None:
    """Verify ``Server.new_session`` creates valid session running w/ dimensions."""
    cmd = "/usr/bin/env PS1='$ ' sh"
    mysession = server.new_session(
        "test_new_session_width_height",
        window_command=cmd,
        x=32,
        y=32,
    )
    window = mysession.windows[0]
    pane = window.panes[0]
    assert pane.display_message("#{window_width}", get_text=True)[0] == "32"
    assert pane.display_message("#{window_height}", get_text=True)[0] == "32"


def test_new_session_environmental_variables(
    server: Server,
) -> None:
    """Server.new_session creates and returns valid session."""
    my_session = server.new_session("test_new_session", environment={"FOO": "HI"})

    assert my_session.show_environment()["FOO"] == "HI"


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
    with pytest.raises(subprocess.CalledProcessError):
        dead_server.raise_if_dead()


def test_raise_if_dead_does_not_raise_if_alive(server: Server) -> None:
    """Verify new_session() does not raise if tmux server is alive."""
    server.new_session()
    server.raise_if_dead()


def test_on_init(server: Server) -> None:
    """Verify on_init callback is called during Server initialization."""
    called_with: list[Server] = []

    def on_init(server: Server) -> None:
        called_with.append(server)

    myserver = Server(socket_name="test_on_init", on_init=on_init)
    try:
        assert len(called_with) == 1
        assert called_with[0] is myserver
    finally:
        if myserver.is_alive():
            myserver.kill()


def test_socket_name_factory(server: Server) -> None:
    """Verify socket_name_factory generates socket names."""
    socket_names: list[str] = []

    def socket_name_factory() -> str:
        name = f"test_socket_{len(socket_names)}"
        socket_names.append(name)
        return name

    myserver = Server(socket_name_factory=socket_name_factory)
    try:
        assert myserver.socket_name == "test_socket_0"
        assert socket_names == ["test_socket_0"]

        # Creating another server should use factory again
        myserver2 = Server(socket_name_factory=socket_name_factory)
        try:
            assert myserver2.socket_name == "test_socket_1"
            assert socket_names == ["test_socket_0", "test_socket_1"]
        finally:
            if myserver2.is_alive():
                myserver2.kill()
    finally:
        if myserver.is_alive():
            myserver.kill()
        if myserver2.is_alive():
            myserver2.kill()


def test_socket_name_precedence(server: Server) -> None:
    """Verify socket_name takes precedence over socket_name_factory."""

    def socket_name_factory() -> str:
        return "from_factory"

    myserver = Server(
        socket_name="explicit_name",
        socket_name_factory=socket_name_factory,
    )
    myserver2 = Server(socket_name_factory=socket_name_factory)
    try:
        assert myserver.socket_name == "explicit_name"

        # Without socket_name, factory is used
        assert myserver2.socket_name == "from_factory"
    finally:
        if myserver.is_alive():
            myserver.kill()
        if myserver2.is_alive():
            myserver2.kill()


def test_server_context_manager(TestServer: type[Server]) -> None:
    """Test Server context manager functionality."""
    with TestServer() as server:
        session = server.new_session()
        assert server.is_alive()
        assert len(server.sessions) == 1
        assert session in server.sessions

    # Server should be killed after exiting context
    assert not server.is_alive()


class StartDirectoryTestFixture(t.NamedTuple):
    """Test fixture for start_directory parameter testing."""

    test_id: str
    start_directory: StrPath | None
    description: str


START_DIRECTORY_TEST_FIXTURES: list[StartDirectoryTestFixture] = [
    StartDirectoryTestFixture(
        test_id="none_value",
        start_directory=None,
        description="None should not add -c flag",
    ),
    StartDirectoryTestFixture(
        test_id="empty_string",
        start_directory="",
        description="Empty string should not add -c flag",
    ),
    StartDirectoryTestFixture(
        test_id="user_path",
        start_directory="{user_path}",
        description="User path should add -c flag",
    ),
    StartDirectoryTestFixture(
        test_id="relative_path",
        start_directory="./relative/path",
        description="Relative path should add -c flag",
    ),
]


@pytest.mark.parametrize(
    list(StartDirectoryTestFixture._fields),
    START_DIRECTORY_TEST_FIXTURES,
    ids=[test.test_id for test in START_DIRECTORY_TEST_FIXTURES],
)
def test_new_session_start_directory(
    test_id: str,
    start_directory: StrPath | None,
    description: str,
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    user_path: pathlib.Path,
) -> None:
    """Test Server.new_session start_directory parameter handling."""
    monkeypatch.chdir(tmp_path)

    # Format path placeholders with actual fixture values
    actual_start_directory = start_directory
    expected_path = None

    if start_directory and str(start_directory) not in {"", "None"}:
        if f"{user_path}" in str(start_directory):
            # Replace placeholder with actual user_path
            actual_start_directory = str(start_directory).format(user_path=user_path)
            expected_path = str(user_path)
        elif str(start_directory).startswith("./"):
            # For relative paths, use tmp_path as base
            temp_dir = tmp_path / "relative" / "path"
            temp_dir.mkdir(parents=True, exist_ok=True)
            actual_start_directory = str(temp_dir)
            expected_path = str(temp_dir.resolve())

    # Should not raise an error
    session = server.new_session(
        session_name=f"test_session_{test_id}",
        start_directory=actual_start_directory,
    )

    assert session.session_name == f"test_session_{test_id}"
    assert server.has_session(f"test_session_{test_id}")

    # Verify working directory if we have an expected path
    if expected_path:
        active_pane = session.active_window.active_pane
        assert active_pane is not None
        active_pane.refresh()
        assert active_pane.pane_current_path is not None
        actual_path = str(pathlib.Path(active_pane.pane_current_path).resolve())
        assert actual_path == expected_path


def test_new_session_start_directory_pathlib(
    server: Server,
    user_path: pathlib.Path,
) -> None:
    """Test Server.new_session accepts pathlib.Path for start_directory."""
    # Pass pathlib.Path directly to test pathlib.Path acceptance
    session = server.new_session(
        session_name="test_pathlib_start_dir",
        start_directory=user_path,
    )

    assert session.session_name == "test_pathlib_start_dir"
    assert server.has_session("test_pathlib_start_dir")

    # Verify working directory
    active_pane = session.active_window.active_pane
    assert active_pane is not None
    active_pane.refresh()
    assert active_pane.pane_current_path is not None
    actual_path = str(pathlib.Path(active_pane.pane_current_path).resolve())
    expected_path = str(user_path.resolve())
    assert actual_path == expected_path
