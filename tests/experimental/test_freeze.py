"""Tests for ``freeze`` -- a live server snapshot reverse-analyzed into IR.

The pure core (:func:`freeze`) maps an immutable
:class:`~libtmux.experimental.models.snapshots.ServerSnapshot` into a declarative
:class:`~libtmux.experimental.workspace.ir.Workspace`, closing the round-trip
``analyze`` opens. These units feed synthetic snapshots -- no tmux.
"""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.experimental.engines import ConcreteEngine
from libtmux.experimental.engines.async_control_mode import AsyncControlModeEngine
from libtmux.experimental.models.snapshots import ServerSnapshot
from libtmux.experimental.workspace.freeze import SHELLS, afreeze_server, freeze

if t.TYPE_CHECKING:
    from libtmux.experimental.workspace.ir import Workspace
    from libtmux.session import Session


def _server(*rows: dict[str, str]) -> ServerSnapshot:
    """Build a ServerSnapshot from flat per-pane rows (one list-panes read)."""
    return ServerSnapshot.from_pane_rows(rows)


def test_freeze_maps_session_window_pane() -> None:
    """A single session's tree becomes a Workspace of Windows of Panes."""
    server = _server(
        {
            "session_id": "$0",
            "session_name": "dev",
            "window_id": "@1",
            "window_index": "0",
            "window_name": "editor",
            "window_layout": "main-vertical",
            "window_active": "1",
            "pane_id": "%1",
            "pane_index": "0",
            "pane_active": "1",
            "pane_current_command": "vim",
            "pane_current_path": "/home/d/work",
        },
    )
    ws = freeze(server)
    assert ws.name == "dev"
    assert [w.name for w in ws.windows] == ["editor"]
    win = ws.windows[0]
    assert win.layout == "main-vertical"
    assert win.focus is True  # the active window
    pane = win.panes[0]
    assert [c.cmd for c in pane.commands] == ["vim"]
    assert pane.start_directory == "/home/d/work"
    assert pane.focus is True  # the active pane


def test_freeze_drops_shell_command() -> None:
    """A pane sitting at a bare shell freezes to an empty pane (no nested shell)."""
    server = _server(
        {
            "session_id": "$0",
            "session_name": "dev",
            "window_id": "@1",
            "window_index": "0",
            "window_name": "main",
            "pane_id": "%1",
            "pane_index": "0",
            "pane_current_command": "zsh",
        },
    )
    pane = freeze(server).windows[0].panes[0]
    assert pane.run is None
    assert "zsh" in SHELLS  # documents the default filter


def test_freeze_keeps_non_shell_command() -> None:
    """A pane running a real program freezes that program as the pane command."""
    server = _server(
        {
            "session_id": "$0",
            "session_name": "dev",
            "window_id": "@1",
            "window_index": "0",
            "window_name": "logs",
            "pane_id": "%1",
            "pane_index": "0",
            "pane_current_command": "tail",
        },
    )
    assert [c.cmd for c in freeze(server).windows[0].panes[0].commands] == ["tail"]


def test_freeze_selects_session_by_name() -> None:
    """With many sessions, ``session=`` picks one to freeze."""
    server = _server(
        {
            "session_id": "$0",
            "session_name": "a",
            "window_id": "@1",
            "window_index": "0",
            "window_name": "w",
            "pane_id": "%1",
            "pane_index": "0",
        },
        {
            "session_id": "$1",
            "session_name": "b",
            "window_id": "@2",
            "window_index": "0",
            "window_name": "w",
            "pane_id": "%2",
            "pane_index": "0",
        },
    )
    assert freeze(server, session="b").name == "b"
    assert freeze(server, session="$0").name == "a"


def test_freeze_ambiguous_session_raises() -> None:
    """With many sessions and no selector, freeze refuses to guess."""
    server = _server(
        {
            "session_id": "$0",
            "session_name": "a",
            "window_id": "@1",
            "window_index": "0",
            "pane_id": "%1",
            "pane_index": "0",
        },
        {
            "session_id": "$1",
            "session_name": "b",
            "window_id": "@2",
            "window_index": "0",
            "pane_id": "%2",
            "pane_index": "0",
        },
    )
    with pytest.raises(ValueError, match=r"ambiguous|multiple|session="):
        freeze(server)


def test_freeze_unknown_session_raises() -> None:
    """A named session that is not present is an error, not an empty workspace."""
    server = _server(
        {
            "session_id": "$0",
            "session_name": "a",
            "window_id": "@1",
            "window_index": "0",
            "pane_id": "%1",
            "pane_index": "0",
        },
    )
    with pytest.raises(ValueError, match="nope"):
        freeze(server, session="nope")


def test_freeze_round_trips_into_a_buildable_workspace() -> None:
    """``freeze`` output compiles and builds -- the declarative round-trip closes."""
    server = _server(
        {
            "session_id": "$0",
            "session_name": "dev",
            "window_id": "@1",
            "window_index": "0",
            "window_name": "editor",
            "pane_id": "%1",
            "pane_index": "0",
            "pane_active": "1",
            "pane_current_command": "vim",
        },
        {
            "session_id": "$0",
            "session_name": "dev",
            "window_id": "@1",
            "window_index": "0",
            "window_name": "editor",
            "pane_id": "%2",
            "pane_index": "1",
            "pane_current_command": "tail",
        },
    )
    ws = freeze(server)
    assert ws.compile().operations[0].kind == "new_session"
    assert ws.build(ConcreteEngine(), preflight=False).ok


def test_afreeze_server_captures_live_tree(session: Session) -> None:
    """A real server freezes in ONE list-panes read, reproducing its windows.

    Validates ``FREEZE_FORMAT`` against live tmux: the frozen Workspace must carry
    the live session's name and every window name, and remain buildable.
    """
    session.new_window(window_name="logs")
    live_names = {w.window_name for w in session.windows}

    async def main() -> Workspace:
        engine = AsyncControlModeEngine.for_server(session.server)
        try:
            return await afreeze_server(engine, session=session.name)
        finally:
            await engine.aclose()

    ws = asyncio.run(main())
    assert ws.name == session.name
    assert {w.name for w in ws.windows} == live_names
    # The captured tree is a valid, buildable spec.
    assert ws.compile().operations[0].kind == "new_session"
