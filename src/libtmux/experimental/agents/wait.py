"""Block until an agent reaches a state -- the fan-in synchronization verbs.

:func:`wait_for_agent_state` and the fleet :func:`wait_for_agents` resolve the
*moment* the :class:`~libtmux.experimental.agents.monitor.AgentMonitor`'s
in-process store shows a pane's agent reach a target state, so **a wait costs
zero tmux calls**: the monitor's drain already ingests the control-mode stream,
and the wait either returns immediately (a level check against the store) or
parks on a future the drain wakes. Outcomes come back as *data* -- an
:class:`AgentWait` carrying a typed :class:`WaitReason` -- never a raise on
timeout, so the fleet variant can report one outcome per pane.

This is the event-driven twin of the command-settle monitor
(:func:`~libtmux.experimental.mcp._settle.accumulate_until_settle`): same
"return on the event, not on a fixed sleep" shape, applied to agent state.
"""

from __future__ import annotations

import asyncio
import enum
import typing as t
from dataclasses import dataclass

from libtmux.experimental.agents.state import AgentState

if t.TYPE_CHECKING:
    from collections.abc import Callable, Collection

    from libtmux.experimental.agents.monitor import AgentMonitor
    from libtmux.experimental.agents.state import Agent


class WaitReason(str, enum.Enum):
    """Why a :func:`wait_for_agent_state` returned.

    Examples
    --------
    >>> WaitReason.REACHED.value
    'reached'
    """

    REACHED = "reached"
    """The target state was observed."""
    TIMEOUT = "timeout"
    """The deadline elapsed before the target was reached."""
    EXITED = "exited"
    """The agent reached EXITED (and EXITED was not the target)."""
    STOPPED = "stopped"
    """The monitor stopped while the wait was parked."""


@dataclass(frozen=True)
class AgentWait:
    """The outcome of a wait, as data (never raised).

    Examples
    --------
    >>> AgentWait(pane_id="%1", reason=WaitReason.REACHED, agent=None).reached
    True
    >>> AgentWait(pane_id="%1", reason=WaitReason.TIMEOUT, agent=None).reached
    False
    """

    pane_id: str
    reason: WaitReason
    agent: Agent | None

    @property
    def reached(self) -> bool:
        """Whether the target state was actually reached."""
        return self.reason is WaitReason.REACHED


def _as_target_set(
    target: AgentState | Collection[AgentState],
) -> frozenset[AgentState]:
    """Normalize a single state or a collection of states to a frozenset.

    ``AgentState`` is checked first because it is a ``str`` subclass (and so also
    a ``Collection``); without the guard a lone state would iterate its characters.

    Examples
    --------
    >>> sorted(s.value for s in _as_target_set(AgentState.IDLE))
    ['idle']
    >>> sorted(s.value for s in _as_target_set(
    ...     {AgentState.IDLE, AgentState.AWAITING_INPUT}))
    ['awaiting_input', 'idle']
    """
    if isinstance(target, AgentState):
        return frozenset({target})
    return frozenset(target)


def _resolve_reason(
    predicate: Callable[[Agent], bool],
    agent: Agent,
) -> WaitReason | None:
    """Decide whether *agent* settles a waiter, and how (pure, loop-free).

    Returns :attr:`WaitReason.REACHED` when the predicate matches,
    :attr:`WaitReason.EXITED` when the agent is terminally gone and the predicate
    did not match (the target is now unreachable), or ``None`` to keep waiting.

    Examples
    --------
    >>> from libtmux.experimental.agents.state import Agent
    >>> running = Agent(pane_id="%1", key="%1", name=None,
    ...                 state=AgentState.RUNNING, since=0.0, source="option",
    ...                 pid=1, alive=True)
    >>> _resolve_reason(lambda a: a.state is AgentState.IDLE, running) is None
    True
    >>> exited = Agent(pane_id="%1", key="%1", name=None,
    ...                state=AgentState.EXITED, since=0.0, source="option",
    ...                pid=1, alive=False)
    >>> _resolve_reason(lambda a: a.state is AgentState.IDLE, exited)
    <WaitReason.EXITED: 'exited'>
    """
    if predicate(agent):
        return WaitReason.REACHED
    if agent.state is AgentState.EXITED:
        return WaitReason.EXITED
    return None


@dataclass
class _Waiter:
    """One parked wait: a settle predicate plus the future to resolve."""

    predicate: Callable[[Agent], bool]
    future: asyncio.Future[tuple[WaitReason, Agent | None]]


class WaiterRegistry:
    """Per-pane registry of parked waiters; the monitor drives :meth:`notify`.

    Pure coordination state (no tmux, no store): the monitor calls
    :meth:`notify` from its single ``_observe`` mutation point whenever a pane's
    agent changes, and every waiter whose predicate the new record settles is
    resolved. Keyed by pane id so a notification only scans that pane's waiters.

    Examples
    --------
    >>> import asyncio
    >>> from libtmux.experimental.agents.state import Agent
    >>> reg = WaiterRegistry()
    >>> async def main():
    ...     waiter = reg.register("%1", lambda a: a.state is AgentState.IDLE)
    ...     reg.notify(Agent(pane_id="%1", key="%1", name=None,
    ...                      state=AgentState.IDLE, since=0.0, source="option",
    ...                      pid=1, alive=True))
    ...     return await waiter.future
    >>> reason, agent = asyncio.run(main())
    >>> reason
    <WaitReason.REACHED: 'reached'>
    """

    def __init__(self) -> None:
        self._waiters: dict[str, list[_Waiter]] = {}

    def register(
        self,
        pane_id: str,
        predicate: Callable[[Agent], bool],
    ) -> _Waiter:
        """Park a waiter for *pane_id*; the future resolves on a matching notify.

        Must be called from within a running event loop (the future is bound to
        it). Returns the :class:`_Waiter` so the caller can :meth:`discard` it.
        """
        loop = asyncio.get_running_loop()
        waiter = _Waiter(predicate, loop.create_future())
        self._waiters.setdefault(pane_id, []).append(waiter)
        return waiter

    def notify(self, agent: Agent) -> None:
        """Resolve every waiter on *agent*'s pane that the record now settles."""
        waiters = self._waiters.get(agent.pane_id)
        if not waiters:
            return
        remaining: list[_Waiter] = []
        for waiter in waiters:
            if waiter.future.done():
                continue
            reason = _resolve_reason(waiter.predicate, agent)
            if reason is None:
                remaining.append(waiter)
            else:
                waiter.future.set_result((reason, agent))
        if remaining:
            self._waiters[agent.pane_id] = remaining
        else:
            self._waiters.pop(agent.pane_id, None)

    def discard(self, pane_id: str, waiter: _Waiter) -> None:
        """Forget *waiter* (called from the wait's ``finally``; no leak)."""
        waiters = self._waiters.get(pane_id)
        if not waiters:
            return
        kept = [existing for existing in waiters if existing is not waiter]
        if kept:
            self._waiters[pane_id] = kept
        else:
            self._waiters.pop(pane_id, None)

    def fail_all(self) -> None:
        """Resolve every parked waiter as :attr:`WaitReason.STOPPED` and clear.

        Called by :meth:`~..monitor.AgentMonitor.stop` so no wait hangs once the
        monitor that would wake it is gone.
        """
        for waiters in self._waiters.values():
            for waiter in waiters:
                if not waiter.future.done():
                    waiter.future.set_result((WaitReason.STOPPED, None))
        self._waiters.clear()


async def wait_for_agent_state(
    monitor: AgentMonitor,
    pane_id: str,
    target: AgentState | Collection[AgentState],
    *,
    timeout: float | None = None,
) -> AgentWait:
    """Block until *pane_id*'s agent reaches *target*; return the outcome as data.

    Adds **zero** tmux calls: a level check against the monitor's store returns
    immediately when the target (or a terminal EXITED) already holds, otherwise
    the call parks on a future the monitor's drain wakes.

    Parameters
    ----------
    monitor : AgentMonitor
        The running monitor whose store is the source of agent state.
    pane_id : str
        The pane to watch (e.g. ``"%1"``).
    target : AgentState or Collection[AgentState]
        The state(s) that satisfy the wait.
    timeout : float or None
        Seconds before giving up; ``None`` waits indefinitely.

    Returns
    -------
    AgentWait
        ``reason`` is ``REACHED``/``TIMEOUT``/``EXITED``/``STOPPED``.

    Examples
    --------
    A pane already in the target state returns immediately (no await on tmux):

    >>> import asyncio
    >>> from libtmux.experimental.agents.monitor import AgentMonitor
    >>> class _Fake:
    ...     async def run(self, request): ...
    ...     async def subscribe(self): ...
    ...     def add_subscription(self, spec): ...
    ...     def set_attach_targets(self, ids): ...
    >>> mon = AgentMonitor(_Fake())
    >>> mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : idle")
    >>> outcome = asyncio.run(
    ...     wait_for_agent_state(mon, "%1", AgentState.IDLE, timeout=1.0))
    >>> outcome.reason
    <WaitReason.REACHED: 'reached'>

    A pane that never reaches the target times out as data (no raise):

    >>> late = asyncio.run(
    ...     wait_for_agent_state(mon, "%1", AgentState.RUNNING, timeout=0.05))
    >>> late.reason
    <WaitReason.TIMEOUT: 'timeout'>
    """
    targets = _as_target_set(target)

    def predicate(agent: Agent) -> bool:
        return agent.state in targets

    current = monitor.agent_for(pane_id)
    if current is not None:
        if predicate(current):
            return AgentWait(pane_id, WaitReason.REACHED, current)
        if current.state is AgentState.EXITED:
            return AgentWait(pane_id, WaitReason.EXITED, current)

    waiter = monitor.waiters.register(pane_id, predicate)
    try:
        reason, settled = await asyncio.wait_for(waiter.future, timeout)
        return AgentWait(pane_id, reason, settled)
    except (asyncio.TimeoutError, TimeoutError):
        return AgentWait(pane_id, WaitReason.TIMEOUT, monitor.agent_for(pane_id))
    finally:
        monitor.waiters.discard(pane_id, waiter)


async def wait_for_agents(
    monitor: AgentMonitor,
    pane_ids: Collection[str],
    target: AgentState | Collection[AgentState],
    *,
    mode: t.Literal["all", "any"] = "all",
    timeout: float | None = None,
) -> list[AgentWait]:
    """Await many panes at once; return one :class:`AgentWait` per pane, in order.

    ``mode="all"`` resolves each pane independently (the list reports every
    pane's true outcome). ``mode="any"`` returns as soon as the first pane
    reaches *target*; panes that had not reached it by then are reported by a
    final level check (``REACHED``/``EXITED`` if they happen to satisfy it now,
    else ``TIMEOUT`` meaning "did not reach before the call returned").

    Examples
    --------
    >>> import asyncio
    >>> from libtmux.experimental.agents.monitor import AgentMonitor
    >>> class _Fake:
    ...     async def run(self, request): ...
    ...     async def subscribe(self): ...
    ...     def add_subscription(self, spec): ...
    ...     def set_attach_targets(self, ids): ...
    >>> mon = AgentMonitor(_Fake())
    >>> mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : idle")
    >>> mon.ingest("%subscription-changed agentstate $0 @0 2 %2 : idle")
    >>> outs = asyncio.run(
    ...     wait_for_agents(mon, ["%1", "%2"], AgentState.IDLE, timeout=1.0))
    >>> [o.reached for o in outs]
    [True, True]
    """
    panes = list(pane_ids)
    if not panes:
        return []
    if mode == "all":
        results = await asyncio.gather(
            *(
                wait_for_agent_state(monitor, pane, target, timeout=timeout)
                for pane in panes
            )
        )
        return list(results)

    # mode == "any": race the per-pane waits, settle on the first REACHED. Shrink
    # the pending set each round so a non-reached completion (EXITED) cannot
    # re-spin the loop on an already-done task.
    loop = asyncio.get_running_loop()
    deadline = None if timeout is None else loop.time() + timeout
    tasks = {
        pane: asyncio.ensure_future(
            wait_for_agent_state(monitor, pane, target, timeout=timeout)
        )
        for pane in panes
    }
    targets = _as_target_set(target)
    pending = set(tasks.values())
    reached = False
    try:
        while pending and not reached:
            remaining = None if deadline is None else max(0.0, deadline - loop.time())
            done, pending = await asyncio.wait(
                pending,
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                break  # deadline elapsed
            reached = any(task.result().reached for task in done)
    finally:
        for task in tasks.values():
            if not task.done():
                task.cancel()

    outcomes: list[AgentWait] = []
    for pane, task in tasks.items():
        if task.done() and not task.cancelled():
            outcomes.append(task.result())
            continue
        current = monitor.agent_for(pane)
        if current is not None and current.state in targets:
            outcomes.append(AgentWait(pane, WaitReason.REACHED, current))
        elif current is not None and current.state is AgentState.EXITED:
            outcomes.append(AgentWait(pane, WaitReason.EXITED, current))
        else:
            outcomes.append(AgentWait(pane, WaitReason.TIMEOUT, current))
    return outcomes
