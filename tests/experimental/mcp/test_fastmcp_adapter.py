"""The optional fastmcp adapter on a real FastMCP server (in-process).

Proves the framework-agnostic projection actually drives fastmcp: the curated
vocabulary registers as typed tools (engine bound out of the schema, safety ->
annotations), and an in-process client can list and call them -- offline against
the ``ConcreteEngine`` and live against a real tmux server. Skipped entirely when
the ``mcp`` extra (fastmcp) is not installed.
"""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.experimental.engines import ConcreteEngine, SubprocessEngine
from libtmux.experimental.mcp.fastmcp_adapter import build_server

fastmcp = pytest.importorskip("fastmcp")

if t.TYPE_CHECKING:
    from libtmux.session import Session


def test_adapter_registers_typed_tools() -> None:
    """The curated vocabulary appears as typed tools with safety annotations."""
    server = build_server(ConcreteEngine())

    async def main() -> t.Any:
        async with fastmcp.Client(server) as client:
            return await client.list_tools()

    tools = asyncio.run(main())
    by_name = {tool.name: tool for tool in tools}
    assert {
        "create_session",
        "create_window",
        "split_pane",
        "send_input",
        "capture_pane",
        "list_sessions",
        "kill_session",
    } <= set(by_name)

    # safety tier -> ToolAnnotations
    assert by_name["capture_pane"].annotations.readOnlyHint is True
    assert by_name["kill_session"].annotations.destructiveHint is True
    assert by_name["create_session"].annotations.readOnlyHint is False

    # the engine is injected, not an agent-facing parameter
    properties = by_name["create_session"].inputSchema.get("properties", {})
    assert "engine" not in properties
    assert "name" in properties


def test_adapter_calls_tool_offline() -> None:
    """Calling a tool through the in-process client returns structured output."""
    server = build_server(ConcreteEngine())

    async def main() -> t.Any:
        async with fastmcp.Client(server) as client:
            return await client.call_tool("create_session", {"name": "dev"})

    result = asyncio.run(main())
    payload = result.structured_content or {}
    assert payload.get("session_id") == "$1"
    assert payload.get("first_pane_id") == "%1"


def test_adapter_live(session: Session) -> None:
    """Drive a real tmux server through fastmcp tools end to end."""
    server = session.server
    mcp = build_server(SubprocessEngine.for_server(server))

    async def main() -> str | None:
        async with fastmcp.Client(mcp) as client:
            created = await client.call_tool("create_session", {"name": "fastmcp-live"})
            session_id = (created.structured_content or {}).get("session_id")
            await client.call_tool(
                "split_pane",
                {"target": session_id, "horizontal": True},
            )
            await client.call_tool("kill_session", {"target": "fastmcp-live"})
            return session_id

    session_id = asyncio.run(main())
    assert session_id is not None
    assert session_id.startswith("$")
    assert not server.sessions.filter(session_name="fastmcp-live")
