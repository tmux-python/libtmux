"""Tests for libtmux test waiter utilities."""

from __future__ import annotations

import shutil
import typing as t

from libtmux.test.waiter import PaneWaiter

if t.TYPE_CHECKING:
    from libtmux.session import Session


def test_wait_for_prompt(session: Session) -> None:
    """Test waiting for prompt."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    session.new_window(
        attach=True,
        window_name="test_waiter",
        window_shell=f"{env} PROMPT_COMMAND='' PS1='READY>' sh",
    )
    pane = session.active_window.active_pane
    assert pane is not None

    waiter = PaneWaiter(pane)
    result = waiter.wait_for_prompt("READY>")
    assert result.success
    assert result.value is not None
    assert "READY>" in result.value


def test_wait_for_text(session: Session) -> None:
    """Test waiting for text."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    session.new_window(
        attach=True,
        window_name="test_waiter",
        window_shell=f"{env} PROMPT_COMMAND='' PS1='READY>' sh",
    )
    pane = session.active_window.active_pane
    assert pane is not None

    waiter = PaneWaiter(pane)
    waiter.wait_for_prompt("READY>")  # Wait for shell to be ready

    pane.send_keys("echo 'Hello World'", literal=True)
    result = waiter.wait_for_text("Hello World")
    assert result.success
    assert result.value is not None
    assert "Hello World" in result.value


def test_wait_timeout(session: Session) -> None:
    """Test timeout behavior."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    session.new_window(
        attach=True,
        window_name="test_waiter",
        window_shell=f"{env} PROMPT_COMMAND='' PS1='READY>' sh",
    )
    pane = session.active_window.active_pane
    assert pane is not None

    waiter = PaneWaiter(pane, timeout=0.1)  # Short timeout
    result = waiter.wait_for_text("this text will never appear")
    assert not result.success
    assert result.value is None
    assert result.error is not None


def test_custom_error_message(session: Session) -> None:
    """Test custom error message."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    session.new_window(
        attach=True,
        window_name="test_waiter",
        window_shell=f"{env} PROMPT_COMMAND='' PS1='READY>' sh",
    )
    pane = session.active_window.active_pane
    assert pane is not None

    waiter = PaneWaiter(pane, timeout=0.1)  # Short timeout
    custom_message = "Custom error message"
    result = waiter.wait_for_text(
        "this text will never appear",
        error_message=custom_message,
    )
    assert not result.success
    assert result.value is None
    assert result.error is not None
    assert str(result.error) == custom_message


def test_wait_for_content_predicate(session: Session) -> None:
    """Test waiting with custom predicate."""
    env = shutil.which("env")
    assert env is not None, "Cannot find usable `env` in PATH."

    session.new_window(
        attach=True,
        window_name="test_waiter",
        window_shell=f"{env} PROMPT_COMMAND='' PS1='READY>' sh",
    )
    pane = session.active_window.active_pane
    assert pane is not None

    waiter = PaneWaiter(pane)
    waiter.wait_for_prompt("READY>")  # Wait for shell to be ready

    pane.send_keys("echo '123'", literal=True)
    result = waiter.wait_for_content(lambda content: "123" in content)
    assert result.success
    assert result.value is not None
    assert "123" in result.value
