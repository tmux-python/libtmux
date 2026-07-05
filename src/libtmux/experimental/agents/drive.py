"""Drive an agent safely: readiness-gated, atomically locked, folded to one call.

:func:`send_to_agent` is the action half of the synchronization layer. It
optionally waits until the agent is ready (reusing
:func:`~libtmux.experimental.agents.wait.wait_for_agent_state`, zero tmux calls),
then injects the prompt **atomically** under a per-pane logical lock so two
concurrent drivers cannot interleave keystrokes, and **folds the whole send into
a single tmux dispatch** via the lazy/chainable plan + the
:class:`~libtmux.experimental.ops.planner.FoldingPlanner` -- a multi-line prompt
collapses to one ``set-buffer ; paste-buffer ; send-keys`` invocation, and a
fleet broadcast (:func:`send_to_agents`) folds N panes' sends into one call.

The per-pane lock (:func:`pane_lock`) is a process-wide chokepoint: both these
verbs *and* the MCP ``asend_input`` tool acquire it, so all async keystroke
injection on a pane serializes through one place. The engine's byte-level
``_write_lock`` is untouched -- it guards pipe writes; this lock guards the whole
logical send one layer up.
"""

from __future__ import annotations

import contextlib
import dataclasses
import time
import typing as t
import weakref
from dataclasses import dataclass, field

from libtmux.experimental.agents.state import AgentState
from libtmux.experimental.agents.wait import (
    AgentWait,
    wait_for_agent_state,
    wait_for_agents,
)
from libtmux.experimental.ops import PasteBuffer, SendKeys, SetBuffer
from libtmux.experimental.ops._types import PaneId
from libtmux.experimental.ops.plan import LazyPlan
from libtmux.experimental.ops.planner import FoldingPlanner

if t.TYPE_CHECKING:
    import asyncio
    from collections.abc import Callable, Collection

    from libtmux.experimental.agents.monitor import AgentMonitor

#: Default states an agent is considered "ready to receive a prompt" in.
READY_STATES: tuple[AgentState, ...] = (
    AgentState.AWAITING_INPUT,
    AgentState.DONE,
    AgentState.IDLE,
)

# Process-wide per-pane logical drive locks (the comprehensive chokepoint). Held
# weakly: a lock survives exactly as long as a sender references it (inside an
# ``async with``), so concurrent holders always share one object and an idle
# pane's lock is collected.
_LOCKS: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()


def pane_lock(pane_id: str) -> asyncio.Lock:
    """Return the shared per-pane logical drive lock for *pane_id*.

    Examples
    --------
    >>> import asyncio
    >>> async def main():
    ...     return pane_lock("%1") is pane_lock("%1")
    >>> asyncio.run(main())
    True
    """
    import asyncio

    lock = _LOCKS.get(pane_id)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[pane_id] = lock
    return lock


@dataclass(frozen=True)
class SendOutcome:
    """The result of a :func:`send_to_agent`, as data.

    Examples
    --------
    >>> SendOutcome(pane_id="%1", sent=True).sent
    True
    """

    pane_id: str
    sent: bool
    wait: AgentWait | None = None
    deduplicated: bool = False


@dataclass
class DedupLedger:
    """Short-TTL record of ``(pane, key)`` sends so a retry is a safe no-op.

    Examples
    --------
    >>> clock = [0.0]
    >>> ledger = DedupLedger(ttl=10.0, clock=lambda: clock[0])
    >>> ledger.get("%1", "turn-1") is None
    True
    >>> ledger.record("%1", "turn-1", SendOutcome("%1", sent=True))
    >>> ledger.get("%1", "turn-1").sent
    True
    >>> clock[0] = 20.0  # past the TTL
    >>> ledger.get("%1", "turn-1") is None
    True
    """

    ttl: float = 30.0
    clock: Callable[[], float] = time.monotonic
    _entries: dict[tuple[str, str], tuple[float, SendOutcome]] = field(
        default_factory=dict,
    )

    def get(self, pane_id: str, key: str) -> SendOutcome | None:
        """Return the live outcome for ``(pane_id, key)``, or ``None`` if expired."""
        entry = self._entries.get((pane_id, key))
        if entry is None:
            return None
        deadline, outcome = entry
        if self.clock() >= deadline:
            del self._entries[(pane_id, key)]
            return None
        return outcome

    def record(self, pane_id: str, key: str, outcome: SendOutcome) -> None:
        """Remember *outcome* for ``(pane_id, key)`` until ``ttl`` elapses."""
        self._entries[(pane_id, key)] = (self.clock() + self.ttl, outcome)


def _buffer_name(pane_id: str) -> str:
    """Return a per-pane paste-buffer name (concurrent fleet sends never collide)."""
    slug = "".join(char if char.isalnum() else "-" for char in pane_id)
    return f"libtmux-send-{slug}"


def _add_send(plan: LazyPlan, pane_id: str, text: str, *, enter: bool) -> None:
    """Record one agent send into *plan* (multi-line via a folded paste).

    Single-line text is one ``send-keys``; multi-line text is
    ``set-buffer ; paste-buffer -p ; send-keys Enter`` -- all chainable, so a
    :class:`~..ops.planner.FoldingPlanner` collapses each send to one dispatch.
    """
    target = PaneId(pane_id)
    if "\n" in text:
        name = _buffer_name(pane_id)
        plan.add(SetBuffer(data=text, buffer_name=name))
        plan.add(
            PasteBuffer(target=target, buffer_name=name, delete=True, bracket=True),
        )
        if enter:
            plan.add(SendKeys(target=target, keys="Enter"))
    else:
        plan.add(SendKeys(target=target, keys=text, enter=enter))


async def send_to_agent(
    monitor: AgentMonitor,
    pane_id: str,
    text: str,
    *,
    wait_ready: bool = True,
    ready_states: Collection[AgentState] = READY_STATES,
    enter: bool = True,
    key: str | None = None,
    timeout: float | None = None,
) -> SendOutcome:
    """Wait until *pane_id*'s agent is ready, then inject *text* in one dispatch.

    Steps: (1) if *wait_ready*, await the agent reaching one of *ready_states*
    (zero tmux calls); a non-ready outcome returns ``sent=False`` with no
    dispatch. (2) Acquire the per-pane :func:`pane_lock` so the whole send is
    atomic. (3) If *key* names an already-delivered send within the dedup TTL,
    return that no-op. (4) Fold the send to a single tmux call and dispatch it.

    Returns
    -------
    SendOutcome
        ``sent`` is whether the keystrokes were dispatched successfully.

    Examples
    --------
    >>> import asyncio
    >>> from libtmux.experimental.engines import AsyncMockEngine
    >>> from libtmux.experimental.agents.monitor import AgentMonitor
    >>> mon = AgentMonitor(AsyncMockEngine())
    >>> mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : idle")
    >>> outcome = asyncio.run(send_to_agent(mon, "%1", "echo hi"))
    >>> outcome.sent
    True
    """
    wait_result: AgentWait | None = None
    if wait_ready:
        wait_result = await wait_for_agent_state(
            monitor, pane_id, frozenset(ready_states), timeout=timeout
        )
        if not wait_result.reached:
            return SendOutcome(pane_id, sent=False, wait=wait_result)

    async with pane_lock(pane_id):
        if key is not None:
            prior = monitor.dedup.get(pane_id, key)
            if prior is not None:
                return dataclasses.replace(prior, wait=wait_result, deduplicated=True)
        plan = LazyPlan()
        _add_send(plan, pane_id, text, enter=enter)
        result = await plan.aexecute(monitor.engine, planner=FoldingPlanner())
        outcome = SendOutcome(pane_id, sent=result.ok, wait=wait_result)
        if key is not None:
            monitor.dedup.record(pane_id, key, outcome)
        return outcome


async def send_to_agents(
    monitor: AgentMonitor,
    pane_ids: Collection[str],
    text: str,
    *,
    wait_ready: bool = True,
    ready_states: Collection[AgentState] = READY_STATES,
    enter: bool = True,
    timeout: float | None = None,
) -> list[SendOutcome]:
    """Broadcast *text* to many agents, folding every ready send into ONE dispatch.

    Waits for all panes' readiness (``mode="all"``), then acquires each ready
    pane's lock in **sorted pane-id order** (deadlock-free against a concurrent
    fleet send) and dispatches every ready pane's send as a single folded tmux
    call. Returns one :class:`SendOutcome` per input pane, in order.

    Examples
    --------
    >>> import asyncio
    >>> from libtmux.experimental.engines import AsyncMockEngine
    >>> from libtmux.experimental.agents.monitor import AgentMonitor
    >>> mon = AgentMonitor(AsyncMockEngine())
    >>> mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : idle")
    >>> mon.ingest("%subscription-changed agentstate $0 @0 2 %2 : idle")
    >>> outs = asyncio.run(send_to_agents(mon, ["%1", "%2"], "echo hi"))
    >>> [o.sent for o in outs]
    [True, True]
    """
    panes = list(pane_ids)
    waits: dict[str, AgentWait] = {}
    if wait_ready:
        for outcome in await wait_for_agents(
            monitor, panes, frozenset(ready_states), mode="all", timeout=timeout
        ):
            waits[outcome.pane_id] = outcome

    outcomes: dict[str, SendOutcome] = {}
    ready: list[str] = []
    for pane in panes:
        if wait_ready and not waits[pane].reached:
            outcomes[pane] = SendOutcome(pane, sent=False, wait=waits.get(pane))
        elif pane not in ready:
            ready.append(pane)

    async with contextlib.AsyncExitStack() as stack:
        for pane in sorted(ready):
            await stack.enter_async_context(pane_lock(pane))
        ok = True
        if ready:
            plan = LazyPlan()
            for pane in ready:
                _add_send(plan, pane, text, enter=enter)
            ok = (await plan.aexecute(monitor.engine, planner=FoldingPlanner())).ok
        for pane in ready:
            outcomes[pane] = SendOutcome(pane, sent=ok, wait=waits.get(pane))

    return [outcomes[pane] for pane in panes]
