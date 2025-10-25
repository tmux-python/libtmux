"""Terminal content waiting utility for libtmux tests.

This module provides functions to wait for specific content to appear in tmux panes,
making it easier to write reliable tests that interact with terminal output.
"""

from __future__ import annotations

import logging
import re
import time
import typing as t
from dataclasses import dataclass
from enum import Enum, auto

from libtmux._internal.retry_extended import retry_until_extended
from libtmux.exc import WaitTimeout
from libtmux.test.constants import (
    RETRY_INTERVAL_SECONDS,
    RETRY_TIMEOUT_SECONDS,
)
from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    from collections.abc import Callable

    from libtmux.pane import Pane
    from libtmux.server import Server
    from libtmux.session import Session
    from libtmux.window import Window

logger = logging.getLogger(__name__)


class ContentMatchType(Enum):
    """Type of content matching to use when waiting for pane content.

    Examples
    --------
    >>> # Using content match types with their intended patterns
    >>> ContentMatchType.EXACT
    <ContentMatchType.EXACT: 1>
    >>> ContentMatchType.CONTAINS
    <ContentMatchType.CONTAINS: 2>
    >>> ContentMatchType.REGEX
    <ContentMatchType.REGEX: 3>
    >>> ContentMatchType.PREDICATE
    <ContentMatchType.PREDICATE: 4>

    >>> # These match types are used to specify how to match content in wait functions
    >>> def demo_match_types():
    ...     # For exact matching (entire content must exactly match)
    ...     exact_type = ContentMatchType.EXACT
    ...     # For substring matching (content contains the specified string)
    ...     contains_type = ContentMatchType.CONTAINS
    ...     # For regex pattern matching
    ...     regex_type = ContentMatchType.REGEX
    ...     # For custom predicate functions
    ...     predicate_type = ContentMatchType.PREDICATE
    ...     return [exact_type, contains_type, regex_type, predicate_type]
    >>> match_types = demo_match_types()
    >>> len(match_types)
    4
    """

    EXACT = auto()  # Full exact match of content
    CONTAINS = auto()  # Content contains the specified string
    REGEX = auto()  # Content matches the specified regex pattern
    PREDICATE = auto()  # Custom predicate function returns True


@dataclass
class WaitResult:
    """Result from a wait operation.

    Attributes
    ----------
    success : bool
        Whether the wait operation succeeded
    content : list[str] | None
        The content of the pane at the time of the match
    matched_content : str | list[str] | None
        The content that matched the pattern
    match_line : int | None
        The line number of the match (0-indexed)
    elapsed_time : float | None
        Time taken for the wait operation
    error : str | None
        Error message if the wait operation failed
    matched_pattern_index : int | None
        Index of the pattern that matched (only for wait_for_any_content)

    Examples
    --------
    >>> # Create a successful wait result
    >>> result = WaitResult(
    ...     success=True,
    ...     content=["line 1", "hello world", "line 3"],
    ...     matched_content="hello world",
    ...     match_line=1,
    ...     elapsed_time=0.5,
    ... )
    >>> result.success
    True
    >>> result.matched_content
    'hello world'
    >>> result.match_line
    1

    >>> # Create a failed wait result with an error message
    >>> error_result = WaitResult(
    ...     success=False,
    ...     error="Timed out waiting for 'pattern' after 5.0 seconds",
    ... )
    >>> error_result.success
    False
    >>> error_result.error
    "Timed out waiting for 'pattern' after 5.0 seconds"
    >>> error_result.content is None
    True

    >>> # Wait result with matched_pattern_index (from wait_for_any_content)
    >>> multi_pattern = WaitResult(
    ...     success=True,
    ...     content=["command output", "success: operation completed", "more output"],
    ...     matched_content="success: operation completed",
    ...     match_line=1,
    ...     matched_pattern_index=2,
    ... )
    >>> multi_pattern.matched_pattern_index
    2
    """

    success: bool
    content: list[str] | None = None
    matched_content: str | list[str] | None = None
    match_line: int | None = None
    elapsed_time: float | None = None
    error: str | None = None
    matched_pattern_index: int | None = None


# Error messages as constants
ERR_PREDICATE_TYPE = "content_pattern must be callable when match_type is PREDICATE"
ERR_EXACT_TYPE = "content_pattern must be a string when match_type is EXACT"
ERR_CONTAINS_TYPE = "content_pattern must be a string when match_type is CONTAINS"
ERR_REGEX_TYPE = (
    "content_pattern must be a string or regex pattern when match_type is REGEX"
)


class PaneContentWaiter:
    r"""Fluent interface for waiting on pane content.

    This class provides a more fluent API for waiting on pane content,
    allowing method chaining for better readability.

    Examples
    --------
    >>> # Basic usage - assuming pane is a fixture from conftest.py
    >>> waiter = PaneContentWaiter(pane)
    >>> isinstance(waiter, PaneContentWaiter)
    True

    >>> # Method chaining to configure options
    >>> waiter = (
    ...     PaneContentWaiter(pane)
    ...     .with_timeout(10.0)
    ...     .with_interval(0.5)
    ...     .without_raising()
    ... )
    >>> waiter.timeout
    10.0
    >>> waiter.interval
    0.5
    >>> waiter.raises
    False

    >>> # Configure line range for capture
    >>> waiter = PaneContentWaiter(pane).with_line_range(0, 10)
    >>> waiter.start_line
    0
    >>> waiter.end_line
    10

    >>> # Create a checker for demonstration
    >>> import re
    >>> def is_ready(content):
    ...     return any("ready" in line.lower() for line in content)

    >>> # Methods available for different match types
    >>> hasattr(waiter, 'wait_for_text')
    True
    >>> hasattr(waiter, 'wait_for_exact_text')
    True
    >>> hasattr(waiter, 'wait_for_regex')
    True
    >>> hasattr(waiter, 'wait_for_predicate')
    True
    >>> hasattr(waiter, 'wait_until_ready')
    True

    A functional example: send text to the pane and wait for it:

    >>> # First, send "hello world" to the pane
    >>> pane.send_keys("echo 'hello world'", enter=True)
    >>>
    >>> # Then wait for it to appear in the pane content
    >>> result = PaneContentWaiter(pane).wait_for_text("hello world")
    >>> result.success
    True
    >>> "hello world" in result.matched_content
    True
    >>>

    With options:

    >>> result = (
    ...     PaneContentWaiter(pane)
    ...     .with_timeout(5.0)
    ...     .wait_for_text("hello world")
    ... )

    Wait for text with a longer timeout:

    >>> pane.send_keys("echo 'Operation completed'", enter=True)
    >>> try:
    ...     result = (
    ...         expect(pane)
    ...         .with_timeout(1.0)  # Reduce timeout for faster doctest execution
    ...         .wait_for_text("Operation completed")
    ...     )
    ...     print(f"Result success: {result.success}")
    ... except Exception as e:
    ...     print(f"Caught exception: {type(e).__name__}: {e}")
    Result success: True

    Wait for regex pattern:

    >>> pane.send_keys("echo 'Process 0 completed.'", enter=True)
    >>> try:
    ...     result = (
    ...         PaneContentWaiter(pane)
    ...         .with_timeout(1.0)  # Reduce timeout for faster doctest execution
    ...         .wait_for_regex(r"Process \d+ completed")
    ...     )
    ...     # Print debug info about the result for doctest
    ...     print(f"Result success: {result.success}")
    ... except Exception as e:
    ...     print(f"Caught exception: {type(e).__name__}: {e}")
    Result success: True

    Custom predicate:

    >>> pane.send_keys("echo 'We are ready!'", enter=True)
    >>> def is_ready(content):
    ...     return any("ready" in line.lower() for line in content)
    >>> result = PaneContentWaiter(pane).wait_for_predicate(is_ready)

    Timeout:

    >>> try:
    ...     result = (
    ...         PaneContentWaiter(pane)
    ...         .with_timeout(0.01)
    ...         .wait_for_exact_text("hello world")
    ...     )
    ... except WaitTimeout:
    ...     print('No exact match')
    No exact match
    """

    def __init__(self, pane: Pane) -> None:
        """Initialize with a tmux pane.

        Parameters
        ----------
        pane : Pane
            The tmux pane to check
        """
        self.pane = pane
        self.timeout: float = RETRY_TIMEOUT_SECONDS
        self.interval: float = RETRY_INTERVAL_SECONDS
        self.raises: bool = True
        self.start_line: t.Literal["-"] | int | None = None
        self.end_line: t.Literal["-"] | int | None = None

    def with_timeout(self, timeout: float) -> PaneContentWaiter:
        """Set the timeout for waiting.

        Parameters
        ----------
        timeout : float
            Maximum time to wait in seconds

        Returns
        -------
        PaneContentWaiter
            Self for method chaining
        """
        self.timeout = timeout
        return self

    def with_interval(self, interval: float) -> PaneContentWaiter:
        """Set the interval between checks.

        Parameters
        ----------
        interval : float
            Time between checks in seconds

        Returns
        -------
        PaneContentWaiter
            Self for method chaining
        """
        self.interval = interval
        return self

    def without_raising(self) -> PaneContentWaiter:
        """Disable raising exceptions on timeout.

        Returns
        -------
        PaneContentWaiter
            Self for method chaining
        """
        self.raises = False
        return self

    def with_line_range(
        self,
        start: t.Literal["-"] | int | None,
        end: t.Literal["-"] | int | None,
    ) -> PaneContentWaiter:
        """Specify lines to capture from the pane.

        Parameters
        ----------
        start : int | "-" | None
            Starting line for capture_pane (passed to pane.capture_pane)
        end : int | "-" | None
            End line for capture_pane (passed to pane.capture_pane)

        Returns
        -------
        PaneContentWaiter
            Self for method chaining
        """
        self.start_line = start
        self.end_line = end
        return self

    def wait_for_text(self, text: str) -> WaitResult:
        """Wait for text to appear in the pane (contains match).

        Parameters
        ----------
        text : str
            Text to wait for (contains match)

        Returns
        -------
        WaitResult
            Result of the wait operation
        """
        return wait_for_pane_content(
            pane=self.pane,
            content_pattern=text,
            match_type=ContentMatchType.CONTAINS,
            timeout=self.timeout,
            interval=self.interval,
            start=self.start_line,
            end=self.end_line,
            raises=self.raises,
        )

    def wait_for_exact_text(self, text: str) -> WaitResult:
        """Wait for exact text to appear in the pane.

        Parameters
        ----------
        text : str
            Text to wait for (exact match)

        Returns
        -------
        WaitResult
            Result of the wait operation
        """
        return wait_for_pane_content(
            pane=self.pane,
            content_pattern=text,
            match_type=ContentMatchType.EXACT,
            timeout=self.timeout,
            interval=self.interval,
            start=self.start_line,
            end=self.end_line,
            raises=self.raises,
        )

    def wait_for_regex(self, pattern: str | re.Pattern[str]) -> WaitResult:
        """Wait for text matching a regex pattern.

        Parameters
        ----------
        pattern : str | re.Pattern
            Regex pattern to match

        Returns
        -------
        WaitResult
            Result of the wait operation
        """
        return wait_for_pane_content(
            pane=self.pane,
            content_pattern=pattern,
            match_type=ContentMatchType.REGEX,
            timeout=self.timeout,
            interval=self.interval,
            start=self.start_line,
            end=self.end_line,
            raises=self.raises,
        )

    def wait_for_predicate(self, predicate: Callable[[list[str]], bool]) -> WaitResult:
        """Wait for a custom predicate function to return True.

        Parameters
        ----------
        predicate : callable
            Function that takes pane content lines and returns boolean

        Returns
        -------
        WaitResult
            Result of the wait operation
        """
        return wait_for_pane_content(
            pane=self.pane,
            content_pattern=predicate,
            match_type=ContentMatchType.PREDICATE,
            timeout=self.timeout,
            interval=self.interval,
            start=self.start_line,
            end=self.end_line,
            raises=self.raises,
        )

    def wait_until_ready(
        self,
        shell_prompt: str | re.Pattern[str] | None = None,
    ) -> WaitResult:
        """Wait until the pane is ready with a shell prompt.

        Parameters
        ----------
        shell_prompt : str | re.Pattern | None
            The shell prompt pattern to look for, or None to auto-detect

        Returns
        -------
        WaitResult
            Result of the wait operation
        """
        return wait_until_pane_ready(
            pane=self.pane,
            shell_prompt=shell_prompt,
            timeout=self.timeout,
            interval=self.interval,
            raises=self.raises,
        )


def expect(pane: Pane) -> PaneContentWaiter:
    r"""Fluent interface for waiting on pane content.

    This function provides a more fluent API for waiting on pane content,
    allowing method chaining for better readability.

    Examples
    --------
    Basic usage with pane fixture:

    >>> waiter = expect(pane)
    >>> isinstance(waiter, PaneContentWaiter)
    True

    Method chaining to configure the waiter:

    >>> configured_waiter = expect(pane).with_timeout(15.0).without_raising()
    >>> configured_waiter.timeout
    15.0
    >>> configured_waiter.raises
    False

    Equivalent to :class:`PaneContentWaiter` but with a more expressive name:

    >>> expect(pane) is not PaneContentWaiter(pane)  # Different instances
    True
    >>> type(expect(pane)) == type(PaneContentWaiter(pane))  # Same class
    True

    A functional example showing actual usage:

    >>> # Send a command to the pane
    >>> pane.send_keys("echo 'testing expect'", enter=True)
    >>>
    >>> # Wait for the output using the expect function
    >>> result = expect(pane).wait_for_text("testing expect")
    >>> result.success
    True
    >>>

    Wait for text with a longer timeout:

    >>> pane.send_keys("echo 'Operation completed'", enter=True)
    >>> try:
    ...     result = (
    ...         expect(pane)
    ...         .with_timeout(1.0)  # Reduce timeout for faster doctest execution
    ...         .without_raising()  # Don't raise exceptions
    ...         .wait_for_text("Operation completed")
    ...     )
    ...     print(f"Result success: {result.success}")
    ... except Exception as e:
    ...     print(f"Caught exception: {type(e).__name__}: {e}")
    Result success: True

    Wait for a regex match without raising exceptions on timeout:
    >>> pane.send_keys("echo 'Process 19 completed'", enter=True)
    >>> try:
    ...     result = (
    ...         expect(pane)
    ...         .with_timeout(1.0)  # Reduce timeout for faster doctest execution
    ...         .without_raising()  # Don't raise exceptions
    ...         .wait_for_regex(r"Process \d+ completed")
    ...     )
    ...     print(f"Result success: {result.success}")
    ... except Exception as e:
    ...     print(f"Caught exception: {type(e).__name__}: {e}")
    Result success: True
    """
    return PaneContentWaiter(pane)


def wait_for_pane_content(
    pane: Pane,
    content_pattern: str | re.Pattern[str] | Callable[[list[str]], bool],
    match_type: ContentMatchType = ContentMatchType.CONTAINS,
    timeout: float = RETRY_TIMEOUT_SECONDS,
    interval: float = RETRY_INTERVAL_SECONDS,
    start: t.Literal["-"] | int | None = None,
    end: t.Literal["-"] | int | None = None,
    raises: bool = True,
) -> WaitResult:
    r"""Wait for specific content to appear in a pane.

    Parameters
    ----------
    pane : Pane
        The tmux pane to wait for content in
    content_pattern : str | re.Pattern | callable
        Content to wait for. This can be:
        - A string to match exactly or check if contained (based on match_type)
        - A compiled regex pattern to match against
        - A predicate function that takes the pane content lines and returns a boolean
    match_type : ContentMatchType
        How to match the content_pattern against pane content
    timeout : float
        Maximum time to wait in seconds
    interval : float
        Time between checks in seconds
    start : int | "-" | None
        Starting line for capture_pane (passed to pane.capture_pane)
    end : int | "-" | None
        End line for capture_pane (passed to pane.capture_pane)
    raises : bool
        Whether to raise an exception on timeout

    Returns
    -------
    WaitResult
        Result object with success status and matched content information

    Raises
    ------
    WaitTimeout
        If raises=True and the timeout is reached before content is found

    Examples
    --------
    Wait with contains match (default), for testing purposes with a small timeout
    and no raises:

    >>> result = wait_for_pane_content(
    ...     pane=pane,
    ...     content_pattern=r"$",  # Look for shell prompt
    ...     timeout=0.5,
    ...     raises=False
    ... )
    >>> isinstance(result, WaitResult)
    True

    Using exact match:

    >>> result_exact = wait_for_pane_content(
    ...     pane=pane,
    ...     content_pattern="exact text to match",
    ...     match_type=ContentMatchType.EXACT,
    ...     timeout=0.1,
    ...     raises=False
    ... )
    >>> isinstance(result_exact, WaitResult)
    True

    Using regex pattern:

    >>> import re
    >>> pattern = re.compile(r"\$|%|>")  # Common shell prompts
    >>> result_regex = wait_for_pane_content(
    ...     pane=pane,
    ...     content_pattern=pattern,
    ...     match_type=ContentMatchType.REGEX,
    ...     timeout=0.1,
    ...     raises=False
    ... )
    >>> isinstance(result_regex, WaitResult)
    True

    Using predicate function:

    >>> def has_at_least_1_line(content):
    ...     return len(content) >= 1
    >>> result_pred = wait_for_pane_content(
    ...     pane=pane,
    ...     content_pattern=has_at_least_1_line,
    ...     match_type=ContentMatchType.PREDICATE,
    ...     timeout=0.1,
    ...     raises=False
    ... )
    >>> isinstance(result_pred, WaitResult)
    True

    Wait for a `$` written on the screen (unsubmitted):

    >>> pane.send_keys("$")
    >>> result = wait_for_pane_content(pane, "$", ContentMatchType.CONTAINS)

    Wait for exact text (unsubmitted, and fails):

    >>> try:
    ...     pane.send_keys("echo 'Success'")
    ...     result = wait_for_pane_content(
    ...         pane,
    ...         "Success",
    ...         ContentMatchType.EXACT,
    ...         timeout=0.01
    ...     )
    ... except WaitTimeout:
    ...     print("No exact match.")
    No exact match.

    Use regex pattern matching:

    >>> import re
    >>> pane.send_keys("echo 'Error: There was a problem.'")
    >>> result = wait_for_pane_content(
    ...     pane,
    ...     re.compile(r"Error: .*"),
    ...     ContentMatchType.REGEX
    ... )

    Use custom predicate function:

    >>> def has_at_least_3_lines(content):
    ...     return len(content) >= 3

    >>> for _ in range(5):
    ...     pane.send_keys("echo 'A line'", enter=True)
    >>> result = wait_for_pane_content(
    ...     pane,
    ...     has_at_least_3_lines,
    ...     ContentMatchType.PREDICATE
    ... )
    """
    result = WaitResult(success=False)

    def check_content() -> bool:
        """Check if the content pattern is in the pane."""
        content = pane.capture_pane(start=start, end=end)
        if isinstance(content, str):
            content = [content]

        result.content = content

        # Handle predicate match type
        if match_type == ContentMatchType.PREDICATE:
            if not callable(content_pattern):
                raise TypeError(ERR_PREDICATE_TYPE)
            # For predicate, we pass the list of content lines
            matched = content_pattern(content)
            if matched:
                result.matched_content = "\n".join(content)
                return True
            return False

        # Handle exact match type
        if match_type == ContentMatchType.EXACT:
            if not isinstance(content_pattern, str):
                raise TypeError(ERR_EXACT_TYPE)
            matched = "\n".join(content) == content_pattern
            if matched:
                result.matched_content = content_pattern
                return True
            return False

        # Handle contains match type
        if match_type == ContentMatchType.CONTAINS:
            if not isinstance(content_pattern, str):
                raise TypeError(ERR_CONTAINS_TYPE)
            content_str = "\n".join(content)
            if content_pattern in content_str:
                result.matched_content = content_pattern
                # Find which line contains the match
                for i, line in enumerate(content):
                    if content_pattern in line:
                        result.match_line = i
                        break
                return True
            return False

        # Handle regex match type
        if match_type == ContentMatchType.REGEX:
            if isinstance(content_pattern, (str, re.Pattern)):
                pattern = (
                    content_pattern
                    if isinstance(content_pattern, re.Pattern)
                    else re.compile(content_pattern)
                )
                content_str = "\n".join(content)
                match = pattern.search(content_str)
                if match:
                    result.matched_content = match.group(0)
                    # Try to find which line contains the match
                    for i, line in enumerate(content):
                        if pattern.search(line):
                            result.match_line = i
                            break
                    return True
                return False
            raise TypeError(ERR_REGEX_TYPE)
        return None

    try:
        success, exception = retry_until_extended(
            check_content,
            timeout,
            interval=interval,
            raises=raises,
        )
        if exception:
            if raises:
                raise
            result.error = str(exception)
            return result
        result.success = success
    except WaitTimeout as e:
        if raises:
            raise
        result.error = str(e)
    return result


def wait_until_pane_ready(
    pane: Pane,
    shell_prompt: str | re.Pattern[str] | Callable[[list[str]], bool] | None = None,
    match_type: ContentMatchType = ContentMatchType.CONTAINS,
    timeout: float = RETRY_TIMEOUT_SECONDS,
    interval: float = RETRY_INTERVAL_SECONDS,
    raises: bool = True,
) -> WaitResult:
    r"""Wait until pane is ready with shell prompt.

    This is a convenience function for the common case of waiting for a shell prompt.

    Parameters
    ----------
    pane : Pane
        The tmux pane to check
    shell_prompt : str | re.Pattern | callable
        The shell prompt pattern to look for, or None to auto-detect
    match_type : ContentMatchType
        How to match the shell_prompt
    timeout : float
        Maximum time to wait in seconds
    interval : float
        Time between checks in seconds
    raises : bool
        Whether to raise an exception on timeout

    Returns
    -------
    WaitResult
        Result of the wait operation

    Examples
    --------
    Basic usage - auto-detecting shell prompt:

    >>> result = wait_until_pane_ready(
    ...     pane=pane,
    ...     timeout=0.5,
    ...     raises=False
    ... )
    >>> isinstance(result, WaitResult)
    True

    Wait with specific prompt pattern:

    >>> result_prompt = wait_until_pane_ready(
    ...     pane=pane,
    ...     shell_prompt=r"$",
    ...     timeout=0.1,
    ...     raises=False
    ... )
    >>> isinstance(result_prompt, WaitResult)
    True

    Using regex pattern:

    >>> import re
    >>> pattern = re.compile(r"[$%#>]")
    >>> result_regex = wait_until_pane_ready(
    ...     pane=pane,
    ...     shell_prompt=pattern,
    ...     match_type=ContentMatchType.REGEX,
    ...     timeout=0.1,
    ...     raises=False
    ... )
    >>> isinstance(result_regex, WaitResult)
    True

    Using custom predicate function:

    >>> def has_prompt(content):
    ...     return any(line.endswith("$") for line in content)
    >>> result_predicate = wait_until_pane_ready(
    ...     pane=pane,
    ...     shell_prompt=has_prompt,
    ...     match_type=ContentMatchType.PREDICATE,
    ...     timeout=0.1,
    ...     raises=False
    ... )
    >>> isinstance(result_predicate, WaitResult)
    True
    """
    if shell_prompt is None:
        # Default to checking for common shell prompts
        def check_for_prompt(lines: list[str]) -> bool:
            content = "\n".join(lines)
            return "$" in content or "%" in content or "#" in content

        shell_prompt = check_for_prompt
        match_type = ContentMatchType.PREDICATE

    return wait_for_pane_content(
        pane=pane,
        content_pattern=shell_prompt,
        match_type=match_type,
        timeout=timeout,
        interval=interval,
        raises=raises,
    )


def wait_for_server_condition(
    server: Server,
    condition: Callable[[Server], bool],
    timeout: float = RETRY_TIMEOUT_SECONDS,
    interval: float = RETRY_INTERVAL_SECONDS,
    raises: bool = True,
) -> bool:
    """Wait for a condition on the server to be true.

    Parameters
    ----------
    server : Server
        The tmux server to check
    condition : callable
        A function that takes the server and returns a boolean
    timeout : float
        Maximum time to wait in seconds
    interval : float
        Time between checks in seconds
    raises : bool
        Whether to raise an exception on timeout

    Returns
    -------
    bool
        True if the condition was met, False if timed out (and raises=False)

    Examples
    --------
    Basic usage with a simple condition:

    >>> def has_sessions(server):
    ...     return len(server.sessions) > 0

    Assuming server has at least one session:

    >>> result = wait_for_server_condition(
    ...     server,
    ...     has_sessions,
    ...     timeout=0.1,
    ...     raises=False
    ... )
    >>> isinstance(result, bool)
    True

    Using a lambda for a simple condition:

    >>> result = wait_for_server_condition(
    ...     server,
    ...     lambda s: len(s.sessions) >= 1,
    ...     timeout=0.1,
    ...     raises=False
    ... )
    >>> isinstance(result, bool)
    True

    Condition that checks for a specific session:

    >>> def has_specific_session(server):
    ...     return any(s.name == "specific_name" for s in server.sessions)

    This will likely timeout since we haven't created that session:

    >>> result = wait_for_server_condition(
    ...     server,
    ...     has_specific_session,
    ...     timeout=0.1,
    ...     raises=False
    ... )
    >>> isinstance(result, bool)
    True
    """

    def check_condition() -> bool:
        return condition(server)

    return retry_until(check_condition, timeout, interval=interval, raises=raises)


def wait_for_session_condition(
    session: Session,
    condition: Callable[[Session], bool],
    timeout: float = RETRY_TIMEOUT_SECONDS,
    interval: float = RETRY_INTERVAL_SECONDS,
    raises: bool = True,
) -> bool:
    """Wait for a condition on the session to be true.

    Parameters
    ----------
    session : Session
        The tmux session to check
    condition : callable
        A function that takes the session and returns a boolean
    timeout : float
        Maximum time to wait in seconds
    interval : float
        Time between checks in seconds
    raises : bool
        Whether to raise an exception on timeout

    Returns
    -------
    bool
        True if the condition was met, False if timed out (and raises=False)

    Examples
    --------
    Basic usage with a simple condition:

    >>> def has_windows(session):
    ...     return len(session.windows) > 0

    Assuming session has at least one window:

    >>> result = wait_for_session_condition(
    ...     session,
    ...     has_windows,
    ...     timeout=0.1,
    ...     raises=False
    ... )
    >>> isinstance(result, bool)
    True

    Using a lambda for a simple condition:

    >>> result = wait_for_session_condition(
    ...     session,
    ...     lambda s: len(s.windows) >= 1,
    ...     timeout=0.1,
    ...     raises=False
    ... )
    >>> isinstance(result, bool)
    True

    Condition that checks for a specific window:

    >>> def has_specific_window(session):
    ...     return any(w.name == "specific_window" for w in session.windows)

    This will likely timeout since we haven't created that window:

    >>> result = wait_for_session_condition(
    ...     session,
    ...     has_specific_window,
    ...     timeout=0.1,
    ...     raises=False
    ... )
    >>> isinstance(result, bool)
    True
    """

    def check_condition() -> bool:
        return condition(session)

    return retry_until(check_condition, timeout, interval=interval, raises=raises)


def wait_for_window_condition(
    window: Window,
    condition: Callable[[Window], bool],
    timeout: float = RETRY_TIMEOUT_SECONDS,
    interval: float = RETRY_INTERVAL_SECONDS,
    raises: bool = True,
) -> bool:
    """Wait for a condition on the window to be true.

    Parameters
    ----------
    window : Window
        The tmux window to check
    condition : callable
        A function that takes the window and returns a boolean
    timeout : float
        Maximum time to wait in seconds
    interval : float
        Time between checks in seconds
    raises : bool
        Whether to raise an exception on timeout

    Returns
    -------
    bool
        True if the condition was met, False if timed out (and raises=False)

    Examples
    --------
    Basic usage with a simple condition:

    >>> def has_panes(window):
    ...     return len(window.panes) > 0

    Assuming window has at least one pane:

    >>> result = wait_for_window_condition(
    ...     window,
    ...     has_panes,
    ...     timeout=0.1,
    ...     raises=False
    ... )
    >>> isinstance(result, bool)
    True

    Using a lambda for a simple condition:

    >>> result = wait_for_window_condition(
    ...     window,
    ...     lambda w: len(w.panes) >= 1,
    ...     timeout=0.1,
    ...     raises=False
    ... )
    >>> isinstance(result, bool)
    True

    Condition that checks window layout:

    >>> def is_tiled_layout(window):
    ...     return window.window_layout == "tiled"

    Check for a specific layout:

    >>> result = wait_for_window_condition(
    ...     window,
    ...     is_tiled_layout,
    ...     timeout=0.1,
    ...     raises=False
    ... )
    >>> isinstance(result, bool)
    True
    """

    def check_condition() -> bool:
        return condition(window)

    return retry_until(check_condition, timeout, interval=interval, raises=raises)


def wait_for_window_panes(
    window: Window,
    expected_count: int,
    timeout: float = RETRY_TIMEOUT_SECONDS,
    interval: float = RETRY_INTERVAL_SECONDS,
    raises: bool = True,
) -> bool:
    """Wait until window has a specific number of panes.

    Parameters
    ----------
    window : Window
        The tmux window to check
    expected_count : int
        The number of panes to wait for
    timeout : float
        Maximum time to wait in seconds
    interval : float
        Time between checks in seconds
    raises : bool
        Whether to raise an exception on timeout

    Returns
    -------
    bool
        True if the condition was met, False if timed out (and raises=False)

    Examples
    --------
    Basic usage - wait for a window to have exactly 1 pane:

    >>> result = wait_for_window_panes(
    ...     window,
    ...     expected_count=1,
    ...     timeout=0.1,
    ...     raises=False
    ... )
    >>> isinstance(result, bool)
    True

    Wait for a window to have 2 panes (will likely timeout in this example):

    >>> result = wait_for_window_panes(
    ...     window,
    ...     expected_count=2,
    ...     timeout=0.1,
    ...     raises=False
    ... )
    >>> isinstance(result, bool)
    True

    In a real test, you might split the window first:

    >>> # window.split_window()  # Create a new pane
    >>> # Then wait for the pane count to update:
    >>> # result = wait_for_window_panes(window, 2)
    """

    def check_pane_count() -> bool:
        # Force refresh window panes list
        panes = window.panes
        return len(panes) == expected_count

    return retry_until(check_pane_count, timeout, interval=interval, raises=raises)


def wait_for_any_content(
    pane: Pane,
    content_patterns: list[str | re.Pattern[str] | Callable[[list[str]], bool]],
    match_types: list[ContentMatchType] | ContentMatchType,
    timeout: float = RETRY_TIMEOUT_SECONDS,
    interval: float = RETRY_INTERVAL_SECONDS,
    start: t.Literal["-"] | int | None = None,
    end: t.Literal["-"] | int | None = None,
    raises: bool = True,
) -> WaitResult:
    """Wait for any of the specified content patterns to appear in a pane.

    This is useful for handling alternative expected outputs.

    Parameters
    ----------
    pane : Pane
        The tmux pane to check
    content_patterns : list[str | re.Pattern | callable]
        List of content patterns to wait for, any of which can match
    match_types : list[ContentMatchType] | ContentMatchType
        How to match each content_pattern against pane content
    timeout : float
        Maximum time to wait in seconds
    interval : float
        Time between checks in seconds
    start : int | "-" | None
        Starting line for capture_pane (passed to pane.capture_pane)
    end : int | "-" | None
        End line for capture_pane (passed to pane.capture_pane)
    raises : bool
        Whether to raise an exception on timeout

    Returns
    -------
    WaitResult
        Result object with success status and matched pattern information

    Raises
    ------
    WaitTimeout
        If raises=True and the timeout is reached before any pattern is found
    TypeError
        If a match type is incompatible with the specified pattern
    ValueError
        If match_types list has a different length than content_patterns

    Examples
    --------
    Wait for any of the specified patterns:

    >>> pane.send_keys("echo 'pattern2'", enter=True)
    >>> result = wait_for_any_content(
    ...     pane,
    ...     ["pattern1", "pattern2"],
    ...     ContentMatchType.CONTAINS
    ... )

    Wait for any of the specified regex patterns:

    >>> import re
    >>> pane.send_keys("echo 'Error: this did not do the trick'", enter=True)
    >>> pane.send_keys("echo 'Success: But subsequently this worked'", enter=True)
    >>> result = wait_for_any_content(
    ...     pane,
    ...     [re.compile(r"Error: .*"), re.compile(r"Success: .*")],
    ...     ContentMatchType.REGEX
    ... )

    Wait for any of the specified predicate functions:

    >>> def has_at_least_3_lines(content):
    ...     return len(content) >= 3
    >>>
    >>> def has_at_least_5_lines(content):
    ...     return len(content) >= 5
    >>>
    >>> for _ in range(5):
    ...     pane.send_keys("echo 'A line'", enter=True)
    >>> result = wait_for_any_content(
    ...     pane,
    ...     [has_at_least_3_lines, has_at_least_5_lines],
    ...     ContentMatchType.PREDICATE
    ... )
    """
    if not content_patterns:
        msg = "At least one content pattern must be provided"
        raise ValueError(msg)

    # If match_types is a single value, convert to a list of the same value
    if not isinstance(match_types, list):
        match_types = [match_types] * len(content_patterns)
    elif len(match_types) != len(content_patterns):
        msg = (
            f"match_types list ({len(match_types)}) "
            f"doesn't match patterns ({len(content_patterns)})"
        )
        raise ValueError(msg)

    result = WaitResult(success=False)
    start_time = time.time()

    def check_any_content() -> bool:
        """Try to match any of the specified patterns."""
        content = pane.capture_pane(start=start, end=end)
        if isinstance(content, str):
            content = [content]

        result.content = content

        for i, (pattern, match_type) in enumerate(
            zip(content_patterns, match_types),
        ):
            # Handle predicate match
            if match_type == ContentMatchType.PREDICATE:
                if not callable(pattern):
                    msg = f"Pattern at index {i}: {ERR_PREDICATE_TYPE}"
                    raise TypeError(msg)
                # For predicate, we pass the list of content lines
                if pattern(content):
                    result.matched_content = "\n".join(content)
                    result.matched_pattern_index = i
                    return True
                continue  # Try next pattern

            # Handle exact match
            if match_type == ContentMatchType.EXACT:
                if not isinstance(pattern, str):
                    msg = f"Pattern at index {i}: {ERR_EXACT_TYPE}"
                    raise TypeError(msg)
                if "\n".join(content) == pattern:
                    result.matched_content = pattern
                    result.matched_pattern_index = i
                    return True
                continue  # Try next pattern

            # Handle contains match
            if match_type == ContentMatchType.CONTAINS:
                if not isinstance(pattern, str):
                    msg = f"Pattern at index {i}: {ERR_CONTAINS_TYPE}"
                    raise TypeError(msg)
                content_str = "\n".join(content)
                if pattern in content_str:
                    result.matched_content = pattern
                    result.matched_pattern_index = i
                    # Find which line contains the match
                    for i, line in enumerate(content):
                        if pattern in line:
                            result.match_line = i
                            break
                    return True
                continue  # Try next pattern

            # Handle regex match
            if match_type == ContentMatchType.REGEX:
                if isinstance(pattern, (str, re.Pattern)):
                    regex = (
                        pattern
                        if isinstance(pattern, re.Pattern)
                        else re.compile(pattern)
                    )
                    content_str = "\n".join(content)
                    match = regex.search(content_str)
                    if match:
                        result.matched_content = match.group(0)
                        result.matched_pattern_index = i
                        # Try to find which line contains the match
                        for i, line in enumerate(content):
                            if regex.search(line):
                                result.match_line = i
                                break
                        return True
                    continue  # Try next pattern
                msg = f"Pattern at index {i}: {ERR_REGEX_TYPE}"
                raise TypeError(msg)

        # None of the patterns matched
        return False

    try:
        success, exception = retry_until_extended(
            check_any_content,
            timeout,
            interval=interval,
            raises=raises,
        )
        if exception:
            if raises:
                raise
            result.error = str(exception)
            return result
        result.success = success
        result.elapsed_time = time.time() - start_time
    except WaitTimeout as e:
        if raises:
            raise
        result.error = str(e)
        result.elapsed_time = time.time() - start_time
    return result


def wait_for_all_content(
    pane: Pane,
    content_patterns: list[str | re.Pattern[str] | Callable[[list[str]], bool]],
    match_types: list[ContentMatchType] | ContentMatchType,
    timeout: float = RETRY_TIMEOUT_SECONDS,
    interval: float = RETRY_INTERVAL_SECONDS,
    start: t.Literal["-"] | int | None = None,
    end: t.Literal["-"] | int | None = None,
    raises: bool = True,
) -> WaitResult:
    """Wait for all patterns to appear in a pane.

    This function waits until all specified patterns are found in a pane.
    It supports mixed match types, allowing different patterns to be matched
    in different ways.

    Parameters
    ----------
    pane : Pane
        The tmux pane to check
    content_patterns : list[str | re.Pattern | callable]
        List of patterns to wait for
    match_types : list[ContentMatchType] | ContentMatchType
        How to match each pattern. Either a single match type for all patterns,
        or a list of match types, one for each pattern.
    timeout : float
        Maximum time to wait in seconds
    interval : float
        Time between checks in seconds
    start : int | "-" | None
        Starting line for capture_pane (passed to pane.capture_pane)
    end : int | "-" | None
        End line for capture_pane (passed to pane.capture_pane)
    raises : bool
        Whether to raise an exception on timeout

    Returns
    -------
    WaitResult
        Result object with status and match information

    Raises
    ------
    WaitTimeout
        If raises=True and the timeout is reached before all patterns are found
    TypeError
        If match types and patterns are incompatible
    ValueError
        If match_types list has a different length than content_patterns

    Examples
    --------
    Wait for all of the specified patterns:

    >>> # Send some text to the pane that will match both patterns
    >>> pane.send_keys("echo 'pattern1 pattern2'", enter=True)
    >>>
    >>> result = wait_for_all_content(
    ...     pane,
    ...     ["pattern1", "pattern2"],
    ...     ContentMatchType.CONTAINS,
    ...     timeout=0.5,
    ...     raises=False
    ... )
    >>> isinstance(result, WaitResult)
    True
    >>> result.success
    True

    Using regex patterns:

    >>> import re
    >>> # Send content that matches both regex patterns
    >>> pane.send_keys("echo 'Error: something went wrong'", enter=True)
    >>> pane.send_keys("echo 'Success: but we fixed it'", enter=True)
    >>>
    >>> result = wait_for_all_content(
    ...     pane,
    ...     [re.compile(r"Error: .*"), re.compile(r"Success: .*")],
    ...     ContentMatchType.REGEX,
    ...     timeout=0.5,
    ...     raises=False
    ... )
    >>> isinstance(result, WaitResult)
    True

    Using predicate functions:

    >>> def has_at_least_3_lines(content):
    ...     return len(content) >= 3
    >>>
    >>> def has_at_least_5_lines(content):
    ...     return len(content) >= 5
    >>>
    >>> # Send enough lines to satisfy both predicates
    >>> for _ in range(5):
    ...     pane.send_keys("echo 'Adding a line'", enter=True)
    >>>
    >>> result = wait_for_all_content(
    ...     pane,
    ...     [has_at_least_3_lines, has_at_least_5_lines],
    ...     ContentMatchType.PREDICATE,
    ...     timeout=0.5,
    ...     raises=False
    ... )
    >>> isinstance(result, WaitResult)
    True
    """
    if not content_patterns:
        msg = "At least one content pattern must be provided"
        raise ValueError(msg)

    # Convert single match_type to list of same type
    if not isinstance(match_types, list):
        match_types = [match_types] * len(content_patterns)
    elif len(match_types) != len(content_patterns):
        msg = (
            f"match_types list ({len(match_types)}) "
            f"doesn't match patterns ({len(content_patterns)})"
        )
        raise ValueError(msg)

    result = WaitResult(success=False)
    matched_patterns: list[str] = []
    start_time = time.time()

    def check_all_content() -> bool:
        content = pane.capture_pane(start=start, end=end)
        if isinstance(content, str):
            content = [content]

        result.content = content
        matched_patterns.clear()

        for i, (pattern, match_type) in enumerate(
            zip(content_patterns, match_types),
        ):
            # Handle predicate match
            if match_type == ContentMatchType.PREDICATE:
                if not callable(pattern):
                    msg = f"Pattern at index {i}: {ERR_PREDICATE_TYPE}"
                    raise TypeError(msg)
                # For predicate, we pass the list of content lines
                if not pattern(content):
                    return False
                matched_patterns.append(f"predicate_function_{i}")
                continue  # Pattern matched, check next

            # Handle exact match
            if match_type == ContentMatchType.EXACT:
                if not isinstance(pattern, str):
                    msg = f"Pattern at index {i}: {ERR_EXACT_TYPE}"
                    raise TypeError(msg)
                if "\n".join(content) != pattern:
                    return False
                matched_patterns.append(pattern)
                continue  # Pattern matched, check next

            # Handle contains match
            if match_type == ContentMatchType.CONTAINS:
                if not isinstance(pattern, str):
                    msg = f"Pattern at index {i}: {ERR_CONTAINS_TYPE}"
                    raise TypeError(msg)
                content_str = "\n".join(content)
                if pattern not in content_str:
                    return False
                matched_patterns.append(pattern)
                continue  # Pattern matched, check next

            # Handle regex match
            if match_type == ContentMatchType.REGEX:
                if isinstance(pattern, (str, re.Pattern)):
                    regex = (
                        pattern
                        if isinstance(pattern, re.Pattern)
                        else re.compile(pattern)
                    )
                    content_str = "\n".join(content)
                    match = regex.search(content_str)
                    if not match:
                        return False
                    matched_patterns.append(
                        pattern if isinstance(pattern, str) else pattern.pattern,
                    )
                    continue  # Pattern matched, check next
                msg = f"Pattern at index {i}: {ERR_REGEX_TYPE}"
                raise TypeError(msg)

        # All patterns matched
        result.matched_content = matched_patterns
        return True

    try:
        success, exception = retry_until_extended(
            check_all_content,
            timeout,
            interval=interval,
            raises=raises,
        )
        if exception:
            if raises:
                raise
            result.error = str(exception)
            return result
        result.success = success
        result.elapsed_time = time.time() - start_time
    except WaitTimeout as e:
        if raises:
            raise
        result.error = str(e)
        result.elapsed_time = time.time() - start_time
    return result


def _contains_match(
    content: list[str],
    pattern: str,
) -> tuple[bool, str | None, int | None]:
    r"""Check if content contains the pattern.

    Parameters
    ----------
    content : list[str]
        Lines of content to check
    pattern : str
        String to check for in content

    Returns
    -------
    tuple[bool, str | None, int | None]
        (matched, matched_content, match_line)

    Examples
    --------
    Pattern found in content:

    >>> content = ["line 1", "hello world", "line 3"]
    >>> matched, matched_text, line_num = _contains_match(content, "hello")
    >>> matched
    True
    >>> matched_text
    'hello'
    >>> line_num
    1

    Pattern not found:

    >>> matched, matched_text, line_num = _contains_match(content, "not found")
    >>> matched
    False
    >>> matched_text is None
    True
    >>> line_num is None
    True

    Pattern spans multiple lines (in the combined content):

    >>> multi_line = ["first part", "second part"]
    >>> content_str = "\n".join(multi_line)  # "first part\nsecond part"
    >>> # A pattern that spans the line boundary can be matched
    >>> "part\nsec" in content_str
    True
    >>> matched, _, _ = _contains_match(multi_line, "part\nsec")
    >>> matched
    True
    """
    content_str = "\n".join(content)
    if pattern in content_str:
        # Find which line contains the match
        return next(
            ((True, pattern, i) for i, line in enumerate(content) if pattern in line),
            (True, pattern, None),
        )

    return False, None, None


def _regex_match(
    content: list[str],
    pattern: str | re.Pattern[str],
) -> tuple[bool, str | None, int | None]:
    r"""Check if content matches the regex pattern.

    Parameters
    ----------
    content : list[str]
        Lines of content to check
    pattern : str | re.Pattern
        Regular expression pattern to match against content

    Returns
    -------
    tuple[bool, str | None, int | None]
        (matched, matched_content, match_line)

    Examples
    --------
    Using string pattern:

    >>> content = ["line 1", "hello world 123", "line 3"]
    >>> matched, matched_text, line_num = _regex_match(content, r"world \d+")
    >>> matched
    True
    >>> matched_text
    'world 123'
    >>> line_num
    1

    Using compiled pattern:

    >>> import re
    >>> pattern = re.compile(r"line \d")
    >>> matched, matched_text, line_num = _regex_match(content, pattern)
    >>> matched
    True
    >>> matched_text
    'line 1'
    >>> line_num
    0

    Pattern not found:

    >>> matched, matched_text, line_num = _regex_match(content, r"not found")
    >>> matched
    False
    >>> matched_text is None
    True
    >>> line_num is None
    True

    Matching groups in pattern:

    >>> content = ["user: john", "email: john@example.com"]
    >>> pattern = re.compile(r"email: ([\w.@]+)")
    >>> matched, matched_text, line_num = _regex_match(content, pattern)
    >>> matched
    True
    >>> matched_text
    'email: john@example.com'
    >>> line_num
    1
    """
    content_str = "\n".join(content)
    regex = pattern if isinstance(pattern, re.Pattern) else re.compile(pattern)

    if match := regex.search(content_str):
        matched_text = match.group(0)
        # Try to find which line contains the match
        return next(
            (
                (True, matched_text, i)
                for i, line in enumerate(content)
                if regex.search(line)
            ),
            (True, matched_text, None),
        )

    return False, None, None


def _match_regex_across_lines(
    content: list[str],
    pattern: re.Pattern[str],
) -> tuple[bool, str | None, int | None]:
    r"""Try to match a regex across multiple lines.

    Args:
        content: List of content lines
        pattern: Regex pattern to match

    Returns
    -------
        (matched, matched_content, match_line)

    Examples
    --------
    Pattern that spans multiple lines:

    >>> import re
    >>> content = ["start of", "multi-line", "content"]
    >>> pattern = re.compile(r"of\nmulti", re.DOTALL)
    >>> matched, matched_text, line_num = _match_regex_across_lines(content, pattern)
    >>> matched
    True
    >>> matched_text
    'of\nmulti'
    >>> line_num
    0

    Pattern that spans multiple lines but isn't found:

    >>> pattern = re.compile(r"not\nfound", re.DOTALL)
    >>> matched, matched_text, line_num = _match_regex_across_lines(content, pattern)
    >>> matched
    False
    >>> matched_text is None
    True
    >>> line_num is None
    True

    Complex multi-line pattern with groups:

    >>> content = ["user: john", "email: john@example.com", "status: active"]
    >>> pattern = re.compile(r"email: ([\w.@]+)\nstatus: (\w+)", re.DOTALL)
    >>> matched, matched_text, line_num = _match_regex_across_lines(content, pattern)
    >>> matched
    True
    >>> matched_text
    'email: john@example.com\nstatus: active'
    >>> line_num
    1
    """
    content_str = "\n".join(content)
    regex = pattern if isinstance(pattern, re.Pattern) else re.compile(pattern)

    if match := regex.search(content_str):
        matched_text = match.group(0)

        # Find the starting position of the match in the joined string
        start_pos = match.start()

        # Count newlines before the match to determine the starting line
        newlines_before_match = content_str[:start_pos].count("\n")
        return True, matched_text, newlines_before_match

    return False, None, None
