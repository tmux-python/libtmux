"""Tests for the tmux:// hierarchy resources on the engine-ops MCP server."""

from __future__ import annotations

import asyncio
import json
import typing as t

import pytest

from libtmux.experimental.engines import MockEngine, SubprocessEngine

fastmcp = pytest.importorskip("fastmcp")

from libtmux.experimental.mcp.fastmcp_adapter import build_server  # noqa: E402

if t.TYPE_CHECKING:
    from libtmux.session import Session


def _text(contents: t.Any) -> str:
    """Join the text of a read_resource result (robust to content shape)."""
    return "".join(getattr(item, "text", "") for item in contents)


def test_resources_read_offline_returns_json() -> None:
    """The sessions resource is registered and returns a JSON array."""
    server = build_server(MockEngine())

    async def main() -> t.Any:
        async with fastmcp.Client(server) as client:
            return await client.read_resource("tmux://sessions")

    payload = json.loads(_text(asyncio.run(main())))
    assert isinstance(payload, list)


def test_resources_read_live_hierarchy(session: Session) -> None:
    """Over a real tmux server, the resources expose the live session + panes."""
    mcp = build_server(SubprocessEngine.for_server(session.server))
    pane = session.active_window.active_pane
    assert pane is not None and pane.pane_id is not None

    async def main() -> tuple[str, str]:
        async with fastmcp.Client(mcp) as client:
            sessions = _text(await client.read_resource("tmux://sessions"))
            content = _text(
                await client.read_resource(f"tmux://panes/{pane.pane_id}/content"),
            )
            return sessions, content

    sessions, _content = asyncio.run(main())
    assert session.session_name is not None
    assert session.session_name in sessions  # the live session is listed
