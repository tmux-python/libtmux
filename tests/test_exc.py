"""Tests for :mod:`libtmux.exc`."""

from __future__ import annotations

import typing as t

import pytest

from libtmux import exc

if t.TYPE_CHECKING:
    from libtmux.server import Server


def test_deprecated_error_is_not_a_tmux_failure() -> None:
    """DeprecatedError is a caller bug, not a tmux failure."""
    assert not issubclass(exc.DeprecatedError, exc.LibTmuxException)


def test_removed_api_escapes_broad_libtmux_handler(server: Server) -> None:
    """A removed API is not swallowed by ``except LibTmuxException``."""
    fell_back = False
    with pytest.raises(exc.DeprecatedError, match=r"Server\.find_where\(\)"):
        try:
            server.find_where({"session_name": "x"})
        except exc.LibTmuxException:
            fell_back = True
    assert not fell_back
