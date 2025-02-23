"""Test utilities for waiting on tmux pane content.

This module provides utilities for waiting on tmux pane content in tests.
Inspired by Playwright's sync API for waiting on page content.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass
from typing import Callable, TypeVar

from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    from libtmux.pane import Pane

T = TypeVar("T")


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

    def wait_for_content(
        self,
        predicate: Callable[[str], bool],
        *,
        timeout: float | None = None,
        error_message: str | None = None,
    ) -> WaitResult[str]:
        """Wait for pane content to match predicate.

        Parameters
        ----------
        predicate : Callable[[str], bool]
            Function that takes pane content as string and returns bool
        timeout : float | None, optional
            Timeout in seconds, by default None (uses instance timeout)
        error_message : str | None, optional
            Custom error message if timeout occurs, by default None

        Returns
        -------
        WaitResult[str]
            Result containing success status and pane content if successful
        """
        timeout = timeout or self.timeout
        result = WaitResult[str](success=False)

        def check_content() -> bool:
            try:
                content = "\n".join(self.pane.capture_pane())
                if predicate(content):
                    result.success = True
                    result.value = content
                    return True
                else:
                    return False
            except Exception as e:
                result.error = e
                return False

        try:
            success = retry_until(check_content, timeout, raises=False)
            if not success:
                result.error = Exception(
                    error_message or "Timed out waiting for content",
                )
        except Exception as e:
            result.error = e
            if error_message:
                result.error = Exception(error_message)

        return result

    def wait_for_prompt(
        self,
        prompt: str,
        *,
        timeout: float | None = None,
        error_message: str | None = None,
    ) -> WaitResult[str]:
        """Wait for specific prompt to appear in pane.

        Parameters
        ----------
        prompt : str
            The prompt text to wait for
        timeout : float | None, optional
            Timeout in seconds, by default None (uses instance timeout)
        error_message : str | None, optional
            Custom error message if timeout occurs, by default None

        Returns
        -------
        WaitResult[str]
            Result containing success status and pane content if successful
        """
        return self.wait_for_content(
            lambda content: prompt in content and len(content.strip()) > 0,
            timeout=timeout,
            error_message=error_message or f"Prompt '{prompt}' not found in pane",
        )

    def wait_for_text(
        self,
        text: str,
        *,
        timeout: float | None = None,
        error_message: str | None = None,
    ) -> WaitResult[str]:
        """Wait for specific text to appear in pane.

        Parameters
        ----------
        text : str
            The text to wait for
        timeout : float | None, optional
            Timeout in seconds, by default None (uses instance timeout)
        error_message : str | None, optional
            Custom error message if timeout occurs, by default None

        Returns
        -------
        WaitResult[str]
            Result containing success status and pane content if successful
        """
        return self.wait_for_content(
            lambda content: text in content,
            timeout=timeout,
            error_message=error_message or f"Text '{text}' not found in pane",
        )
