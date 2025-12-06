"""Tests for deprecated libtmux Window APIs.

These tests verify that deprecated methods raise DeprecatedError.
"""

from __future__ import annotations

import typing as t

import pytest

from libtmux.exc import DeprecatedError

if t.TYPE_CHECKING:
    from libtmux.session import Session


def test_split_window_raises_deprecated_error(session: Session) -> None:
    """Test Window.split_window() raises DeprecatedError."""
    window = session.active_window

    with pytest.raises(
        DeprecatedError, match=r"Window\.split_window\(\) was deprecated"
    ):
        window.split_window()


def test_attached_pane_raises_deprecated_error(session: Session) -> None:
    """Test Window.attached_pane raises DeprecatedError."""
    window = session.active_window

    with pytest.raises(DeprecatedError, match=r"Window\.attached_pane was deprecated"):
        _ = window.attached_pane


def test_select_window_raises_deprecated_error(session: Session) -> None:
    """Test Window.select_window() raises DeprecatedError."""
    window = session.active_window

    with pytest.raises(
        DeprecatedError, match=r"Window\.select_window\(\) was deprecated"
    ):
        window.select_window()


def test_kill_window_raises_deprecated_error(session: Session) -> None:
    """Test Window.kill_window() raises DeprecatedError."""
    # Create a new window to kill (so we don't kill our only window)
    session.new_window(window_name="extra_window")
    window = session.active_window

    with pytest.raises(
        DeprecatedError, match=r"Window\.kill_window\(\) was deprecated"
    ):
        window.kill_window()


def test_set_window_option_raises_deprecated_error(session: Session) -> None:
    """Test Window.set_window_option() raises DeprecatedError."""
    window = session.active_window

    with pytest.raises(
        DeprecatedError, match=r"Window\.set_window_option\(\) was deprecated"
    ):
        window.set_window_option("main-pane-height", 20)


def test_show_window_options_raises_deprecated_error(session: Session) -> None:
    """Test Window.show_window_options() raises DeprecatedError."""
    window = session.active_window

    with pytest.raises(
        DeprecatedError, match=r"Window\.show_window_options\(\) was deprecated"
    ):
        window.show_window_options()


def test_show_window_option_raises_deprecated_error(session: Session) -> None:
    """Test Window.show_window_option() raises DeprecatedError."""
    window = session.active_window

    with pytest.raises(
        DeprecatedError, match=r"Window\.show_window_option\(\) was deprecated"
    ):
        window.show_window_option("main-pane-height")


def test_window_get_raises_deprecated_error(session: Session) -> None:
    """Test Window.get() raises DeprecatedError."""
    window = session.active_window

    with pytest.raises(DeprecatedError, match=r"Window\.get\(\) was deprecated"):
        window.get("window_id")


def test_window_getitem_raises_deprecated_error(session: Session) -> None:
    """Test Window.__getitem__() raises DeprecatedError."""
    window = session.active_window

    with pytest.raises(DeprecatedError, match=r"Window\[key\] lookup was deprecated"):
        _ = window["window_id"]


def test_window_get_by_id_raises_deprecated_error(session: Session) -> None:
    """Test Window.get_by_id() raises DeprecatedError."""
    window = session.active_window

    with pytest.raises(DeprecatedError, match=r"Window\.get_by_id\(\) was deprecated"):
        window.get_by_id("%0")


def test_window_where_raises_deprecated_error(session: Session) -> None:
    """Test Window.where() raises DeprecatedError."""
    window = session.active_window

    with pytest.raises(DeprecatedError, match=r"Window\.where\(\) was deprecated"):
        window.where({"pane_id": "%0"})


def test_window_find_where_raises_deprecated_error(session: Session) -> None:
    """Test Window.find_where() raises DeprecatedError."""
    window = session.active_window

    with pytest.raises(DeprecatedError, match=r"Window\.find_where\(\) was deprecated"):
        window.find_where({"pane_id": "%0"})


def test_window_list_panes_raises_deprecated_error(session: Session) -> None:
    """Test Window.list_panes() raises DeprecatedError."""
    window = session.active_window

    with pytest.raises(DeprecatedError, match=r"Window\.list_panes\(\) was deprecated"):
        window.list_panes()


def test_window_children_raises_deprecated_error(session: Session) -> None:
    """Test Window.children raises DeprecatedError."""
    window = session.active_window

    with pytest.raises(DeprecatedError, match=r"Window\.children was deprecated"):
        _ = window.children


def test_window__panes_raises_deprecated_error(session: Session) -> None:
    """Test Window._panes raises DeprecatedError."""
    window = session.active_window

    with pytest.raises(DeprecatedError, match=r"Window\._panes was deprecated"):
        _ = window._panes


def test_window__list_panes_raises_deprecated_error(session: Session) -> None:
    """Test Window._list_panes() raises DeprecatedError."""
    window = session.active_window

    with pytest.raises(
        DeprecatedError, match=r"Window\._list_panes\(\) was deprecated"
    ):
        window._list_panes()
