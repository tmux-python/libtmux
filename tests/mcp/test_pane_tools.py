"""Tests for libtmux MCP pane tools."""

from __future__ import annotations

import typing as t

import pytest
from fastmcp.exceptions import ToolError

from libtmux.mcp.models import PaneContentMatch
from libtmux.mcp.tools.pane_tools import (
    capture_pane,
    clear_pane,
    get_pane_info,
    kill_pane,
    resize_pane,
    search_panes,
    send_keys,
    set_pane_title,
)
from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    from libtmux.pane import Pane
    from libtmux.server import Server
    from libtmux.session import Session


def test_send_keys(mcp_server: Server, mcp_pane: Pane) -> None:
    """send_keys sends keys to a pane."""
    result = send_keys(
        keys="echo hello_mcp",
        pane_id=mcp_pane.pane_id,
        socket_name=mcp_server.socket_name,
    )
    assert "sent" in result.lower()


def test_capture_pane(mcp_server: Server, mcp_pane: Pane) -> None:
    """capture_pane returns pane content."""
    result = capture_pane(
        pane_id=mcp_pane.pane_id,
        socket_name=mcp_server.socket_name,
    )
    assert isinstance(result, str)


def test_get_pane_info(mcp_server: Server, mcp_pane: Pane) -> None:
    """get_pane_info returns detailed pane info."""
    result = get_pane_info(
        pane_id=mcp_pane.pane_id,
        socket_name=mcp_server.socket_name,
    )
    assert result.pane_id == mcp_pane.pane_id
    assert result.pane_width is not None
    assert result.pane_height is not None


def test_set_pane_title(mcp_server: Server, mcp_pane: Pane) -> None:
    """set_pane_title sets the pane title."""
    result = set_pane_title(
        title="my_test_title",
        pane_id=mcp_pane.pane_id,
        socket_name=mcp_server.socket_name,
    )
    assert result.pane_id == mcp_pane.pane_id


def test_clear_pane(mcp_server: Server, mcp_pane: Pane) -> None:
    """clear_pane clears pane content."""
    result = clear_pane(
        pane_id=mcp_pane.pane_id,
        socket_name=mcp_server.socket_name,
    )
    assert "cleared" in result.lower()


def test_resize_pane_dimensions(mcp_server: Server, mcp_pane: Pane) -> None:
    """resize_pane resizes a pane with height/width."""
    result = resize_pane(
        pane_id=mcp_pane.pane_id,
        height=10,
        width=40,
        socket_name=mcp_server.socket_name,
    )
    assert result.pane_id == mcp_pane.pane_id


def test_resize_pane_zoom(mcp_server: Server, mcp_session: Session) -> None:
    """resize_pane zooms a pane."""
    window = mcp_session.active_window
    window.split()
    pane = window.active_pane
    assert pane is not None
    result = resize_pane(
        pane_id=pane.pane_id,
        zoom=True,
        socket_name=mcp_server.socket_name,
    )
    assert result.pane_id == pane.pane_id


def test_resize_pane_zoom_mutual_exclusivity(
    mcp_server: Server, mcp_pane: Pane
) -> None:
    """resize_pane raises ToolError when zoom combined with dimensions."""
    with pytest.raises(ToolError, match="Cannot combine zoom"):
        resize_pane(
            pane_id=mcp_pane.pane_id,
            zoom=True,
            height=10,
            socket_name=mcp_server.socket_name,
        )


def test_kill_pane(mcp_server: Server, mcp_session: Session) -> None:
    """kill_pane kills a pane."""
    window = mcp_session.active_window
    new_pane = window.split()
    pane_id = new_pane.pane_id
    result = kill_pane(
        pane_id=pane_id,
        socket_name=mcp_server.socket_name,
    )
    assert "killed" in result.lower()


# ---------------------------------------------------------------------------
# search_panes tests
# ---------------------------------------------------------------------------


class SearchPanesFixture(t.NamedTuple):
    """Test fixture for search_panes."""

    test_id: str
    command: str
    pattern: str
    match_case: bool
    scope_to_session: bool
    expected_match: bool
    expected_min_lines: int


SEARCH_PANES_FIXTURES: list[SearchPanesFixture] = [
    SearchPanesFixture(
        test_id="simple_match",
        command="echo FINDME_unique_string_12345",
        pattern="FINDME_unique_string_12345",
        match_case=False,
        scope_to_session=False,
        expected_match=True,
        expected_min_lines=1,
    ),
    SearchPanesFixture(
        test_id="case_insensitive_match",
        command="echo UPPERCASE_findme_test",
        pattern="uppercase_findme_test",
        match_case=False,
        scope_to_session=False,
        expected_match=True,
        expected_min_lines=1,
    ),
    SearchPanesFixture(
        test_id="case_sensitive_no_match",
        command="echo CaseSensitiveTest",
        pattern="casesensitivetest",
        match_case=True,
        scope_to_session=False,
        expected_match=False,
        expected_min_lines=0,
    ),
    SearchPanesFixture(
        test_id="case_sensitive_match",
        command="echo CaseSensitiveExact",
        pattern="CaseSensitiveExact",
        match_case=True,
        scope_to_session=False,
        expected_match=True,
        expected_min_lines=1,
    ),
    SearchPanesFixture(
        test_id="regex_pattern",
        command="echo error_code_42_found",
        pattern=r"error_code_\d+_found",
        match_case=False,
        scope_to_session=False,
        expected_match=True,
        expected_min_lines=1,
    ),
    SearchPanesFixture(
        test_id="no_match",
        command="echo nothing_special",
        pattern="XYZZY_nonexistent_pattern_99999",
        match_case=False,
        scope_to_session=False,
        expected_match=False,
        expected_min_lines=0,
    ),
    SearchPanesFixture(
        test_id="scoped_to_session",
        command="echo session_scoped_marker",
        pattern="session_scoped_marker",
        match_case=False,
        scope_to_session=True,
        expected_match=True,
        expected_min_lines=1,
    ),
]


@pytest.mark.parametrize(
    SearchPanesFixture._fields,
    SEARCH_PANES_FIXTURES,
    ids=[f.test_id for f in SEARCH_PANES_FIXTURES],
)
def test_search_panes(
    mcp_server: Server,
    mcp_session: Session,
    mcp_pane: Pane,
    test_id: str,
    command: str,
    pattern: str,
    match_case: bool,
    scope_to_session: bool,
    expected_match: bool,
    expected_min_lines: int,
) -> None:
    """search_panes finds text in pane contents."""
    # Extract the echoed text from the command for polling
    echo_marker = command.split("echo ", 1)[1] if "echo " in command else command
    mcp_pane.send_keys(command, enter=True)
    retry_until(
        lambda: echo_marker in "\n".join(mcp_pane.capture_pane()),
        2,
        raises=True,
    )

    kwargs: dict[str, t.Any] = {
        "pattern": pattern,
        "match_case": match_case,
        "socket_name": mcp_server.socket_name,
    }
    if scope_to_session:
        kwargs["session_name"] = mcp_session.session_name

    result = search_panes(**kwargs)
    assert isinstance(result, list)

    if expected_match:
        assert len(result) >= 1
        match = next((r for r in result if r.pane_id == mcp_pane.pane_id), None)
        assert match is not None
        assert len(match.matched_lines) >= expected_min_lines
        assert match.session_id is not None
        assert match.window_id is not None
    else:
        pane_matches = [r for r in result if r.pane_id == mcp_pane.pane_id]
        assert len(pane_matches) == 0


def test_search_panes_basic(mcp_server: Server, mcp_pane: Pane) -> None:
    """search_panes smoke test with a unique marker."""
    mcp_pane.send_keys("echo SMOKE_TEST_MARKER_abc123", enter=True)
    retry_until(
        lambda: "SMOKE_TEST_MARKER_abc123" in "\n".join(mcp_pane.capture_pane()),
        2,
        raises=True,
    )

    result = search_panes(
        pattern="SMOKE_TEST_MARKER_abc123",
        socket_name=mcp_server.socket_name,
    )
    assert isinstance(result, list)
    assert len(result) >= 1
    assert any(r.pane_id == mcp_pane.pane_id for r in result)


def test_search_panes_returns_pane_content_match_model(
    mcp_server: Server, mcp_pane: Pane
) -> None:
    """search_panes returns PaneContentMatch models."""
    mcp_pane.send_keys("echo MODEL_TYPE_CHECK_xyz", enter=True)
    retry_until(
        lambda: "MODEL_TYPE_CHECK_xyz" in "\n".join(mcp_pane.capture_pane()),
        2,
        raises=True,
    )

    result = search_panes(
        pattern="MODEL_TYPE_CHECK_xyz",
        socket_name=mcp_server.socket_name,
    )
    assert len(result) >= 1
    for item in result:
        assert isinstance(item, PaneContentMatch)


def test_search_panes_includes_window_and_session_names(
    mcp_server: Server, mcp_session: Session, mcp_pane: Pane
) -> None:
    """search_panes populates window_name and session_name."""
    mcp_pane.send_keys("echo CONTEXT_FIELDS_CHECK_789", enter=True)
    retry_until(
        lambda: "CONTEXT_FIELDS_CHECK_789" in "\n".join(mcp_pane.capture_pane()),
        2,
        raises=True,
    )

    result = search_panes(
        pattern="CONTEXT_FIELDS_CHECK_789",
        socket_name=mcp_server.socket_name,
    )
    match = next((r for r in result if r.pane_id == mcp_pane.pane_id), None)
    assert match is not None
    assert match.window_name is not None
    assert match.session_name is not None
    assert match.session_name == mcp_session.session_name


def test_search_panes_invalid_regex(mcp_server: Server) -> None:
    """search_panes raises ToolError on invalid regex."""
    with pytest.raises(ToolError, match="Invalid regex pattern"):
        search_panes(
            pattern="[invalid",
            socket_name=mcp_server.socket_name,
        )


# ---------------------------------------------------------------------------
# search_panes is_caller annotation tests
# ---------------------------------------------------------------------------


class SearchPanesCallerFixture(t.NamedTuple):
    """Test fixture for search_panes is_caller annotation."""

    test_id: str
    tmux_pane_env: str | None
    use_real_pane_id: bool
    expected_is_caller: bool | None


SEARCH_PANES_CALLER_FIXTURES: list[SearchPanesCallerFixture] = [
    SearchPanesCallerFixture(
        test_id="caller_pane_annotated",
        tmux_pane_env=None,
        use_real_pane_id=True,
        expected_is_caller=True,
    ),
    SearchPanesCallerFixture(
        test_id="outside_tmux_no_annotation",
        tmux_pane_env=None,
        use_real_pane_id=False,
        expected_is_caller=None,
    ),
]


@pytest.mark.parametrize(
    SearchPanesCallerFixture._fields,
    SEARCH_PANES_CALLER_FIXTURES,
    ids=[f.test_id for f in SEARCH_PANES_CALLER_FIXTURES],
)
def test_search_panes_is_caller(
    mcp_server: Server,
    mcp_pane: Pane,
    monkeypatch: pytest.MonkeyPatch,
    test_id: str,
    tmux_pane_env: str | None,
    use_real_pane_id: bool,
    expected_is_caller: bool | None,
) -> None:
    """search_panes annotates results with is_caller based on TMUX_PANE."""
    marker = f"IS_CALLER_TEST_{test_id}_{id(mcp_pane)}"
    mcp_pane.send_keys(f"echo {marker}", enter=True)
    retry_until(
        lambda: marker in "\n".join(mcp_pane.capture_pane()),
        2,
        raises=True,
    )

    if use_real_pane_id:
        monkeypatch.setenv("TMUX_PANE", mcp_pane.pane_id or "")
    elif tmux_pane_env is not None:
        monkeypatch.setenv("TMUX_PANE", tmux_pane_env)
    else:
        monkeypatch.delenv("TMUX_PANE", raising=False)

    result = search_panes(
        pattern=marker,
        socket_name=mcp_server.socket_name,
    )
    match = next((r for r in result if r.pane_id == mcp_pane.pane_id), None)
    assert match is not None
    assert match.is_caller is expected_is_caller
