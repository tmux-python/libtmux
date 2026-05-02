"""Test for libtmux Server object."""

from __future__ import annotations

import logging
import os
import pathlib
import shutil
import subprocess
import time
import typing as t

import pytest

from libtmux import exc
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


def test_new_session_returns_populated_session(server: Server) -> None:
    """Server.new_session returns Session populated from -P output."""
    session = server.new_session(session_name="test_populated")
    assert session.session_id is not None
    assert session.session_name == "test_populated"
    assert session.window_id is not None
    assert session.pane_id is not None


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


def test_no_server_sessions(server: Server) -> None:
    """Verify ``Server.sessions`` returns empty list without tmux server."""
    assert server.sessions == []


def test_no_server_attached_sessions(server: Server) -> None:
    """Verify ``Server.attached_sessions`` returns empty list without tmux server."""
    assert server.attached_sessions == []


def test_no_server_is_alive(server: Server) -> None:
    """Verify is_alive() returns False without tmux server."""
    assert not server.is_alive()


def test_with_server_is_alive(server: Server) -> None:
    """Verify is_alive() returns True when tmux server is alive."""
    server.new_session()
    assert server.is_alive()


def test_raise_if_dead_no_server_raises(server: Server) -> None:
    """Verify ``Server.raise_if_dead`` raises if tmux server is dead."""
    with pytest.raises(subprocess.CalledProcessError):
        server.raise_if_dead()


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


def test_tmux_bin_default(server: Server) -> None:
    """Default tmux_bin is None, falls back to shutil.which."""
    assert server.tmux_bin is None


def test_tmux_bin_custom_path(caplog: pytest.LogCaptureFixture) -> None:
    """Custom tmux_bin path is used for commands.

    Uses a manual Server instance (not the ``server`` fixture) because this
    test must control the tmux_bin parameter at construction time.
    """
    tmux_path = shutil.which("tmux")
    assert tmux_path is not None
    s = Server(socket_name="test_tmux_bin", tmux_bin=tmux_path)
    try:
        assert s.tmux_bin == tmux_path
        with caplog.at_level(logging.DEBUG, logger="libtmux.common"):
            s.cmd("list-sessions")
        running_records = [r for r in caplog.records if hasattr(r, "tmux_cmd")]
        assert any(tmux_path in r.tmux_cmd for r in running_records)
    finally:
        if s.is_alive():
            s.kill()


def test_tmux_bin_invalid_path() -> None:
    """Invalid tmux_bin raises TmuxCommandNotFound."""
    from libtmux import exc

    s = Server(tmux_bin="/nonexistent/tmux")
    with pytest.raises(exc.TmuxCommandNotFound):
        s.cmd("list-sessions")


def test_tmux_bin_invalid_path_raise_if_dead() -> None:
    """Invalid tmux_bin raises TmuxCommandNotFound in raise_if_dead()."""
    from libtmux import exc

    s = Server(tmux_bin="/nonexistent/tmux")
    with pytest.raises(exc.TmuxCommandNotFound):
        s.raise_if_dead()


class ConfirmBeforeCase(t.NamedTuple):
    """Test case for confirm_before()."""

    test_id: str
    confirm_key: str
    use_default_yes: bool
    custom_confirm_key: str | None
    option_name: str
    expected_value: str
    min_tmux_version: str | None


CONFIRM_BEFORE_CASES: list[ConfirmBeforeCase] = [
    ConfirmBeforeCase(
        test_id="confirm_y",
        confirm_key="y",
        use_default_yes=False,
        custom_confirm_key=None,
        option_name="@cf_test_y",
        expected_value="yes",
        min_tmux_version="3.4",
    ),
    ConfirmBeforeCase(
        test_id="default_yes_enter",
        confirm_key="Enter",
        use_default_yes=True,
        custom_confirm_key=None,
        option_name="@cf_test_enter",
        expected_value="yes",
        min_tmux_version="3.4",
    ),
]


@pytest.mark.parametrize(
    list(ConfirmBeforeCase._fields),
    CONFIRM_BEFORE_CASES,
    ids=[c.test_id for c in CONFIRM_BEFORE_CASES],
)
def test_confirm_before(
    test_id: str,
    confirm_key: str,
    use_default_yes: bool,
    custom_confirm_key: str | None,
    option_name: str,
    expected_value: str,
    min_tmux_version: str | None,
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """Test Server.confirm_before() with send-keys -K confirmation."""
    from libtmux.common import has_gte_version

    if min_tmux_version and not has_gte_version(min_tmux_version):
        pytest.skip(f"Requires tmux {min_tmux_version}+")

    with control_mode() as ctl:
        kwargs: dict[str, t.Any] = {"target_client": ctl.client_name}
        if use_default_yes:
            kwargs["default_yes"] = True
        if custom_confirm_key is not None:
            kwargs["confirm_key"] = custom_confirm_key

        server.confirm_before(f"set -g {option_name} {expected_value}", **kwargs)
        server.cmd("send-keys", "-K", "-c", ctl.client_name, confirm_key)

    result = server.cmd("show-options", "-gv", option_name)
    assert result.stdout[0] == expected_value


class CommandPromptCase(t.NamedTuple):
    """Test case for command_prompt()."""

    test_id: str
    template: str
    keys: list[str]
    inputs: str | None
    option_name: str
    expected_value: str
    min_tmux_version: str | None


COMMAND_PROMPT_CASES: list[CommandPromptCase] = [
    CommandPromptCase(
        test_id="type_and_submit",
        template="set -g @cp_typed '%1'",
        keys=["h", "e", "l", "l", "o", "Enter"],
        inputs=None,
        option_name="@cp_typed",
        expected_value="hello",
        min_tmux_version="3.4",
    ),
    CommandPromptCase(
        test_id="prefill_and_submit",
        template="set -g @cp_prefill '%1'",
        keys=["Enter"],
        inputs="prefilled",
        option_name="@cp_prefill",
        expected_value="prefilled",
        min_tmux_version="3.4",
    ),
]


@pytest.mark.parametrize(
    list(CommandPromptCase._fields),
    COMMAND_PROMPT_CASES,
    ids=[c.test_id for c in COMMAND_PROMPT_CASES],
)
def test_command_prompt(
    test_id: str,
    template: str,
    keys: list[str],
    inputs: str | None,
    option_name: str,
    expected_value: str,
    min_tmux_version: str | None,
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """Test Server.command_prompt() with send-keys -K input."""
    from libtmux.common import has_gte_version

    if min_tmux_version and not has_gte_version(min_tmux_version):
        pytest.skip(f"Requires tmux {min_tmux_version}+")

    with control_mode() as ctl:
        kwargs: dict[str, t.Any] = {"target_client": ctl.client_name}
        if inputs is not None:
            kwargs["inputs"] = inputs

        server.command_prompt(template, **kwargs)

        for key in keys:
            server.cmd("send-keys", "-K", "-c", ctl.client_name, key)

    result = server.cmd("show-options", "-gv", option_name)
    assert result.stdout[0] == expected_value


@pytest.mark.parametrize(
    ("kwargs", "expected_flag", "min_tmux_version"),
    [
        ({"expand_format": True}, "-F", "3.3"),
        ({"literal": True}, "-l", "3.6"),
        ({"bspace_exit": True}, "-e", None),
    ],
    ids=["expand_format_v33", "literal_v36", "bspace_exit"],
)
def test_command_prompt_extra_flags(
    kwargs: dict[str, t.Any],
    expected_flag: str,
    min_tmux_version: str | None,
    monkeypatch: pytest.MonkeyPatch,
    server: Server,
) -> None:
    """``command_prompt`` exposes -F/-l/-e flags.

    End-to-end behaviour for these flags depends on tmux internals
    that are awkward to drive from a headless test (format
    expansion, comma-split disabling, backspace-exit). Verify the
    constructed argv instead, matching the test_display_menu_flags
    monkeypatch pattern.
    """
    from libtmux.common import has_gte_version

    if min_tmux_version and not has_gte_version(min_tmux_version):
        pytest.skip(f"Requires tmux {min_tmux_version}+")

    captured: list[tuple[str, ...]] = []
    real_cmd = server.cmd

    class _StubResult:
        stderr: t.ClassVar[list[str]] = []
        stdout: t.ClassVar[list[str]] = []

    def fake_cmd(cmd: str, *args: str, **_kw: t.Any) -> t.Any:
        if cmd == "command-prompt":
            captured.append((cmd, *args))
            return _StubResult()
        return real_cmd(cmd, *args, **_kw)

    monkeypatch.setattr(server, "cmd", fake_cmd)
    server.command_prompt("set -g @x '%1'", **kwargs)

    assert captured, "Server.cmd was not invoked"
    _name, *flags = captured[0]
    assert expected_flag in flags


class DisplayMenuCase(t.NamedTuple):
    """Test case for display_menu() flag variations."""

    test_id: str
    items: tuple[str, ...]
    kwargs: dict[str, t.Any]
    min_tmux_version: str | None


_MENU_ITEM = ("First", "1", "select-pane")


DISPLAY_MENU_CASES: list[DisplayMenuCase] = [
    DisplayMenuCase(
        test_id="basic",
        items=_MENU_ITEM,
        kwargs={},
        min_tmux_version=None,
    ),
    DisplayMenuCase(
        test_id="with_title",
        items=_MENU_ITEM,
        kwargs={"title": "menu_title"},
        min_tmux_version=None,
    ),
    DisplayMenuCase(
        test_id="with_position",
        items=_MENU_ITEM,
        kwargs={"x": "C", "y": "C"},
        min_tmux_version=None,
    ),
    DisplayMenuCase(
        test_id="with_starting_choice",
        items=_MENU_ITEM,
        kwargs={"starting_choice": "0"},
        min_tmux_version=None,
    ),
    DisplayMenuCase(
        test_id="with_border_lines_v33",
        items=_MENU_ITEM,
        kwargs={"border_lines": "single"},
        min_tmux_version="3.3",
    ),
    DisplayMenuCase(
        test_id="with_style_v33",
        items=_MENU_ITEM,
        kwargs={"style": "bg=blue"},
        min_tmux_version="3.3",
    ),
    DisplayMenuCase(
        test_id="with_border_style_v33",
        items=_MENU_ITEM,
        kwargs={"border_style": "fg=red"},
        min_tmux_version="3.3",
    ),
    DisplayMenuCase(
        test_id="with_stay_open",
        items=_MENU_ITEM,
        kwargs={"stay_open": True},
        min_tmux_version="3.2",
    ),
    DisplayMenuCase(
        test_id="with_selected_style_v34",
        items=_MENU_ITEM,
        kwargs={"selected_style": "bg=yellow"},
        min_tmux_version="3.4",
    ),
    DisplayMenuCase(
        test_id="with_mouse_v35",
        items=_MENU_ITEM,
        kwargs={"mouse": True},
        min_tmux_version="3.5",
    ),
]


@pytest.mark.parametrize(
    list(DisplayMenuCase._fields),
    DISPLAY_MENU_CASES,
    ids=[c.test_id for c in DISPLAY_MENU_CASES],
)
def test_display_menu_flags(
    test_id: str,
    items: tuple[str, ...],
    kwargs: dict[str, t.Any],
    min_tmux_version: str | None,
    monkeypatch: pytest.MonkeyPatch,
    server: Server,
) -> None:
    """Test Server.display_menu() argument construction.

    ``Server.display_menu``'s own docstring states it cannot be tested
    with :class:`ControlMode` (``tty.sy=0`` makes tmux's
    ``menu_prepare()`` return NULL and the call hangs). Without a
    TTY-backed client there is no way to invoke ``tmux display-menu``
    end-to-end, so this test stubs ``Server.cmd`` to capture and assert
    the constructed argument vector instead — the only deviation from
    the test-suite's standard "use real tmux" pattern.
    """
    from libtmux.common import has_gte_version

    if min_tmux_version and not has_gte_version(min_tmux_version):
        pytest.skip(f"Requires tmux {min_tmux_version}+")

    captured: list[tuple[str, ...]] = []
    real_cmd = server.cmd

    class _StubResult:
        stderr: t.ClassVar[list[str]] = []
        stdout: t.ClassVar[list[str]] = []

    def fake_cmd(cmd: str, *args: str, **_kw: t.Any) -> t.Any:
        if cmd == "display-menu":
            captured.append((cmd, *args))
            return _StubResult()
        return real_cmd(cmd, *args, **_kw)

    monkeypatch.setattr(server, "cmd", fake_cmd)
    server.display_menu(*items, **kwargs)

    assert captured, "Server.cmd was not invoked"
    cmd, *flags = captured[0]
    assert cmd == "display-menu"
    # Items are appended at the end; every non-boolean flag value
    # should appear somewhere in the constructed argv. (Boolean
    # flags emit only the switch, not a value.)
    for value in kwargs.values():
        if isinstance(value, bool):
            continue
        assert str(value) in flags
    for item in items:
        assert item in flags


def test_lock_server(
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """Test Server.lock_server() runs without error."""
    with control_mode():
        server.lock_server()


def test_lock_client(
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """Test Server.lock_client() runs without error."""
    with control_mode():
        server.lock_client()


def test_refresh_client(
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """Test Server.refresh_client() runs without error."""
    with control_mode():
        server.refresh_client()


def test_suspend_client(
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """Test Server.suspend_client() runs without error."""
    with control_mode():
        server.suspend_client()


def test_server_access_list(server: Server) -> None:
    """Test Server.server_access() list mode."""
    from libtmux.common import has_gte_version

    if not has_gte_version("3.3"):
        pytest.skip("server-access added in tmux 3.3")

    server.new_session(session_name="access_test")
    result = server.server_access(list_access=True)
    assert isinstance(result, list)


def test_start_server(server: Server) -> None:
    """Test Server.start_server() runs without error."""
    server.new_session(session_name="startsvr_test")
    server.start_server()  # idempotent — already running


def test_bind_unbind_key(server: Server) -> None:
    """Test Server.bind_key() and unbind_key() cycle."""
    server.new_session(session_name="bind_test")

    server.bind_key("F12", "display-message bound", key_table="root")

    # Verify binding exists
    keys = server.list_keys(key_table="root")
    assert any("F12" in line for line in keys)

    # Unbind
    server.unbind_key("F12", key_table="root")

    # Verify binding gone
    keys = server.list_keys(key_table="root")
    assert not any("F12" in line and "display-message" in line for line in keys)


def test_list_keys(server: Server) -> None:
    """Test Server.list_keys() returns key bindings."""
    server.new_session(session_name="listkeys_test")
    result = server.list_keys()
    assert isinstance(result, list)
    assert len(result) > 0  # default bindings exist


def test_list_commands(server: Server) -> None:
    """Test Server.list_commands() returns command listing."""
    server.new_session(session_name="listcmds_test")

    # All commands
    result = server.list_commands()
    assert len(result) > 50  # tmux has many commands

    # Filtered
    result = server.list_commands(command_name="send-keys")
    assert len(result) >= 1
    assert "send-keys" in result[0]


def test_show_messages(
    control_mode: t.Callable[..., t.Any],
    server: Server,
) -> None:
    """Test Server.show_messages() returns message log.

    ``tmux show-messages`` resolves the log against a target client
    (see ``cmd-show-messages.c``). In headless CI no client is
    attached, so spawn one via :func:`control_mode` and target it.
    """
    with control_mode() as ctl:
        result = server.show_messages(target_client=ctl.client_name)
    assert isinstance(result, list)


def test_show_messages_terminals_jobs(server: Server) -> None:
    """Test Server.show_messages(terminals=...) and (jobs=...) work clientless.

    ``-T`` and ``-J`` are early-return paths in cmd-show-messages.c that
    don't reach ``format_create_from_target``, so they don't require a
    client. Verify both modes return a list without raising.
    """
    server.new_session(session_name="showmsg_alt_test")

    terminals = server.show_messages(terminals=True)
    assert isinstance(terminals, list)

    jobs = server.show_messages(jobs=True)
    assert isinstance(jobs, list)


def test_show_prompt_history(server: Server) -> None:
    """Test Server.show_prompt_history() returns history."""
    from libtmux.common import has_gte_version

    if not has_gte_version("3.3"):
        pytest.skip("show-prompt-history added in tmux 3.3")

    server.new_session(session_name="showph_test")
    result = server.show_prompt_history()
    assert isinstance(result, list)


def test_clear_prompt_history(server: Server) -> None:
    """Test Server.clear_prompt_history() clears history."""
    from libtmux.common import has_gte_version

    if not has_gte_version("3.3"):
        pytest.skip("clear-prompt-history added in tmux 3.3")

    server.new_session(session_name="clearph_test")
    server.clear_prompt_history()
    # Verify specific type can be cleared
    server.clear_prompt_history(prompt_type="command")


def test_wait_for_set_flag(server: Server) -> None:
    """Test Server.wait_for() with set_flag."""
    server.new_session(session_name="wait_test")
    # Just set the flag — should not block or error
    server.wait_for("test_channel_set", set_flag=True)


def test_run_shell_basic(server: Server) -> None:
    """Test Server.run_shell() executes command and returns output."""
    from libtmux.common import has_gte_version

    # tmux <3.5 does not write run-shell stdout back to the cmdq subprocess.
    # Restored by upstream commit fb37d52d, first released in 3.5.
    if not has_gte_version("3.5"):
        pytest.skip("run-shell stdout passthrough requires tmux 3.5+")

    server.new_session(session_name="run_shell_test")
    result = server.run_shell("echo hello_from_run_shell")
    assert result is not None
    assert any("hello_from_run_shell" in line for line in result)


def test_run_shell_background(server: Server) -> None:
    """Test Server.run_shell() in background mode."""
    server.new_session(session_name="run_shell_bg_test")
    result = server.run_shell("echo bg_test", background=True)
    assert result is None


class BufferCase(t.NamedTuple):
    """Test case for buffer operations."""

    test_id: str
    data: str
    buffer_name: str | None
    append: bool | None
    expected_content: str


BUFFER_CASES: list[BufferCase] = [
    BufferCase(
        test_id="set_show_default",
        data="hello_buf",
        buffer_name=None,
        append=None,
        expected_content="hello_buf",
    ),
    BufferCase(
        test_id="set_show_named",
        data="named_data",
        buffer_name="mybuf",
        append=None,
        expected_content="named_data",
    ),
]


@pytest.mark.parametrize(
    list(BufferCase._fields),
    BUFFER_CASES,
    ids=[c.test_id for c in BUFFER_CASES],
)
def test_buffer_set_show(
    test_id: str,
    data: str,
    buffer_name: str | None,
    append: bool | None,
    expected_content: str,
    server: Server,
) -> None:
    """Test Server.set_buffer() and show_buffer() cycle."""
    server.new_session(session_name=f"buf_{test_id}")
    kwargs: dict[str, t.Any] = {}
    if buffer_name is not None:
        kwargs["buffer_name"] = buffer_name
    if append is not None:
        kwargs["append"] = append

    server.set_buffer(data, **kwargs)
    result = server.show_buffer(buffer_name=buffer_name)
    assert result == expected_content


def test_buffer_append(server: Server) -> None:
    """Test Server.set_buffer() with append flag."""
    server.new_session(session_name="buf_append")
    server.set_buffer("first", buffer_name="append_test")
    server.set_buffer("_second", buffer_name="append_test", append=True)
    result = server.show_buffer(buffer_name="append_test")
    assert result == "first_second"


def test_buffer_delete(server: Server) -> None:
    """Test Server.delete_buffer()."""
    server.new_session(session_name="buf_delete")
    server.set_buffer("to_delete", buffer_name="del_buf")
    # Verify it exists
    assert server.show_buffer(buffer_name="del_buf") == "to_delete"

    # Delete it
    server.delete_buffer(buffer_name="del_buf")

    # Verify it's gone — show-buffer should raise
    with pytest.raises(exc.LibTmuxException):
        server.show_buffer(buffer_name="del_buf")


def test_buffer_save_load(server: Server, tmp_path: pathlib.Path) -> None:
    """Test Server.save_buffer() and load_buffer() cycle."""
    server.new_session(session_name="buf_saveload")

    # Set and save
    server.set_buffer("save_test_data")
    buf_file = tmp_path / "saved_buf.txt"
    server.save_buffer(buf_file)

    # Verify file content
    assert buf_file.read_text() == "save_test_data"

    # Load into a named buffer
    server.load_buffer(buf_file, buffer_name="loaded_buf")
    assert server.show_buffer(buffer_name="loaded_buf") == "save_test_data"


def test_buffer_save_append(server: Server, tmp_path: pathlib.Path) -> None:
    """Test Server.save_buffer() with append flag."""
    server.new_session(session_name="buf_saveappend")

    buf_file = tmp_path / "append_buf.txt"

    server.set_buffer("first_line", buffer_name="app1")
    server.save_buffer(buf_file, buffer_name="app1")

    server.set_buffer("second_line", buffer_name="app2")
    server.save_buffer(buf_file, buffer_name="app2", append=True)

    content = buf_file.read_text()
    assert "first_line" in content
    assert "second_line" in content


def test_list_buffers(server: Server) -> None:
    """Test Server.list_buffers()."""
    server.new_session(session_name="buf_list")
    server.set_buffer("buf_a", buffer_name="list_a")
    server.set_buffer("buf_b", buffer_name="list_b")

    result = server.list_buffers()
    assert len(result) >= 2


def test_if_shell_true(server: Server) -> None:
    """Test Server.if_shell() with true condition."""
    server.new_session(session_name="ifshell_test")
    server.if_shell("true", "set -g @if_test_true yes")

    result = server.cmd("show-options", "-gv", "@if_test_true")
    assert result.stdout[0] == "yes"


def test_if_shell_false_with_else(server: Server) -> None:
    """Test Server.if_shell() with false condition and else branch."""
    server.new_session(session_name="ifshell_else")
    server.if_shell(
        "false",
        "set -g @if_else_test yes",
        else_command="set -g @if_else_test no",
    )

    result = server.cmd("show-options", "-gv", "@if_else_test")
    assert result.stdout[0] == "no"


def test_source_file(server: Server, tmp_path: pathlib.Path) -> None:
    """Test Server.source_file() sources a config file."""
    server.new_session(session_name="source_test")

    conf = tmp_path / "source_test.conf"
    conf.write_text("set -g @source_test_opt yes\n")

    server.source_file(conf)

    # Verify the option was set
    result = server.cmd("show-options", "-gv", "@source_test_opt")
    assert result.stdout[0] == "yes"


def test_source_file_quiet(server: Server) -> None:
    """Test Server.source_file() with quiet flag ignores missing files."""
    server.new_session(session_name="source_quiet")

    # Non-existent file with quiet should not raise
    server.source_file("/nonexistent/path.conf", quiet=True)


def test_list_clients(server: Server) -> None:
    """Test Server.list_clients() returns list without error."""
    server.new_session(session_name="list_clients_test")
    result = server.list_clients()
    assert isinstance(result, list)


def test_new_session_client_flags(
    server: Server,
) -> None:
    """Test Server.new_session() with client_flags flag."""
    session = server.new_session(
        session_name="flags_test",
        client_flags="no-output",
    )
    assert session.session_name == "flags_test"
