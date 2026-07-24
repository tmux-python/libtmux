"""Tests for the safety tier-gate wired into the fastmcp adapter."""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.experimental.engines import MockEngine

fastmcp = pytest.importorskip("fastmcp")

from libtmux.experimental.mcp.fastmcp_adapter import build_server  # noqa: E402


def _names_at(level: str, **kwargs: t.Any) -> set[str]:
    """Return the visible tool names from a server built at *level*."""

    async def main() -> set[str]:
        server = build_server(MockEngine(), safety_level=level, **kwargs)
        async with fastmcp.Client(server) as client:
            return {tool.name for tool in await client.list_tools()}

    return asyncio.run(main())


def test_safety_gate_static_visibility() -> None:
    """Each tier hides the tools above it from the listing."""
    readonly = _names_at("readonly")
    mutating = _names_at("mutating")
    destructive = _names_at("destructive")

    assert "list_sessions" in readonly  # readonly always visible
    assert "create_session" not in readonly  # mutating hidden at readonly
    assert "create_session" in mutating  # ... visible at mutating
    assert "kill_session" not in readonly  # destructive hidden ...
    assert "kill_session" not in mutating  # ... and at mutating
    assert "kill_session" in destructive  # visible only at destructive


def test_safety_gate_keeps_per_op_hidden_at_every_tier() -> None:
    """Regression: the subtractive gate never re-exposes hidden per-op tools."""
    for level in ("readonly", "mutating", "destructive"):
        names = _names_at(level, include_operations=True, expose_operations=False)
        assert not any(name.startswith("op_") for name in names), (
            f"per-op tools leaked into the listing at safety_level={level!r}"
        )
    # expose_operations=True surfaces them (and they still respect the tier)
    exposed = _names_at(
        "destructive",
        include_operations=True,
        expose_operations=True,
    )
    assert any(name.startswith("op_") for name in exposed)


def test_safety_gate_blocks_destructive_call_at_readonly() -> None:
    """A destructive tool cannot be successfully called at the readonly tier."""

    async def main() -> tuple[str, t.Any]:
        server = build_server(MockEngine(), safety_level="readonly")
        async with fastmcp.Client(server) as client:
            try:
                result = await client.call_tool("kill_session", {"target": "$1"})
            except Exception as error:
                return ("raised", type(error).__name__)
            return ("result", result.is_error)

    kind, value = asyncio.run(main())
    # Either the hidden tool is rejected (raised) or surfaced as an error result;
    # never a clean success.
    assert kind == "raised" or value is True


def test_safety_gate_plan_tool_tier() -> None:
    """Plan tools obey the tier too (build_workspace is mutating)."""
    readonly = _names_at("readonly")
    mutating = _names_at("mutating")
    assert "preview_plan" in readonly  # readonly plan tool always visible
    assert "build_workspace" not in readonly  # mutating plan tool hidden ...
    assert "build_workspaces" not in readonly
    assert "build_workspace" in mutating  # ... visible at mutating
    assert "build_workspaces" in mutating
