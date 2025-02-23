"""Tests for libtmux test waiter utilities."""

from __future__ import annotations

import shutil
import typing as t

from libtmux.exc import WaitTimeout
from libtmux.test.waiter import (
    PaneWaiter,
    WaiterContentError,
    WaiterTimeoutError,
)

if t.TYPE_CHECKING:
    from pytest import MonkeyPatch

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
    assert isinstance(result.error, WaiterTimeoutError)
    assert str(result.error) == "Text 'this text will never appear' not found in pane"


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
    assert isinstance(result.error, WaiterTimeoutError)
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


def test_wait_for_content_inner_exception(
    session: Session,
    monkeypatch: MonkeyPatch,
) -> None:
    """Test exception handling in wait_for_content's inner try-except."""
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

    def mock_capture_pane(*args: t.Any, **kwargs: t.Any) -> list[str]:
        """Mock capture_pane that raises an exception."""
        msg = "Test error"
        raise WaiterContentError(msg)

    monkeypatch.setattr(pane, "capture_pane", mock_capture_pane)
    result = waiter.wait_for_text("some text")
    assert not result.success
    assert result.value is None
    assert result.error is not None
    assert isinstance(result.error, WaiterContentError)
    assert str(result.error) == "Error capturing pane content"
    assert isinstance(result.error.__cause__, WaiterContentError)
    assert str(result.error.__cause__) == "Test error"


def test_wait_for_content_outer_exception(
    session: Session,
    monkeypatch: MonkeyPatch,
) -> None:
    """Test exception handling in wait_for_content's outer try-except."""
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

    def mock_retry_until(*args: t.Any, **kwargs: t.Any) -> bool:
        """Mock retry_until that raises an exception."""
        msg = "Custom error"
        raise WaitTimeout(msg)

    monkeypatch.setattr("libtmux.test.waiter.retry_until", mock_retry_until)
    result = waiter.wait_for_text(
        "some text",
        error_message="Custom error",
    )
    assert not result.success
    assert result.value is None
    assert result.error is not None
    assert isinstance(result.error, WaiterTimeoutError)
    assert str(result.error) == "Custom error"


def test_wait_for_content_outer_exception_no_custom_message(
    session: Session,
    monkeypatch: MonkeyPatch,
) -> None:
    """Test exception handling in wait_for_content's outer try-except.

    Tests behavior when no custom error message is provided.
    """
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

    def mock_capture_pane(*args: t.Any, **kwargs: t.Any) -> list[str]:
        """Mock capture_pane that raises an exception."""
        msg = "Test error"
        raise WaiterContentError(msg)

    monkeypatch.setattr(pane, "capture_pane", mock_capture_pane)
    result = waiter.wait_for_text("some text")  # No custom error message
    assert not result.success
    assert result.value is None
    assert result.error is not None
    assert isinstance(result.error, WaiterContentError)
    assert str(result.error) == "Error capturing pane content"
    assert isinstance(result.error.__cause__, WaiterContentError)
    assert str(result.error.__cause__) == "Test error"


def test_wait_for_content_retry_exception(
    monkeypatch: MonkeyPatch,
    session: Session,
) -> None:
    """Test that retry exceptions are handled correctly."""
    window = session.new_window("test_waiter")
    pane = window.active_pane
    assert pane is not None

    def mock_retry_until(
        predicate: t.Callable[[], bool],
        seconds: float | None = None,
        interval: float | None = None,
        raises: bool | None = None,
    ) -> t.NoReturn:
        msg = "Text 'some text' not found in pane"
        raise WaitTimeout(msg)

    monkeypatch.setattr("libtmux.test.waiter.retry_until", mock_retry_until)
    waiter = PaneWaiter(pane)
    result = waiter.wait_for_content(lambda content: "some text" in content)

    assert not result.success
    assert result.value is None
    assert str(result.error) == "Text 'some text' not found in pane"
