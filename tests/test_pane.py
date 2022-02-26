"""Test for tmuxp Pane object."""
import logging

logger = logging.getLogger(__name__)


def test_resize_pane(session):
    """Test Pane.resize_pane()."""

    window = session.attached_window
    window.rename_window("test_resize_pane")

    pane1 = window.attached_pane
    pane1_height = pane1["pane_height"]
    window.split_window()

    pane1.resize_pane(height=4)
    assert pane1["pane_height"] != pane1_height
    assert int(pane1["pane_height"]) == 4

    pane1.resize_pane(height=3)
    assert int(pane1["pane_height"]) == 3


def test_send_keys(session):
    pane = session.attached_window.attached_pane
    pane.send_keys("c-c", literal=True)

    pane_contents = "\n".join(pane.cmd("capture-pane", "-p").stdout)
    assert "c-c" in pane_contents

    pane.send_keys("c-a", literal=False)
    assert "c-a" not in pane_contents, "should not print to pane"


def test_set_height(session):
    window = session.new_window(window_name="test_set_height")
    window.split_window()
    pane1 = window.attached_pane
    pane1_height = pane1["pane_height"]

    pane1.set_height(4)
    assert pane1["pane_height"] != pane1_height
    assert int(pane1["pane_height"]) == 4


def test_set_width(session):
    window = session.new_window(window_name="test_set_width")
    window.split_window()

    window.select_layout("main-vertical")
    pane1 = window.attached_pane
    pane1_width = pane1["pane_width"]

    pane1.set_width(10)
    assert pane1["pane_width"] != pane1_width
    assert int(pane1["pane_width"]) == 10

    pane1.reset()
