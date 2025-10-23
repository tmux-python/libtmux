"""Exception hierarchy used across libtmux (sync and async)."""

from __future__ import annotations

import typing as _t

from libtmux._internal.query_list import ObjectDoesNotExist

if _t.TYPE_CHECKING:
    from libtmux.neo import ListExtraArgs


class LibtmuxError(Exception):
    """Root exception for libtmux."""


class LibTmuxException(LibtmuxError):
    """Historical base name kept for backwards compatibility."""


class TmuxSessionExists(LibTmuxException):
    """Session does not exist in the server."""


class TmuxCommandNotFound(LibTmuxException):
    """Application binary for tmux not found."""


class TmuxObjectDoesNotExist(ObjectDoesNotExist):
    """The query returned multiple objects when only one was expected."""

    def __init__(
        self,
        obj_key: str | None = None,
        obj_id: str | None = None,
        list_cmd: str | None = None,
        list_extra_args: ListExtraArgs | None = None,
        *args: object,
    ) -> None:
        if all(arg is not None for arg in [obj_key, obj_id, list_cmd, list_extra_args]):
            message = (
                f"Could not find {obj_key}={obj_id} for {list_cmd} "
                f"{list_extra_args if list_extra_args is not None else ''}"
            )
            super().__init__(message)
        else:
            super().__init__("Could not find object")


class VersionTooLow(LibTmuxException):
    """Raised if tmux below the minimum version to use libtmux."""


class BadSessionName(LibTmuxException):
    """Disallowed session name for tmux (empty, contains periods or colons)."""

    def __init__(
        self,
        reason: str,
        session_name: str | None = None,
        *args: object,
    ) -> None:
        message = f"Bad session name: {reason}"
        if session_name is not None:
            message += f" (session name: {session_name})"
        super().__init__(message)


class OptionError(LibTmuxException):
    """Root error for invalid, ambiguous or unknown options."""


class UnknownOption(OptionError):
    """Option unknown to tmux show-option(s) or show-window-option(s)."""


class UnknownColorOption(UnknownOption):
    """Unknown color option."""

    def __init__(self, *args: object) -> None:
        super().__init__("Server.colors must equal 88 or 256")


class InvalidOption(OptionError):
    """Option invalid to tmux, introduced in tmux v2.4."""


class AmbiguousOption(OptionError):
    """Option that could potentially match more than one."""


class WaitTimeout(LibTmuxException):
    """Function timed out without meeting condition."""


class VariableUnpackingError(LibTmuxException):
    """Error unpacking variable."""

    def __init__(self, variable: _t.Any | None = None, *args: object) -> None:
        super().__init__(f"Unexpected variable: {variable!s}")


class PaneError(LibTmuxException):
    """Any type of pane related error."""


class PaneNotFound(PaneError):
    """Pane not found."""

    def __init__(self, pane_id: str | None = None, *args: object) -> None:
        message = "Pane not found" if pane_id is None else f"Pane not found: {pane_id}"
        super().__init__(message)


class WindowError(LibTmuxException):
    """Any type of window related error."""


class MultipleActiveWindows(WindowError):
    """Multiple active windows."""

    def __init__(self, count: int, *args: object) -> None:
        super().__init__(f"Multiple active windows: {count} found")


class NoActiveWindow(WindowError):
    """No active window found."""

    def __init__(self, *args: object) -> None:
        super().__init__("No active windows found")


class NoWindowsExist(WindowError):
    """No windows exist for object."""

    def __init__(self, *args: object) -> None:
        super().__init__("No windows exist for object")


class AdjustmentDirectionRequiresAdjustment(LibTmuxException, ValueError):
    """If *adjustment_direction* is set, *adjustment* must be set."""

    def __init__(self) -> None:
        super().__init__("adjustment_direction requires adjustment")


class WindowAdjustmentDirectionRequiresAdjustment(
    WindowError,
    AdjustmentDirectionRequiresAdjustment,
):
    """ValueError for :meth:`libtmux.Window.resize_window`."""


class PaneAdjustmentDirectionRequiresAdjustment(
    WindowError,
    AdjustmentDirectionRequiresAdjustment,
):
    """ValueError for :meth:`libtmux.Pane.resize_pane`."""


class RequiresDigitOrPercentage(LibTmuxException, ValueError):
    """Requires digit (int or str digit) or a percentage."""

    def __init__(self) -> None:
        super().__init__("Requires digit (int or str digit) or a percentage.")


# Async-first additions -----------------------------------------------------


class OperationTimeout(LibtmuxError):
    """Raised when an operation exceeds a provided timeout."""


class Cancelled(LibtmuxError):
    """Raised when an operation is cancelled by the user or transport."""


class TransportClosed(LibtmuxError):
    """Raised when the transport is closed unexpectedly."""


class ProtocolError(LibtmuxError):
    """Raised when tmux control-mode frames cannot be parsed."""


class CommandError(LibtmuxError):
    """Raised when tmux returns %error or a non-zero exit."""

    def __init__(self, *, stdout: str, stderr: str, returncode: int) -> None:
        message = stderr or stdout or f"tmux exited {returncode}"
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


__all__ = sorted(
    {
        "AdjustmentDirectionRequiresAdjustment",
        "AmbiguousOption",
        "BadSessionName",
        "Cancelled",
        "CommandError",
        "InvalidOption",
        "LibTmuxException",
        "LibtmuxError",
        "MultipleActiveWindows",
        "NoActiveWindow",
        "NoWindowsExist",
        "OperationTimeout",
        "OptionError",
        "PaneAdjustmentDirectionRequiresAdjustment",
        "PaneError",
        "PaneNotFound",
        "ProtocolError",
        "RequiresDigitOrPercentage",
        "TmuxCommandNotFound",
        "TmuxObjectDoesNotExist",
        "TmuxSessionExists",
        "TransportClosed",
        "UnknownColorOption",
        "UnknownOption",
        "VariableUnpackingError",
        "VersionTooLow",
        "WaitTimeout",
        "WindowAdjustmentDirectionRequiresAdjustment",
        "WindowError",
    }
)
