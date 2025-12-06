"""Tests for libtmux Pane object."""

from __future__ import annotations

import logging
import pathlib
import shutil
import typing as t

import pytest

from libtmux import exc
from libtmux.common import has_gte_version
from libtmux.constants import PaneDirection, ResizeAdjustmentDirection
from libtmux.test.retry import retry_until
from tests.helpers import wait_for_line

if t.TYPE_CHECKING:
    from libtmux._internal.types import StrPath
    from libtmux.pane import Pane
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
    # Wait for "Hello World !" to appear in output (handles control mode async)
    wait_for_line(pane, lambda line: "Hello World !" in line)
    pane_contents = "\n".join(pane.capture_pane())
    expected_full = r'$ printf "\n%s\n" "Hello World !"' + "\n\nHello World !\n$"
    expected_no_prompt = r'$ printf "\n%s\n" "Hello World !"' + "\n\nHello World !"
    if session.server.engine.__class__.__name__ == "ControlModeEngine":
        # Control mode may capture before prompt appears (async behavior)
        assert pane_contents in (expected_full, expected_no_prompt)
    else:
        assert pane_contents == expected_full


@pytest.mark.engines(["subprocess", "control"])
def test_capture_pane_trims_whitespace_tail(session: Session) -> None:
    """capture-pane should drop trailing whitespace-only lines for all engines."""
    pane = session.active_pane
    assert pane is not None

    pane.send_keys('printf "line1\\n   \\n"', literal=True, suppress_history=False)
    wait_for_line(pane, lambda line: "line1" in line)

    lines = pane.capture_pane()
    assert lines
    # The last line should not be empty/whitespace-only
    assert lines[-1].strip() != ""
    # Ensure the whitespace-only line was trimmed
    assert "line1" in "\n".join(lines)


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
    if session.server.engine.__class__.__name__ == "ControlModeEngine":
        assert pane_contents in ('$ printf "%s"\n$', '$ printf "%s"')
    else:
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


def test_send_keys_flag_only_reset_emits_clean_argv(
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
) -> None:
    """``send_keys(reset=True)`` (no positional) emits ``send-keys -R`` only.

    tmux's flag-only path (``cmd-send-keys.c:223-225``) supports ``-R`` and
    ``-N`` without any trailing key argument; ``cmd=None`` routes through
    that path so the emitted argv has no spurious empty string.
    """
    pane = session.active_window.active_pane
    assert pane is not None

    captured: list[tuple[str, ...]] = []
    real_cmd = pane.cmd

    def fake_cmd(cmd_name: str, *args: t.Any, **kw: t.Any) -> t.Any:
        captured.append((cmd_name, *(str(a) for a in args)))
        return real_cmd(cmd_name, *args, **kw)

    monkeypatch.setattr(pane, "cmd", fake_cmd)

    pane.send_keys(reset=True)

    send_keys_calls = [c for c in captured if c[0] == "send-keys"]
    assert send_keys_calls == [("send-keys", "-R")]


def test_send_keys_flag_only_repeat_emits_dash_N(
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
) -> None:
    """``send_keys(repeat=3)`` flag-only emits ``send-keys -N 3`` only."""
    pane = session.active_window.active_pane
    assert pane is not None

    captured: list[tuple[str, ...]] = []
    real_cmd = pane.cmd

    def fake_cmd(cmd_name: str, *args: t.Any, **kw: t.Any) -> t.Any:
        captured.append((cmd_name, *(str(a) for a in args)))
        return real_cmd(cmd_name, *args, **kw)

    monkeypatch.setattr(pane, "cmd", fake_cmd)

    pane.send_keys(repeat=3, reset=True)

    send_keys_calls = [c for c in captured if c[0] == "send-keys"]
    assert send_keys_calls == [("send-keys", "-R", "-N", "3")]


def test_send_keys_flag_only_requires_a_flag(session: Session) -> None:
    """``send_keys()`` with neither ``cmd`` nor a flag raises ValueError."""
    pane = session.active_window.active_pane
    assert pane is not None

    with pytest.raises(ValueError, match="requires at least one of"):
        pane.send_keys()


PANE_FORMAT_FIELDS = (
    "pane_dead",
    "pane_format",
    "pane_in_mode",
    "pane_input_off",
    "pane_last",
    "pane_marked",
    "pane_marked_set",
    "pane_mode",
    "pane_path",
    "pane_pipe",
    "pane_synchronized",
)


@pytest.mark.parametrize("field_name", PANE_FORMAT_FIELDS)
def test_pane_format_field_declared_and_hydrated(
    field_name: str,
    session: Session,
) -> None:
    """Tmux's pane-scope format tokens hydrate onto the typed ``Pane`` object.

    Verifies each registered ``pane_*`` token from tmux's ``format_table[]``
    has a corresponding typed field on the ``Obj`` dataclass and that
    ``refresh()`` populates it. Older tmux releases that don't recognize a
    token expand it to the empty string, so the field reads as ``None``.
    """
    pane = session.active_window.active_pane
    assert pane is not None

    # Field must be declared on the dataclass.
    assert field_name in pane.__dataclass_fields__

    pane.refresh()
    value = getattr(pane, field_name)
    assert value is None or isinstance(value, str)


def test_pane_synchronized_reflects_window_state(session: Session) -> None:
    """``pane.pane_synchronized`` flips when synchronize-panes toggles."""
    window = session.active_window
    window.split()
    pane = window.active_pane
    assert pane is not None

    window.set_option("synchronize-panes", "on")
    pane.refresh()
    assert pane.pane_synchronized == "1"

    window.set_option("synchronize-panes", "off")
    pane.refresh()
    assert pane.pane_synchronized == "0"


PANE_SCOPE_OVERRIDE_FIELDS = (
    "cursor_x",
    "cursor_y",
    "cursor_flag",
    "mouse_all_flag",
    "mouse_any_flag",
    "mouse_button_flag",
    "mouse_sgr_flag",
    "mouse_standard_flag",
    "scroll_region_lower",
    "scroll_region_upper",
    "alternate_saved_x",
    "alternate_saved_y",
    "history_bytes",
    "history_limit",
    "history_size",
    "insert_flag",
    "keypad_cursor_flag",
    "keypad_flag",
    "origin_flag",
    "wrap_flag",
)


@pytest.mark.parametrize("field_name", PANE_SCOPE_OVERRIDE_FIELDS)
def test_pane_scope_override_field_hydrates(
    field_name: str,
    session: Session,
) -> None:
    """Per-token scope overrides admit each token into list-panes -F.

    These tokens' callbacks all dereference ``ft->wp`` in tmux's
    ``format.c`` (verified across tmux 3.2a through master), so the value
    must hydrate to a string on every supported tmux version. A ``None``
    here indicates the scope gate excluded the token from the format
    string, which is the regression class these overrides prevent.
    """
    pane = session.active_window.active_pane
    assert pane is not None
    pane.refresh()
    value = getattr(pane, field_name)
    assert value is not None, f"{field_name} should hydrate via list-panes"
    assert isinstance(value, str)


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
        test_id="no_expand",
        cmd="#{pane_id}",
        # no_expand=True → -l flag: output should be the literal string, not
        # the expanded pane id (which would start with %)
        kwargs={"get_text": True, "no_expand": True},
        expected_in_output="#{pane_id}",
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


def test_display_message_warns_on_tmux_error(session: Session) -> None:
    """Tmux stderr on ``display-message`` surfaces as a :class:`UserWarning`."""
    pane = session.active_window.active_pane
    assert pane is not None

    with pytest.warns(UserWarning, match="only one of -F or argument"):
        pane.display_message("x", get_text=True, format_string="#{pane_id}")


def test_split_percentage(session: Session) -> None:
    """Test Pane.split() with percentage parameter."""
    from libtmux.common import has_gte_version

    # tmux 3.4 has a regression in split-window -p; fixed in 3.5.
    # Per CHANGES FROM 3.4 TO 3.5: "Fix split-window -p."
    if not has_gte_version("3.5"):
        pytest.skip("split-window -p was broken in tmux 3.4 (fixed in 3.5)")

    window = session.new_window(window_name="test_split_pct")
    window.resize(height=40, width=80)
    pane = window.active_pane
    assert pane is not None

    new_pane = pane.split(percentage=25)
    assert new_pane in window.panes
    assert len(window.panes) == 2

    # The new pane should be roughly 25% of the window height
    new_pane.refresh()
    assert new_pane.pane_height is not None
    assert int(new_pane.pane_height) <= 15  # ~25% of 40


def test_split_percentage_size_mutual_exclusion(session: Session) -> None:
    """Test that size and percentage are mutually exclusive."""
    window = session.new_window(window_name="test_split_mutex")
    pane = window.active_pane
    assert pane is not None
    with pytest.raises(ValueError, match="Cannot specify both"):
        pane.split(size=10, percentage=50)


def test_send_prefix(session: Session) -> None:
    """Test Pane.send_prefix() sends prefix key without error."""
    pane = session.active_window.active_pane
    assert pane is not None
    pane.send_prefix()


def test_copy_mode(session: Session) -> None:
    """Test Pane.copy_mode() enters copy mode."""
    pane = session.active_window.active_pane
    assert pane is not None
    pane.copy_mode()
    # Exit copy mode
    pane.send_keys("q", enter=False)


def test_copy_mode_source_pane(session: Session) -> None:
    """Test Pane.copy_mode(source_pane=...) reads another pane's history."""
    window = session.new_window(window_name="copy_src")
    src = window.active_pane
    assert src is not None
    dest = window.split()
    src.send_keys("echo SOURCE_TEXT", enter=True)

    dest.copy_mode(source_pane=str(src.pane_id))
    dest.send_keys("q", enter=False)


def test_copy_mode_page_down(session: Session) -> None:
    """Test Pane.copy_mode(page_down=True) on tmux 3.5+."""
    if not has_gte_version("3.5"):
        pytest.skip("page_down requires tmux 3.5+")

    pane = session.active_window.active_pane
    assert pane is not None
    pane.copy_mode()
    pane.copy_mode(page_down=True)
    pane.send_keys("q", enter=False)


def test_clock_mode(session: Session) -> None:
    """Test Pane.clock_mode() enters clock mode."""
    pane = session.active_window.active_pane
    assert pane is not None
    pane.clock_mode()
    # Exit clock mode
    pane.send_keys("q", enter=False)


@pytest.mark.parametrize(
    "method",
    ["choose_buffer", "choose_client", "choose_tree", "customize_mode"],
)
def test_chooser_smoke(method: str, session: Session) -> None:
    """Smoke test: chooser/customize methods invoke without error."""
    pane = session.active_window.active_pane
    assert pane is not None
    getattr(pane, method)()


def test_choose_tree_with_flags(session: Session) -> None:
    """Test Pane.choose_tree() with format, filter, sort, reverse, zoom."""
    pane = session.active_window.active_pane
    assert pane is not None
    pane.choose_tree(
        format_string="#{session_name}",
        filter_expression="#{?session_attached,1,0}",
        sort_order="name",
        reverse=True,
        zoom=True,
    )


def test_find_window(session: Session) -> None:
    """Test Pane.find_window() opens filtered tree."""
    pane = session.active_window.active_pane
    assert pane is not None
    pane.find_window("sh")


def test_display_panes(
    control_mode: t.Callable[..., t.Any],
    session: Session,
) -> None:
    """Test Pane.display_panes() shows pane numbers."""
    pane = session.active_window.active_pane
    assert pane is not None
    with control_mode():
        pane.display_panes()


class DisplayPopupCase(t.NamedTuple):
    """Test case for display_popup() flag variations."""

    test_id: str
    kwargs: dict[str, t.Any]
    min_tmux_version: str | None


DISPLAY_POPUP_CASES: list[DisplayPopupCase] = [
    DisplayPopupCase(
        test_id="basic",
        kwargs={},
        min_tmux_version=None,
    ),
    DisplayPopupCase(
        test_id="dimensions",
        kwargs={"width": 40, "height": 10},
        min_tmux_version=None,
    ),
    DisplayPopupCase(
        test_id="position",
        kwargs={"x": "C", "y": "C"},
        min_tmux_version=None,
    ),
    DisplayPopupCase(
        test_id="start_directory",
        kwargs={"start_directory": pathlib.Path("/tmp")},
        min_tmux_version=None,
    ),
    DisplayPopupCase(
        test_id="title_v33",
        kwargs={"title": "popup_title"},
        min_tmux_version="3.3",
    ),
    DisplayPopupCase(
        test_id="border_lines_v33",
        kwargs={"border_lines": "single"},
        min_tmux_version="3.3",
    ),
    DisplayPopupCase(
        test_id="style_v33",
        kwargs={"style": "bg=blue"},
        min_tmux_version="3.3",
    ),
    DisplayPopupCase(
        test_id="border_style_v33",
        kwargs={"border_style": "fg=red"},
        min_tmux_version="3.3",
    ),
    DisplayPopupCase(
        test_id="environment_v33",
        kwargs={"environment": {"FOO": "bar"}},
        min_tmux_version="3.3",
    ),
    DisplayPopupCase(
        test_id="no_border_v33",
        kwargs={"no_border": True},
        min_tmux_version="3.3",
    ),
    DisplayPopupCase(
        test_id="close_on_any_key_v36",
        kwargs={"close_on_any_key": True},
        min_tmux_version="3.6",
    ),
    DisplayPopupCase(
        test_id="no_keys_v36",
        kwargs={"no_keys": True},
        min_tmux_version="3.6",
    ),
]


@pytest.mark.parametrize(
    list(DisplayPopupCase._fields),
    DISPLAY_POPUP_CASES,
    ids=[c.test_id for c in DISPLAY_POPUP_CASES],
)
def test_display_popup_flags(
    test_id: str,
    kwargs: dict[str, t.Any],
    min_tmux_version: str | None,
    control_mode: t.Callable[..., t.Any],
    session: Session,
    tmp_path: pathlib.Path,
) -> None:
    """Test Pane.display_popup() flag combinations.

    Each case adds a flag and runs ``touch <marker>`` inside the popup;
    verifying the marker file proves the popup invoked the command and
    the wrapper's flag-building branch was exercised.
    """
    if min_tmux_version and not has_gte_version(min_tmux_version):
        pytest.skip(f"Requires tmux {min_tmux_version}+")

    marker = tmp_path / f"popup_{test_id}.marker"
    pane = session.active_window.active_pane
    assert pane is not None

    call_kwargs = {"command": f"touch {marker}", "close_on_exit": True, **kwargs}

    with control_mode():
        pane.display_popup(**call_kwargs)

    retry_until(lambda: marker.exists(), 3, raises=True)


def test_display_popup_close_on_success(
    control_mode: t.Callable[..., t.Any],
    session: Session,
    tmp_path: pathlib.Path,
) -> None:
    """Test Pane.display_popup() with close_on_success (-EE) alone."""
    marker = tmp_path / "popup_close_on_success.marker"
    pane = session.active_window.active_pane
    assert pane is not None

    with control_mode():
        pane.display_popup(command=f"touch {marker}", close_on_success=True)

    retry_until(lambda: marker.exists(), 3, raises=True)


def test_display_popup_mutual_exclusion(session: Session) -> None:
    """close_on_exit and close_on_success are mutually exclusive."""
    pane = session.active_window.active_pane
    assert pane is not None
    with pytest.raises(ValueError, match="mutually exclusive"):
        pane.display_popup(close_on_exit=True, close_on_success=True)


def test_display_popup_close_existing(
    control_mode: t.Callable[..., t.Any],
    session: Session,
) -> None:
    """Test Pane.display_popup(close_existing=True) returns cleanly.

    ``-C`` (close existing popup) is a no-op when there is no popup;
    the test confirms the wrapper builds the flag without erroring.
    """
    pane = session.active_window.active_pane
    assert pane is not None

    with control_mode():
        pane.display_popup(close_existing=True)


def test_display_popup_target_client(
    control_mode: t.Callable[..., t.Any],
    session: Session,
    tmp_path: pathlib.Path,
) -> None:
    """Test Pane.display_popup(target_client=...) emits ``-c <client>``.

    ``-c`` has been on ``display-popup`` since tmux 3.2a, so no version
    guard is needed. The popup itself is invisible without a TTY-backed
    client; this is a smoke test for the flag-passing path.
    """
    pane = session.active_window.active_pane
    assert pane is not None
    marker = tmp_path / "popup_target_client.marker"

    with control_mode() as ctl:
        pane.display_popup(
            command=f"touch {marker}",
            close_on_exit=True,
            target_client=ctl.client_name,
        )

    retry_until(lambda: marker.exists(), 3, raises=True)


def test_paste_buffer(session: Session) -> None:
    """Test Pane.paste_buffer() pastes buffer content into pane."""
    env = shutil.which("env")
    assert env is not None

    window = session.new_window(
        window_name="test_paste",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = window.active_pane
    assert pane is not None

    retry_until(lambda: "$" in "\n".join(pane.capture_pane()), 2, raises=True)

    # Set buffer and paste it
    session.server.set_buffer("pasted_content", buffer_name="paste_test")
    pane.paste_buffer(buffer_name="paste_test")

    # Verify content appeared in pane
    retry_until(
        lambda: "pasted_content" in "\n".join(pane.capture_pane()),
        3,
        raises=True,
    )


def test_pipe_pane(session: Session, tmp_path: pathlib.Path) -> None:
    """Test Pane.pipe() pipes output to a file."""
    env = shutil.which("env")
    assert env is not None

    window = session.new_window(
        window_name="test_pipe",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = window.active_pane
    assert pane is not None

    retry_until(lambda: "$" in "\n".join(pane.capture_pane()), 2, raises=True)

    pipe_file = tmp_path / "pipe_output.txt"

    # Start piping
    pane.pipe(f"cat >> {pipe_file}")

    # Send some text
    pane.send_keys("echo pipe_test_ok", enter=True)
    retry_until(
        lambda: "pipe_test_ok" in "\n".join(pane.capture_pane()), 3, raises=True
    )

    # Stop piping
    pane.pipe()

    # Verify file has content
    retry_until(
        lambda: pipe_file.exists() and pipe_file.stat().st_size > 0, 3, raises=True
    )
    content = pipe_file.read_text()
    assert "pipe_test_ok" in content


def test_respawn_pane_kill(session: Session) -> None:
    """Test Pane.respawn() with kill flag on active pane."""
    window = session.new_window(window_name="test_respawn")
    pane = window.active_pane
    assert pane is not None

    # Respawn the active pane with kill
    pane.respawn(kill=True, shell="sh")

    # Pane should still exist and be alive
    pane.refresh()
    assert pane in window.panes


def test_move_pane(session: Session) -> None:
    """Test Pane.move() moves pane to another window."""
    w1 = session.new_window(window_name="move_src")
    pane = w1.active_pane
    assert pane is not None
    pane_to_move = pane.split(shell="sleep 1m")
    assert len(w1.panes) == 2

    w2 = session.new_window(window_name="move_dst")
    initial_w2_panes = len(w2.panes)

    pane_to_move.move(w2)

    w1.refresh()
    w2.refresh()
    assert len(w1.panes) == 1
    assert len(w2.panes) == initial_w2_panes + 1


def test_join_pane(session: Session) -> None:
    """Test Pane.join() roundtrip with break_pane."""
    window = session.new_window(window_name="test_join")
    pane = window.active_pane
    assert pane is not None

    # Create a second pane and break it out
    new_pane = pane.split(shell="sleep 1m")
    assert len(window.panes) == 2

    new_window = new_pane.break_pane()
    window.refresh()
    assert len(window.panes) == 1

    # Join the pane back
    new_pane.join(window)
    window.refresh()
    assert len(window.panes) == 2

    # The new window should be gone (only had one pane)
    session.refresh()
    window_ids = [w.window_id for w in session.windows]
    assert new_window.window_id not in window_ids


def test_join_pane_horizontal(session: Session) -> None:
    """Test Pane.join() with horizontal split."""
    window = session.new_window(window_name="test_join_h")
    window.resize(height=40, width=80)
    pane = window.active_pane
    assert pane is not None

    new_pane = pane.split(shell="sleep 1m")
    new_pane.break_pane()

    new_pane.join(window, vertical=False)
    window.refresh()
    assert len(window.panes) == 2


def test_break_pane_basic(session: Session) -> None:
    """Test Pane.break_pane() creates a new window."""
    window = session.new_window(window_name="test_break")
    initial_window_count = len(session.windows)
    pane = window.active_pane
    assert pane is not None

    new_pane = pane.split(shell="sleep 1m")
    assert len(window.panes) == 2

    new_window = new_pane.break_pane()
    session.refresh()

    assert len(session.windows) == initial_window_count + 1
    window.refresh()
    assert len(window.panes) == 1
    assert new_window.window_id is not None


def test_break_pane_with_name(session: Session) -> None:
    """Test Pane.break_pane() with window_name."""
    window = session.new_window(window_name="test_break_name")
    pane = window.active_pane
    assert pane is not None

    new_pane = pane.split(shell="sleep 1m")
    new_window = new_pane.break_pane(window_name="my_broken")
    assert new_window.window_name == "my_broken"


def test_break_pane_no_name_uses_natural_name(session: Session) -> None:
    """Pane.break_pane() without a name keeps tmux's default window name.

    The tmux 3.7 break-pane crash workaround injects a placeholder ``-n``
    when no ``window_name`` is given. On tmux 3.7a/3.7b, where the crash is
    already fixed, that placeholder must not leak as the window name -- the
    broken window should keep tmux's own auto-name (here ``sleep``).
    """
    window = session.new_window(window_name="test_break_natural")
    pane = window.active_pane
    assert pane is not None

    new_pane = pane.split(shell="sleep 123")
    broken = new_pane.break_pane()
    assert broken.window_name == "sleep"


def test_swap_pane(session: Session) -> None:
    """Test Pane.swap() swaps two panes."""
    window = session.new_window(window_name="test_swap_pane")
    window.resize(height=40, width=80)
    pane1 = window.active_pane
    assert pane1 is not None
    pane2 = pane1.split()

    pane1_id = pane1.pane_id
    pane2_id = pane2.pane_id

    # Record initial indices
    pane1.refresh()
    pane2.refresh()
    pane1_idx = pane1.pane_index
    pane2_idx = pane2.pane_index

    # Swap
    pane1.swap(pane2)

    # Verify indices swapped
    pane1.refresh()
    pane2.refresh()
    assert pane1.pane_index == pane2_idx
    assert pane2.pane_index == pane1_idx
    assert pane1.pane_id == pane1_id
    assert pane2.pane_id == pane2_id


def test_swap_pane_move_up_down(session: Session) -> None:
    """Pane.swap(move_up=True) / (move_down=True) work without a target."""
    window = session.new_window(window_name="test_swap_move")
    window.resize(height=40, width=80)
    pane1 = window.active_pane
    assert pane1 is not None
    pane2 = pane1.split()

    pane1.refresh()
    pane2.refresh()
    pane1_idx = pane1.pane_index
    pane2_idx = pane2.pane_index

    # move_down on pane1: swap with the next pane (pane2)
    pane1.swap(move_down=True)
    pane1.refresh()
    pane2.refresh()
    assert pane1.pane_index == pane2_idx
    assert pane2.pane_index == pane1_idx

    # move_up on pane1: swap back to the original layout
    pane1.swap(move_up=True)
    pane1.refresh()
    pane2.refresh()
    assert pane1.pane_index == pane1_idx
    assert pane2.pane_index == pane2_idx


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({}, "target or move_up"),
        ({"move_up": True, "move_down": True}, "mutually exclusive"),
        ({"move_up": True, "target": "%0"}, "mutually exclusive"),
    ],
)
def test_swap_pane_invalid_args(
    session: Session,
    kwargs: dict[str, t.Any],
    match: str,
) -> None:
    """Pane.swap() rejects missing or conflicting arguments."""
    pane = session.active_window.active_pane
    assert pane is not None
    with pytest.raises(exc.LibTmuxException, match=match):
        pane.swap(**kwargs)


def test_clear_history(session: Session) -> None:
    """Test Pane.clear_history()."""
    env = shutil.which("env")
    assert env is not None

    window = session.new_window(
        window_name="test_clearhist",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = window.active_pane
    assert pane is not None

    retry_until(lambda: "$" in "\n".join(pane.capture_pane()), 2, raises=True)

    # Send some commands to build up history
    pane.send_keys("echo line1", enter=True)
    pane.send_keys("echo line2", enter=True)
    retry_until(lambda: "line2" in "\n".join(pane.capture_pane()), 3, raises=True)

    # Clear history
    pane.clear_history()

    # The scrollback should be cleared (visible content may still show current)
    history = pane.capture_pane(start=-100)
    # After clearing, scrollback history should be much shorter
    assert len(history) <= 30  # reasonable bound after clear


def test_pane_reset_clears_history_and_sends_reset(session: Session) -> None:
    """Pane.reset() runs both ``send-keys -R`` and ``clear-history`` (#650).

    Populates scrollback, calls ``reset()``, then verifies the markers are
    gone — proving ``clear-history`` actually ran.
    """
    env = shutil.which("env")
    assert env is not None

    window = session.new_window(
        window_name="test_reset_650",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = window.active_pane
    assert pane is not None

    retry_until(lambda: "$" in "\n".join(pane.capture_pane()), 2, raises=True)

    # Populate scrollback.
    for n in range(5):
        pane.send_keys(f"echo reset_marker_{n}", enter=True)
    retry_until(
        lambda: "reset_marker_4" in "\n".join(pane.capture_pane()),
        3,
        raises=True,
    )

    # Sanity-check that the history is non-trivial pre-reset.
    pre = pane.capture_pane(start=-100)
    assert any("reset_marker_" in line for line in pre)

    result = pane.reset()
    assert result is pane

    # After reset, scrollback should be empty — the old code left the markers
    # behind because clear-history never executed.
    post = pane.capture_pane(start=-100)
    assert not any("reset_marker_" in line for line in post)


def test_pane_reset_targets_non_active_pane(session: Session) -> None:
    """Pane.reset() clears the target pane, not tmux's cmdq default.

    Regresses the bundled-IPC fix for the race-and-misroute combination:
    the previous two-call form raced under busy pane writers, and a naïve
    one-call form (``send-keys -R ; clear-history`` with one ``-t``) would
    route ``clear-history`` to tmux's default pane because the ``;``
    separator doesn't propagate ``-t`` across subcommands. The fix passes
    ``-t`` on both subcommands, so reset() must clear the *target* pane's
    scrollback while leaving any active sibling pane untouched.
    """
    env = shutil.which("env")
    assert env is not None

    window = session.new_window(
        window_name="test_reset_targets",
        window_shell=f"{env} PS1='$ ' sh",
    )
    # `attach=False` keeps the original pane active; the newly-split pane
    # is the non-active one. Call reset() on the non-active pane so a
    # missing -t on clear-history would route to the active sibling
    # instead.
    active_sibling = window.active_pane
    assert active_sibling is not None
    target = window.split(
        shell=f"{env} PS1='$ ' sh",
        attach=False,
    )
    assert target.pane_id != active_sibling.pane_id

    window.refresh()
    assert window.active_pane is not None
    assert window.active_pane.pane_id == active_sibling.pane_id

    # Push enough output through both panes to accumulate scrollback.
    # `seq 1 200` scrolls past the default 24-row visible region.
    def _history_size(pane: Pane) -> int:
        line = pane.cmd("display-message", "-p", "#{history_size}").stdout[0]
        return int(line)

    retry_until(
        lambda: "$" in "\n".join(active_sibling.capture_pane()),
        2,
        raises=True,
    )
    active_sibling.send_keys("seq 1 200", enter=True)
    retry_until(lambda: _history_size(active_sibling) > 0, 3, raises=True)

    retry_until(lambda: "$" in "\n".join(target.capture_pane()), 2, raises=True)
    target.send_keys("seq 1 200", enter=True)
    retry_until(lambda: _history_size(target) > 0, 3, raises=True)

    target_pre = _history_size(target)
    sibling_pre = _history_size(active_sibling)
    assert target_pre > 0
    assert sibling_pre > 0

    target.reset()

    # Target pane: history cleared.
    assert _history_size(target) == 0
    # Active sibling pane: untouched. (Under a missing-target clear-history,
    # this would have been wiped because it is the active pane.)
    assert _history_size(active_sibling) == sibling_pre


def test_pane_refresh_raises_when_pane_id_is_none(session: Session) -> None:
    """``Pane.refresh()`` raises ``ValueError`` when ``pane_id`` is unset.

    Mirrors the Client.refresh ``-O``-safe contract: the previous
    ``assert isinstance(...)`` stripped under ``python -O`` and let
    ``None`` flow into ``_refresh``, surfacing as a confusing downstream
    error. The explicit raise keeps the failure mode loud regardless of
    optimization level.
    """
    from libtmux.pane import Pane

    pane = Pane(server=session.server)
    assert pane.pane_id is None

    with pytest.raises(ValueError, match="pane_id"):
        pane.refresh()


class CaptureFlagWarnCase(t.NamedTuple):
    """Test case for capture_pane() 3.7 flag warn-and-ignore paths."""

    test_id: str
    kwargs: dict[str, t.Any]
    match: str


CAPTURE_FLAG_WARN_CASES: list[CaptureFlagWarnCase] = [
    CaptureFlagWarnCase(
        test_id="hyperlinks",
        kwargs={"hyperlinks": True},
        match="hyperlinks requires tmux 3.7",
    ),
    CaptureFlagWarnCase(
        test_id="line_numbers",
        kwargs={"line_numbers": True},
        match="line_numbers requires tmux 3.7",
    ),
    CaptureFlagWarnCase(
        test_id="line_flags",
        kwargs={"line_flags": True},
        match="line_flags requires tmux 3.7",
    ),
]


@pytest.mark.parametrize(
    list(CaptureFlagWarnCase._fields),
    CAPTURE_FLAG_WARN_CASES,
    ids=[c.test_id for c in CAPTURE_FLAG_WARN_CASES],
)
def test_capture_pane_3_7_flags(
    test_id: str,
    kwargs: dict[str, t.Any],
    match: str,
    session: Session,
) -> None:
    """Pane.capture_pane() -H/-L/-F on tmux 3.7+; warn-and-ignore below."""
    window = session.new_window(window_name="capture_37")
    pane = window.active_pane
    assert pane is not None

    if has_gte_version("3.7"):
        assert isinstance(pane.capture_pane(**kwargs), list)
    else:
        with pytest.warns(UserWarning, match=match):
            pane.capture_pane(**kwargs)


def test_split_empty(session: Session) -> None:
    """Pane.split(empty=True) creates an empty pane on tmux 3.7+."""
    window = session.new_window(window_name="split_empty")
    window.resize(height=40, width=80)
    pane = window.active_pane
    assert pane is not None

    if has_gte_version("3.7"):
        new_pane = pane.split(empty=True)
        assert new_pane in window.panes
        assert len(window.panes) == 2
    else:
        with pytest.warns(UserWarning, match="empty requires tmux 3.7"):
            pane.split(empty=True)


class SplitFlagCase(t.NamedTuple):
    """Test case for Pane.split() tmux 3.7 styling/remain flags."""

    test_id: str
    kwargs: dict[str, t.Any]


SPLIT_FLAG_CASES: list[SplitFlagCase] = [
    SplitFlagCase(test_id="style", kwargs={"style": "bg=red"}),
    SplitFlagCase(
        test_id="active_border_style", kwargs={"active_border_style": "fg=green"}
    ),
    SplitFlagCase(
        test_id="inactive_border_style", kwargs={"inactive_border_style": "fg=blue"}
    ),
    SplitFlagCase(test_id="message", kwargs={"message": "bye"}),
    SplitFlagCase(test_id="keep", kwargs={"keep": True}),
]


@pytest.mark.parametrize(
    list(SplitFlagCase._fields),
    SPLIT_FLAG_CASES,
    ids=[c.test_id for c in SPLIT_FLAG_CASES],
)
def test_split_3_7_flags(
    test_id: str,
    kwargs: dict[str, t.Any],
    session: Session,
) -> None:
    """Pane.split() tmux 3.7 styling/remain flags work on 3.7+; warn below."""
    window = session.new_window(window_name="split_37")
    window.resize(height=40, width=80)
    pane = window.active_pane
    assert pane is not None

    if has_gte_version("3.7"):
        new_pane = pane.split(**kwargs)
        assert new_pane in window.panes
    else:
        with pytest.warns(UserWarning, match=r"require tmux 3.7"):
            pane.split(**kwargs)


class _SplitEmptyValueKwargs(t.TypedDict, total=False):
    style: str
    active_border_style: str
    inactive_border_style: str
    message: str


class _SplitEmptyValueCase(t.NamedTuple):
    test_id: str
    option_kwargs: _SplitEmptyValueKwargs


_SPLIT_EMPTY_VALUE_CASES = (
    _SplitEmptyValueCase(test_id="style", option_kwargs={"style": ""}),
    _SplitEmptyValueCase(
        test_id="active_border_style", option_kwargs={"active_border_style": ""}
    ),
    _SplitEmptyValueCase(
        test_id="inactive_border_style", option_kwargs={"inactive_border_style": ""}
    ),
    _SplitEmptyValueCase(test_id="message", option_kwargs={"message": ""}),
)


@pytest.mark.parametrize(
    ("test_id", "option_kwargs"),
    _SPLIT_EMPTY_VALUE_CASES,
    ids=[case.test_id for case in _SPLIT_EMPTY_VALUE_CASES],
)
def test_split_preserves_empty_option_values(
    session: Session,
    test_id: str,
    option_kwargs: _SplitEmptyValueKwargs,
) -> None:
    """Pane.split() emits empty value flags as a separate argv entry."""
    window = session.new_window(window_name=f"split_empty_{test_id}")
    window.resize(height=40, width=120)
    pane = window.active_pane
    assert pane is not None

    if has_gte_version("3.7"):
        new_pane = pane.split(**option_kwargs)
        assert new_pane in window.panes
    else:
        with pytest.warns(UserWarning, match=r"require tmux 3.7"):
            pane.split(**option_kwargs)


def test_paste_buffer_no_vis(session: Session) -> None:
    """Pane.paste_buffer(no_vis=True) uses -S on tmux 3.7+; warn below."""
    env = shutil.which("env")
    assert env is not None

    window = session.new_window(
        window_name="paste_novis",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = window.active_pane
    assert pane is not None
    retry_until(lambda: "$" in "\n".join(pane.capture_pane()), 2, raises=True)

    session.server.set_buffer("raw_content", buffer_name="novis_test")
    if has_gte_version("3.7"):
        pane.paste_buffer(buffer_name="novis_test", no_vis=True)
        retry_until(
            lambda: "raw_content" in "\n".join(pane.capture_pane()),
            3,
            raises=True,
        )
    else:
        with pytest.warns(UserWarning, match="no_vis requires tmux 3.7"):
            pane.paste_buffer(buffer_name="novis_test", no_vis=True)


class _NewPaneEmptyValueKwargs(t.TypedDict, total=False):
    style: str
    active_border_style: str
    inactive_border_style: str
    message: str


class _NewPaneEmptyValueCase(t.NamedTuple):
    test_id: str
    option_kwargs: _NewPaneEmptyValueKwargs


_NEW_PANE_EMPTY_VALUE_CASES = (
    _NewPaneEmptyValueCase(test_id="style", option_kwargs={"style": ""}),
    _NewPaneEmptyValueCase(
        test_id="active_border_style",
        option_kwargs={"active_border_style": ""},
    ),
    _NewPaneEmptyValueCase(
        test_id="inactive_border_style",
        option_kwargs={"inactive_border_style": ""},
    ),
    _NewPaneEmptyValueCase(test_id="message", option_kwargs={"message": ""}),
)


def test_new_pane_floating(session: Session) -> None:
    """Pane.new_pane() creates a floating pane on tmux 3.7+ (else raises)."""
    window = session.new_window(window_name="floating_pane")
    window.resize(height=50, width=200)
    pane = window.active_pane
    assert pane is not None

    if has_gte_version("3.7"):
        floating = pane.new_pane(width=80, height=15, x=5, y=3, shell="sleep 30")
        assert floating.pane_floating_flag == "1"
        assert floating.pane_width == "80"
        assert floating.pane_height == "15"
    else:
        with pytest.raises(exc.LibTmuxException, match=r"new_pane .*requires tmux 3.7"):
            pane.new_pane(width=40, height=10)


def test_new_pane_keep(session: Session) -> None:
    """Pane.new_pane(keep=True) sets remain-on-exit (-k) on tmux 3.7+."""
    window = session.new_window(window_name="floating_keep")
    window.resize(height=50, width=200)
    pane = window.active_pane
    assert pane is not None

    if has_gte_version("3.7"):
        floating = pane.new_pane(width=80, height=15, keep=True, shell="sleep 30")
        assert floating.pane_floating_flag == "1"
        remain = floating.cmd("show-options", "-p", "-v", "remain-on-exit").stdout
        assert remain == ["key"]
    else:
        with pytest.raises(exc.LibTmuxException, match=r"requires tmux 3.7"):
            pane.new_pane(width=40, height=10, keep=True)


@pytest.mark.parametrize(
    ("test_id", "option_kwargs"),
    _NEW_PANE_EMPTY_VALUE_CASES,
    ids=[case.test_id for case in _NEW_PANE_EMPTY_VALUE_CASES],
)
def test_new_pane_preserves_empty_option_values(
    session: Session,
    test_id: str,
    option_kwargs: _NewPaneEmptyValueKwargs,
) -> None:
    """Pane.new_pane() preserves empty string option values."""
    window = session.new_window(window_name=f"floating_empty_{test_id}")
    pane = window.active_pane
    assert pane is not None

    if has_gte_version("3.7"):
        floating = pane.new_pane(
            width=40,
            height=10,
            shell="sleep 30",
            **option_kwargs,
        )
        assert floating.pane_floating_flag == "1"
    else:
        with pytest.raises(exc.LibTmuxException, match=r"requires tmux 3.7"):
            pane.new_pane(width=40, height=10, **option_kwargs)


def test_new_pane_error_tags_subcommand(session: Session) -> None:
    """Pane.new_pane() tags LibTmuxException with the new-pane subcommand."""
    window = session.new_window(window_name="new_pane_err")
    pane = window.active_pane
    assert pane is not None

    if has_gte_version("3.7"):
        with pytest.raises(exc.LibTmuxException) as excinfo:
            pane.new_pane(target="%99999")
        assert excinfo.value.subcommand == "new-pane"
        assert str(excinfo.value).startswith("new-pane:")
    else:
        with pytest.raises(exc.LibTmuxException, match=r"requires tmux 3.7"):
            pane.new_pane(target="%99999")
