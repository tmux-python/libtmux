"""Tests for libtmux Pane object."""

from __future__ import annotations

import logging
import pathlib
import shutil
import typing as t

import pytest

from libtmux.common import has_gte_version
from libtmux.constants import PaneDirection, ResizeAdjustmentDirection
from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    from libtmux._internal.types import StrPath
    from libtmux.session import Session

logger = logging.getLogger(__name__)


def test_send_keys(session: Session) -> None:
    """Verify Pane.send_keys()."""
    pane = session.active_window.active_pane
    assert pane is not None
    pane.send_keys("c-c", literal=True)

    pane_contents = "\n".join(pane.cmd("capture-pane", "-p").stdout)
    assert "c-c" in pane_contents

    pane.send_keys("c-a", literal=False)
    assert "c-a" not in pane_contents, "should not print to pane"


def test_set_height(session: Session) -> None:
    """Verify Pane.set_height()."""
    window = session.new_window(window_name="test_set_height")
    window.split()
    pane1 = window.active_pane
    assert pane1 is not None
    pane1_height = pane1.pane_height

    pane1.set_height(4)
    assert pane1.pane_height != pane1_height
    assert pane1.pane_height is not None
    assert int(pane1.pane_height) == 4


def test_set_width(session: Session) -> None:
    """Verify Pane.set_width()."""
    window = session.new_window(window_name="test_set_width")
    window.split()

    window.select_layout("main-vertical")
    pane1 = window.active_pane
    assert pane1 is not None
    pane1_width = pane1.pane_width

    pane1.set_width(10)
    assert pane1.pane_width != pane1_width
    assert pane1.pane_width is not None
    assert int(pane1.pane_width) == 10

    pane1.reset()


def test_capture_pane(session: Session) -> None:
    """Verify Pane.capture_pane()."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    session.new_window(
        attach=True,
        window_name="capture_pane",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = session.active_window.active_pane
    assert pane is not None
    pane_contents = "\n".join(pane.capture_pane())
    assert pane_contents == "$"
    pane.send_keys(
        r'printf "\n%s\n" "Hello World !"',
        literal=True,
        suppress_history=False,
    )
    pane_contents = "\n".join(pane.capture_pane())
    assert pane_contents == r'$ printf "\n%s\n" "Hello World !"{}'.format(
        "\n\nHello World !\n$",
    )


def test_capture_pane_start(session: Session) -> None:
    """Assert Pane.capture_pane() with ``start`` param."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    session.new_window(
        attach=True,
        window_name="capture_pane_start",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = session.active_window.active_pane
    assert pane is not None
    pane_contents = "\n".join(pane.capture_pane())
    assert pane_contents == "$"
    pane.send_keys(r'printf "%s"', literal=True, suppress_history=False)
    pane_contents = "\n".join(pane.capture_pane())
    assert pane_contents == '$ printf "%s"\n$'
    pane.send_keys("clear -x", literal=True, suppress_history=False)

    def wait_until_pane_cleared() -> bool:
        pane_contents = "\n".join(pane.capture_pane())
        return "clear -x" not in pane_contents

    retry_until(wait_until_pane_cleared, 1, raises=True)

    def pane_contents_shell_prompt() -> bool:
        pane_contents = "\n".join(pane.capture_pane())
        return pane_contents == "$"

    retry_until(pane_contents_shell_prompt, 1, raises=True)

    pane_contents_history_start = pane.capture_pane(start=-2)
    assert pane_contents_history_start[0] == '$ printf "%s"'
    assert pane_contents_history_start[1] == "$ clear -x"
    assert pane_contents_history_start[-1] == "$"

    pane.send_keys("")

    def pane_contents_capture_visible_only_shows_prompt() -> bool:
        pane_contents = "\n".join(pane.capture_pane(start=1))
        return pane_contents == "$"

    assert retry_until(pane_contents_capture_visible_only_shows_prompt, 1, raises=True)


def test_capture_pane_end(session: Session) -> None:
    """Assert Pane.capture_pane() with ``end`` param."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    session.new_window(
        attach=True,
        window_name="capture_pane_end",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = session.active_window.active_pane
    assert pane is not None
    pane_contents = "\n".join(pane.capture_pane())
    assert pane_contents == "$"
    pane.send_keys(r'printf "%s"', literal=True, suppress_history=False)
    pane_contents = "\n".join(pane.capture_pane())
    assert pane_contents == '$ printf "%s"\n$'
    pane_contents = "\n".join(pane.capture_pane(end=0))
    assert pane_contents == '$ printf "%s"'
    pane_contents = "\n".join(pane.capture_pane(end="-"))
    assert pane_contents == '$ printf "%s"\n$'


def test_pane_split_window_zoom(
    session: Session,
) -> None:
    """Verify splitting window with zoom."""
    window_without_zoom = session.new_window(window_name="split_without_zoom")
    initial_pane_without_zoom = window_without_zoom.active_pane
    assert initial_pane_without_zoom is not None
    window_with_zoom = session.new_window(window_name="split_with_zoom")
    initial_pane_with_zoom = window_with_zoom.active_pane
    assert initial_pane_with_zoom is not None
    pane_without_zoom = initial_pane_without_zoom.split(
        zoom=False,
    )
    pane_with_zoom = initial_pane_with_zoom.split(
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
    """Verify resizing pane."""
    session.cmd("detach-client", "-s")

    window = session.active_window
    pane = window.split(attach=False)
    window.split(direction=PaneDirection.Above, attach=False)

    assert pane is not None

    window.resize(height=500, width=500)

    pane_height_adjustment = 10

    assert pane.pane_height is not None
    assert pane.pane_width is not None

    #
    # Manual resizing
    #

    # Manual: Height
    pane_height_before = int(pane.pane_height)
    pane.resize(
        height="50",
    )
    assert int(pane.pane_height) == 50

    # Manual: Width
    window.select_layout("main-horizontal")
    pane.resize(
        width="75",
    )
    assert int(pane.pane_width) == 75

    # Manual: Height percentage
    window.select_layout("main-vertical")
    pane_height_before = int(pane.pane_height)
    pane.resize(
        height="15%",
    )
    assert int(pane.pane_height) == 75

    # Manual: Width percentage
    window.select_layout("main-horizontal")
    pane.resize(
        width="15%",
    )
    assert int(pane.pane_width) == 75

    #
    # Adjustments
    #

    # Adjustment: Down
    pane_height_before = int(pane.pane_height)
    pane.resize(
        adjustment_direction=ResizeAdjustmentDirection.Down,
        adjustment=pane_height_adjustment * 2,
    )
    assert pane_height_before - (pane_height_adjustment * 2) == int(pane.pane_height)

    # Adjustment: Up
    pane_height_before = int(pane.pane_height)
    pane.resize(
        adjustment_direction=ResizeAdjustmentDirection.Up,
        adjustment=pane_height_adjustment,
    )
    assert pane_height_before + pane_height_adjustment == int(pane.pane_height)

    #
    # Zoom
    #
    pane.resize(height=50)

    # Zoom
    pane.resize(height=2)
    pane_height_before = int(pane.pane_height)
    pane.resize(
        zoom=True,
    )
    pane_height_expanded = int(pane.pane_height)
    assert pane_height_before < pane_height_expanded


def test_split_pane_size(session: Session) -> None:
    """Pane.split()."""
    window = session.new_window(window_name="split window size")
    window.resize(height=100, width=100)
    pane = window.active_pane
    assert pane is not None

    short_pane = pane.split(size=10)
    assert short_pane.pane_height == "10"

    assert short_pane.at_left
    assert short_pane.at_right
    assert not short_pane.at_top
    assert short_pane.at_bottom

    narrow_pane = pane.split(direction=PaneDirection.Right, size=10)
    assert narrow_pane.pane_width == "10"

    assert not narrow_pane.at_left
    assert narrow_pane.at_right
    assert narrow_pane.at_top
    assert not narrow_pane.at_bottom

    new_pane = pane.split(size="10%")
    assert new_pane.pane_height == "8"

    new_pane = short_pane.split(direction=PaneDirection.Right, size="10%")
    assert new_pane.pane_width == "10"

    assert not new_pane.at_left
    assert new_pane.at_right


def test_set_title(session: Session) -> None:
    """Test Pane.set_title() sets pane title."""
    window = session.active_window
    pane = window.active_pane
    assert pane is not None
    result = pane.set_title("test-title")
    assert result == pane  # returns self for chaining
    assert pane.pane_title == "test-title"
    assert pane.title == "test-title"


def test_set_title_special_characters(session: Session) -> None:
    """Test Pane.set_title() with spaces and unicode."""
    pane = session.active_window.active_pane
    assert pane is not None
    pane.set_title("my pane title")
    assert pane.pane_title == "my pane title"

    pane.set_title("my π pane")
    assert pane.pane_title == "my π pane"


def test_pane_context_manager(session: Session) -> None:
    """Test Pane context manager functionality."""
    window = session.new_window()
    initial_pane_count = len(window.panes)

    with window.split() as pane:
        assert len(window.panes) == initial_pane_count + 1
        assert pane in window.panes

    # Pane should be killed after exiting context
    window.refresh()
    assert len(window.panes) == initial_pane_count


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
    """Test Pane.split start_directory parameter handling."""
    monkeypatch.chdir(tmp_path)

    window = session.new_window(window_name=f"test_split_{test_id}")
    pane = window.active_pane
    assert pane is not None

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
    new_pane = pane.split(start_directory=actual_start_directory)

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
    """Test Pane.split accepts pathlib.Path for start_directory."""
    window = session.new_window(window_name="test_split_pathlib")
    pane = window.active_pane
    assert pane is not None

    # Pass pathlib.Path directly to test pathlib.Path acceptance
    new_pane = pane.split(start_directory=user_path)

    assert new_pane in window.panes
    assert len(window.panes) == 2

    # Verify working directory
    new_pane.refresh()
    assert new_pane.pane_current_path is not None
    actual_path = str(pathlib.Path(new_pane.pane_current_path).resolve())
    expected_path = str(user_path.resolve())
    assert actual_path == expected_path


class SendKeysCase(t.NamedTuple):
    """Test case for send_keys() flag variations."""

    test_id: str
    key: str
    kwargs: dict[str, t.Any]
    expected_in_capture: str | None
    not_expected_in_capture: str | None
    min_tmux_version: str | None


SEND_KEYS_CASES: list[SendKeysCase] = [
    SendKeysCase(
        test_id="reset_terminal",
        key="",
        kwargs={"reset": True, "enter": False},
        expected_in_capture=None,
        not_expected_in_capture=None,
        min_tmux_version=None,
    ),
    SendKeysCase(
        test_id="repeat_count",
        key="a",
        kwargs={"repeat": 3, "literal": True, "enter": False},
        expected_in_capture="aaa",
        not_expected_in_capture=None,
        min_tmux_version=None,
    ),
    SendKeysCase(
        test_id="hex_key_A",
        key="41",
        kwargs={"hex_keys": True, "enter": False},
        expected_in_capture="A",
        not_expected_in_capture=None,
        min_tmux_version=None,
    ),
    SendKeysCase(
        test_id="expand_formats",
        key="a",
        kwargs={"expand_formats": True, "repeat": 2, "enter": False},
        expected_in_capture="aa",
        not_expected_in_capture=None,
        min_tmux_version=None,
    ),
    SendKeysCase(
        test_id="key_name_flag",
        key="a",
        kwargs={"key_name": True, "enter": False},
        expected_in_capture=None,
        not_expected_in_capture=None,
        min_tmux_version="3.4",
    ),
]


@pytest.mark.parametrize(
    list(SendKeysCase._fields),
    SEND_KEYS_CASES,
    ids=[c.test_id for c in SEND_KEYS_CASES],
)
def test_send_keys_flags(
    test_id: str,
    key: str,
    kwargs: dict[str, t.Any],
    expected_in_capture: str | None,
    not_expected_in_capture: str | None,
    min_tmux_version: str | None,
    session: Session,
) -> None:
    """Test send_keys() with various flag combinations."""
    if min_tmux_version and not has_gte_version(min_tmux_version):
        pytest.skip(f"Requires tmux {min_tmux_version}+")

    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    window = session.new_window(
        window_name=f"sk_{test_id[:15]}",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = window.active_pane
    assert pane is not None

    retry_until(lambda: "$" in "\n".join(pane.capture_pane()), 2, raises=True)

    pane.send_keys(key, **kwargs)

    if expected_in_capture is not None:
        retry_until(
            lambda: expected_in_capture in "\n".join(pane.capture_pane()),
            3,
            raises=True,
        )

    if not_expected_in_capture is not None:
        # Give a brief moment then verify absence
        contents = "\n".join(pane.capture_pane())
        assert not_expected_in_capture not in contents


def test_select_pane_direction(session: Session) -> None:
    """Test Pane.select() with direction flags."""
    window = session.new_window(window_name="test_select_dir")
    window.resize(height=40, width=80)
    pane_top = window.active_pane
    assert pane_top is not None
    pane_bottom = pane_top.split(direction=PaneDirection.Below)

    # Top pane should be active (it was active before split with -d default)
    pane_bottom.select()
    pane_bottom.refresh()
    assert pane_bottom.pane_active == "1"

    # Select up → should go to top pane
    pane_bottom.select(direction=ResizeAdjustmentDirection.Up)
    pane_top.refresh()
    assert pane_top.pane_active == "1"

    # Select down → should go back to bottom
    pane_top.select(direction=ResizeAdjustmentDirection.Down)
    pane_bottom.refresh()
    assert pane_bottom.pane_active == "1"


def test_select_pane_last(session: Session) -> None:
    """Test Pane.select() with last flag."""
    window = session.new_window(window_name="test_select_last")
    pane1 = window.active_pane
    assert pane1 is not None
    pane2 = pane1.split()

    # pane2 is now active (attach=True by default... wait, default is False)
    # After split, pane2 is NOT active since attach=False by default
    # Select pane2 explicitly
    pane2.select()
    pane2.refresh()
    assert pane2.pane_active == "1"

    # Now select pane1
    pane1.select()
    pane1.refresh()
    assert pane1.pane_active == "1"

    # Use -l to go back to last (pane2)
    pane1.select(last=True)
    pane2.refresh()
    assert pane2.pane_active == "1"


def test_select_pane_mark(session: Session) -> None:
    """Test Pane.select() with mark/clear_mark flags."""
    window = session.new_window(window_name="test_select_mark")
    pane = window.active_pane
    assert pane is not None

    # Mark the pane — verify no error
    pane.select(mark=True)

    # Clear the mark — verify no error
    pane.select(clear_mark=True)


def test_select_pane_disable_enable_input(session: Session) -> None:
    """Test Pane.select() with disable/enable input flags."""
    env = shutil.which("env")
    assert env is not None

    window = session.new_window(
        window_name="test_input_toggle",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = window.active_pane
    assert pane is not None

    retry_until(lambda: "$" in "\n".join(pane.capture_pane()), 2, raises=True)

    # Disable input
    pane.select(disable_input=True)

    # Send keys — they should not appear since input is disabled
    pane.send_keys("echo disabled_test", enter=False)

    # Verify "disabled_test" does NOT appear
    contents = "\n".join(pane.capture_pane())
    assert "disabled_test" not in contents

    # Re-enable input
    pane.select(enable_input=True)

    # Now send keys — they should appear
    pane.send_keys("echo enabled_ok", enter=True)
    retry_until(
        lambda: "enabled_ok" in "\n".join(pane.capture_pane()),
        3,
        raises=True,
    )


class DisplayMessageCase(t.NamedTuple):
    """Test case for display_message() flag variations."""

    test_id: str
    cmd: str
    kwargs: dict[str, t.Any]
    expected_in_output: str | None
    min_tmux_version: str | None


DISPLAY_MESSAGE_CASES: list[DisplayMessageCase] = [
    DisplayMessageCase(
        test_id="format_string",
        cmd="",
        kwargs={"get_text": True, "format_string": "#{pane_id}"},
        expected_in_output="%",
        min_tmux_version=None,
    ),
    DisplayMessageCase(
        test_id="all_formats",
        cmd="",
        kwargs={"get_text": True, "all_formats": True},
        expected_in_output="session_name",
        min_tmux_version=None,
    ),
    DisplayMessageCase(
        test_id="verbose",
        cmd="",
        kwargs={"get_text": True, "verbose": True, "all_formats": True},
        expected_in_output="session_name",
        min_tmux_version=None,
    ),
    DisplayMessageCase(
        test_id="list_formats",
        cmd="",
        kwargs={"get_text": True, "list_formats": True},
        expected_in_output=None,
        min_tmux_version="3.4",
    ),
]


@pytest.mark.parametrize(
    list(DisplayMessageCase._fields),
    DISPLAY_MESSAGE_CASES,
    ids=[c.test_id for c in DISPLAY_MESSAGE_CASES],
)
def test_display_message_flags(
    test_id: str,
    cmd: str,
    kwargs: dict[str, t.Any],
    expected_in_output: str | None,
    min_tmux_version: str | None,
    session: Session,
) -> None:
    """Test display_message() with various flag combinations."""
    if min_tmux_version and not has_gte_version(min_tmux_version):
        pytest.skip(f"Requires tmux {min_tmux_version}+")

    pane = session.active_window.active_pane
    assert pane is not None

    result = pane.display_message(cmd, **kwargs)

    if expected_in_output is not None:
        assert result is not None
        output = "\n".join(result)
        assert expected_in_output in output
