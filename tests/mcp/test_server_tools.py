"""Tests for libtmux MCP server tools."""

from __future__ import annotations

import json
import typing as t

import pytest

from libtmux.mcp.tools.server_tools import (
    create_session,
    get_server_info,
    kill_server,
    list_sessions,
)

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session


def test_list_sessions(mcp_server: Server, mcp_session: Session) -> None:
    """list_sessions returns JSON array of sessions."""
    result = list_sessions(socket_name=mcp_server.socket_name)
    data = json.loads(result)
    assert isinstance(data, list)
    assert len(data) >= 1
    session_ids = [s["session_id"] for s in data]
    assert mcp_session.session_id in session_ids


def test_list_sessions_empty_server(mcp_server: Server) -> None:
    """list_sessions returns empty array when no sessions."""
    # Kill all sessions first
    for s in mcp_server.sessions:
        s.kill()
    result = list_sessions(socket_name=mcp_server.socket_name)
    data = json.loads(result)
    assert data == []


def test_create_session(mcp_server: Server) -> None:
    """create_session creates a new tmux session."""
    result = create_session(
        session_name="mcp_test_new",
        socket_name=mcp_server.socket_name,
    )
    data = json.loads(result)
    assert data["session_name"] == "mcp_test_new"
    assert data["session_id"] is not None


def test_create_session_duplicate(mcp_server: Server, mcp_session: Session) -> None:
    """create_session raises error for duplicate session name."""
    from fastmcp.exceptions import ToolError

    with pytest.raises(ToolError):
        create_session(
            session_name=mcp_session.session_name,
            socket_name=mcp_server.socket_name,
        )


def test_get_server_info(mcp_server: Server, mcp_session: Session) -> None:
    """get_server_info returns server status."""
    result = get_server_info(socket_name=mcp_server.socket_name)
    data = json.loads(result)
    assert data["is_alive"] is True
    assert data["session_count"] >= 1


class ListSessionsFilterFixture(t.NamedTuple):
    """Test fixture for list_sessions with filters."""

    test_id: str
    filters: dict[str, str] | None
    expected_count: int | None
    expect_error: bool
    error_match: str | None


LIST_SESSIONS_FILTER_FIXTURES: list[ListSessionsFilterFixture] = [
    ListSessionsFilterFixture(
        test_id="no_filters",
        filters=None,
        expected_count=None,
        expect_error=False,
        error_match=None,
    ),
    ListSessionsFilterFixture(
        test_id="exact_session_name",
        filters={"session_name": "<session_name>"},
        expected_count=1,
        expect_error=False,
        error_match=None,
    ),
    ListSessionsFilterFixture(
        test_id="contains_operator",
        filters={"session_name__contains": "<partial>"},
        expected_count=1,
        expect_error=False,
        error_match=None,
    ),
    ListSessionsFilterFixture(
        test_id="startswith_operator",
        filters={"session_name__startswith": "<partial>"},
        expected_count=None,
        expect_error=False,
        error_match=None,
    ),
    ListSessionsFilterFixture(
        test_id="regex_operator",
        filters={"session_name__regex": ".*"},
        expected_count=None,
        expect_error=False,
        error_match=None,
    ),
    ListSessionsFilterFixture(
        test_id="icontains_operator",
        filters={"session_name__icontains": "<partial_upper>"},
        expected_count=1,
        expect_error=False,
        error_match=None,
    ),
    ListSessionsFilterFixture(
        test_id="no_match",
        filters={"session_name": "nonexistent_xyz_999"},
        expected_count=0,
        expect_error=False,
        error_match=None,
    ),
    ListSessionsFilterFixture(
        test_id="invalid_operator",
        filters={"session_name__badop": "test"},
        expected_count=None,
        expect_error=True,
        error_match="Invalid filter operator",
    ),
    ListSessionsFilterFixture(
        test_id="multiple_filters",
        filters={"session_name__contains": "<partial>", "session_name__regex": ".*"},
        expected_count=None,
        expect_error=False,
        error_match=None,
    ),
]


@pytest.mark.parametrize(
    ListSessionsFilterFixture._fields,
    LIST_SESSIONS_FILTER_FIXTURES,
    ids=[f.test_id for f in LIST_SESSIONS_FILTER_FIXTURES],
)
def test_list_sessions_with_filters(
    mcp_server: Server,
    mcp_session: Session,
    test_id: str,
    filters: dict[str, str] | None,
    expected_count: int | None,
    expect_error: bool,
    error_match: str | None,
) -> None:
    """list_sessions supports QueryList filtering."""
    from fastmcp.exceptions import ToolError

    if filters is not None:
        session_name = mcp_session.session_name
        assert session_name is not None
        resolved: dict[str, str] = {}
        for k, v in filters.items():
            if v == "<session_name>":
                resolved[k] = session_name
            elif v == "<partial>":
                resolved[k] = session_name[:4]
            elif v == "<partial_upper>":
                resolved[k] = session_name[:4].upper()
            else:
                resolved[k] = v
        filters = resolved

    if expect_error:
        with pytest.raises(ToolError, match=error_match):
            list_sessions(
                socket_name=mcp_server.socket_name,
                filters=filters,
            )
    else:
        result = list_sessions(
            socket_name=mcp_server.socket_name,
            filters=filters,
        )
        data = json.loads(result)
        assert isinstance(data, list)
        if expected_count is not None:
            assert len(data) == expected_count
        else:
            assert len(data) >= 1


def test_kill_server(mcp_server: Server, mcp_session: Session) -> None:
    """kill_server kills the tmux server."""
    result = kill_server(socket_name=mcp_server.socket_name)
    assert "killed" in result.lower()
