"""Tests for the pure object-graph snapshots."""

from __future__ import annotations

import pytest

from libtmux.experimental.models import (
    PaneSnapshot,
    ServerSnapshot,
    WindowSnapshot,
)
from libtmux.experimental.models.snapshots import _as_bool, _as_int


@pytest.mark.parametrize(
    ("value", "expected"),
    [("3", 3), ("0", 0), ("", None), (None, None), ("nope", None)],
)
def test_as_int(value: str | None, expected: int | None) -> None:
    """Format values coerce to int or None."""
    assert _as_int(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", True), ("0", False), ("", False), (None, False), ("on", True)],
)
def test_as_bool(value: str | None, expected: bool) -> None:
    """Flag values coerce to bool."""
    assert _as_bool(value) is expected


def test_pane_from_format_typed_core() -> None:
    """A pane snapshot exposes a typed core derived from the raw mapping."""
    pane = PaneSnapshot.from_format(
        {
            "pane_id": "%1",
            "pane_index": "2",
            "pane_active": "1",
            "pane_width": "80",
            "pane_height": "24",
            "pane_current_command": "vim",
        },
    )
    assert pane.pane_id == "%1"
    assert pane.pane_index == 2
    assert pane.active is True
    assert pane.width == 80
    assert pane.current_command == "vim"


def test_raw_fields_preserved() -> None:
    """The full raw mapping is retained even for un-promoted fields."""
    pane = PaneSnapshot.from_format({"pane_id": "%1", "pane_tty": "/dev/pts/3"})
    assert pane.fields["pane_tty"] == "/dev/pts/3"


def test_window_from_format_has_empty_panes() -> None:
    """A window built from a format mapping starts with no panes."""
    window = WindowSnapshot.from_format({"window_id": "@1", "window_name": "main"})
    assert window.panes == ()


def test_from_pane_rows_builds_tree_in_order() -> None:
    """Flat pane rows group into an ordered session/window/pane tree."""
    rows = [
        {
            "session_id": "$0",
            "session_name": "a",
            "window_id": "@1",
            "window_index": "0",
            "pane_id": "%1",
        },
        {
            "session_id": "$0",
            "session_name": "a",
            "window_id": "@1",
            "window_index": "0",
            "pane_id": "%2",
        },
        {
            "session_id": "$0",
            "session_name": "a",
            "window_id": "@2",
            "window_index": "1",
            "pane_id": "%3",
        },
        {
            "session_id": "$1",
            "session_name": "b",
            "window_id": "@3",
            "window_index": "0",
            "pane_id": "%4",
        },
    ]
    server = ServerSnapshot.from_pane_rows(rows, socket_name="test")

    assert server.socket_name == "test"
    assert [s.session_id for s in server.sessions] == ["$0", "$1"]
    first = server.sessions[0]
    assert first.name == "a"
    assert [w.window_id for w in first.windows] == ["@1", "@2"]
    assert [p.pane_id for p in first.windows[0].panes] == ["%1", "%2"]
    assert [p.pane_id for p in first.windows[1].panes] == ["%3"]
    assert server.sessions[1].windows[0].panes[0].pane_id == "%4"


def test_empty_rows_yield_empty_server() -> None:
    """No rows produces a server snapshot with no sessions."""
    assert ServerSnapshot.from_pane_rows([]).sessions == ()


def test_tree_round_trips_through_dict() -> None:
    """A full server tree survives a to_dict / from_dict round-trip."""
    rows = [
        {
            "session_id": "$0",
            "session_name": "a",
            "window_id": "@1",
            "window_index": "0",
            "pane_id": "%1",
            "pane_active": "1",
        },
        {
            "session_id": "$0",
            "session_name": "a",
            "window_id": "@1",
            "window_index": "0",
            "pane_id": "%2",
            "pane_active": "0",
        },
    ]
    server = ServerSnapshot.from_pane_rows(rows, socket_name="test")
    assert ServerSnapshot.from_dict(server.to_dict()) == server
