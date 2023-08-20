"""libtmux exceptions.

libtmux.exc
~~~~~~~~~~~

"""


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
