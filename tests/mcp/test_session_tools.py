"""Tests for libtmux MCP session tools."""

from __future__ import annotations

import typing as t

import pytest
from fastmcp.exceptions import ToolError

from libtmux.mcp.tools.session_tools import (
    create_window,
    kill_session,
    list_windows,
    rename_session,
)

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session


def test_list_windows(mcp_server: Server, mcp_session: Session) -> None:
    """list_windows returns a list of WindowInfo models."""
    result = list_windows(
        session_name=mcp_session.session_name,
        socket_name=mcp_server.socket_name,
    )
    assert isinstance(result, list)
    assert len(result) >= 1
    assert result[0].window_id is not None


def test_list_windows_by_id(mcp_server: Server, mcp_session: Session) -> None:
    """list_windows can find session by ID."""
    result = list_windows(
        session_id=mcp_session.session_id,
        socket_name=mcp_server.socket_name,
    )
    assert len(result) >= 1


def test_create_window(mcp_server: Server, mcp_session: Session) -> None:
    """create_window creates a new window in a session."""
    result = create_window(
        session_name=mcp_session.session_name,
        window_name="mcp_test_win",
        socket_name=mcp_server.socket_name,
    )
    assert result.window_name == "mcp_test_win"


def test_create_window_invalid_direction(
    mcp_server: Server, mcp_session: Session
) -> None:
    """create_window raises ToolError on invalid direction."""
    with pytest.raises(ToolError, match="Invalid direction"):
        create_window(
            session_name=mcp_session.session_name,
            window_name="bad_dir",
            direction="sideways",  # type: ignore[arg-type]
            socket_name=mcp_server.socket_name,
        )


def test_rename_session(mcp_server: Server, mcp_session: Session) -> None:
    """rename_session renames an existing session."""
    original_name = mcp_session.session_name
    result = rename_session(
        new_name="mcp_renamed",
        session_name=original_name,
        socket_name=mcp_server.socket_name,
    )
    assert result.session_name == "mcp_renamed"


class ListWindowsFilterFixture(t.NamedTuple):
    """Test fixture for list_windows with filters."""

    test_id: str
    provide_session: bool
    filters: dict[str, str] | None
    expected_min_count: int
    expect_error: bool


LIST_WINDOWS_FILTER_FIXTURES: list[ListWindowsFilterFixture] = [
    ListWindowsFilterFixture(
        test_id="no_filters_scoped",
        provide_session=True,
        filters=None,
        expected_min_count=1,
        expect_error=False,
    ),
    ListWindowsFilterFixture(
        test_id="no_filters_all_sessions",
        provide_session=False,
        filters=None,
        expected_min_count=1,
        expect_error=False,
    ),
    ListWindowsFilterFixture(
        test_id="filter_by_name",
        provide_session=True,
        filters={"window_name": "<window_name>"},
        expected_min_count=1,
        expect_error=False,
    ),
    ListWindowsFilterFixture(
        test_id="filter_by_name_contains",
        provide_session=False,
        filters={"window_name__contains": "<partial_window>"},
        expected_min_count=1,
        expect_error=False,
    ),
    ListWindowsFilterFixture(
        test_id="filter_active",
        provide_session=True,
        filters={"window_active": "1"},
        expected_min_count=1,
        expect_error=False,
    ),
    ListWindowsFilterFixture(
        test_id="invalid_operator",
        provide_session=True,
        filters={"window_name__badop": "test"},
        expected_min_count=0,
        expect_error=True,
    ),
    ListWindowsFilterFixture(
        test_id="cross_session_filter",
        provide_session=False,
        filters={"window_name": "<cross_window_name>"},
        expected_min_count=1,
        expect_error=False,
    ),
]


@pytest.mark.parametrize(
    ListWindowsFilterFixture._fields,
    LIST_WINDOWS_FILTER_FIXTURES,
    ids=[f.test_id for f in LIST_WINDOWS_FILTER_FIXTURES],
)
def test_list_windows_with_filters(
    mcp_server: Server,
    mcp_session: Session,
    test_id: str,
    provide_session: bool,
    filters: dict[str, str] | None,
    expected_min_count: int,
    expect_error: bool,
) -> None:
    """list_windows supports QueryList filtering and scope broadening."""
    # Create a second session with a named window for cross-session tests
    second_session = mcp_server.new_session(session_name="mcp_filter_second")
    cross_win = second_session.new_window(window_name="cross_target_win")

    window = mcp_session.active_window
    window_name = window.window_name
    assert window_name is not None

    if filters is not None:
        resolved: dict[str, str] = {}
        for k, v in filters.items():
            if v == "<window_name>":
                resolved[k] = window_name
            elif v == "<partial_window>":
                resolved[k] = window_name[:3]
            elif v == "<cross_window_name>":
                resolved[k] = "cross_target_win"
            else:
                resolved[k] = v
        filters = resolved

    kwargs: dict[str, t.Any] = {
        "socket_name": mcp_server.socket_name,
        "filters": filters,
    }
    if provide_session:
        kwargs["session_name"] = mcp_session.session_name

    if expect_error:
        with pytest.raises(ToolError, match="Invalid filter operator"):
            list_windows(**kwargs)
    else:
        result = list_windows(**kwargs)
        assert isinstance(result, list)
        assert len(result) >= expected_min_count

    # Cleanup
    cross_win.kill()
    second_session.kill()


def test_kill_session(mcp_server: Server) -> None:
    """kill_session kills a session."""
    mcp_server.new_session(session_name="mcp_kill_me")
    result = kill_session(
        session_name="mcp_kill_me",
        socket_name=mcp_server.socket_name,
    )
    assert "killed" in result.lower()
    assert not mcp_server.has_session("mcp_kill_me")
