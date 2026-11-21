"""Tests for the agent query DSL (``agents()``) over the in-process store.

These are pure, sans-I/O units: synthetic :class:`Agent` records (and a monitor
fed synthetic notifications) drive the query, asserting it adds **zero** tmux
calls and mirrors the ``panes()`` query shape.
"""

from __future__ import annotations

from libtmux.experimental.agents.state import Agent, AgentState
from libtmux.experimental.engines import AsyncMockEngine
from libtmux.experimental.query import ATTENTION, AgentQuery, agents


def _agent(
    pane_id: str,
    state: AgentState,
    *,
    name: str | None = None,
    since: float = 0.0,
) -> Agent:
    """Build a synthetic Agent record for query tests."""
    return Agent(
        pane_id=pane_id,
        key=pane_id,
        name=name,
        state=state,
        since=since,
        source="option",
        pid=None,
        alive=True,
    )


def test_agents_starts_empty_query() -> None:
    """``agents()`` returns an immutable, chainable query."""
    assert agents() == AgentQuery()
    assert agents().filter(name="claude") is not agents()


def test_filter_by_state_over_sequence() -> None:
    """Filtering by state narrows a pure sequence of Agent records."""
    rows = [
        _agent("%1", AgentState.AWAITING_INPUT),
        _agent("%2", AgentState.RUNNING),
        _agent("%3", AgentState.AWAITING_INPUT),
    ]
    matched = agents().filter(state=AgentState.AWAITING_INPUT).all(rows)
    assert [a.pane_id for a in matched] == ["%1", "%3"]


def test_query_reads_monitor_store_zero_calls() -> None:
    """A query resolves against a monitor's live store with no tmux round-trip."""
    from libtmux.experimental.agents.monitor import AgentMonitor

    mon = AgentMonitor(AsyncMockEngine())
    mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : idle")
    mon.ingest("%subscription-changed agentstate $0 @0 2 %2 : running")
    idle = agents().filter(state=AgentState.IDLE).all(mon)
    assert [a.pane_id for a in idle] == ["%1"]


def test_order_by_since() -> None:
    """``order_by`` sorts by an Agent attribute."""
    rows = [
        _agent("%1", AgentState.RUNNING, since=3.0),
        _agent("%2", AgentState.RUNNING, since=1.0),
        _agent("%3", AgentState.RUNNING, since=2.0),
    ]
    ordered = agents().order_by("since").map(lambda a: a.pane_id).all(rows)
    assert ordered == ("%2", "%3", "%1")


def test_most_urgent_picks_blocked_agent() -> None:
    """``most_urgent`` returns the agent whose state ranks highest in attention."""
    rows = [
        _agent("%1", AgentState.RUNNING),
        _agent("%2", AgentState.AWAITING_INPUT),
        _agent("%3", AgentState.IDLE),
    ]
    top = agents().most_urgent(rows)
    assert top is not None
    assert top.pane_id == "%2"


def test_done_outranks_idle_by_default() -> None:
    """DONE is visible above idle in the default attention ladder."""
    rows = [
        _agent("%1", AgentState.IDLE),
        _agent("%2", AgentState.DONE),
    ]
    top = agents().most_urgent(rows)
    assert top is not None
    assert top.pane_id == "%2"


def test_most_urgent_none_when_empty() -> None:
    """``most_urgent`` returns ``None`` when nothing matches."""
    assert agents().filter(name="nobody").most_urgent([]) is None


def test_rollup_groups_most_urgent_per_key() -> None:
    """``rollup`` collapses each group to its most-urgent state."""
    rows = [
        _agent("%1", AgentState.RUNNING, name="claude"),
        _agent("%2", AgentState.AWAITING_INPUT, name="claude"),
        _agent("%3", AgentState.IDLE, name="codex"),
    ]
    rolled = agents().rollup(rows, key=lambda a: a.name)
    assert rolled == {
        "claude": AgentState.AWAITING_INPUT,
        "codex": AgentState.IDLE,
    }


def test_attention_priority_is_overridable() -> None:
    """A caller-supplied priority map changes which state wins a rollup."""
    rows = [
        _agent("%1", AgentState.RUNNING, name="claude"),
        _agent("%2", AgentState.AWAITING_INPUT, name="claude"),
    ]
    # Invert the default: make RUNNING outrank AWAITING_INPUT.
    priority = {**ATTENTION, AgentState.RUNNING: 99}
    rolled = agents().rollup(rows, key=lambda a: a.name, priority=priority)
    assert rolled == {"claude": AgentState.RUNNING}
