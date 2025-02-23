"""Tests for libtmux Pane object."""

from __future__ import annotations

import logging
import shutil
import typing as t

import pytest

from libtmux.common import has_gte_version, has_lt_version, has_lte_version
from libtmux.constants import PaneDirection, ResizeAdjustmentDirection
from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    from libtmux.session import Session
    from libtmux.window import Window

logger = logging.getLogger(__name__)


def setup_shell_window(
    session: Session,
    window_name: str,
    environment: dict[str, str] | None = None,
) -> Window:
    """Set up a shell window with consistent environment and prompt.

    Args:
        session: The tmux session to create the window in
        window_name: Name for the new window
        environment: Optional environment variables to set in the window

    Returns
    -------
        The created Window object with shell ready
    """
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    window = session.new_window(
        attach=True,
        window_name=window_name,
        window_shell=f"{env} PROMPT_COMMAND='' PS1='READY>' sh",
        environment=environment,
    )

    pane = window.active_pane
    assert pane is not None

    # Wait for shell to be ready
    def wait_for_prompt() -> bool:
        try:
            pane_contents = "\n".join(pane.capture_pane())
            return "READY>" in pane_contents and len(pane_contents.strip()) > 0
        except Exception:
            return False

    retry_until(wait_for_prompt, 2, raises=True)
    return window


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
    window = setup_shell_window(session, "capture_pane")
    pane = window.active_pane
    assert pane is not None

    pane.send_keys(
        r'printf "\n%s\n" "Hello World !"',
        literal=True,
        suppress_history=False,
    )

    def wait_for_output() -> bool:
        try:
            pane_contents = "\n".join(pane.capture_pane())
            return (
                "Hello World !" in pane_contents
                and pane_contents.count("READY>") >= 2
                and r'printf "\n%s\n" "Hello World !"' in pane_contents
            )
        except Exception:
            return False

    # Wait for command output and new prompt
    retry_until(wait_for_output, 2, raises=True)

    pane_contents = "\n".join(pane.capture_pane())
    assert r'READY>printf "\n%s\n" "Hello World !"' in pane_contents
    assert "Hello World !" in pane_contents
    assert pane_contents.count("READY>") >= 2


def test_capture_pane_start(session: Session) -> None:
    """Assert Pane.capture_pane() with ``start`` param."""
    window = setup_shell_window(session, "capture_pane_start")
    pane = window.active_pane
    assert pane is not None

    pane_contents = "\n".join(pane.capture_pane())
    assert "READY>" in pane_contents

    pane.send_keys(r'printf "%s"', literal=True, suppress_history=False)

    def wait_for_command() -> bool:
        try:
            pane_contents = "\n".join(pane.capture_pane())
        except Exception:
            return False
        else:
            has_command = r'printf "%s"' in pane_contents
            has_prompts = pane_contents.count("READY>") >= 2
            return has_command and has_prompts

    retry_until(wait_for_command, 2, raises=True)

    pane.send_keys("clear -x", literal=True, suppress_history=False)

    def wait_until_pane_cleared() -> bool:
        pane_contents = "\n".join(pane.capture_pane())
        return "clear -x" not in pane_contents

    retry_until(wait_until_pane_cleared, 1, raises=True)

    def pane_contents_shell_prompt() -> bool:
        pane_contents = "\n".join(pane.capture_pane())
        return "READY>" in pane_contents and len(pane_contents.strip()) > 0

    retry_until(pane_contents_shell_prompt, 1, raises=True)

    pane_contents_history_start = pane.capture_pane(start=-2)
    assert r'READY>printf "%s"' in pane_contents_history_start[0]
    assert "READY>clear -x" in pane_contents_history_start[1]
    assert "READY>" in pane_contents_history_start[-1]

    pane.send_keys("")

    def pane_contents_capture_visible_only_shows_prompt() -> bool:
        pane_contents = "\n".join(pane.capture_pane(start=1))
        return "READY>" in pane_contents and len(pane_contents.strip()) > 0

    assert retry_until(pane_contents_capture_visible_only_shows_prompt, 1, raises=True)


def test_capture_pane_end(session: Session) -> None:
    """Assert Pane.capture_pane() with ``end`` param."""
    window = setup_shell_window(session, "capture_pane_end")
    pane = window.active_pane
    assert pane is not None

    pane_contents = "\n".join(pane.capture_pane())
    assert "READY>" in pane_contents

    pane.send_keys(r'printf "%s"', literal=True, suppress_history=False)

    def wait_for_command() -> bool:
        try:
            pane_contents = "\n".join(pane.capture_pane())
        except Exception:
            return False
        else:
            has_command = r'printf "%s"' in pane_contents
            has_prompts = pane_contents.count("READY>") >= 2
            return has_command and has_prompts

    retry_until(wait_for_command, 2, raises=True)

    pane_contents = "\n".join(pane.capture_pane(end=0))
    assert r'READY>printf "%s"' in pane_contents

    pane_contents = "\n".join(pane.capture_pane(end="-"))
    assert r'READY>printf "%s"' in pane_contents
    assert pane_contents.count("READY>") >= 2


@pytest.mark.skipif(
    has_lte_version("3.1"),
    reason="3.2 has the -Z flag on split-window",
)
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


@pytest.mark.skipif(
    has_lt_version("2.9"),
    reason="resize-window only exists in tmux 2.9+",
)
def test_resize_pane(
    session: Session,
) -> None:
    """Verify resizing window."""
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
    pane.resize_pane(
        height="50",
    )
    assert int(pane.pane_height) == 50

    # Manual: Width
    window.select_layout("main-horizontal")
    pane.resize_pane(
        width="75",
    )
    assert int(pane.pane_width) == 75

    if has_gte_version("3.1"):
        # Manual: Height percentage
        window.select_layout("main-vertical")
        pane_height_before = int(pane.pane_height)
        pane.resize_pane(
            height="15%",
        )
        assert int(pane.pane_height) == 75

        # Manual: Width percentage
        window.select_layout("main-horizontal")
        pane.resize_pane(
            width="15%",
        )
        assert int(pane.pane_width) == 75

    #
    # Adjustments
    #

    # Adjustment: Down
    pane_height_before = int(pane.pane_height)
    pane.resize_pane(
        adjustment_direction=ResizeAdjustmentDirection.Down,
        adjustment=pane_height_adjustment * 2,
    )
    assert pane_height_before - (pane_height_adjustment * 2) == int(pane.pane_height)

    # Adjustment: Up
    pane_height_before = int(pane.pane_height)
    pane.resize_pane(
        adjustment_direction=ResizeAdjustmentDirection.Up,
        adjustment=pane_height_adjustment,
    )
    assert pane_height_before + pane_height_adjustment == int(pane.pane_height)

    #
    # Zoom
    #
    pane.resize_pane(height=50)

    # Zoom
    pane.resize_pane(height=2)
    pane_height_before = int(pane.pane_height)
    pane.resize_pane(
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

    if has_gte_version("3.1"):
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
    else:
        window_height_before = (
            int(window.window_height) if isinstance(window.window_height, str) else 0
        )
        window_width_before = (
            int(window.window_width) if isinstance(window.window_width, str) else 0
        )
        new_pane = pane.split(size="10%")
        assert new_pane.pane_height == str(int(window_height_before * 0.1))

        new_pane = new_pane.split(direction=PaneDirection.Right, size="10%")
        assert new_pane.pane_width == str(int(window_width_before * 0.1))


def test_pane_context_manager(session: Session) -> None:
    """Test Pane context manager functionality."""
    window = session.new_window()
    with window.split() as pane:
        pane.send_keys('echo "Hello"')
        assert pane in window.panes
        assert len(window.panes) == 2  # Initial pane + new pane

    # Pane should be killed after exiting context
    assert pane not in window.panes
    assert len(window.panes) == 1  # Only initial pane remains
