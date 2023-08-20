"""libtmux exceptions.

libtmux.exc
~~~~~~~~~~~

"""
import typing as t


class LibTmuxException(Exception):

    """Base Exception for libtmux Errors."""


class TmuxSessionExists(LibTmuxException):

    """Session does not exist in the server."""


class TmuxCommandNotFound(LibTmuxException):

    """Application binary for tmux not found."""


class VersionTooLow(LibTmuxException):

    """Raised if tmux below the minimum version to use libtmux."""


class BadSessionName(LibTmuxException):

    """Disallowed session name for tmux (empty, contains periods or colons)."""

    def __init__(
        self, reason: str, session_name: t.Optional[str] = None, *args: object
    ):
        msg = f"Bad session name: {reason}"
        if session_name is not None:
            msg += f" (session name: {session_name})"
        return super().__init__(msg)


class OptionError(LibTmuxException):

    """Root error for any error involving invalid, ambiguous or bad options."""


class UnknownOption(OptionError):

    """Option unknown to tmux show-option(s) or show-window-option(s)."""


class UnknownColorOption(UnknownOption):

    """Unknown color option."""

    def __init__(self, *args: object):
        return super().__init__("Server.colors must equal 88 or 256")


class InvalidOption(OptionError):

    """Option invalid to tmux, introduced in tmux v2.4."""


class AmbiguousOption(OptionError):

    """Option that could potentially match more than one."""


class WaitTimeout(LibTmuxException):

    """Function timed out without meeting condition"""


class VariableUnpackingError(LibTmuxException):

    """Error unpacking variable"""

    def __init__(self, variable: t.Optional[t.Any] = None, *args: object):
        return super().__init__(f"Unexpected variable: {variable!s}")


class PaneError(LibTmuxException):
    """Any type of pane related error"""


class PaneNotFound(PaneError):
    """Pane not found"""

    def __init__(self, pane_id: t.Optional[str] = None, *args: object):
        if pane_id is not None:
            return super().__init__(f"Pane not found: {pane_id}")
        return super().__init__("Pane not found")


class WindowError(LibTmuxException):

    """Any type of window related error"""


class MultipleActiveWindows(WindowError):

    """Multiple active windows"""

    def __init__(self, count: int, *args: object):
        return super().__init__(f"Multiple active windows: {count} found")


class NoActiveWindow(WindowError):

    """No active window found"""

    def __init__(self, *args: object):
        return super().__init__("No active windows found")


class NoWindowsExist(WindowError):

    """No windows exist for object"""

    def __init__(self, *args: object):
        return super().__init__("No windows exist for object")
