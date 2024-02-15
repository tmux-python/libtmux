"""Tests for libtmux Pane object."""
import logging
import shutil

import pytest

from libtmux.common import has_gte_version, has_lt_version
from libtmux.constants import ResizeAdjustmentDirection
from libtmux.session import Session

logger = logging.getLogger(__name__)


def test_send_keys(session: Session) -> None:
    """Verify Pane.send_keys()."""
    pane = session.attached_window.attached_pane
    assert pane is not None
    pane.send_keys("c-c", literal=True)

    pane_contents = "\n".join(pane.cmd("capture-pane", "-p").stdout)
    assert "c-c" in pane_contents

    pane.send_keys("c-a", literal=False)
    assert "c-a" not in pane_contents, "should not print to pane"


def test_set_height(session: Session) -> None:
    """Verify Pane.set_height()."""
    window = session.new_window(window_name="test_set_height")
    window.split_window()
    pane1 = window.attached_pane
    assert pane1 is not None
    pane1_height = pane1.pane_height

    pane1.set_height(4)
    assert pane1.pane_height != pane1_height
    assert pane1.pane_height is not None
    assert int(pane1.pane_height) == 4


def test_set_width(session: Session) -> None:
    """Verify Pane.set_width()."""
    window = session.new_window(window_name="test_set_width")
    window.split_window()

    window.select_layout("main-vertical")
    pane1 = window.attached_pane
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
    pane = session.attached_window.attached_pane
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
    pane = session.attached_window.attached_pane
    assert pane is not None
    pane_contents = "\n".join(pane.capture_pane())
    assert pane_contents == "$"
    pane.send_keys(r'printf "%s"', literal=True, suppress_history=False)
    pane_contents = "\n".join(pane.capture_pane())
    assert pane_contents == '$ printf "%s"\n$'
    pane.send_keys("clear -x", literal=True, suppress_history=False)
    pane_contents = "\n".join(pane.capture_pane())
    assert pane_contents == "$"
    pane_contents_start = pane.capture_pane(start=-2)
    assert pane_contents_start[0] == '$ printf "%s"'
    assert pane_contents_start[1] == "$ clear -x"
    assert pane_contents_start[-1] == "$"
    pane_contents_start = pane.capture_pane(start="-")
    assert pane_contents == "$"


def test_capture_pane_end(session: Session) -> None:
    """Assert Pane.capture_pane() with ``end`` param."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    session.new_window(
        attach=True,
        window_name="capture_pane_end",
        window_shell=f"{env} PS1='$ ' sh",
    )
    pane = session.attached_window.attached_pane
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


@pytest.mark.skipif(
    has_lt_version("2.9"),
    reason="resize-window only exists in tmux 2.9+",
)
def test_resize_pane(
    session: Session,
) -> None:
    """Verify resizing window."""
    session.cmd("detach-client", "-s")

    window = session.attached_window
    pane = window.split_window(attach=False)
    window.split_window(vertical=True, attach=False)

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
