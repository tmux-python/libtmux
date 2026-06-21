"""Exceptions for the experimental imsg engine."""

from __future__ import annotations

from libtmux.exc import LibTmuxException


class ImsgError(LibTmuxException):
    """Base error for the native imsg engine."""


class ImsgProtocolError(ImsgError):
    """The imsg wire protocol was violated (bad frame, size, or framing)."""


class UnsupportedProtocolVersion(ImsgError):
    """The tmux server speaks an imsg protocol version this engine lacks."""

    def __init__(self, version: str) -> None:
        self.version = version
        msg = f"unsupported tmux imsg protocol version: {version}"
        super().__init__(msg)
