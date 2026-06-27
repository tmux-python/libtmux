"""Tests for the agents MCP tools (callables driven directly)."""

from __future__ import annotations

import typing as t

from libtmux.experimental.agents.monitor import AgentMonitor


class _FakeEngine:
    async def run(self, request: object) -> None: ...

    async def subscribe(self) -> t.AsyncIterator[object]:
        return
        yield

    def add_subscription(self, spec: object) -> None: ...
    def set_attach_targets(self, ids: object) -> None: ...


def test_list_agents_reflects_ingested_state() -> None:
    """list_agents shape: ingested option-line produces the expected pane dict."""
    mon = AgentMonitor(_FakeEngine())
    mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : running")
    listing = [{"pane_id": a.pane_id, "state": a.state.value} for a in mon.agents]
    assert {"pane_id": "%1", "state": "running"} in listing
