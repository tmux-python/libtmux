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


class BadSessionName(LibTmuxException):

    """Session name is not allowed."""

    pass


class UnknownOption(LibTmuxException):

    """Option unknown to tmux show-option(s) or show-window-option(s)."""

    pass
