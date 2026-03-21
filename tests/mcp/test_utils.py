"""Tests for libtmux MCP utilities."""

from __future__ import annotations

import typing as t

import pytest
from fastmcp.exceptions import ToolError

from libtmux import exc
from libtmux.mcp._utils import (
    _apply_filters,
    _get_caller_pane_id,
    _get_server,
    _invalidate_server,
    _resolve_pane,
    _resolve_session,
    _resolve_window,
    _serialize_pane,
    _serialize_session,
    _serialize_window,
    _server_cache,
)

if t.TYPE_CHECKING:
    from libtmux.pane import Pane
    from libtmux.server import Server
    from libtmux.session import Session
    from libtmux.window import Window


def test_get_server_creates_server() -> None:
    """_get_server creates a Server instance."""
    server = _get_server(socket_name="test_mcp_util")
    assert server is not None
    assert server.socket_name == "test_mcp_util"


def test_get_server_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    """_get_server returns the same instance for the same socket."""
    _server_cache.clear()
    s1 = _get_server(socket_name="test_cache")
    # Simulate a live server so the cache is not evicted
    monkeypatch.setattr(s1, "is_alive", lambda: True)
    s2 = _get_server(socket_name="test_cache")
    assert s1 is s2
    # Verify 3-tuple cache key includes tmux_bin
    assert (s1.socket_name, None, None) in _server_cache


def test_get_server_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """_get_server reads LIBTMUX_SOCKET env var."""
    _server_cache.clear()
    monkeypatch.setenv("LIBTMUX_SOCKET", "env_socket")
    server = _get_server()
    assert server.socket_name == "env_socket"


def test_resolve_session_by_name(mcp_server: Server, mcp_session: Session) -> None:
    """_resolve_session finds session by name."""
    result = _resolve_session(mcp_server, session_name=mcp_session.session_name)
    assert result.session_id == mcp_session.session_id


def test_resolve_session_by_id(mcp_server: Server, mcp_session: Session) -> None:
    """_resolve_session finds session by ID."""
    result = _resolve_session(mcp_server, session_id=mcp_session.session_id)
    assert result.session_id == mcp_session.session_id


def test_resolve_session_not_found(mcp_server: Server, mcp_session: Session) -> None:
    """_resolve_session raises when session not found."""
    with pytest.raises(exc.TmuxObjectDoesNotExist):
        _resolve_session(mcp_server, session_name="nonexistent_session_xyz")


def test_resolve_session_fallback(mcp_server: Server, mcp_session: Session) -> None:
    """_resolve_session returns first session when no filter given."""
    result = _resolve_session(mcp_server)
    assert result.session_id is not None


def test_resolve_window_by_id(mcp_server: Server, mcp_window: Window) -> None:
    """_resolve_window finds window by ID."""
    result = _resolve_window(mcp_server, window_id=mcp_window.window_id)
    assert result.window_id == mcp_window.window_id


def test_resolve_window_not_found(mcp_server: Server, mcp_session: Session) -> None:
    """_resolve_window raises when window not found."""
    with pytest.raises(exc.TmuxObjectDoesNotExist):
        _resolve_window(mcp_server, window_id="@99999")


def test_resolve_pane_by_id(mcp_server: Server, mcp_pane: Pane) -> None:
    """_resolve_pane finds pane by ID."""
    result = _resolve_pane(mcp_server, pane_id=mcp_pane.pane_id)
    assert result.pane_id == mcp_pane.pane_id


def test_resolve_pane_not_found(mcp_server: Server, mcp_session: Session) -> None:
    """_resolve_pane raises when pane not found."""
    with pytest.raises(exc.PaneNotFound):
        _resolve_pane(mcp_server, pane_id="%99999")


def test_serialize_session(mcp_session: Session) -> None:
    """_serialize_session produces a SessionInfo model."""
    from libtmux.mcp.models import SessionInfo

    data = _serialize_session(mcp_session)
    assert isinstance(data, SessionInfo)
    assert data.session_id == mcp_session.session_id
    assert data.session_name is not None
    assert data.window_count >= 0


def test_serialize_window(mcp_window: Window) -> None:
    """_serialize_window produces a WindowInfo model."""
    from libtmux.mcp.models import WindowInfo

    data = _serialize_window(mcp_window)
    assert isinstance(data, WindowInfo)
    assert data.window_id is not None
    assert data.window_name is not None
    assert data.window_index is not None
    assert data.pane_count >= 0


def test_serialize_pane(mcp_pane: Pane) -> None:
    """_serialize_pane produces a PaneInfo model."""
    from libtmux.mcp.models import PaneInfo

    data = _serialize_pane(mcp_pane)
    assert isinstance(data, PaneInfo)
    assert data.pane_id is not None
    assert data.window_id is not None
    assert data.session_id is not None


def test_get_server_evicts_dead(monkeypatch: pytest.MonkeyPatch) -> None:
    """_get_server evicts cached server when is_alive returns False."""
    _server_cache.clear()
    s1 = _get_server(socket_name="test_evict")
    # Patch is_alive to return False to simulate a dead server
    monkeypatch.setattr(s1, "is_alive", lambda: False)
    s2 = _get_server(socket_name="test_evict")
    assert s1 is not s2


def test_invalidate_server() -> None:
    """_invalidate_server removes matching entries from cache."""
    _server_cache.clear()
    _get_server(socket_name="test_inv")
    assert len(_server_cache) == 1
    _invalidate_server(socket_name="test_inv")
    assert len(_server_cache) == 0


class ApplyFiltersFixture(t.NamedTuple):
    """Test fixture for _apply_filters."""

    test_id: str
    filters: dict[str, str] | str | None
    expected_count: int | None  # None = don't check exact count
    expect_error: bool
    error_match: str | None


APPLY_FILTERS_FIXTURES: list[ApplyFiltersFixture] = [
    ApplyFiltersFixture(
        test_id="none_returns_all",
        filters=None,
        expected_count=None,
        expect_error=False,
        error_match=None,
    ),
    ApplyFiltersFixture(
        test_id="empty_dict_returns_all",
        filters={},
        expected_count=None,
        expect_error=False,
        error_match=None,
    ),
    ApplyFiltersFixture(
        test_id="exact_match",
        filters={"session_name": "<session_name>"},
        expected_count=1,
        expect_error=False,
        error_match=None,
    ),
    ApplyFiltersFixture(
        test_id="no_match_returns_empty",
        filters={"session_name": "nonexistent_xyz_999"},
        expected_count=0,
        expect_error=False,
        error_match=None,
    ),
    ApplyFiltersFixture(
        test_id="invalid_operator",
        filters={"session_name__badop": "test"},
        expected_count=None,
        expect_error=True,
        error_match="Invalid filter operator",
    ),
    ApplyFiltersFixture(
        test_id="contains_operator",
        filters={"session_name__contains": "<partial>"},
        expected_count=1,
        expect_error=False,
        error_match=None,
    ),
    ApplyFiltersFixture(
        test_id="string_filter_exact",
        filters='{"session_name": "<session_name>"}',
        expected_count=1,
        expect_error=False,
        error_match=None,
    ),
    ApplyFiltersFixture(
        test_id="string_filter_contains",
        filters='{"session_name__contains": "<partial>"}',
        expected_count=1,
        expect_error=False,
        error_match=None,
    ),
    ApplyFiltersFixture(
        test_id="string_filter_invalid_json",
        filters="{bad json",
        expected_count=None,
        expect_error=True,
        error_match="Invalid filters JSON",
    ),
    ApplyFiltersFixture(
        test_id="string_filter_not_object",
        filters='"just a string"',
        expected_count=None,
        expect_error=True,
        error_match="filters must be a JSON object",
    ),
    ApplyFiltersFixture(
        test_id="string_filter_array",
        filters='["not", "a", "dict"]',
        expected_count=None,
        expect_error=True,
        error_match="filters must be a JSON object",
    ),
]


@pytest.mark.parametrize(
    ApplyFiltersFixture._fields,
    APPLY_FILTERS_FIXTURES,
    ids=[f.test_id for f in APPLY_FILTERS_FIXTURES],
)
def test_apply_filters(
    mcp_server: Server,
    mcp_session: Session,
    test_id: str,
    filters: dict[str, str] | str | None,
    expected_count: int | None,
    expect_error: bool,
    error_match: str | None,
) -> None:
    """_apply_filters bridges dict params to QueryList.filter()."""
    # Substitute placeholders with real session name
    if isinstance(filters, str):
        session_name = mcp_session.session_name
        assert session_name is not None
        filters = filters.replace("<session_name>", session_name)
        filters = filters.replace("<partial>", session_name[:4])
    elif filters is not None:
        session_name = mcp_session.session_name
        assert session_name is not None
        resolved: dict[str, str] = {}
        for k, v in filters.items():
            if v == "<session_name>":
                resolved[k] = session_name
            elif v == "<partial>":
                resolved[k] = session_name[:4]
            else:
                resolved[k] = v
        filters = resolved

    sessions = mcp_server.sessions

    if expect_error:
        with pytest.raises(ToolError, match=error_match):
            _apply_filters(sessions, filters, _serialize_session)
    else:
        result = _apply_filters(sessions, filters, _serialize_session)
        assert isinstance(result, list)
        if expected_count is not None:
            assert len(result) == expected_count
        else:
            assert len(result) >= 1


# ---------------------------------------------------------------------------
# _get_caller_pane_id / _serialize_pane is_caller tests
# ---------------------------------------------------------------------------


def test_get_caller_pane_id_returns_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """_get_caller_pane_id returns TMUX_PANE when set."""
    monkeypatch.setenv("TMUX_PANE", "%42")
    assert _get_caller_pane_id() == "%42"


def test_get_caller_pane_id_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """_get_caller_pane_id returns None outside tmux."""
    monkeypatch.delenv("TMUX_PANE", raising=False)
    assert _get_caller_pane_id() is None


class SerializePaneCallerFixture(t.NamedTuple):
    """Test fixture for _serialize_pane is_caller annotation."""

    test_id: str
    tmux_pane_env: str | None
    use_real_pane_id: bool
    expected_is_caller: bool | None


SERIALIZE_PANE_CALLER_FIXTURES: list[SerializePaneCallerFixture] = [
    SerializePaneCallerFixture(
        test_id="matching_pane_id",
        tmux_pane_env=None,
        use_real_pane_id=True,
        expected_is_caller=True,
    ),
    SerializePaneCallerFixture(
        test_id="non_matching_pane_id",
        tmux_pane_env="%99999",
        use_real_pane_id=False,
        expected_is_caller=False,
    ),
    SerializePaneCallerFixture(
        test_id="unset_outside_tmux",
        tmux_pane_env=None,
        use_real_pane_id=False,
        expected_is_caller=None,
    ),
]


@pytest.mark.parametrize(
    SerializePaneCallerFixture._fields,
    SERIALIZE_PANE_CALLER_FIXTURES,
    ids=[f.test_id for f in SERIALIZE_PANE_CALLER_FIXTURES],
)
def test_serialize_pane_is_caller(
    mcp_pane: Pane,
    monkeypatch: pytest.MonkeyPatch,
    test_id: str,
    tmux_pane_env: str | None,
    use_real_pane_id: bool,
    expected_is_caller: bool | None,
) -> None:
    """_serialize_pane sets is_caller based on TMUX_PANE env var."""
    if use_real_pane_id:
        monkeypatch.setenv("TMUX_PANE", mcp_pane.pane_id or "")
    elif tmux_pane_env is not None:
        monkeypatch.setenv("TMUX_PANE", tmux_pane_env)
    else:
        monkeypatch.delenv("TMUX_PANE", raising=False)

    data = _serialize_pane(mcp_pane)
    assert data.is_caller is expected_is_caller
