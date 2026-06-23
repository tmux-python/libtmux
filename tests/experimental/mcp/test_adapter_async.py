"""The async-first FastMCP adapter -- awaited tools, per-op, and plan tiers.

Exercised offline via an in-process FastMCP client over a sync ``ConcreteEngine``
wrapped into the async protocol, so the async registration path is validated with
no tmux.
"""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.experimental.engines import ConcreteEngine
from libtmux.experimental.mcp.vocabulary._bridge import SyncToAsyncEngine

fastmcp = pytest.importorskip("fastmcp")


def _async_server(**kwargs: t.Any) -> t.Any:
    """Build an async server over a wrapped in-memory engine."""
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server

    return build_async_server(
        SyncToAsyncEngine(ConcreteEngine()), events="off", **kwargs
    )


def test_async_server_exposes_curated_and_conveniences() -> None:
    """The async server surfaces the curated verbs plus the new conveniences."""

    async def main() -> set[str]:
        async with fastmcp.Client(_async_server()) as client:
            return {tool.name for tool in await client.list_tools()}

    names = asyncio.run(main())
    expected = {
        "create_session",
        "grep_pane",
        "capture_active_pane",
        "resolve_relative_pane",
        "find_pane_by_position",
        "select_pane",
        "resize_pane",
        "run_tmux",
        "list_clients",
        "has_session",
    }
    assert expected <= names
    # The per-op surface is hidden by default.
    assert not any(name.startswith("op_") for name in names)


def test_async_tool_call_returns_typed_data() -> None:
    """An awaited curated tool returns its typed result over the client."""

    async def main() -> t.Any:
        async with fastmcp.Client(_async_server()) as client:
            result = await client.call_tool("create_session", {"name": "dev"})
            raw = await client.call_tool("run_tmux", {"args": ["list-sessions"]})
            return result.data, raw.data

    session, raw = asyncio.run(main())
    assert session.session_id == "$1"
    assert raw.ok is True


def test_async_per_op_dispatch() -> None:
    """A hidden per-op tool dispatches via the async run path."""

    async def main() -> t.Any:
        async with fastmcp.Client(_async_server(expose_operations=True)) as client:
            result = await client.call_tool("op_list_sessions", {})
            return result.data

    data = asyncio.run(main())
    assert data["status"] == "complete"


def test_async_plan_preview() -> None:
    """The pure preview_plan tool is registered on the async server."""

    async def main() -> t.Any:
        async with fastmcp.Client(_async_server()) as client:
            result = await client.call_tool(
                "preview_plan",
                {"operations": [{"kind": "start_server"}]},
            )
            return result.data

    data = asyncio.run(main())
    assert data["ok"] is True
