"""Test for libtmux Session object."""

from __future__ import annotations

import logging
import pathlib
import shutil
import typing as t

import pytest

from libtmux import exc
from libtmux._internal.types import StrPath
from libtmux.common import has_gte_version, has_lt_version
from libtmux.constants import WindowDirection
from libtmux.pane import Pane
from libtmux.session import Session
from libtmux.test.constants import TEST_SESSION_PREFIX
from libtmux.test.random import namer
from libtmux.window import Window

if t.TYPE_CHECKING:
    from libtmux.server import Server

logger = logging.getLogger(__name__)


def test_has_session(server: Server, session: Session) -> None:
    """Server.has_session returns True if has session_name exists."""
    TEST_SESSION_NAME = session.session_name
    assert TEST_SESSION_NAME is not None
    assert server.has_session(TEST_SESSION_NAME)
    if has_gte_version("2.1"):
        assert not server.has_session(TEST_SESSION_NAME[:-2])
        assert server.has_session(TEST_SESSION_NAME[:-2], exact=False)
    assert not server.has_session("asdf2314324321")


def test_select_window(session: Session) -> None:
    """Session.select_window moves window."""
    # get the current window_base_index, since different user tmux config
    # may start at 0 or 1, or whatever they want.
    window_idx = session.active_window.window_index
    assert window_idx is not None
    window_base_index = int(window_idx)

    session.new_window(window_name="test_window")
    window_count = len(session.windows)

    assert window_count >= 2  # 2 or more windows

    assert len(session.windows) == window_count

    # tmux selects a window, moves to it, shows it as active_window
    selected_window1 = session.select_window(window_base_index)
    assert isinstance(selected_window1, Window)
    active_window1 = session.active_window

    assert selected_window1.id == active_window1.id

    # again: tmux selects a window, moves to it, shows it as
    # active_window
    selected_window2 = session.select_window(window_base_index + 1)
    assert isinstance(selected_window2, Window)
    active_window2 = session.active_window

    assert selected_window2.id == active_window2.id

    # assure these windows were really different
    assert selected_window1.id != selected_window2.id


def test_select_window_returns_Window(session: Session) -> None:
    """Session.select_window returns Window object."""
    window_count = len(session.windows)
    assert len(session.windows) == window_count

    window_idx = session.active_window.window_index
    assert window_idx is not None
    window_base_index = int(window_idx)
    window = session.select_window(window_base_index)
    assert isinstance(window, Window)


def test_active_window(session: Session) -> None:
    """Session.active_window returns Window."""
    assert isinstance(session.active_window, Window)


def test_active_pane(session: Session) -> None:
    """Session.active_pane returns Pane."""
    assert isinstance(session.active_pane, Pane)


def test_session_rename(session: Session) -> None:
    """Session.rename_session renames session."""
    session_name = session.session_name
    assert session_name is not None
    TEST_SESSION_NAME = session_name

    test_name = "testingdis_sessname"
    session.rename_session(test_name)
    session_name = session.session_name
    assert session_name is not None
    assert session_name == test_name
    session.rename_session(TEST_SESSION_NAME)
    session_name = session.session_name
    assert session_name is not None
    assert session_name == TEST_SESSION_NAME


def test_new_session(server: Server) -> None:
    """Server.new_session creates new session."""
    new_session_name = TEST_SESSION_PREFIX + next(namer)
    new_session = server.new_session(session_name=new_session_name, detach=True)

    assert isinstance(new_session, Session)
    assert new_session.session_name == new_session_name


def test_show_options(session: Session) -> None:
    """Session.show_options() returns dict."""
    options = session.show_options()
    assert isinstance(options, dict)


def test_set_show_options_single(session: Session) -> None:
    """Set option then Session.show_options(key)."""
    session.set_option("history-limit", 20)
    assert session.show_option("history-limit") == 20

    session.set_option("history-limit", 40)
    assert session.show_option("history-limit") == 40

    assert session.show_options()["history-limit"] == 40


def test_set_show_option(session: Session) -> None:
    """Set option then Session.show_option(key)."""
    session.set_option("history-limit", 20)
    assert session.show_option("history-limit") == 20

    session.set_option("history-limit", 40)

    assert session.show_option("history-limit") == 40


def test_empty_session_option_returns_None(session: Session) -> None:
    """Verify Session.show_option returns None for unset option."""
    assert session.show_option("default-shell") is None


def test_show_option_unknown(session: Session) -> None:
    """Session.show_option raises UnknownOption for invalid option."""
    cmd_exception: type[exc.OptionError] = exc.UnknownOption
    if has_gte_version("3.0"):
        cmd_exception = exc.InvalidOption
    with pytest.raises(cmd_exception):
        session.show_option("moooz")


def test_show_option_ambiguous(session: Session) -> None:
    """Session.show_option raises AmbiguousOption for ambiguous option."""
    with pytest.raises(exc.AmbiguousOption):
        session.show_option("default-")


def test_set_option_ambiguous(session: Session) -> None:
    """Session.set_option raises AmbiguousOption for invalid option."""
    with pytest.raises(exc.AmbiguousOption):
        session.set_option("default-", 43)


def test_set_option_invalid(session: Session) -> None:
    """Session.set_option raises UnknownOption for invalid option."""
    if has_gte_version("2.4"):
        with pytest.raises(exc.InvalidOption):
            session.set_option("afewewfew", 43)
    else:
        with pytest.raises(exc.UnknownOption):
            session.set_option("afewewfew", 43)


def test_show_environment(session: Session) -> None:
    """Session.show_environment() returns dict."""
    vars_ = session.show_environment()
    assert isinstance(vars_, dict)


def test_set_show_environment_single(session: Session) -> None:
    """Set environment then Session.show_environment(key)."""
    session.set_environment("FOO", "BAR")
    assert session.getenv("FOO") == "BAR"

    session.set_environment("FOO", "DAR")
    assert session.getenv("FOO") == "DAR"

    assert session.show_environment()["FOO"] == "DAR"


def test_show_environment_not_set(session: Session) -> None:
    """Not set environment variable returns None."""
    assert session.getenv("BAR") is None


def test_remove_environment(session: Session) -> None:
    """Remove environment variable."""
    assert session.getenv("BAM") is None
    session.set_environment("BAM", "OK")
    assert session.getenv("BAM") == "OK"
    session.remove_environment("BAM")
    assert session.getenv("BAM") is None


def test_unset_environment(session: Session) -> None:
    """Unset environment variable."""
    assert session.getenv("BAM") is None
    session.set_environment("BAM", "OK")
    assert session.getenv("BAM") == "OK"
    session.unset_environment("BAM")
    assert session.getenv("BAM") is None


class PeriodRaisesBadSessionName(t.NamedTuple):
    """Test fixture for bad session name names."""

    test_id: str
    session_name: str
    raises: bool


PERIOD_RAISES_BAD_SESSION_NAME_FIXTURES: list[PeriodRaisesBadSessionName] = [
    PeriodRaisesBadSessionName(
        test_id="period_in_name",
        session_name="hey.period",
        raises=True,
    ),
    PeriodRaisesBadSessionName(
        test_id="colon_in_name",
        session_name="hey:its a colon",
        raises=True,
    ),
    PeriodRaisesBadSessionName(
        test_id="valid_name",
        session_name="hey moo",
        raises=False,
    ),
]


@pytest.mark.parametrize(
    list(PeriodRaisesBadSessionName._fields),
    PERIOD_RAISES_BAD_SESSION_NAME_FIXTURES,
    ids=[test.test_id for test in PERIOD_RAISES_BAD_SESSION_NAME_FIXTURES],
)
def test_periods_raise_bad_session_name(
    server: Server,
    session: Session,
    test_id: str,
    session_name: str,
    raises: bool,
) -> None:
    """Verify session names with periods raise BadSessionName."""
    new_name = session_name + "moo"  # used for rename / switch
    if raises:
        with pytest.raises(exc.BadSessionName):
            session.rename_session(new_name)

        with pytest.raises(exc.BadSessionName):
            server.new_session(session_name)

        with pytest.raises(exc.BadSessionName):
            server.has_session(session_name)

        with pytest.raises(exc.BadSessionName):
            server.switch_client(new_name)

        with pytest.raises(exc.BadSessionName):
            server.attach_session(new_name)

    else:
        server.new_session(session_name)
        server.has_session(session_name)
        session.rename_session(new_name)
        with pytest.raises(exc.LibTmuxException):
            server.switch_client(new_name)


def test_cmd_inserts_session_id(session: Session) -> None:
    """Verify Session.cmd() inserts session_id."""
    current_session_id = session.session_id
    last_arg = "last-arg"
    cmd = session.cmd("not-a-command", last_arg)
    assert "-t" in cmd.cmd
    assert current_session_id in cmd.cmd
    assert cmd.cmd[-1] == last_arg


class SessionWindowEnvironmentFixture(t.NamedTuple):
    """Test fixture for window environment variables in sessions."""

    test_id: str
    environment: dict[str, str]


SESSION_WINDOW_ENV_FIXTURES: list[SessionWindowEnvironmentFixture] = [
    SessionWindowEnvironmentFixture(
        test_id="single_env_var",
        environment={"ENV_VAR": "window"},
    ),
    SessionWindowEnvironmentFixture(
        test_id="multiple_env_vars",
        environment={"ENV_VAR_1": "window_1", "ENV_VAR_2": "window_2"},
    ),
]


@pytest.mark.skipif(
    has_lt_version("3.0"),
    reason="needs -e flag for new-window which was introduced in 3.0",
)
@pytest.mark.parametrize(
    list(SessionWindowEnvironmentFixture._fields),
    SESSION_WINDOW_ENV_FIXTURES,
    ids=[test.test_id for test in SESSION_WINDOW_ENV_FIXTURES],
)
def test_new_window_with_environment(
    session: Session,
    test_id: str,
    environment: dict[str, str],
) -> None:
    """Verify new window with environment vars."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    window = session.new_window(
        attach=True,
        window_name="window_with_environment",
        window_shell=f"{env} PS1='$ ' sh",
        environment=environment,
    )
    pane = window.active_pane
    assert pane is not None
    for k, v in environment.items():
        pane.send_keys(f"echo ${k}")
        assert pane.capture_pane()[-2] == v


@pytest.mark.skipif(
    has_gte_version("3.0"),
    reason="3.0 has the -e flag on new-window",
)
def test_new_window_with_environment_logs_warning_for_old_tmux(
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify new window with environment vars create a warning if tmux is too old."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    session.new_window(
        attach=True,
        window_name="window_with_environment",
        window_shell=f"{env} PS1='$ ' sh",
        environment={"ENV_VAR": "window"},
    )

    assert any("Environment flag ignored" in record.msg for record in caplog.records), (
        "Warning missing"
    )


@pytest.mark.skipif(
    has_lt_version("3.2"),
    reason="Only 3.2+ has the -a and -b flag on new-window",
)
def test_session_new_window_with_direction(
    session: Session,
) -> None:
    """Verify new window with direction."""
    window = session.active_window
    window.refresh()

    window_initial = session.new_window(window_name="Example")
    assert window_initial.window_index == "2"

    window_before = session.new_window(
        window_name="Window before",
        direction=WindowDirection.Before,
    )
    window_initial.refresh()
    assert window_before.window_index == "1"
    assert window_initial.window_index == "3"

    window_after = session.new_window(
        window_name="Window after",
        direction=WindowDirection.After,
    )
    window_initial.refresh()
    window_after.refresh()
    assert window_after.window_index == "3"
    assert window_initial.window_index == "4"
    assert window_before.window_index == "1"


@pytest.mark.skipif(
    has_gte_version("3.1"),
    reason="Only 3.1 has the -a and -b flag on new-window",
)
def test_session_new_window_with_direction_logs_warning_for_old_tmux(
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify new window with direction create a warning if tmux is too old."""
    session.new_window(
        window_name="session_window_with_direction",
        direction=WindowDirection.After,
    )

    assert any("Direction flag ignored" in record.msg for record in caplog.records), (
        "Warning missing"
    )


def test_session_context_manager(server: Server) -> None:
    """Test Session context manager functionality."""
    with server.new_session() as session:
        window = session.new_window()
        assert len(session.windows) >= 2  # Initial window + new window
        assert window in session.windows

    # Session should be killed after exiting context
    session_name = session.session_name
    assert session_name is not None
    assert not server.has_session(session_name)


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
def test_new_window_start_directory(
    test_id: str,
    start_directory: StrPath | None,
    description: str,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    user_path: pathlib.Path,
) -> None:
    """Test Session.new_window start_directory parameter handling."""
    monkeypatch.chdir(tmp_path)

    # Format path placeholders with actual fixture values
    actual_start_directory = start_directory
    expected_path = None

    if start_directory and str(start_directory) not in ["", "None"]:
        if "{user_path}" in str(start_directory):
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
    window = session.new_window(
        window_name=f"test_window_{test_id}",
        start_directory=actual_start_directory,
    )

    assert window.window_name == f"test_window_{test_id}"
    assert window in session.windows

    # Verify working directory if we have an expected path
    if expected_path:
        active_pane = window.active_pane
        assert active_pane is not None
        active_pane.refresh()
        assert active_pane.pane_current_path is not None
        actual_path = str(pathlib.Path(active_pane.pane_current_path).resolve())
        assert actual_path == expected_path


def test_new_window_start_directory_pathlib(
    session: Session, user_path: pathlib.Path
) -> None:
    """Test Session.new_window accepts pathlib.Path for start_directory."""
    # Pass pathlib.Path directly to test pathlib.Path acceptance
    window = session.new_window(
        window_name="test_pathlib_start_dir",
        start_directory=user_path,
    )

    assert window.window_name == "test_pathlib_start_dir"
    assert window in session.windows

    # Verify working directory
    active_pane = window.active_pane
    assert active_pane is not None
    active_pane.refresh()
    assert active_pane.pane_current_path is not None
    actual_path = str(pathlib.Path(active_pane.pane_current_path).resolve())
    expected_path = str(user_path.resolve())
    assert actual_path == expected_path
