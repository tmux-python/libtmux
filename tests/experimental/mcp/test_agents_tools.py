"""Tests for the agents MCP tools (callables driven directly)."""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.experimental.agents.monitor import AgentMonitor

if t.TYPE_CHECKING:
    from fastmcp import FastMCP


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
    mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : done")
    listing = [{"pane_id": a.pane_id, "state": a.state.value} for a in mon.agents]
    assert {"pane_id": "%1", "state": "done"} in listing


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
    monitor = register_agents(t.cast("FastMCP[t.Any]", mcp), engine)
    monitor.ingest("%subscription-changed agentstate $0 @0 1 %1 : running")

    watch = mcp.tools["watch_agents"].fn
    result = asyncio.run(watch(timeout_s=0.01))

    assert engine.subscribe_calls == 0  # fix: watch_agents does not re-subscribe
    assert result == {"transitions": [], "count": 0}  # static store over the window


class _InstallCase(t.NamedTuple):
    """An install_agent_hooks scenario and the dict the tool should return."""

    test_id: str
    registered: bool
    expected: dict[str, str]


_INSTALL_CASES = (
    _InstallCase("known_agent", True, {"agent": "claude", "status": "installed"}),
    _InstallCase(
        "unknown_agent",
        False,
        {"agent": "claude", "error": "unknown agent"},
    ),
)


@pytest.mark.parametrize(
    "case",
    _INSTALL_CASES,
    ids=[c.test_id for c in _INSTALL_CASES],
)
def test_install_agent_hooks(
    case: _InstallCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """install_agent_hooks returns the hook status, or an error for unknown agents."""
    pytest.importorskip("fastmcp")
    from libtmux.experimental.agents.hooks import registry
    from libtmux.experimental.mcp.vocabulary.agents import register_agents

    class _FakeHook:
        def install(self) -> None: ...

        def status(self) -> str:
            return "installed"

    def _get(name: str) -> _FakeHook:
        if not case.registered:
            raise KeyError(name)
        return _FakeHook()

    monkeypatch.setattr(registry, "get", _get)
    mcp = _CapturingMcp()
    register_agents(t.cast("FastMCP[t.Any]", mcp), _FakeEngine())

    install = mcp.tools["install_agent_hooks"].fn
    assert asyncio.run(install("claude")) == case.expected


class _DispatchEngine(_FakeEngine):
    """A fake engine that records dispatched requests and succeeds."""

    def __init__(self) -> None:
        self.requests: list[t.Any] = []

    async def run(self, request: t.Any) -> t.Any:
        from libtmux.experimental.engines.base import CommandResult

        self.requests.append(request)
        return CommandResult(cmd=request.args, returncode=0)


def test_wait_for_agent_tool_reports_reached() -> None:
    """The wait_for_agent tool returns the typed outcome as a dict."""
    pytest.importorskip("fastmcp")
    from libtmux.experimental.mcp.vocabulary.agents import register_agents

    mcp = _CapturingMcp()
    monitor = register_agents(t.cast("FastMCP[t.Any]", mcp), _FakeEngine())
    monitor.ingest("%subscription-changed agentstate $0 @0 1 %1 : done")

    wait = mcp.tools["wait_for_agent"].fn
    result = asyncio.run(wait("%1", "done", 0.5))

    assert result["reached"] is True
    assert result["reason"] == "reached"
    assert result["state"] == "done"


def test_send_to_agent_tool_dispatches_when_ready() -> None:
    """The send_to_agent tool folds a ready send into a single dispatch."""
    pytest.importorskip("fastmcp")
    from libtmux.experimental.mcp.vocabulary.agents import register_agents

    engine = _DispatchEngine()
    mcp = _CapturingMcp()
    monitor = register_agents(t.cast("FastMCP[t.Any]", mcp), engine)
    monitor.ingest("%subscription-changed agentstate $0 @0 1 %1 : idle")

    send = mcp.tools["send_to_agent"].fn
    result = asyncio.run(send("%1", "echo hi"))

    assert result["sent"] is True
    assert len(engine.requests) == 1
