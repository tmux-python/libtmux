"""Test utilities for waiting on tmux pane content.

This module provides utilities for waiting on tmux pane content in tests.
Inspired by Playwright's sync API for waiting on page content.
"""

from __future__ import annotations

import time
import typing as t
from dataclasses import dataclass
from typing import (
    TypeVar,
)

from libtmux.exc import LibTmuxException
from libtmux.test.retry import WaitTimeout, retry_until

if t.TYPE_CHECKING:
    from libtmux.pane import Pane

T = TypeVar("T")


class WaiterError(LibTmuxException):
    """Base exception for waiter errors."""


class WaiterTimeoutError(WaiterError):
    """Exception raised when waiting for content times out."""


class WaiterContentError(WaiterError):
    """Exception raised when there's an error getting or checking content."""


@dataclass
class WaitResult(t.Generic[T]):
    """Result of a wait operation."""

    success: bool
    value: T | None = None
    error: Exception | None = None


class PaneWaiter:
    """Utility class for waiting on tmux pane content."""

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
        result: WaitResult,
    ) -> bool:
        """Check pane content against predicate.

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
    ) -> WaitResult:
        """Wait for content in the pane to match a predicate."""
        result = WaitResult(success=False, value=None, error=None)
        try:
            # Give the shell a moment to be ready
            time.sleep(0.1)
            success = retry_until(
                lambda: self._check_content(predicate, result),
                seconds=timeout_seconds or self.timeout,
                interval=interval_seconds,
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
            if isinstance(e, (WaiterTimeoutError, WaiterContentError)):
                result.error = e
            else:
                result.error = WaiterContentError("Error capturing pane content")
                result.error.__cause__ = e
            result.success = False
        return result

    def wait_for_prompt(
        self,
        prompt: str,
        timeout_seconds: float | None = None,
        error_message: str | None = None,
    ) -> WaitResult:
        """Wait for a specific prompt to appear in the pane."""
        return self.wait_for_content(
            lambda content: prompt in content and len(content.strip()) > 0,
            timeout_seconds=timeout_seconds,
            error_message=error_message or f"Prompt '{prompt}' not found in pane",
        )

    def wait_for_text(
        self,
        text: str,
        timeout_seconds: float | None = None,
        error_message: str | None = None,
    ) -> WaitResult:
        """Wait for specific text to appear in the pane."""
        return self.wait_for_content(
            lambda content: text in content,
            timeout_seconds=timeout_seconds,
            error_message=error_message or f"Text '{text}' not found in pane",
        )
