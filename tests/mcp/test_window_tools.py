"""Tests for libtmux MCP window tools."""

from __future__ import annotations

import json
import typing as t

from libtmux.mcp.tools.window_tools import (
    kill_window,
    list_panes,
    rename_window,
    resize_window,
    select_layout,
    split_window,
)

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session


def test_list_panes(mcp_server: Server, mcp_session: Session) -> None:
    """list_panes returns JSON array of panes."""
    window = mcp_session.active_window
    result = list_panes(
        window_id=window.window_id,
        socket_name=mcp_server.socket_name,
    )
    data = json.loads(result)
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "pane_id" in data[0]


def test_split_window(mcp_server: Server, mcp_session: Session) -> None:
    """split_window creates a new pane."""
    window = mcp_session.active_window
    initial_pane_count = len(window.panes)
    result = split_window(
        window_id=window.window_id,
        socket_name=mcp_server.socket_name,
    )
    data = json.loads(result)
    assert "pane_id" in data
    assert len(window.panes) == initial_pane_count + 1


def test_split_window_with_direction(mcp_server: Server, mcp_session: Session) -> None:
    """split_window respects direction parameter."""
    window = mcp_session.active_window
    result = split_window(
        window_id=window.window_id,
        direction="right",
        socket_name=mcp_server.socket_name,
    )
    data = json.loads(result)
    assert "pane_id" in data


def test_rename_window(mcp_server: Server, mcp_session: Session) -> None:
    """rename_window renames a window."""
    window = mcp_session.active_window
    result = rename_window(
        new_name="mcp_renamed_win",
        window_id=window.window_id,
        socket_name=mcp_server.socket_name,
    )
    data = json.loads(result)
    assert data["window_name"] == "mcp_renamed_win"


def test_select_layout(mcp_server: Server, mcp_session: Session) -> None:
    """select_layout changes window layout."""
    window = mcp_session.active_window
    window.split()
    result = select_layout(
        layout="even-horizontal",
        window_id=window.window_id,
        socket_name=mcp_server.socket_name,
    )
    data = json.loads(result)
    assert "window_id" in data


def test_resize_window(mcp_server: Server, mcp_session: Session) -> None:
    """resize_window resizes a window."""
    window = mcp_session.active_window
    result = resize_window(
        window_id=window.window_id,
        height=20,
        width=60,
        socket_name=mcp_server.socket_name,
    )
    data = json.loads(result)
    assert data["window_id"] == window.window_id


def test_kill_window(mcp_server: Server, mcp_session: Session) -> None:
    """kill_window kills a window."""
    new_window = mcp_session.new_window(window_name="mcp_kill_win")
    window_id = new_window.window_id
    result = kill_window(
        window_id=window_id,
        socket_name=mcp_server.socket_name,
    )
    assert "killed" in result.lower()
