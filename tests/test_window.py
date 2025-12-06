"""Test for libtmux Window object."""

from __future__ import annotations

import logging
import pathlib
import shutil
import time
import typing as t

import pytest

from libtmux import exc
from libtmux._internal.query_list import ObjectDoesNotExist
from libtmux.constants import (
    OptionScope,
    PaneDirection,
    ResizeAdjustmentDirection,
    WindowDirection,
)
from libtmux.pane import Pane
from libtmux.server import Server
from libtmux.window import Window

if t.TYPE_CHECKING:
    from libtmux._internal.types import StrPath
    from libtmux.session import Session

logger = logging.getLogger(__name__)


def test_select_window(session: Session) -> None:
    """Test Window.select_window()."""
    window_count = len(session.windows)
    # to do, get option for   base-index from tmux
    # for now however, let's get the index from the first window.
    assert window_count == 1

    assert session.active_window.window_index is not None
    window_base_index = int(session.active_window.window_index)

    window = session.new_window(window_name="testing 3")

    # self.assertEqual(2,
    # int(session.active_window.index))
    assert window.window_index is not None
    assert int(window_base_index) + 1 == int(window.window_index)

    session.select_window(str(window_base_index))
    assert window_base_index == int(session.active_window.window_index)

    session.select_window("testing 3")
    assert session.active_window.window_index is not None
    assert int(window_base_index) + 1 == int(session.active_window.window_index)

    assert len(session.windows) == 2


def test_fresh_window_data(session: Session) -> None:
    """Verify window data is fresh."""
    active_window = session.active_window
    assert active_window is not None
    pane_base_idx = active_window._show_option("pane-base-index", global_=True)
    assert pane_base_idx is not None
    pane_base_index = int(pane_base_idx)

    assert len(session.windows) == 1

    assert len(session.active_window.panes) == 1
    current_windows = len(session.windows)
    assert session.session_id != "@0"
    assert current_windows == 1

    assert len(session.active_window.panes) == 1
    assert isinstance(session.server, Server)
    # len(session.active_window.panes))

    assert len(session.windows) == 1
    assert len(session.active_window.panes) == 1
    for w in session.windows:
        assert isinstance(w, Window)
    window = session.active_window
    assert isinstance(window, Window)
    assert len(session.active_window.panes) == 1
    window.split()

    active_window = session.active_window
    assert active_window is not None
    pane_to_select = active_window.panes.get(pane_index=str(pane_base_index))
    assert pane_to_select is not None
    pane_to_select.select()

    active_pane = session.active_pane
    assert active_pane is not None
    active_pane.send_keys("cd /srv/www/flaskr")

    pane_to_select_2 = active_window.panes.get(pane_index=str(pane_base_index + 1))
    assert pane_to_select_2 is not None
    pane_to_select_2.select()
    active_pane = session.active_pane
    assert active_pane is not None
    active_pane.send_keys("source .venv/bin/activate")
    session.new_window(window_name="second")
    current_windows += 1
    assert current_windows == len(session.windows)
    session.new_window(window_name="hey")
    current_windows += 1
    assert current_windows == len(session.windows)

    session.select_window("1")
    window_to_kill = session.windows.get(window_name="hey")
    assert window_to_kill is not None
    window_to_kill.kill()
    current_windows -= 1
    assert current_windows == len(session.windows)


def test_newest_pane_data(session: Session) -> None:
    """Test window.panes has fresh data."""
    window = session.new_window(window_name="test", attach=True)
    assert isinstance(window, Window)
    assert len(window.panes) == 1
    window.split(attach=True)

    assert len(window.panes) == 2
    # note: the below used to accept -h, removing because split now
    # has attach as its only argument now
    window.split(attach=True)
    assert len(window.panes) == 3


def test_active_pane(session: Session) -> None:
    """Window.active_window returns active Pane."""
    window = session.active_window  # current window
    assert isinstance(window.active_pane, Pane)


def test_split(session: Session) -> None:
    """Window.split() splits window, returns new Pane, vertical."""
    window_name = "test split window"
    window = session.new_window(window_name=window_name, attach=True)
    pane = window.split()
    assert len(window.panes) == 2
    assert isinstance(pane, Pane)

    assert window.window_width is not None
    first_pane = window.panes[0]
    assert first_pane.pane_height is not None

    assert float(first_pane.pane_height) <= ((float(window.window_width) + 1) / 2)


def test_split_shell(session: Session) -> None:
    """Window.split() splits window, returns new Pane, vertical."""
    window_name = "test split window"
    cmd = "sleep 1m"
    window = session.new_window(window_name=window_name, attach=True)
    pane = window.split(shell=cmd)
    assert len(window.panes) == 2
    assert isinstance(pane, Pane)

    first_pane = window.panes[0]
    assert first_pane.pane_height is not None
    assert window.window_width is not None

    assert float(first_pane.pane_height) <= ((float(window.window_width) + 1) / 2)
    pane_start_command = pane.pane_start_command or ""
    assert pane_start_command.replace('"', "") == cmd


def test_split_horizontal(session: Session) -> None:
    """Window.split() splits window, returns new Pane, horizontal."""
    window_name = "test split window"
    window = session.new_window(window_name=window_name, attach=True)
    pane = window.split(direction=PaneDirection.Right)
    assert len(window.panes) == 2
    assert isinstance(pane, Pane)

    first_pane = window.panes[0]

    assert first_pane.pane_width is not None
    assert window.window_width is not None

    assert float(first_pane.pane_width) <= ((float(window.window_width) + 1) / 2)


def test_split_size(session: Session) -> None:
    """Window.split() respects size."""
    window = session.new_window(window_name="split window size")
    window.resize(height=100, width=100)

    pane = window.split(size=10)
    assert pane.pane_height == "10"

    pane = window.split(direction=PaneDirection.Right, size=10)
    assert pane.pane_width == "10"

    pane = window.split(size="10%")
    assert pane.pane_height == "8"

    pane = window.split(direction=PaneDirection.Right, size="10%")
    assert pane.pane_width == "8"


class WindowRenameFixture(t.NamedTuple):
    """Test fixture for window rename functionality."""

    test_id: str
    window_name_before: str
    window_name_input: str
    window_name_after: str


WINDOW_RENAME_FIXTURES: list[WindowRenameFixture] = [
    WindowRenameFixture(
        test_id="rename_with_spaces",
        window_name_before="test",
        window_name_input="ha ha ha fjewlkjflwef",
        window_name_after="ha ha ha fjewlkjflwef",
    ),
    WindowRenameFixture(
        test_id="rename_with_escapes",
        window_name_before=r"hello \ wazzup 0",
        window_name_input=r"hello \ wazzup 0",
        window_name_after=r"hello \\ wazzup 0",
    ),
]


@pytest.mark.parametrize(
    list(WindowRenameFixture._fields),
    WINDOW_RENAME_FIXTURES,
    ids=[test.test_id for test in WINDOW_RENAME_FIXTURES],
)
def test_window_rename(
    session: Session,
    test_id: str,
    window_name_before: str,
    window_name_input: str,
    window_name_after: str,
) -> None:
    """Test Window.rename_window()."""
    session.set_option("automatic-rename", "off", scope=None)
    window = session.new_window(window_name=window_name_before, attach=True)

    assert window == session.active_window
    assert window.window_name == window_name_before

    window.rename_window(window_name_input)

    window = session.active_window
    assert window.window_name == window_name_after


def test_kill_window(session: Session) -> None:
    """Test window.kill() kills window."""
    session.new_window()
    # create a second window to not kick out the client.
    # there is another way to do this via options too.

    w = session.active_window

    assert w.window_id is not None

    w.kill()
    with pytest.raises(ObjectDoesNotExist):
        w.refresh()


def test_show_window_options(session: Session) -> None:
    """Window.show_options() returns dict."""
    window = session.new_window(window_name="test_window")

    options = window.show_options()
    assert isinstance(options, dict)

    options_2 = window._show_options()
    assert isinstance(options_2, dict)

    pane_options = window._show_options(scope=OptionScope.Pane)
    assert isinstance(pane_options, dict)

    pane_options_global = window._show_options(scope=OptionScope.Pane, global_=True)
    assert isinstance(pane_options_global, dict)

    window_options = window._show_options(scope=OptionScope.Window)
    assert isinstance(window_options, dict)

    window_options_global = window._show_options(scope=OptionScope.Window, global_=True)
    assert isinstance(window_options_global, dict)

    server_options = window._show_options(scope=OptionScope.Server)
    assert isinstance(server_options, dict)

    server_options_global = window._show_options(scope=OptionScope.Server, global_=True)
    assert isinstance(server_options_global, dict)


def test_set_window_and_show_window_options(session: Session) -> None:
    """Window.set_option() then Window.show_option(key)."""
    window = session.new_window(window_name="test_window")

    window.set_option("main-pane-height", 20)
    assert window.show_option("main-pane-height") == 20

    window.set_option("main-pane-height", 40)
    assert window.show_option("main-pane-height") == 40
    assert window.show_options()["main-pane-height"] == 40

    window.set_option("pane-border-format", " #P ")
    assert window.show_option("pane-border-format") == " #P "


def test_set_and_show_window_options(session: Session) -> None:
    """Window.set_option() then Window._show_options(key)."""
    window = session.new_window(window_name="test_window")

    window.set_option("main-pane-height", 20)
    assert window._show_option("main-pane-height") == 20

    window.set_option("main-pane-height", 40)
    assert window._show_option("main-pane-height") == 40

    # By default, show-options will session scope, even if target is a window
    with pytest.raises(KeyError):
        assert window._show_options(scope=OptionScope.Session)["main-pane-height"] == 40

    assert window._show_option("main-pane-height") == 40

    window.set_option("pane-border-format", " #P ")
    assert window._show_option("pane-border-format") == " #P "


def test_empty_window_option_returns_None(session: Session) -> None:
    """Verify unset window option returns None."""
    window = session.new_window(window_name="test_window")
    assert window.show_option("alternate-screen") is None


def test_show_window_option(session: Session) -> None:
    """Set option then Window.show_option(key)."""
    window = session.new_window(window_name="test_window")

    window.set_option("main-pane-height", 20)
    assert window.show_option("main-pane-height") == 20

    window.set_option("main-pane-height", 40)
    assert window.show_option("main-pane-height") == 40
    assert window.show_option("main-pane-height") == 40


def test_show_window_option_unknown(session: Session) -> None:
    """Window.show_option raises InvalidOption for bad option key."""
    window = session.new_window(window_name="test_window")

    with pytest.raises(exc.InvalidOption):
        window.show_option("moooz")


def test_show_window_option_ambiguous(session: Session) -> None:
    """show_option raises AmbiguousOption for ambiguous option."""
    window = session.new_window(window_name="test_window")

    with pytest.raises(exc.AmbiguousOption):
        window.show_option("clock-mode")


def test_set_window_option_ambiguous(session: Session) -> None:
    """set_option raises AmbiguousOption for ambiguous option."""
    window = session.new_window(window_name="test_window")

    with pytest.raises(exc.AmbiguousOption):
        window.set_option("clock-mode", 12)


def test_set_window_option_invalid(session: Session) -> None:
    """Window.set_option raises InvalidOption for invalid option key."""
    window = session.new_window(window_name="test_window")

    with pytest.raises(exc.InvalidOption):
        window.set_option("afewewfew", 43)


def test_move_window(session: Session) -> None:
    """Window.move_window results in changed index."""
    window = session.new_window(window_name="test_window")
    assert window.window_index is not None
    new_index = str(int(window.window_index) + 1)
    window.move_window(new_index)
    assert window.window_index == new_index


def test_move_window_to_other_session(server: Server, session: Session) -> None:
    """Window.move_window to other session."""
    window = session.new_window(window_name="test_window")
    new_session = server.new_session("test_move_window")
    window.move_window(session=new_session.session_id)
    window_id = window.window_id
    assert window_id is not None
    assert new_session.windows.get(window_id=window_id) == window


def test_select_layout_accepts_no_arg(server: Server, session: Session) -> None:
    """Tmux allows select-layout with no arguments, so let's allow it here."""
    window = session.new_window(window_name="test_window")
    window.select_layout()


def test_empty_window_name(session: Session) -> None:
    """New windows can be created with empty string for window name."""
    session.set_option("automatic-rename", "off")
    window = session.new_window(window_name="''", attach=True)

    assert window == session.active_window
    assert window.window_name == "''"
    assert session.session_name is not None

    cmd = session.cmd(
        "list-windows",
        "-F",
        "#{window_name}",
        "-f",
        "#{==:#{session_name}," + session.session_name + "}",
    )
    assert "''" in cmd.stdout


class WindowSplitEnvironmentFixture(t.NamedTuple):
    """Test fixture for window split with environment variables."""

    test_id: str
    environment: dict[str, str]


WINDOW_SPLIT_ENV_FIXTURES: list[WindowSplitEnvironmentFixture] = [
    WindowSplitEnvironmentFixture(
        test_id="single_env_var",
        environment={"ENV_VAR": "pane"},
    ),
    WindowSplitEnvironmentFixture(
        test_id="multiple_env_vars",
        environment={"ENV_VAR_1": "pane_1", "ENV_VAR_2": "pane_2"},
    ),
]


@pytest.mark.parametrize(
    list(WindowSplitEnvironmentFixture._fields),
    WINDOW_SPLIT_ENV_FIXTURES,
    ids=[test.test_id for test in WINDOW_SPLIT_ENV_FIXTURES],
)
def test_split_with_environment(
    session: Session,
    test_id: str,
    environment: dict[str, str],
) -> None:
    """Verify splitting window with environment variables."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    window = session.new_window(window_name="split_with_environment")
    pane = window.split(
        shell=f"{env} PS1='$ ' sh",
        environment=environment,
    )
    assert pane is not None
    # wait a bit for the prompt to be ready as the test gets flaky otherwise
    time.sleep(0.05)
    for k, v in environment.items():
        pane.send_keys(f"echo ${k}")
        assert pane.capture_pane()[-2] == v


def test_split_window_zoom(
    session: Session,
) -> None:
    """Verify splitting window with zoom."""
    window_without_zoom = session.new_window(window_name="split_without_zoom")
    window_with_zoom = session.new_window(window_name="split_with_zoom")
    pane_without_zoom = window_without_zoom.split(
        zoom=False,
    )
    pane_with_zoom = window_with_zoom.split(
        zoom=True,
    )

    assert pane_without_zoom.width == pane_without_zoom.window_width
    assert pane_without_zoom.height is not None
    assert pane_without_zoom.window_height is not None
    assert pane_without_zoom.height < pane_without_zoom.window_height

    assert pane_with_zoom.width == pane_with_zoom.window_width
    assert pane_with_zoom.height == pane_with_zoom.window_height


def test_resize(
    session: Session,
) -> None:
    """Verify resizing window."""
    session.cmd("detach-client", "-s")

    window = session.active_window
    window_height_adjustment = 10

    assert window.window_height is not None
    assert window.window_width is not None

    #
    # Manual resizing
    #

    # Manual: Height
    window_height_before = int(window.window_height)
    window.resize(
        height=10,
    )
    assert int(window.window_height) == 10

    # Manual: Width
    window.resize(
        width=10,
    )
    assert int(window.window_width) == 10

    #
    # Adjustments
    #

    # Adjustment: Down
    window_height_before = int(window.window_height)
    window.resize(
        adjustment_direction=ResizeAdjustmentDirection.Down,
        adjustment=window_height_adjustment * 2,
    )
    assert window_height_before + (window_height_adjustment * 2) == int(
        window.window_height,
    )

    # Adjustment: Up
    window_height_before = int(window.window_height)
    window.resize(
        adjustment_direction=ResizeAdjustmentDirection.Up,
        adjustment=window_height_adjustment,
    )
    assert window_height_before - window_height_adjustment == int(window.window_height)

    #
    # Shrink and expand
    #
    window.resize(height=50)

    # Shrink
    window_height_before = int(window.window_height)
    window.resize(
        shrink=True,
    )
    window_height_shrunk = int(window.window_height)
    assert window_height_before > window_height_shrunk

    assert window

    # Expand
    window.resize(height=2)
    window_height_before = int(window.window_height)
    window.resize(
        expand=True,
    )
    window_height_expanded = int(window.window_height)
    assert window_height_before < window_height_expanded


def test_new_window_with_direction(
    session: Session,
) -> None:
    """Verify new window with direction."""
    window = session.active_window
    window.refresh()

    window_initial = session.new_window(window_name="Example")
    assert window_initial.window_index == "2"

    window_before = window_initial.new_window(
        window_name="Window before",
        direction=WindowDirection.Before,
    )
    window_initial.refresh()
    assert window_before.window_index == "2"
    assert window_initial.window_index == "3"

    window_after = window_initial.new_window(
        window_name="Window after",
        direction=WindowDirection.After,
    )
    window_initial.refresh()
    window_after.refresh()
    assert window_after.window_index == "4"
    assert window_initial.window_index == "3"
    assert window_before.window_index == "2"


def test_window_context_manager(session: Session) -> None:
    """Test Window context manager functionality."""
    with session.new_window() as window:
        pane = window.split()
        assert window in session.windows
        assert pane in window.panes
        assert len(window.panes) == 2  # Initial pane + new pane

    # Window should be killed after exiting context
    assert window not in session.windows


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
def test_split_start_directory(
    test_id: str,
    start_directory: StrPath | None,
    description: str,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    user_path: pathlib.Path,
) -> None:
    """Test Window.split start_directory parameter handling."""
    monkeypatch.chdir(tmp_path)

    window = session.new_window(window_name=f"test_window_split_{test_id}")

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
    new_pane = window.split(start_directory=actual_start_directory)

    assert new_pane in window.panes
    assert len(window.panes) == 2

    # Verify working directory if we have an expected path
    if expected_path:
        new_pane.refresh()
        assert new_pane.pane_current_path is not None
        actual_path = str(pathlib.Path(new_pane.pane_current_path).resolve())
        assert actual_path == expected_path


def test_split_start_directory_pathlib(
    session: Session,
    user_path: pathlib.Path,
) -> None:
    """Test Window.split accepts pathlib.Path for start_directory."""
    window = session.new_window(window_name="test_window_split_pathlib")

    # Pass pathlib.Path directly to test pathlib.Path acceptance
    new_pane = window.split(start_directory=user_path)

    assert new_pane in window.panes
    assert len(window.panes) == 2

    # Verify working directory
    new_pane.refresh()
    assert new_pane.pane_current_path is not None
    actual_path = str(pathlib.Path(new_pane.pane_current_path).resolve())
    expected_path = str(user_path.resolve())
    assert actual_path == expected_path


# --- Deprecation Warning Tests ---


class DeprecatedMethodTestCase(t.NamedTuple):
    """Test case for deprecated method errors."""

    test_id: str
    method_name: str  # Name of deprecated method to call
    args: tuple[t.Any, ...]  # Positional args
    kwargs: dict[str, t.Any]  # Keyword args
    expected_error_match: str  # Regex pattern to match error message


# These methods were deprecated in 0.50.0 and still emit warnings (not errors)
DEPRECATED_WARNING_WINDOW_METHOD_TEST_CASES: list[DeprecatedMethodTestCase] = [
    DeprecatedMethodTestCase(
        test_id="set_window_option",
        method_name="set_window_option",
        args=("main-pane-height", 20),
        kwargs={},
        expected_error_match=r"Window\.set_window_option\(\) is deprecated",
    ),
    DeprecatedMethodTestCase(
        test_id="show_window_options",
        method_name="show_window_options",
        args=(),
        kwargs={},
        expected_error_match=r"Window\.show_window_options\(\) is deprecated",
    ),
    DeprecatedMethodTestCase(
        test_id="show_window_option",
        method_name="show_window_option",
        args=("main-pane-height",),
        kwargs={},
        expected_error_match=r"Window\.show_window_option\(\) is deprecated",
    ),
]


def _build_deprecated_warning_method_params() -> list[t.Any]:
    """Build pytest params for deprecated method warning tests."""
    return [
        pytest.param(tc, id=tc.test_id)
        for tc in DEPRECATED_WARNING_WINDOW_METHOD_TEST_CASES
    ]


@pytest.mark.parametrize("test_case", _build_deprecated_warning_method_params())
def test_deprecated_window_methods_emit_warning(
    session: Session,
    test_case: DeprecatedMethodTestCase,
) -> None:
    """Verify deprecated Window methods emit DeprecationWarning (0.50.0)."""
    window = session.new_window(window_name="test_deprecation")
    method = getattr(window, test_case.method_name)

    with pytest.warns(DeprecationWarning, match=test_case.expected_error_match):
        method(*test_case.args, **test_case.kwargs)
