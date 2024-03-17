"""Test for libtmux Window object."""

import logging
import shutil
import time
import typing as t

import pytest

from libtmux import exc
from libtmux._internal.query_list import ObjectDoesNotExist
from libtmux.common import has_gte_version, has_lt_version, has_lte_version
from libtmux.constants import (
    PaneDirection,
    ResizeAdjustmentDirection,
    WindowDirection,
)
from libtmux.pane import Pane
from libtmux.server import Server
from libtmux.session import Session
from libtmux.window import Window

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
    pane_base_idx = active_window.show_window_option("pane-base-index", g=True)
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

    assert len(session.windows), 1
    assert len(session.active_window.panes) == 1
    for w in session.windows:
        assert isinstance(w, Window)
    window = session.active_window
    assert isinstance(window, Window)
    assert len(session.active_window.panes) == 1
    window.split()

    active_window = session.active_window
    assert active_window is not None
    active_window.select_pane(pane_base_index)

    active_pane = session.active_pane
    assert active_pane is not None
    active_pane.send_keys("cd /srv/www/flaskr")

    active_window.select_pane(pane_base_index + 1)
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
    session.kill_window(target_window="hey")
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
    if has_gte_version("3.2"):
        pane_start_command = pane.pane_start_command or ""
        assert pane_start_command.replace('"', "") == cmd

    else:
        assert pane.pane_start_command == cmd


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

    if has_gte_version("3.1"):
        pane = window.split(size=10)
        assert pane.pane_height == "10"

        pane = window.split(direction=PaneDirection.Right, size=10)
        assert pane.pane_width == "10"

        pane = window.split(size="10%")
        assert pane.pane_height == "8"

        pane = window.split(direction=PaneDirection.Right, size="10%")
        assert pane.pane_width == "8"
    else:
        window_height_before = (
            int(window.window_height) if isinstance(window.window_height, str) else 0
        )
        window_width_before = (
            int(window.window_width) if isinstance(window.window_width, str) else 0
        )
        pane = window.split(size="10%")
        assert pane.pane_height == str(int(window_height_before * 0.1))

        pane = window.split(direction=PaneDirection.Right, size="10%")
        assert pane.pane_width == str(int(window_width_before * 0.1))


@pytest.mark.parametrize(
    "window_name_before,window_name_after",
    [("test", "ha ha ha fjewlkjflwef"), ("test", "hello \\ wazzup 0")],
)
def test_window_rename(
    session: Session,
    window_name_before: str,
    window_name_after: str,
) -> None:
    """Test Window.rename_window()."""
    window_name_before = "test"
    window_name_after = "ha ha ha fjewlkjflwef"

    session.set_option("automatic-rename", "off")
    window = session.new_window(window_name=window_name_before, attach=True)

    assert window == session.active_window
    assert window.window_name == window_name_before

    window.rename_window(window_name_after)

    window = session.active_window

    assert window.window_name == window_name_after

    window = session.active_window

    assert window.window_name == window_name_after


def test_kill_window(session: Session) -> None:
    """Test window.kill_window() kills window."""
    session.new_window()
    # create a second window to not kick out the client.
    # there is another way to do this via options too.

    w = session.active_window

    assert w.window_id is not None

    w.kill_window()
    with pytest.raises(ObjectDoesNotExist):
        w.refresh()


def test_show_window_options(session: Session) -> None:
    """Window.show_window_options() returns dict."""
    window = session.new_window(window_name="test_window")

    options = window.show_window_options()
    assert isinstance(options, dict)


def test_set_show_window_options(session: Session) -> None:
    """Set option then Window.show_window_options(key)."""
    window = session.new_window(window_name="test_window")

    window.set_window_option("main-pane-height", 20)
    assert window.show_window_option("main-pane-height") == 20

    window.set_window_option("main-pane-height", 40)
    assert window.show_window_option("main-pane-height") == 40
    assert window.show_window_options()["main-pane-height"] == 40

    if has_gte_version("2.3"):
        window.set_window_option("pane-border-format", " #P ")
        assert window.show_window_option("pane-border-format") == " #P "


def test_empty_window_option_returns_None(session: Session) -> None:
    """Verify unset window option returns None."""
    window = session.new_window(window_name="test_window")
    assert window.show_window_option("alternate-screen") is None


def test_show_window_option(session: Session) -> None:
    """Set option then Window.show_window_option(key)."""
    window = session.new_window(window_name="test_window")

    window.set_window_option("main-pane-height", 20)
    assert window.show_window_option("main-pane-height") == 20

    window.set_window_option("main-pane-height", 40)
    assert window.show_window_option("main-pane-height") == 40
    assert window.show_window_option("main-pane-height") == 40


def test_show_window_option_unknown(session: Session) -> None:
    """Window.show_window_option raises UnknownOption for bad option key."""
    window = session.new_window(window_name="test_window")

    cmd_exception: t.Type[exc.OptionError] = exc.UnknownOption
    if has_gte_version("3.0"):
        cmd_exception = exc.InvalidOption
    with pytest.raises(cmd_exception):
        window.show_window_option("moooz")


def test_show_window_option_ambiguous(session: Session) -> None:
    """show_window_option raises AmbiguousOption for ambiguous option."""
    window = session.new_window(window_name="test_window")

    with pytest.raises(exc.AmbiguousOption):
        window.show_window_option("clock-mode")


def test_set_window_option_ambiguous(session: Session) -> None:
    """set_window_option raises AmbiguousOption for ambiguous option."""
    window = session.new_window(window_name="test_window")

    with pytest.raises(exc.AmbiguousOption):
        window.set_window_option("clock-mode", 12)


def test_set_window_option_invalid(session: Session) -> None:
    """Window.set_window_option raises ValueError for invalid option key."""
    window = session.new_window(window_name="test_window")

    if has_gte_version("2.4"):
        with pytest.raises(exc.InvalidOption):
            window.set_window_option("afewewfew", 43)
    else:
        with pytest.raises(exc.UnknownOption):
            window.set_window_option("afewewfew", 43)


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


@pytest.mark.skipif(
    has_lt_version("3.2"),
    reason="needs filter introduced in tmux >= 3.2",
)
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


@pytest.mark.skipif(
    has_lt_version("3.0"),
    reason="needs -e flag for split-window which was introduced in 3.0",
)
@pytest.mark.parametrize(
    "environment",
    [
        {"ENV_VAR": "pane"},
        {"ENV_VAR_1": "pane_1", "ENV_VAR_2": "pane_2"},
    ],
)
def test_split_with_environment(
    session: Session,
    environment: t.Dict[str, str],
) -> None:
    """Verify splitting window with environment variables."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in Path."

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


@pytest.mark.skipif(
    has_lte_version("3.1"),
    reason="3.2 has the -Z flag on split-window",
)
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


@pytest.mark.skipif(
    has_gte_version("3.0"),
    reason="3.0 has the -e flag on split-window",
)
def test_split_with_environment_logs_warning_for_old_tmux(
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify splitting window with environment variables warns if tmux too old."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in Path."

    window = session.new_window(window_name="split_with_environment")
    window.split(
        shell=f"{env} PS1='$ ' sh",
        environment={"ENV_VAR": "pane"},
    )

    assert any(
        "Environment flag ignored" in record.msg for record in caplog.records
    ), "Warning missing"


@pytest.mark.skipif(
    has_lt_version("2.9"),
    reason="resize-window only exists in tmux 2.9+",
)
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
        window.window_height
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


@pytest.mark.skipif(
    has_lt_version("3.2"),
    reason="Only 3.2+ has the -a and -b flag on new-window",
)
def test_new_window_with_direction(
    session: Session,
) -> None:
    """Verify new window with direction."""
    window = session.active_window
    window.refresh()

    window_initial = session.new_window(window_name="Example")
    assert window_initial.window_index == "2"

    window_before = window_initial.new_window(
        window_name="Window before", direction=WindowDirection.Before
    )
    window_initial.refresh()
    assert window_before.window_index == "2"
    assert window_initial.window_index == "3"

    window_after = window_initial.new_window(
        window_name="Window after", direction=WindowDirection.After
    )
    window_initial.refresh()
    window_after.refresh()
    assert window_after.window_index == "4"
    assert window_initial.window_index == "3"
    assert window_before.window_index == "2"


@pytest.mark.skipif(
    has_gte_version("3.2"),
    reason="Only 3.2+ has the -a and -b flag on new-window",
)
def test_new_window_with_direction_logs_warning_for_old_tmux(
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify new window with direction create a warning if tmux is too old."""
    window = session.active_window
    window.refresh()

    window.new_window(
        window_name="window_with_direction",
        direction=WindowDirection.After,
    )

    assert any(
        "Window target ignored" in record.msg for record in caplog.records
    ), "Warning missing"

    assert any(
        "Direction flag ignored" in record.msg for record in caplog.records
    ), "Warning missing"
