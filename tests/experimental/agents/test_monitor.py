"""Unit tests for AgentMonitor.ingest (no live tmux)."""

from __future__ import annotations

from libtmux.experimental.agents.monitor import AgentMonitor
from libtmux.experimental.agents.state import AgentState


class _FakeEngine:
    async def run(self, request: object) -> None: ...

    async def subscribe(self) -> None: ...

    def add_subscription(self, spec: object) -> None: ...

    def set_attach_targets(self, ids: object) -> None: ...


def test_ingest_option_line_updates_agent() -> None:
    """Option-channel %subscription-changed maps to a store entry."""
    mon = AgentMonitor(_FakeEngine())
    mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : running")
    by_pane = {a.pane_id: a for a in mon.agents}
    assert by_pane["%1"].state is AgentState.RUNNING


def test_ingest_osc_output_updates_agent() -> None:
    r"""OSC %output line feeds the OscSignal and lands in the store."""
    mon = AgentMonitor(_FakeEngine())
    mon.ingest("%output %2 \033]3008;state=awaiting_input\033\\")
    by_pane = {a.pane_id: a for a in mon.agents}
    assert by_pane["%2"].state is AgentState.AWAITING_INPUT


def test_stale_does_not_clobber() -> None:
    """Second (newer counter) option update beats the first — latest-wins."""
    mon = AgentMonitor(_FakeEngine())
    mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : running")
    mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : idle")
    # newest wins; both via the option writer so the second (newer counter) wins
    by_pane = {a.pane_id: a for a in mon.agents}
    assert by_pane["%1"].state is AgentState.IDLE
