"""Tests for the agents MCP tools (callables driven directly)."""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.experimental.agents.monitor import AgentMonitor


class _FakeEngine:
    async def run(self, request: object) -> None: ...

    async def subscribe(self) -> t.AsyncIterator[object]:
        return
        yield

    def add_subscription(self, spec: object) -> None: ...
    def set_attach_targets(self, ids: object) -> None: ...


class _CountingEngine(_FakeEngine):
    """A fake engine that records how many times ``subscribe()`` is called."""

    def __init__(self) -> None:
        self.subscribe_calls = 0

    async def subscribe(self) -> t.AsyncIterator[object]:
        self.subscribe_calls += 1
        return
        yield


class _CapturingMcp:
    """A FastMCP stand-in that captures registered tools by name."""

    def __init__(self) -> None:
        self.tools: dict[str, t.Any] = {}

    def add_tool(self, tool: t.Any) -> None:
        self.tools[tool.name] = tool


def test_list_agents_reflects_ingested_state() -> None:
    """list_agents shape: ingested option-line produces the expected pane dict."""
    mon = AgentMonitor(_FakeEngine())
    mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : running")
    listing = [{"pane_id": a.pane_id, "state": a.state.value} for a in mon.agents]
    assert {"pane_id": "%1", "state": "running"} in listing


def test_watch_agents_observes_store_without_subscribing() -> None:
    """watch_agents reads the monitor's store; it opens no second subscription.

    The monitor's own drain is the sole ingester, so watch_agents must only read
    ``monitor.agents`` -- a second ``subscribe()`` would double-ingest and drift
    the clock.
    """
    pytest.importorskip("fastmcp")
    from libtmux.experimental.mcp.vocabulary.agents import register_agents

    engine = _CountingEngine()
    mcp = _CapturingMcp()
    monitor = register_agents(mcp, engine)
    monitor.ingest("%subscription-changed agentstate $0 @0 1 %1 : running")

    watch = mcp.tools["watch_agents"].fn
    result = asyncio.run(watch(timeout_s=0.01))

    assert engine.subscribe_calls == 0  # fix: watch_agents does not re-subscribe
    assert result == {"transitions": [], "count": 0}  # static store over the window
