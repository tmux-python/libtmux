"""Tests for the derived tmux tree helpers."""

from __future__ import annotations

from libtmux.experimental.agents.tree import PANE_FORMAT, diff_panes, panes_of
from libtmux.experimental.models.snapshots import ServerSnapshot


def test_pane_format_requests_floating_flag() -> None:
    """The monitor's pane format requests pane_floating_flag (tmux 3.7 floats)."""
    assert "pane_floating_flag" in PANE_FORMAT


def _snap(pane_ids: list[str]) -> ServerSnapshot:
    rows = [
        {
            "session_id": "$0",
            "window_id": "@0",
            "window_index": "0",
            "pane_id": pid,
            "pane_index": str(i),
        }
        for i, pid in enumerate(pane_ids)
    ]
    return ServerSnapshot.from_pane_rows(rows)


def test_panes_of_flattens() -> None:
    """Test that panes_of flattens a snapshot into a pane map."""
    assert set(panes_of(_snap(["%1", "%2"]))) == {"%1", "%2"}


def test_diff_panes_reports_added_and_removed() -> None:
    """Test that diff_panes reports added and removed pane IDs."""
    old = panes_of(_snap(["%1", "%2"]))
    new = panes_of(_snap(["%2", "%3"]))
    added, removed = diff_panes(old, new)
    assert added == ["%3"]
    assert removed == ["%1"]
