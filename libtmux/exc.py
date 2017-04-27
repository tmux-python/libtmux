# -*- coding: utf-8 -*-
"""libtmux exceptions.

libtmux.exc
~~~~~~~~~~~

"""
from __future__ import absolute_import, unicode_literals, with_statement


class LibTmuxException(Exception):

    """Base Exception for libtmux Errors."""


class TmuxSessionExists(LibTmuxException):

    """Session does not exist in the server."""

    pass


class TmuxCommandNotFound(LibTmuxException):

    """Application binary for tmux not found."""

    pass


class VersionTooLow(LibTmuxException):

    """Raised if tmux below the minimum version to use libtmux."""

    pass


class BadSessionName(LibTmuxException):

    """Disallowed session name for tmux (empty, contains periods or colons)."""

    pass


class OptionError(LibTmuxException):

    """Root error for any error involving invalid, ambiguous or bad options."""

    pass


class UnknownOption(OptionError):

    """Option unknown to tmux show-option(s) or show-window-option(s)."""

    pass


class InvalidOption(OptionError):

    """Option invalid to tmux, introduced in tmux v2.4."""

    pass


class AmbiguousOption(OptionError):

    """Option that could potentially match more than one."""

    pass
