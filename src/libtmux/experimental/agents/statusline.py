"""Render the agent fleet into tmux's status line -- a live UI in one set-option.

The "instantly rendering UI" surface, parallel to the floating
:class:`~libtmux.experimental.agents.hud.HudRenderer`:
:func:`paint_status_line` reads agent state from the in-process store (**zero**
tmux calls -- the monitor's drain already populated it) and writes a compact
fleet summary into ``status-right`` with a **single** ``set-option`` dispatch.

The default :func:`render_status_line` is a per-state tally in attention order;
pass your own ``render`` (or ``labels``) for a different look. This writer owns
the *mechanism* (read at zero cost -> one dispatch), not the format -- the look is
policy, like the rollup priority ladder.
"""

from __future__ import annotations

import collections
import typing as t

from libtmux.experimental.agents.state import AgentState
from libtmux.experimental.ops import SetOption, arun

if t.TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from libtmux.experimental.agents.monitor import AgentMonitor
    from libtmux.experimental.agents.state import Agent
    from libtmux.experimental.engines.base import AsyncTmuxEngine
    from libtmux.experimental.ops._types import Target

#: Short per-state labels for the default tally (override via ``labels``).
DEFAULT_LABELS: dict[AgentState, str] = {
    AgentState.AWAITING_INPUT: "wait",
    AgentState.DONE: "done",
    AgentState.IDLE: "idle",
    AgentState.RUNNING: "run",
    AgentState.EXITED: "exit",
    AgentState.UNKNOWN: "?",
}

#: The order states appear in the default tally (most-urgent first).
_ATTENTION_ORDER: tuple[AgentState, ...] = (
    AgentState.AWAITING_INPUT,
    AgentState.DONE,
    AgentState.IDLE,
    AgentState.RUNNING,
    AgentState.UNKNOWN,
    AgentState.EXITED,
)

#: A source of agent records: a monitor (read its ``agents`` snapshot at zero
#: tmux cost), or a pure sequence of :class:`~..state.Agent`.
AgentSource = t.Union["AgentMonitor", "Sequence[Agent]"]


def render_status_line(
    agents: Sequence[Agent],
    *,
    labels: Mapping[AgentState, str] = DEFAULT_LABELS,
) -> str:
    """Render a compact per-state tally of *agents* (pure; no tmux).

    Non-zero states only, most-urgent first, as ``label:count`` joined by spaces
    -- e.g. ``"wait:1 run:2"``. An empty fleet renders ``""``.

    Examples
    --------
    >>> from libtmux.experimental.agents.state import Agent, AgentState
    >>> def a(pid, st):
    ...     return Agent(pane_id=pid, key=pid, name=None, state=st, since=0.0,
    ...                  source="option", pid=None, alive=True)
    >>> render_status_line([a("%1", AgentState.RUNNING),
    ...                     a("%2", AgentState.AWAITING_INPUT)])
    'wait:1 run:1'
    >>> render_status_line([])
    ''
    """
    merged = {**DEFAULT_LABELS, **labels}
    counts = collections.Counter(agent.state for agent in agents)
    parts = [
        f"{merged[state]}:{counts[state]}"
        for state in _ATTENTION_ORDER
        if counts.get(state)
    ]
    return " ".join(parts)


def status_line_op(
    value: str,
    *,
    option: str = "status-right",
    target: Target | None = None,
    global_: bool = False,
) -> SetOption:
    """Build the single ``set-option`` that paints *value* into the status line.

    Examples
    --------
    >>> status_line_op("wait:1", global_=True).render()
    ('set-option', '-g', 'status-right', 'wait:1')
    """
    return SetOption(option=option, value=value, target=target, global_=global_)


async def paint_status_line(
    engine: AsyncTmuxEngine,
    source: AgentSource,
    *,
    render: Callable[[Sequence[Agent]], str] = render_status_line,
    option: str = "status-right",
    target: Target | None = None,
    global_: bool = False,
) -> bool:
    """Paint the fleet summary into the status line in one ``set-option``.

    Reads agents from *source* -- a monitor (its ``agents`` snapshot, **zero**
    tmux calls) or a pure sequence -- renders them, and dispatches a single
    ``set-option``. Returns whether the write succeeded.

    Examples
    --------
    >>> import asyncio
    >>> from libtmux.experimental.engines import AsyncConcreteEngine
    >>> from libtmux.experimental.agents.state import Agent, AgentState
    >>> agents = [Agent(pane_id="%1", key="%1", name=None,
    ...                 state=AgentState.AWAITING_INPUT, since=0.0,
    ...                 source="option", pid=None, alive=True)]
    >>> asyncio.run(paint_status_line(AsyncConcreteEngine(), agents, global_=True))
    True
    """
    store_agents = getattr(source, "agents", None)
    agents: Sequence[Agent] = (
        store_agents
        if store_agents is not None
        else tuple(t.cast("Sequence[Agent]", source))
    )
    value = render(agents)
    op = status_line_op(value, option=option, target=target, global_=global_)
    result = await arun(op, engine)
    return result.ok
