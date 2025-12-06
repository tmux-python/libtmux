"""Tests for deprecated libtmux Pane APIs.

These tests verify that deprecated methods raise DeprecatedError.
"""

from __future__ import annotations

import typing as t

import pytest

from libtmux import exc

if t.TYPE_CHECKING:
    from libtmux.session import Session


def test_resize_pane_raises_deprecated_error(session: Session) -> None:
    """Test Pane.resize_pane() raises DeprecatedError."""
    window = session.active_window
    pane = window.active_pane
    assert pane is not None

    with pytest.raises(
        exc.DeprecatedError, match=r"Pane\.resize_pane\(\) was deprecated"
    ):
        pane.resize_pane(height=4)


def test_select_pane_raises_deprecated_error(session: Session) -> None:
    """Test Pane.select_pane() raises DeprecatedError."""
    window = session.active_window
    pane = window.active_pane
    assert pane is not None

    with pytest.raises(
        exc.DeprecatedError, match=r"Pane\.select_pane\(\) was deprecated"
    ):
        pane.select_pane()


def test_split_window_raises_deprecated_error(session: Session) -> None:
    """Test Pane.split_window() raises DeprecatedError."""
    window = session.active_window
    pane = window.active_pane
    assert pane is not None

    with pytest.raises(
        exc.DeprecatedError, match=r"Pane\.split_window\(\) was deprecated"
    ):
        pane.split_window()


def test_pane_get_raises_deprecated_error(session: Session) -> None:
    """Test Pane.get() raises DeprecatedError."""
    window = session.active_window
    pane = window.active_pane
    assert pane is not None

    with pytest.raises(exc.DeprecatedError, match=r"Pane\.get\(\) was deprecated"):
        pane.get("pane_id")


def test_pane_getitem_raises_deprecated_error(session: Session) -> None:
    """Test Pane.__getitem__() raises DeprecatedError."""
    window = session.active_window
    pane = window.active_pane
    assert pane is not None

    with pytest.raises(exc.DeprecatedError, match=r"Pane\[key\] lookup was deprecated"):
        _ = pane["pane_id"]
