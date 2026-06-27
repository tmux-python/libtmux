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
from libtmux.experimental.ops import NewSession
from libtmux.experimental.ops.serialize import operation_to_dict

fastmcp = pytest.importorskip("fastmcp")

if t.TYPE_CHECKING:
    from libtmux.session import Session


def test_adapter_registers_typed_tools() -> None:
    """The curated vocabulary appears as typed tools with safety annotations."""
    # destructive tier so the kill_* tools this asserts on are visible
    server = build_server(ConcreteEngine(), safety_level="destructive")

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
    # destructive tier so the live kill_session call below is permitted
    mcp = build_server(SubprocessEngine.for_server(server), safety_level="destructive")

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


def test_adapter_operations_hidden_by_default() -> None:
    """Per-operation tools are registered but hidden; plan tools stay visible."""
    server = build_server(ConcreteEngine())

    async def main() -> t.Any:
        async with fastmcp.Client(server) as client:
            return await client.list_tools()

    names = {tool.name for tool in asyncio.run(main())}
    assert not any(name.startswith("op_") for name in names)
    assert {
        "preview_plan",
        "execute_plan",
        "result_schema",
        "build_workspace",
    } <= names


def test_adapter_exposes_per_op_tools() -> None:
    """``expose_operations`` reveals one typed ``op_<kind>`` per operation."""
    # destructive tier so the destructive op_kill_* tools are visible too
    server = build_server(
        ConcreteEngine(),
        expose_operations=True,
        safety_level="destructive",
    )

    async def main() -> t.Any:
        async with fastmcp.Client(server) as client:
            return await client.list_tools()

    by_name = {tool.name: tool for tool in asyncio.run(main())}
    assert "op_split_window" in by_name
    assert "op_new_session" in by_name

    # the target the registry omits is re-injected into the per-op schema
    properties = by_name["op_split_window"].inputSchema.get("properties", {})
    assert "target" in properties
    assert "horizontal" in properties

    # safety tier -> annotations
    assert by_name["op_kill_session"].annotations.destructiveHint is True
    assert by_name["op_capture_pane"].annotations.readOnlyHint is True


def test_adapter_per_op_call_offline() -> None:
    """A per-op tool builds + runs its operation, returning the serialized result."""
    server = build_server(ConcreteEngine(), expose_operations=True)

    async def main() -> t.Any:
        async with fastmcp.Client(server) as client:
            return await client.call_tool("op_new_session", {"session_name": "raw"})

    payload = asyncio.run(main()).structured_content or {}
    assert payload["operation"]["kind"] == "new_session"
    assert payload["new_id"] == "$1"


def test_adapter_plan_tools_offline() -> None:
    """preview/execute/result_schema drive a serialized plan with forward refs."""
    server = build_server(ConcreteEngine())
    operations = [operation_to_dict(NewSession(session_name="dev", capture_panes=True))]

    async def main() -> tuple[t.Any, t.Any, t.Any]:
        async with fastmcp.Client(server) as client:
            preview = await client.call_tool("preview_plan", {"operations": operations})
            outcome = await client.call_tool("execute_plan", {"operations": operations})
            schema = await client.call_tool("result_schema", {"kind": "new_session"})
            return preview, outcome, schema

    preview, outcome, schema = asyncio.run(main())
    assert preview.structured_content["ok"] is True
    assert outcome.structured_content["ok"] is True
    # the new session's captured sub-ids surface as forward-ref bindings
    assert outcome.structured_content["bindings"]["0"] == "$1"
    assert outcome.structured_content["bindings"]["0:pane"] == "%1"
    assert "first_pane_id" in schema.structured_content["binding_fields"]


def test_adapter_build_workspace_offline() -> None:
    """The workspace tool builds a declarative spec in one call (preflight off)."""
    server = build_server(ConcreteEngine())
    spec = {
        "session_name": "ws",
        "windows": [{"window_name": "editor", "panes": ["vim", "pytest -q"]}],
    }

    async def main() -> t.Any:
        async with fastmcp.Client(server) as client:
            return await client.call_tool(
                "build_workspace",
                {"spec": spec, "preflight": False},
            )

    payload = asyncio.run(main()).structured_content or {}
    assert payload["ok"] is True


def test_default_server_builds() -> None:
    """The packaged ``default_server`` factory exposes the curated + plan tools."""
    from libtmux.experimental.mcp import default_server

    server = default_server()

    async def main() -> t.Any:
        async with fastmcp.Client(server) as client:
            return await client.list_tools()

    names = {tool.name for tool in asyncio.run(main())}
    assert "create_session" in names
    assert "execute_plan" in names


def test_main_help_exits() -> None:
    """The console-script entry parses ``--help`` and exits cleanly."""
    from libtmux.experimental.mcp import main

    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0


def test_adapter_plan_live(session: Session) -> None:
    """Execute a serialized plan over real tmux through the execute_plan tool."""
    server = session.server
    mcp = build_server(SubprocessEngine.for_server(server))
    operations = [
        operation_to_dict(NewSession(session_name="plan-live", capture_panes=True)),
    ]

    async def main() -> t.Any:
        async with fastmcp.Client(mcp) as client:
            return await client.call_tool("execute_plan", {"operations": operations})

    outcome = asyncio.run(main()).structured_content
    assert outcome["ok"] is True
    assert outcome["bindings"]["0"].startswith("$")
    assert server.sessions.filter(session_name="plan-live")
    server.cmd("kill-session", "-t", "plan-live")
