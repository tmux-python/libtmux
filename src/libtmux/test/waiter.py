"""Test utilities for waiting on tmux pane content.

This module provides utilities for waiting on tmux pane content in tests.
Inspired by Playwright's sync API for waiting on page content.

The main class is :class:`PaneWaiter` which provides methods to wait for specific
content to appear in a tmux pane. This is particularly useful for testing shell
commands and their output.

Examples
--------
>>> from libtmux.test.waiter import PaneWaiter
>>> # Create a new window and get its pane
>>> window = session.new_window(window_name="test_waiter")
>>> pane = window.active_pane
>>> # Create a waiter for the pane
>>> waiter = PaneWaiter(pane)
>>> # Wait for a specific prompt
>>> result = waiter.wait_for_prompt("$ ")
>>> result.success
True
>>> # Send a command and wait for its output
>>> pane.send_keys("echo 'Hello World'")
>>> result = waiter.wait_for_text("Hello World")
>>> result.success
True
>>> "Hello World" in result.value
True

The waiter also handles timeouts and errors gracefully:

>>> # Wait for text that won't appear (times out)
>>> result = waiter.wait_for_text("this won't appear", timeout_seconds=0.1)
>>> result.success
False
>>> isinstance(result.error, WaiterTimeoutError)
True
"""

from __future__ import annotations

import time
import typing as t
from dataclasses import dataclass
from typing import (
    TypeVar,
)

from libtmux.exc import LibTmuxException, WaitTimeout
from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    from libtmux.pane import Pane

T = TypeVar("T")


class WaiterError(LibTmuxException):
    """Base exception for waiter errors.

    This is the parent class for all waiter-specific exceptions.
    """


class WaiterTimeoutError(WaiterError):
    """Exception raised when waiting for content times out.

    This exception is raised when the content being waited for does not appear
    within the specified timeout period.

    Examples
    --------
    >>> waiter = PaneWaiter(pane, timeout=0.1)  # Short timeout
    >>> result = waiter.wait_for_text("won't appear")
    >>> isinstance(result.error, WaiterTimeoutError)
    True
    >>> str(result.error)
    "Text 'won't appear' not found in pane"
    """


class WaiterContentError(WaiterError):
    r"""Exception raised when there's an error getting or checking content.

    This exception is raised when there's an error accessing or reading the
    pane content, for example if the pane is no longer available.

    Examples
    --------
    >>> # Example of handling content errors
    >>> try:
    ...     content = "\\n".join(pane.capture_pane())
    ... except Exception as e:
    ...     error = WaiterContentError("Error capturing pane content")
    ...     error.__cause__ = e
    ...     raise error from e
    """


@dataclass
class WaitResult(t.Generic[T]):
    """Result of a wait operation.

    This class encapsulates the result of a wait operation, including whether it
    succeeded, the value found (if any), and any error that occurred.

    Parameters
    ----------
    success : bool
        Whether the wait operation succeeded
    value : T | None
        The value found, if any
    error : Exception | None
        The error that occurred, if any

    Examples
    --------
    >>> # Successful wait result
    >>> result = WaitResult[str](success=True, value="found content")
    >>> result.success
    True
    >>> result.value
    'found content'
    >>> result.error is None
    True

    >>> # Failed wait result with error
    >>> error = WaiterTimeoutError("Timed out")
    >>> result = WaitResult[str](success=False, error=error)
    >>> result.success
    False
    >>> result.value is None
    True
    >>> isinstance(result.error, WaiterTimeoutError)
    True
    """

    success: bool
    value: T | None = None
    error: Exception | None = None


class PaneWaiter:
    """Utility class for waiting on tmux pane content.

    This class provides methods to wait for specific content to appear in a tmux pane.
    It supports waiting for exact text matches, prompts, and custom predicates.

    Parameters
    ----------
    pane : Pane
        The tmux pane to wait on
    timeout : float, optional
        Default timeout in seconds, by default 2.0

    Examples
    --------
    Basic usage with text:

    >>> waiter = PaneWaiter(pane)
    >>> pane.send_keys("echo 'test'")
    >>> result = waiter.wait_for_text("test")
    >>> result.success
    True
    >>> "test" in result.value
    True

    Waiting for a prompt:

    >>> waiter = PaneWaiter(pane)
    >>> result = waiter.wait_for_prompt("$ ")
    >>> result.success
    True
    >>> "$ " in result.value
    True

    Custom predicate:

    >>> waiter = PaneWaiter(pane)
    >>> result = waiter.wait_for_content(lambda content: "error" not in content.lower())
    >>> result.success
    True

    Handling timeouts:

    >>> waiter = PaneWaiter(pane, timeout=0.1)  # Short timeout
    >>> result = waiter.wait_for_text("won't appear")
    >>> result.success
    False
    >>> isinstance(result.error, WaiterTimeoutError)
    True
    """

    def __init__(self, pane: Pane, timeout: float = 2.0) -> None:
        """Initialize PaneWaiter.

        Parameters
        ----------
        pane : Pane
            The tmux pane to wait on
        timeout : float, optional
            Default timeout in seconds, by default 2.0
        """
        self.pane = pane
        self.timeout = timeout

    def _check_content(
        self,
        predicate: t.Callable[[str], bool],
        result: WaitResult[str],
    ) -> bool:
        """Check pane content against predicate.

        This internal method captures the pane content and checks it against
        the provided predicate function.

        Parameters
        ----------
        predicate : Callable[[str], bool]
            Function that takes pane content as string and returns bool
        result : WaitResult
            Result object to store content if predicate matches

        Returns
        -------
        bool
            True if predicate matches, False otherwise

        Raises
        ------
        WaiterContentError
            If there's an error capturing pane content

        Examples
        --------
        >>> waiter = PaneWaiter(pane)
        >>> result = WaitResult[str](success=False)
        >>> success = waiter._check_content(lambda c: "test" in c, result)
        >>> success  # True if "test" is found in pane content
        True
        >>> result.value is not None
        True
        """
        try:
            content = "\n".join(self.pane.capture_pane())
            if predicate(content):
                result.value = content
                return True
            return False
        except Exception as e:
            error = WaiterContentError("Error capturing pane content")
            error.__cause__ = e
            raise error from e

    def wait_for_content(
        self,
        predicate: t.Callable[[str], bool],
        timeout_seconds: float | None = None,
        interval_seconds: float | None = None,
        error_message: str | None = None,
    ) -> WaitResult[str]:
        """Wait for content in the pane to match a predicate.

        This is the core waiting method that other methods build upon. It repeatedly
        checks the pane content against a predicate function until it returns True
        or times out.

        Parameters
        ----------
        predicate : Callable[[str], bool]
            Function that takes pane content as string and returns bool
        timeout_seconds : float | None, optional
            Maximum time to wait in seconds, by default None (uses instance timeout)
        interval_seconds : float | None, optional
            Time between checks in seconds, by default None (uses 0.05)
        error_message : str | None, optional
            Custom error message for timeout, by default None

        Returns
        -------
        WaitResult[str]
            Result of the wait operation

        Examples
        --------
        >>> waiter = PaneWaiter(pane)
        >>> # Wait for content containing "success" but not "error"
        >>> result = waiter.wait_for_content(
        ...     lambda content: "success" in content and "error" not in content
        ... )
        >>> result.success
        True

        >>> # Wait with custom timeout and interval
        >>> result = waiter.wait_for_content(
        ...     lambda content: "test" in content,
        ...     timeout_seconds=5.0,
        ...     interval_seconds=0.1,
        ... )
        >>> result.success
        True

        >>> # Wait with custom error message
        >>> result = waiter.wait_for_content(
        ...     lambda content: False,  # Never succeeds
        ...     timeout_seconds=0.1,
        ...     error_message="Custom timeout message",
        ... )
        >>> str(result.error)
        'Custom timeout message'
        """
        result = WaitResult[str](success=False, value=None, error=None)
        try:
            # Give the shell a moment to be ready
            time.sleep(0.1)
            success = retry_until(
                lambda: self._check_content(predicate, result),
                seconds=timeout_seconds or self.timeout,
                interval=interval_seconds or 0.05,
                raises=True,
            )
            result.success = success
            if not success:
                result.error = WaiterTimeoutError(
                    error_message or "Timed out waiting for content",
                )
        except WaitTimeout as e:
            result.error = WaiterTimeoutError(error_message or str(e))
            result.success = False
        except WaiterContentError as e:
            result.error = e
            result.success = False
        except Exception as e:
            result.error = WaiterTimeoutError(error_message or str(e))
            result.success = False
        return result

    def wait_for_prompt(
        self,
        prompt: str,
        timeout_seconds: float | None = None,
        error_message: str | None = None,
    ) -> WaitResult[str]:
        """Wait for a specific prompt to appear in the pane.

        This method waits for a specific shell prompt to appear in the pane.
        It ensures the prompt is at the end of non-empty content.

        Parameters
        ----------
        prompt : str
            The prompt text to wait for
        timeout_seconds : float | None, optional
            Maximum time to wait in seconds, by default None (uses instance timeout)
        error_message : str | None, optional
            Custom error message for timeout, by default None

        Returns
        -------
        WaitResult[str]
            Result of the wait operation

        Examples
        --------
        >>> waiter = PaneWaiter(pane)
        >>> # Wait for bash prompt
        >>> result = waiter.wait_for_prompt("$ ")
        >>> result.success
        True
        >>> "$ " in result.value
        True

        >>> # Wait for custom prompt
        >>> result = waiter.wait_for_prompt("my_prompt> ")
        >>> result.success
        True
        """
        return self.wait_for_content(
            lambda content: prompt in content and len(content.strip()) > 0,
            timeout_seconds=timeout_seconds,
            error_message=error_message or f"Prompt '{prompt}' not found in pane",
        )

    def wait_for_text(
        self,
        text: str,
        timeout_seconds: float | None = None,
        interval_seconds: float | None = None,
        error_message: str | None = None,
    ) -> WaitResult[str]:
        """Wait for text to appear in the pane.

        This method waits for specific text to appear anywhere in the pane content.

        Parameters
        ----------
        text : str
            The text to wait for
        timeout_seconds : float | None, optional
            Maximum time to wait in seconds, by default None (uses instance timeout)
        interval_seconds : float | None, optional
            Time between checks in seconds, by default None (uses 0.05)
        error_message : str | None, optional
            Custom error message for timeout, by default None

        Returns
        -------
        WaitResult[str]
            Result of the wait operation

        Examples
        --------
        >>> waiter = PaneWaiter(pane)
        >>> # Send a command and wait for its output
        >>> pane.send_keys("echo 'Hello World'")
        >>> result = waiter.wait_for_text("Hello World")
        >>> result.success
        True
        >>> "Hello World" in result.value
        True

        >>> # Wait with custom timeout
        >>> result = waiter.wait_for_text(
        ...     "test output",
        ...     timeout_seconds=5.0,
        ...     error_message="Failed to find test output",
        ... )
        >>> result.success
        True
        """
        if error_message is None:
            error_message = f"Text '{text}' not found in pane"
        return self.wait_for_content(
            lambda content: text in content,
            timeout_seconds=timeout_seconds,
            interval_seconds=interval_seconds,
            error_message=error_message,
        )
