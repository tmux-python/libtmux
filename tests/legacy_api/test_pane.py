"""Tests for libtmux Pane object."""

from __future__ import annotations

import logging
import shutil
import typing as t

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


def test_resize_pane(session: Session) -> None:
    """Verify Pane.resize_pane()."""
    window = setup_shell_window(session, "test_resize_pane")
    pane = window.active_pane
    assert pane is not None

    pane1 = window.attached_pane
    assert pane1 is not None
    pane1_height = pane1["pane_height"]
    window.split_window()

    pane1.resize_pane(height=4)
    assert pane1["pane_height"] != pane1_height
    assert int(pane1["pane_height"]) == 4

    pane1.resize_pane(height=3)
    assert int(pane1["pane_height"]) == 3


def test_send_keys(session: Session) -> None:
    """Verify Pane.send_keys()."""
    window = setup_shell_window(session, "test_send_keys")
    pane = window.active_pane
    assert pane is not None

    pane.send_keys("echo 'test'", literal=True)

    def wait_for_echo() -> bool:
        try:
            pane_contents = "\n".join(pane.capture_pane())
            return (
                "test" in pane_contents
                and "echo 'test'" in pane_contents
                and pane_contents.count("READY>") >= 2
            )
        except Exception:
            return False

    retry_until(wait_for_echo, 2, raises=True)


def test_set_height(session: Session) -> None:
    """Verify Pane.set_height()."""
    window = session.new_window(window_name="test_set_height")
    window.split_window()
    pane1 = window.attached_pane
    assert pane1 is not None
    pane1_height = pane1["pane_height"]

    pane1.set_height(4)
    assert pane1["pane_height"] != pane1_height
    assert int(pane1["pane_height"]) == 4


def test_set_width(session: Session) -> None:
    """Verify Pane.set_width()."""
    window = session.new_window(window_name="test_set_width")
    window.split_window()

    window.select_layout("main-vertical")
    pane1 = window.attached_pane
    assert pane1 is not None
    pane1_width = pane1["pane_width"]

    pane1.set_width(10)
    assert pane1["pane_width"] != pane1_width
    assert int(pane1["pane_width"]) == 10

    pane1.reset()


def test_capture_pane(session: Session) -> None:
    """Verify Pane.capture_pane()."""
    window = setup_shell_window(session, "test_capture_pane")
    pane = window.active_pane
    assert pane is not None

    pane_contents = "\n".join(pane.capture_pane())
    assert "READY>" in pane_contents
