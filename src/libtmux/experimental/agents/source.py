"""Where agent records come from, and how urgent they are.

Every read-side surface over the fleet -- the :mod:`~libtmux.experimental.query`
agent query, the workspace status projection, the status-line painter -- takes
the same polymorphic source (a live :class:`~.monitor.AgentMonitor`, or a plain
sequence of :class:`~.state.Agent` records) and ranks the result by the same
attention ladder. Both live here, in a leaf module every one of those surfaces
can import.
"""

from __future__ import annotations

import typing as t

from libtmux.experimental.agents.state import AgentState

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.experimental.agents.monitor import AgentMonitor
    from libtmux.experimental.agents.state import Agent

#: A source of agent records: a monitor to read its store, or pre-taken records.
AgentSource = t.Union["AgentMonitor", "Sequence[Agent]"]

#: Default attention ladder for agent rollups (higher value = more urgent). The
#: ordering is a *documented default* a caller can override per call: surveyed
#: orchestrators disagree on the exact weighting, so it is policy, not a rule.
ATTENTION: dict[AgentState, int] = {
    AgentState.AWAITING_INPUT: 5,
    AgentState.DONE: 4,
    AgentState.IDLE: 3,
    AgentState.RUNNING: 2,
    AgentState.UNKNOWN: 1,
    AgentState.EXITED: 0,
}

#: The states in attention order, most urgent first (derived from :data:`ATTENTION`
#: so a re-weighting cannot leave a renderer's order stale).
ATTENTION_ORDER: tuple[AgentState, ...] = tuple(
    sorted(ATTENTION, key=lambda state: ATTENTION[state], reverse=True),
)


def agent_rows(source: AgentSource) -> tuple[Agent, ...]:
    """Resolve *source* into agent records (read a monitor's store, or pass through).

    A monitor is detected by its ``agents`` snapshot property (zero tmux calls --
    the store is already populated by the monitor's own drain); any other value is
    taken as a pure sequence of :class:`~.state.Agent` records.

    Parameters
    ----------
    source : AgentSource
        A monitor, or a sequence of agent records.

    Returns
    -------
    tuple[Agent, ...]

    Examples
    --------
    >>> from libtmux.experimental.agents.state import Agent, AgentState
    >>> record = Agent(pane_id="%1", key="%1", name=None, state=AgentState.RUNNING,
    ...                since=0.0, source="option", pid=None, alive=True)
    >>> agent_rows([record]) == (record,)
    True
    >>> agent_rows(())
    ()
    """
    store_agents = getattr(source, "agents", None)
    if store_agents is not None:
        return tuple(store_agents)
    return tuple(t.cast("Sequence[Agent]", source))
