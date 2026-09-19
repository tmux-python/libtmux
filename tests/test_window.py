"""Test for libtmux Window object."""

from __future__ import annotations

import logging
import pathlib
import shutil
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
from libtmux.test.retry import retry_until
from libtmux.window import Window

if t.TYPE_CHECKING:
    from libtmux._internal.types import StrPath
    from libtmux.session import Session

logger = logging.getLogger(__name__)


@pytest.mark.parametrize("raw", [None, "0", "1"])
def test_decoded_window_fields_are_local(raw: str | None) -> None:
    """Window dimensions and flags decode without a running server."""
    window = Window(
        server=Server(tmux_bin="missing-decoded-fields-tmux"),
        window_width="80",
        window_height="24",
        window_active=raw,
    )
    assert window.width_cells == 80
    assert window.height_cells == 24
    assert window.width == "80"
    assert window.height == "24"
    assert window.is_active is (None if raw is None else raw == "1")
    window.window_width = None
    window.window_height = None
    assert window.width_cells is None
    assert window.height_cells is None


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
        # Create with a plain name and only assert that rename doubles the
        # backslash: window_set_name() has escaped names via vis(3) since tmux
        # 2.6, so this holds on all supported versions. (new-window only began
        # escaping names in tmux 3.7, so a backslash in the *create* name is
        # version-dependent and must not be asserted here.)
        test_id="rename_with_escapes",
        window_name_before="test",
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


class WindowNameSpecialCharFixture(t.NamedTuple):
    """Test fixture for ':'/'.' window names across tmux versions."""

    test_id: str
    window_name: str


# The tmux 3.7 point release briefly rejected ':' and '.' in window names,
# then reverted it in 3.7a as "overly pernickety" (tmux commit 166267c8).
# Every tmux libtmux supports -- 3.2a-3.6 and 3.7a onward -- accepts them.
WINDOW_NAME_SPECIAL_CHAR_FIXTURES: list[WindowNameSpecialCharFixture] = [
    WindowNameSpecialCharFixture(test_id="colon", window_name="project:frontend"),
    WindowNameSpecialCharFixture(test_id="period", window_name="app-v1.0"),
]


@pytest.mark.parametrize(
    list(WindowNameSpecialCharFixture._fields),
    WINDOW_NAME_SPECIAL_CHAR_FIXTURES,
    ids=[tc.test_id for tc in WINDOW_NAME_SPECIAL_CHAR_FIXTURES],
)
def test_new_window_name_colon_period_accepted(
    session: Session,
    test_id: str,
    window_name: str,
) -> None:
    """Window names with ':' and '.' are accepted verbatim.

    The lone tmux 3.7 point release briefly rejected these characters before
    3.7a reverted the restriction (tmux commit 166267c8, "overly
    pernickety"). libtmux's version helpers strip the letter suffix, so
    :func:`~libtmux.common.get_version` cannot tell 3.7 from 3.7a -- both
    report ``3.7`` -- so CI exercises 3.7a/3.7b rather than the superseded
    3.7 release.
    """
    window = session.new_window(window_name=window_name)
    assert window.window_name == window_name
    window.kill()


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


@pytest.mark.parametrize(
    ("flag_name", "destination_offset"), [("after", 0), ("before", 1)]
)
def test_move_window_relative_returns_fresh_window(
    flag_name: str,
    destination_offset: int,
    session: Session,
) -> None:
    """Window.move_window() returns fresh state for relative moves."""
    destination_window = session.active_window
    session.new_window(window_name="move_middle")
    moving_window = session.new_window(window_name="move_relative")
    assert destination_window.window_index is not None
    assert moving_window.window_id is not None

    destination = str(int(destination_window.window_index) + destination_offset)
    if flag_name == "after":
        moving_window.move_window(destination, after=True)
    else:
        moving_window.move_window(destination, before=True)

    fresh_window = Window.from_window_id(
        server=session.server,
        window_id=moving_window.window_id,
    )
    assert moving_window.window_index == fresh_window.window_index
    assert moving_window.session_id == fresh_window.session_id


def test_move_window_to_other_session_with_destination(
    server: Server,
    session: Session,
) -> None:
    """Window.move_window() returns fresh state for cross-session moves."""
    window = session.new_window(window_name="move_cross_session")
    assert window.window_id is not None
    new_session = server.new_session("test_move_window_destination")
    destination = "99"

    window.move_window(destination=destination, session=new_session.session_id)

    fresh_window = Window.from_window_id(server=server, window_id=window.window_id)
    assert fresh_window.session_id == new_session.session_id
    assert fresh_window.window_index == destination
    assert window.session_id == fresh_window.session_id
    assert window.window_index == fresh_window.window_index


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
    retry_until(lambda: "$" in "\n".join(pane.capture_pane()), 2, raises=True)
    for k, v in environment.items():
        pane.send_keys(f"echo ${k}")

        def output_ready(expected: str = v) -> bool:
            lines = pane.capture_pane()
            return len(lines) >= 2 and lines[-2] == expected

        retry_until(output_ready, 2, raises=True)
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


def test_select_layout_spread(session: Session) -> None:
    """Test Window.select_layout() with spread flag."""
    window = session.new_window(window_name="test_layout_spread")
    window.resize(height=40, width=80)
    pane = window.active_pane
    assert pane is not None
    pane.split()
    pane.split()
    assert len(window.panes) == 3

    # Spread panes evenly — verify no error
    window.select_layout(spread=True)


def test_select_layout_next_previous(session: Session) -> None:
    """Test Window.select_layout() with next/previous flags."""
    window = session.new_window(window_name="test_layout_cycle")
    window.resize(height=40, width=80)
    pane = window.active_pane
    assert pane is not None
    pane.split()

    # Set a known layout
    window.select_layout("even-horizontal")
    window.refresh()
    layout_before = window.window_layout

    # Cycle to next layout
    window.select_layout(next_layout=True)
    window.refresh()
    layout_after_next = window.window_layout

    assert layout_before != layout_after_next

    # Cycle back to previous
    window.select_layout(previous_layout=True)
    window.refresh()
    layout_after_prev = window.window_layout

    assert layout_after_prev == layout_before


def test_select_layout_round_trip_is_byte_exact(session: Session) -> None:
    """A saved ``window_layout`` fed back into ``select_layout`` is exact.

    tmux 3.8 made ``#{window_layout}`` JSON for non-control clients, while
    ``select-layout`` still accepts the classic grammar too. libtmux treats
    the value as an opaque token on every version -- it never parses or
    validates it -- so a saved layout must restore byte-for-byte regardless
    of which form the running tmux emits.
    """
    window = session.new_window(window_name="test_layout_round_trip")
    window.resize(height=40, width=80)
    pane = window.active_pane
    assert pane is not None
    pane.split()
    pane.split()

    window.select_layout("even-horizontal")
    window.refresh()
    saved = window.window_layout
    assert saved is not None

    window.select_layout("main-vertical")
    window.refresh()
    assert window.window_layout != saved

    window.select_layout(saved)
    window.refresh()
    assert window.window_layout == saved


def test_select_layout_round_trip_preserves_pane_identity_on_json(
    session: Session,
) -> None:
    """On tmux 3.8+, restoring a saved layout puts each pane back in place.

    python exposes no public control-mode client, so every caller is a
    plain reader -- ``#{window_layout}`` is JSON from tmux 3.8 on, and
    JSON carries each pane's id. Restoring a saved JSON layout from a
    *different* one must put every pane back at its original position,
    not merely reproduce the same shape. Before 3.8 the saved value is
    the classic string, which the ``Notes`` on
    :meth:`Window.select_layout` document as shape-exact but not
    identity-exact -- not asserted here, since whether a given
    arrangement happens to rotate depends on tmux's own internal pane
    order, not on anything libtmux controls.
    """
    from libtmux.common import has_gte_version

    if not has_gte_version("3.8"):
        pytest.skip("JSON window_layout, and its pane-identity guarantee, need 3.8+")

    window = session.new_window(window_name="test_layout_identity")
    window.resize(height=40, width=80)
    pane = window.active_pane
    assert pane is not None
    pane.split()
    pane.split()
    pane.split()

    window.select_layout("main-vertical-mirrored")
    window.refresh()
    saved = window.window_layout
    assert saved is not None
    assert saved.startswith("{"), "expected a JSON layout on tmux 3.8+"
    before = {p.pane_id: (p.left_cells, p.top_cells) for p in window.panes}

    window.select_layout("even-horizontal")
    window.refresh()
    assert {p.pane_id: (p.left_cells, p.top_cells) for p in window.panes} != before

    window.select_layout(saved)
    window.refresh()
    after = {p.pane_id: (p.left_cells, p.top_cells) for p in window.panes}
    assert after == before


def test_last_pane(session: Session) -> None:
    """Test Window.last_pane() selects the previously active pane."""
    window = session.new_window(window_name="test_last_pane")
    pane1 = window.active_pane
    assert pane1 is not None
    pane2 = pane1.split()

    # Select pane2 then pane1 to establish history
    pane2.select()
    pane1.select()

    # last_pane should go back to pane2
    result = window.last_pane()
    assert result is not None
    pane2.refresh()
    assert pane2.pane_active == "1"


def test_next_layout(session: Session) -> None:
    """Test Window.next_layout() cycles to the next layout."""
    window = session.new_window(window_name="test_next_layout")
    window.resize(height=40, width=80)
    pane = window.active_pane
    assert pane is not None
    pane.split()

    window.select_layout("even-horizontal")
    window.refresh()
    layout_before = window.window_layout

    window.next_layout()
    window.refresh()
    layout_after = window.window_layout

    assert layout_before != layout_after


def test_previous_layout(session: Session) -> None:
    """Test Window.previous_layout() cycles back."""
    window = session.new_window(window_name="test_prev_layout")
    window.resize(height=40, width=80)
    pane = window.active_pane
    assert pane is not None
    pane.split()

    window.select_layout("even-horizontal")
    window.refresh()
    layout_before = window.window_layout

    window.next_layout()
    window.previous_layout()
    window.refresh()
    layout_after = window.window_layout

    assert layout_before == layout_after


def test_select_layout_mutual_exclusion(session: Session) -> None:
    """Test that layout string and flags are mutually exclusive."""
    window = session.new_window(window_name="test_layout_mutex")
    with pytest.raises(ValueError, match="Cannot specify both"):
        window.select_layout("tiled", spread=True)


def test_select_layout_dash_o_is_a_layout_not_the_undo_flag(session: Session) -> None:
    """A layout value beginning with ``-`` is never read as a tmux flag.

    Raw ``select-layout -o`` is tmux's *undo* flag (restores the previous
    layout), not a layout named ``-o``. A caller passing a hostile or
    accidental ``"-o"`` string must get a refusal, not a silent undo.
    Before this fix, the call returned successfully and undid the
    just-applied layout.

    Refused client-side (``ValueError``), before ever reaching tmux: on
    tmux 3.3/3.3a, sending an actually-invalid layout *string* (which is
    what "-o" becomes once forced to be read as one, rather than as the
    undo flag) crashes the whole daemon instead of refusing cleanly --
    confirmed by hand against that version. A client-side refusal side-
    steps that regardless of which tmux is running; see
    ``test_select_layout_dash_o_crashes_tmux_3_3a_if_forced_through`` for
    the raw-tmux confirmation this guards against.
    """
    window = session.new_window(window_name="test_layout_dash_o")
    window.resize(height=40, width=80)
    pane = window.active_pane
    assert pane is not None
    pane.split()

    window.select_layout("even-horizontal")
    window.refresh()
    before = window.window_layout

    with pytest.raises(ValueError, match="looks like a tmux flag"):
        window.select_layout("-o")

    # The undo flag would have restored the previous layout; a refusal
    # must leave the current one untouched, and the server alive.
    window.refresh()
    assert window.window_layout == before
    assert window.server.is_alive()


@pytest.mark.parametrize(
    "value",
    ["garbage", "no-such-preset", "next", "zzzz,80x24,0,0,0", "{not json"],
)
def test_select_layout_refuses_a_value_tmux_cannot_parse(
    session: Session,
    value: str,
) -> None:
    """Only a preset name or a layout tmux reported reaches tmux.

    On tmux 3.3/3.3a any unparseable layout, not only one beginning with
    ``-``, exits the daemon; without the refusal the server is gone there.
    A JSON-looking value is refused only below 3.8, where it is unparseable.
    """
    from libtmux.common import has_gte_version

    window = session.new_window(window_name="test_layout_unparseable")
    if value.startswith("{") and not has_gte_version(
        "3.8",
        tmux_bin=session.server.tmux_bin,
    ):
        with pytest.raises(exc.VersionTooLow, match=r"3\.8"):
            window.select_layout(value)
    elif value.startswith("{"):
        with pytest.raises(exc.LibTmuxException):
            window.select_layout(value)
    else:
        with pytest.raises(ValueError, match=r"neither a preset name"):
            window.select_layout(value)
    assert window.server.is_alive()


@pytest.mark.parametrize("value", ["tile", "even-h"])
def test_select_layout_accepts_a_unique_preset_prefix(
    session: Session,
    value: str,
) -> None:
    """A prefix that resolves to exactly one preset applies.

    tmux's own ``layout_set_lookup`` is a prefix match: ``"tile"`` and
    ``"even-h"`` each name exactly one preset (``tiled``,
    ``even-horizontal``) and apply on every supported tmux version,
    including 3.3a, where an unparseable value would crash the daemon --
    a unique prefix never reaches that path.
    """
    window = session.new_window(window_name="test_layout_prefix")
    window.select_layout(value)
    assert window.server.is_alive()


def test_select_layout_refuses_an_ambiguous_prefix(session: Session) -> None:
    """A prefix matching more than one preset is refused, naming both.

    ``"even-"`` prefixes both ``even-horizontal`` and ``even-vertical`` on
    every version; raw tmux refuses it cleanly ("invalid layout: even-"),
    and the client-side guard does too, naming the candidates in its
    message.
    """
    window = session.new_window(window_name="test_layout_ambiguous")
    with pytest.raises(ValueError, match="is ambiguous between"):
        window.select_layout("even-")
    assert window.server.is_alive()


def test_select_layout_prefix_ambiguity_is_scoped_to_the_live_version(
    session: Session,
) -> None:
    """A prefix's ambiguity depends on which presets the live tmux has.

    ``"main-h"`` uniquely names ``main-horizontal`` below tmux 3.5, where
    the mirrored presets don't exist yet, but is ambiguous with
    ``main-horizontal-mirrored`` on 3.5+ -- confirmed against raw tmux on
    3.3a (applies) and 3.7c (refused, "invalid layout: main-h") before
    this fix existed.
    """
    from libtmux.common import has_gte_version

    window = session.new_window(window_name="test_layout_prefix_scoped")
    if has_gte_version("3.5", tmux_bin=session.server.tmux_bin):
        with pytest.raises(ValueError, match="is ambiguous between"):
            window.select_layout("main-h")
    else:
        window.select_layout("main-h")
    assert window.server.is_alive()


def test_select_layout_mirrored_preset_needs_tmux_3_5(session: Session) -> None:
    """A mirrored preset below 3.5 is an unknown name to tmux, and fatal on 3.3a."""
    from libtmux.common import has_gte_version

    window = session.new_window(window_name="test_layout_mirrored")
    if has_gte_version("3.5", tmux_bin=session.server.tmux_bin):
        window.select_layout("main-vertical-mirrored")
    else:
        with pytest.raises(exc.VersionTooLow, match=r"3\.5"):
            window.select_layout("main-vertical-mirrored")
    assert window.server.is_alive()


def test_select_layout_dash_o_crashes_tmux_3_3a_if_forced_through(
    server: Server,
) -> None:
    """Raw tmux confirmation for the guard above's stated reason.

    Not a python defect: on tmux 3.3 and 3.3a specifically, forcing "-o"
    to be read as a layout *string* (``select-layout -- -o``) frees an
    uninitialized pointer and kills the daemon outright ("server exited
    unexpectedly"), rather than refusing with an error -- fixed upstream
    in 3.4. Skipped on every other version, where raw tmux refuses
    cleanly and the server survives (already covered by this port's
    matrix runs). This is *why* ``Window.select_layout`` refuses a
    leading ``-`` itself instead of relying only on tmux's own response.
    """
    from libtmux.common import get_version_str

    version = get_version_str(tmux_bin=server.tmux_bin)
    if version not in {"3.3", "3.3a"}:
        pytest.skip(f"tmux {version} is not the 3.3/3.3a crash case")

    server.new_session(session_name="crash_check")
    proc = server.cmd("select-layout", "--", "-o")
    assert proc.returncode != 0
    assert "server exited unexpectedly" in "\n".join(proc.stderr)
    assert not server.is_alive()


def test_select_layout_empty_string_is_refused(session: Session) -> None:
    """An explicit empty-string layout is refused, unlike omitting it.

    ``select_layout(None)`` is tmux's own "no layout" invocation (reapplies
    the current layout); ``select_layout("")`` is a distinct, almost
    certainly accidental call -- a caller-supplied value that happened to
    be empty -- and silently falling back to the same behavior hides that
    mistake.
    """
    window = session.new_window(window_name="test_layout_empty")
    with pytest.raises(ValueError, match="empty string"):
        window.select_layout("")


def test_link_unlink_window(server: Server, session: Session) -> None:
    """Test Window.link() and Window.unlink()."""
    # Create a second session
    s2 = server.new_session(session_name="link_target")

    # Create a window in the first session
    w = session.new_window(window_name="link_test")

    # Link it to s2
    w.link(s2, detach=True)

    # Verify window appears in s2
    s2.refresh()
    s2_window_names = [win.window_name for win in s2.windows]
    assert "link_test" in s2_window_names

    # Unlink from s2 — select a different window first
    linked_windows = [win for win in s2.windows if win.window_name == "link_test"]
    assert len(linked_windows) > 0

    # We need another window in s2 before unlinking the last one
    linked_windows[0].unlink()

    # Verify it's gone from s2
    s2.refresh()
    s2_window_names = [win.window_name for win in s2.windows]
    assert "link_test" not in s2_window_names


def test_rotate_window(session: Session) -> None:
    """Test Window.rotate() rotates pane positions."""
    window = session.new_window(window_name="test_rotate")
    window.resize(height=40, width=80)
    pane1 = window.active_pane
    assert pane1 is not None
    pane2 = pane1.split()
    pane3 = pane2.split()

    pane1.refresh()
    pane2.refresh()
    pane3.refresh()
    idx_before = (pane1.pane_index, pane2.pane_index, pane3.pane_index)

    window.rotate()

    pane1.refresh()
    pane2.refresh()
    pane3.refresh()
    idx_after = (pane1.pane_index, pane2.pane_index, pane3.pane_index)

    assert idx_before != idx_after


def test_respawn_window(session: Session) -> None:
    """Test Window.respawn() with kill flag."""
    window = session.new_window(window_name="test_respawn_w")

    # Respawn the window with kill
    window.respawn(kill=True, shell="sh")

    # Window should still exist
    window.refresh()
    session.refresh()
    assert window.window_id in [w.window_id for w in session.windows]


def test_swap_window(session: Session) -> None:
    """Test Window.swap() swaps two windows."""
    w1 = session.new_window(window_name="swap_w1")
    w2 = session.new_window(window_name="swap_w2")

    w1_idx = w1.window_index
    w2_idx = w2.window_index

    w1.swap(w2)

    w1.refresh()
    w2.refresh()
    assert w1.window_index == w2_idx
    assert w2.window_index == w1_idx


def test_move_window_kill_target(session: Session) -> None:
    """Test Window.move_window() with kill_target flag."""
    session.new_window(window_name="move_w1")
    w2 = session.new_window(window_name="move_w2")
    assert w2.window_index is not None
    w2_index = w2.window_index
    initial_count = len(session.windows)

    # Move first extra window to w2's index, killing w2
    extra_windows = [w for w in session.windows if w.window_name == "move_w1"]
    assert len(extra_windows) == 1
    extra_windows[0].move_window(destination=w2_index, kill_target=True)
    session.refresh()
    assert len(session.windows) == initial_count - 1


def test_move_window_renumber(session: Session) -> None:
    """Test Window.move_window() with renumber flag."""
    session.new_window(window_name="ren_w1")
    w2 = session.new_window(window_name="ren_w2")
    w3 = session.new_window(window_name="ren_w3")

    # Kill middle window to create gap
    w2.kill()

    # Move w3 with renumber
    w3.move_window(renumber=True)
    session.refresh()

    # Verify indices are contiguous
    indices = sorted(
        int(w.window_index) for w in session.windows if w.window_index is not None
    )
    for i in range(len(indices) - 1):
        assert indices[i + 1] - indices[i] == 1


def test_move_window_no_select(session: Session) -> None:
    """Test Window.move_window() with no_select flag."""
    w1 = session.new_window(window_name="nosel_w1", attach=True)
    w2 = session.new_window(window_name="nosel_w2", attach=False)

    # w1 is active
    session.refresh()
    assert session.active_window.window_id == w1.window_id

    # Move w2 with no_select — active window should not change
    w2.move_window(destination="99", no_select=True)
    session.refresh()
    assert session.active_window.window_id == w1.window_id


class WindowDisplayMessageCase(t.NamedTuple):
    """Test case for Window.display_message() flag variations."""

    test_id: str
    cmd: str
    kwargs: dict[str, t.Any]
    expected_in_output: str | None
    min_tmux_version: str | None


WINDOW_DISPLAY_MESSAGE_CASES: list[WindowDisplayMessageCase] = [
    WindowDisplayMessageCase(
        test_id="window_id",
        cmd="#{window_id}",
        kwargs={"get_text": True},
        expected_in_output="@",
        min_tmux_version=None,
    ),
    WindowDisplayMessageCase(
        test_id="window_index_via_format_string",
        cmd="",
        kwargs={"get_text": True, "format_string": "#{window_index}"},
        # pytest plugin sets `base-index 1` (pytest_plugin.py:110), so the
        # first window in a fresh session is index 1, not 0.
        expected_in_output="1",
        min_tmux_version=None,
    ),
    WindowDisplayMessageCase(
        test_id="zoomed_flag_default_zero",
        cmd="#{window_zoomed_flag}",
        kwargs={"get_text": True},
        expected_in_output="0",
        min_tmux_version=None,
    ),
    WindowDisplayMessageCase(
        test_id="no_expand_literal",
        cmd="#{window_id}",
        kwargs={"get_text": True, "no_expand": True},
        expected_in_output="#{window_id}",
        min_tmux_version="3.4",
    ),
]


@pytest.mark.parametrize(
    list(WindowDisplayMessageCase._fields),
    WINDOW_DISPLAY_MESSAGE_CASES,
    ids=[c.test_id for c in WINDOW_DISPLAY_MESSAGE_CASES],
)
def test_window_display_message_flags(
    test_id: str,
    cmd: str,
    kwargs: dict[str, t.Any],
    expected_in_output: str | None,
    min_tmux_version: str | None,
    session: Session,
) -> None:
    """Window.display_message() resolves window-scoped formats."""
    from libtmux.common import has_gte_version

    if min_tmux_version and not has_gte_version(min_tmux_version):
        pytest.skip(f"Requires tmux {min_tmux_version}+")

    window = session.active_window
    result = window.display_message(cmd, **kwargs)

    if expected_in_output is not None:
        assert result is not None
        output = "\n".join(result)
        assert expected_in_output in output


def test_window_display_message_no_text_returns_none(
    session: Session,
) -> None:
    """Without ``get_text=True`` the call renders to status line and returns None."""
    window = session.active_window
    result = window.display_message("hi from libtmux")
    assert result is None


def test_window_display_message_target_client(
    control_mode: t.Callable[..., t.Any],
    session: Session,
) -> None:
    """``target_client`` is plumbed through as ``-c``."""
    from libtmux.common import has_gte_version

    if not has_gte_version("3.3"):
        pytest.skip(
            "display-message -p via control-mode client unreliable on tmux 3.2a"
        )

    window = session.active_window
    with control_mode() as ctl:
        result = window.display_message(
            "#{window_id}", get_text=True, target_client=ctl.client_name
        )
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].startswith("@")


def test_window_display_message_warns_on_tmux_error(session: Session) -> None:
    """Tmux stderr on ``display-message`` surfaces as a :class:`UserWarning`."""
    window = session.active_window
    with pytest.warns(UserWarning, match="only one of -F or argument"):
        window.display_message("x", get_text=True, format_string="#{window_id}")


def test_window_zoomed_flag_field_toggle(session: Session) -> None:
    """``window.window_zoomed_flag`` reflects tmux's zoom state across refresh.

    ``refresh()`` repopulates the field after each ``resize-pane -Z`` toggle:
    the flag reads ``"0"`` for an un-zoomed window and ``"1"`` once a pane
    has been zoomed.
    """
    window = session.active_window
    # Need at least two panes for zoom to mean anything.
    window.split()
    window.refresh()
    assert window.window_zoomed_flag == "0"

    pane = window.active_pane
    assert pane is not None
    pane.resize(zoom=True)
    window.refresh()
    assert window.window_zoomed_flag == "1"

    pane.resize(zoom=True)
    window.refresh()
    assert window.window_zoomed_flag == "0"


def test_window_search_panes_filter_by_id(session: Session) -> None:
    """``Window.search_panes(filter=...)`` returns only the matching pane id."""
    window = session.active_window
    target = window.split()

    matches = window.search_panes(filter=f"#{{m:{target.pane_id},#{{pane_id}}}}")
    assert [p.pane_id for p in matches] == [target.pane_id]


def test_window_search_panes_no_filter_equivalent_to_property(
    session: Session,
) -> None:
    """``search_panes()`` with no filter matches the existing ``panes`` property."""
    window = session.active_window
    window.split()

    from_property = sorted(p.pane_id for p in window.panes if p.pane_id)
    from_method = sorted(p.pane_id for p in window.search_panes() if p.pane_id)
    assert from_property == from_method


WINDOW_FORMAT_FIELDS = (
    "window_active_clients_list",
    "window_active_sessions_list",
    "window_activity_flag",
    "window_bell_flag",
    "window_bigger",
    "window_end_flag",
    "window_flags",
    "window_format",
    "window_last_flag",
    "window_silence_flag",
    "window_start_flag",
    "window_visible_layout",
)


@pytest.mark.parametrize("field_name", WINDOW_FORMAT_FIELDS)
def test_window_format_field_declared_and_hydrated(
    field_name: str,
    session: Session,
) -> None:
    """Tmux's window-scope format tokens hydrate onto the typed ``Window``."""
    window = session.active_window
    assert field_name in window.__dataclass_fields__

    window.refresh()
    value = getattr(window, field_name)
    assert value is None or isinstance(value, str)


def test_window_flags_field_returns_string(session: Session) -> None:
    """``window_flags`` summarizes window state and reads as a string.

    The value is often empty for an idle window; the contract is that the
    field hydrates as a string (never ``None``) once tmux has populated it.
    """
    window = session.active_window
    window.refresh()
    assert isinstance(window.window_flags, str)


def test_window_refresh_raises_when_window_id_is_none(session: Session) -> None:
    """``Window.refresh()`` raises ``ValueError`` when ``window_id`` is unset.

    Mirrors the Client.refresh ``-O``-safe contract: the previous
    ``assert isinstance(...)`` stripped under ``python -O`` and let
    ``None`` flow into ``_refresh``. The explicit raise keeps the
    failure mode loud regardless of optimization level.
    """
    from libtmux.window import Window

    window = Window(server=session.server)
    assert window.window_id is None

    with pytest.raises(ValueError, match="window_id"):
        window.refresh()


def test_new_pane(session: Session) -> None:
    """Window.new_pane() creates a floating pane on tmux 3.7+ (else raises)."""
    from libtmux.common import has_gte_version

    window = session.new_window(window_name="win_floating")
    window.resize(height=50, width=200)

    if has_gte_version("3.7"):
        floating = window.new_pane(width=60, height=12, shell="sleep 30")
        assert floating.pane_floating_flag == "1"
        assert floating in window.panes
    else:
        with pytest.raises(exc.LibTmuxException, match=r"new_pane .*requires tmux 3.7"):
            window.new_pane(width=40, height=10)


@pytest.mark.parametrize(
    ("has_mirrored", "raises"),
    [
        pytest.param(True, False, id="3.5-applies"),
        pytest.param(False, True, id="below-3.5-refuses"),
    ],
)
def test_layout_prefix_resolving_to_a_mirrored_preset_follows_the_version(
    has_mirrored: bool,
    raises: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A prefix naming only a mirrored preset is refused below the release that has it.

    tmux resolves a preset by unique prefix, so ``"main-vertical-m"`` names
    ``main-vertical-mirrored`` and nothing else. That preset enters tmux's own
    table in 3.5; below it the name is unknown, and an unknown layout kills the
    server on 3.3/3.3a -- so the refusal has to happen here rather than at tmux.
    """
    from libtmux import window as window_module

    monkeypatch.setattr(
        window_module,
        "has_gte_version",
        lambda version, **_kw: not (version == "3.5" and not has_mirrored),
    )

    if raises:
        with pytest.raises(exc.VersionTooLow, match=r"main-vertical-mirrored"):
            window_module._require_layout_value("main-vertical-m", tmux_bin=None)
    else:
        window_module._require_layout_value("main-vertical-m", tmux_bin=None)
