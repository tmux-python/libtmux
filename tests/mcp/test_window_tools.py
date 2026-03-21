"""Tests for libtmux MCP window tools."""

from __future__ import annotations

import json
import typing as t

import pytest
from fastmcp.exceptions import ToolError

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


def test_split_window_invalid_direction(
    mcp_server: Server, mcp_session: Session
) -> None:
    """split_window raises ToolError on invalid direction."""
    window = mcp_session.active_window
    with pytest.raises(ToolError, match="Invalid direction"):
        split_window(
            window_id=window.window_id,
            direction="diagonal",  # type: ignore[arg-type]
            socket_name=mcp_server.socket_name,
        )


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


class ListPanesFilterFixture(t.NamedTuple):
    """Test fixture for list_panes with filters."""

    test_id: str
    scope: str  # "window", "session", "server"
    filters: dict[str, str] | None
    expected_min_count: int
    expect_error: bool


LIST_PANES_FILTER_FIXTURES: list[ListPanesFilterFixture] = [
    ListPanesFilterFixture(
        test_id="window_scope_no_filter",
        scope="window",
        filters=None,
        expected_min_count=1,
        expect_error=False,
    ),
    ListPanesFilterFixture(
        test_id="session_scope_no_filter",
        scope="session",
        filters=None,
        expected_min_count=1,
        expect_error=False,
    ),
    ListPanesFilterFixture(
        test_id="server_scope_no_filter",
        scope="server",
        filters=None,
        expected_min_count=1,
        expect_error=False,
    ),
    ListPanesFilterFixture(
        test_id="filter_active_pane",
        scope="window",
        filters={"pane_active": "1"},
        expected_min_count=1,
        expect_error=False,
    ),
    ListPanesFilterFixture(
        test_id="filter_by_command_contains",
        scope="server",
        filters={"pane_current_command__regex": ".*"},
        expected_min_count=1,
        expect_error=False,
    ),
    ListPanesFilterFixture(
        test_id="invalid_operator",
        scope="window",
        filters={"pane_id__badop": "test"},
        expected_min_count=0,
        expect_error=True,
    ),
    ListPanesFilterFixture(
        test_id="session_scope_with_filter",
        scope="session",
        filters={"pane_active": "1"},
        expected_min_count=1,
        expect_error=False,
    ),
]


@pytest.mark.parametrize(
    ListPanesFilterFixture._fields,
    LIST_PANES_FILTER_FIXTURES,
    ids=[f.test_id for f in LIST_PANES_FILTER_FIXTURES],
)
def test_list_panes_with_filters(
    mcp_server: Server,
    mcp_session: Session,
    test_id: str,
    scope: str,
    filters: dict[str, str] | None,
    expected_min_count: int,
    expect_error: bool,
) -> None:
    """list_panes supports QueryList filtering and scope broadening."""
    window = mcp_session.active_window

    kwargs: dict[str, t.Any] = {
        "socket_name": mcp_server.socket_name,
        "filters": filters,
    }
    if scope == "window":
        kwargs["window_id"] = window.window_id
    elif scope == "session":
        kwargs["session_name"] = mcp_session.session_name

    if expect_error:
        with pytest.raises(ToolError, match="Invalid filter operator"):
            list_panes(**kwargs)
    else:
        result = list_panes(**kwargs)
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) >= expected_min_count


def test_kill_window(mcp_server: Server, mcp_session: Session) -> None:
    """kill_window kills a window."""
    new_window = mcp_session.new_window(window_name="mcp_kill_win")
    window_id = new_window.window_id
    result = kill_window(
        window_id=window_id,
        socket_name=mcp_server.socket_name,
    )
    assert "killed" in result.lower()
