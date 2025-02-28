"""Provide exceptions used by libtmux.

libtmux.exc
~~~~~~~~~~~

This module implements exceptions used throughout libtmux for error
handling in sessions, windows, panes, and general usage. It preserves
existing exception definitions for backward compatibility and does not
remove any doctests.

Notes
-----
Exceptions in this module inherit from :exc:`LibTmuxException` or
specialized base classes to form a hierarchy of tmux-related errors.
"""

from __future__ import annotations

import typing as t

from libtmux._internal.query_list import ObjectDoesNotExist

if t.TYPE_CHECKING:
    from libtmux.neo import ListExtraArgs


class LibTmuxException(Exception):
    """Base exception for all libtmux errors."""


class TmuxSessionExists(LibTmuxException):
    """Raised if a tmux session with the requested name already exists."""


class TmuxCommandNotFound(LibTmuxException):
    """Raised when the tmux binary cannot be found on the system."""


class TmuxObjectDoesNotExist(ObjectDoesNotExist):
    """Raised when a tmux object cannot be found in the server output."""

    def __init__(
        self,
        obj_key: str | None = None,
        obj_id: str | None = None,
        list_cmd: str | None = None,
        list_extra_args: ListExtraArgs | None = None,
        *args: object,
    ) -> None:
        if all(arg is not None for arg in [obj_key, obj_id, list_cmd, list_extra_args]):
            super().__init__(
                f"Could not find {obj_key}={obj_id} for {list_cmd} "
                f"{list_extra_args if list_extra_args is not None else ''}",
            )
        else:
            super().__init__("Could not find object")


class VersionTooLow(LibTmuxException):
    """Raised if the installed tmux version is below the minimum required."""


class BadSessionName(LibTmuxException):
    """Raised if a tmux session name is disallowed (e.g., empty, has colons/periods)."""

    def __init__(
        self,
        reason: str,
        session_name: str | None = None,
        *args: object,
    ) -> None:
        msg = f"Bad session name: {reason}"
        if session_name is not None:
            msg += f" (session name: {session_name})"
        super().__init__(msg)


class OptionError(LibTmuxException):
    """Base exception for errors involving invalid, ambiguous, or unknown options."""


class UnknownOption(OptionError):
    """Raised if tmux reports an unknown option."""


class UnknownColorOption(UnknownOption):
    """Raised if a server color option is unknown (must be 88 or 256)."""

    def __init__(self, *args: object) -> None:
        super().__init__("Server.colors must equal 88 or 256")


class InvalidOption(OptionError):
    """Raised if tmux reports an invalid option (tmux >= 2.4)."""


class AmbiguousOption(OptionError):
    """Raised if tmux reports an option that could match more than one."""


class WaitTimeout(LibTmuxException):
    """Raised when a function times out waiting for a condition."""


class VariableUnpackingError(LibTmuxException):
    """Raised when an environment variable cannot be unpacked as expected."""

    def __init__(self, variable: t.Any | None = None, *args: object) -> None:
        super().__init__(f"Unexpected variable: {variable!s}")


class PaneError(LibTmuxException):
    """Base exception for pane-related errors."""


class PaneNotFound(PaneError):
    """Raised if a specified pane cannot be found."""

    def __init__(self, pane_id: str | None = None, *args: object) -> None:
        if pane_id is not None:
            super().__init__(f"Pane not found: {pane_id}")
        else:
            super().__init__("Pane not found")


class WindowError(LibTmuxException):
    """Base exception for window-related errors."""


class MultipleActiveWindows(WindowError):
    """Raised if multiple active windows are detected (where only one is expected)."""

    def __init__(self, count: int, *args: object) -> None:
        super().__init__(f"Multiple active windows: {count} found")


class NoActiveWindow(WindowError):
    """Raised if no active window exists when one is expected."""

    def __init__(self, *args: object) -> None:
        super().__init__("No active windows found")


class NoWindowsExist(WindowError):
    """Raised if a session or server has no windows."""

    def __init__(self, *args: object) -> None:
        super().__init__("No windows exist for object")


class AdjustmentDirectionRequiresAdjustment(LibTmuxException, ValueError):
    """Raised if an adjustment direction is set, but no adjustment value is provided."""

    def __init__(self) -> None:
        super().__init__("adjustment_direction requires adjustment")


class WindowAdjustmentDirectionRequiresAdjustment(
    WindowError,
    AdjustmentDirectionRequiresAdjustment,
):
    """Raised if window resizing requires an adjustment value, but none is provided."""


class PaneAdjustmentDirectionRequiresAdjustment(
    WindowError,
    AdjustmentDirectionRequiresAdjustment,
):
    """Raised if pane resizing requires an adjustment value, but none is provided."""


class RequiresDigitOrPercentage(LibTmuxException, ValueError):
    """Raised if a sizing argument must be a digit or a percentage."""

    def __init__(self) -> None:
        super().__init__("Requires digit (int or str digit) or a percentage.")
