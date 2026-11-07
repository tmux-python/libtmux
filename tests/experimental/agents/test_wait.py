"""Unit tests for the wait synchronization verbs (no live tmux)."""

from __future__ import annotations

import asyncio

from libtmux.experimental.agents.monitor import AgentMonitor
from libtmux.experimental.agents.state import Agent, AgentState
from libtmux.experimental.agents.wait import (
    WaiterRegistry,
    WaitReason,
    _resolve_reason,
    wait_for_agent_state,
    wait_for_agents,
)


class _FakeEngine:
    async def run(self, request: object) -> None: ...

    async def subscribe(self) -> None: ...

    def add_subscription(self, spec: object) -> None: ...

    def set_attach_targets(self, ids: object) -> None: ...


def _agent(pane_id: str, state: AgentState) -> Agent:
    return Agent(
        pane_id=pane_id,
        key=pane_id,
        name="claude",
        state=state,
        since=0.0,
        source="option",
        pid=1,
        alive=state is not AgentState.EXITED,
    )


def test_resolve_reason_matches_predicate() -> None:
    """A satisfying record reaches; a terminal EXITED ends an unmet wait."""
    running = _agent("%1", AgentState.RUNNING)
    exited = _agent("%1", AgentState.EXITED)
    want_idle = lambda a: a.state is AgentState.IDLE  # noqa: E731
    assert _resolve_reason(want_idle, running) is None
    assert _resolve_reason(want_idle, exited) is WaitReason.EXITED
    assert _resolve_reason(lambda a: a.state is AgentState.RUNNING, running) is (
        WaitReason.REACHED
    )


def test_registry_notify_resolves_only_matching_waiters() -> None:
    """Notify resolves matching waiters and leaves the rest parked."""

    async def main() -> tuple[bool, bool]:
        reg = WaiterRegistry()
        idle = reg.register("%1", lambda a: a.state is AgentState.IDLE)
        running = reg.register("%1", lambda a: a.state is AgentState.RUNNING)
        reg.notify(_agent("%1", AgentState.IDLE))
        return idle.future.done(), running.future.done()

    idle_done, running_done = asyncio.run(main())
    assert idle_done is True
    assert running_done is False


def test_wait_returns_immediately_when_already_in_state() -> None:
    """A level check short-circuits with zero awaits when the target holds."""

    async def main() -> WaitReason:
        mon = AgentMonitor(_FakeEngine())
        mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : idle")
        return (
            await wait_for_agent_state(mon, "%1", AgentState.IDLE, timeout=1.0)
        ).reason

    assert asyncio.run(main()) is WaitReason.REACHED


def test_wait_can_target_done_state() -> None:
    """DONE is a first-class target for turn-complete fan-in waits."""

    async def main() -> WaitReason:
        mon = AgentMonitor(_FakeEngine())
        mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : done")
        return (
            await wait_for_agent_state(mon, "%1", AgentState.DONE, timeout=1.0)
        ).reason

    assert asyncio.run(main()) is WaitReason.REACHED


def test_wait_wakes_on_later_ingest() -> None:
    """A parked wait resolves the moment the drain ingests the target state."""

    async def main() -> WaitReason:
        mon = AgentMonitor(_FakeEngine())

        async def trigger() -> None:
            await asyncio.sleep(0.05)
            mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : idle")

        task = asyncio.create_task(trigger())
        outcome = await wait_for_agent_state(mon, "%1", AgentState.IDLE, timeout=2.0)
        await task
        return outcome.reason

    assert asyncio.run(main()) is WaitReason.REACHED


def test_wait_resolves_exited_when_agent_dies_first() -> None:
    """A pane that reaches EXITED ends a wait for a live state with EXITED."""

    async def main() -> WaitReason:
        mon = AgentMonitor(_FakeEngine())

        async def trigger() -> None:
            await asyncio.sleep(0.05)
            mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : exited")

        task = asyncio.create_task(trigger())
        outcome = await wait_for_agent_state(mon, "%1", AgentState.IDLE, timeout=2.0)
        await task
        return outcome.reason

    assert asyncio.run(main()) is WaitReason.EXITED


def test_wait_times_out_as_data() -> None:
    """A target that never arrives returns TIMEOUT, never raises."""

    async def main() -> WaitReason:
        mon = AgentMonitor(_FakeEngine())
        mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : running")
        return (
            await wait_for_agent_state(mon, "%1", AgentState.IDLE, timeout=0.05)
        ).reason

    assert asyncio.run(main()) is WaitReason.TIMEOUT


def test_stop_resolves_parked_wait_as_stopped() -> None:
    """monitor.stop() resolves parked waits as STOPPED so they never hang."""

    async def main() -> WaitReason:
        mon = AgentMonitor(_FakeEngine())

        async def stopper() -> None:
            await asyncio.sleep(0.05)
            await mon.stop()

        task = asyncio.create_task(stopper())
        outcome = await wait_for_agent_state(mon, "%1", AgentState.IDLE, timeout=5.0)
        await task
        return outcome.reason

    assert asyncio.run(main()) is WaitReason.STOPPED


def test_wait_for_agents_all() -> None:
    """mode='all' reports one outcome per pane, each resolved independently."""

    async def main() -> list[bool]:
        mon = AgentMonitor(_FakeEngine())
        mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : idle")
        mon.ingest("%subscription-changed agentstate $0 @0 2 %2 : idle")
        outs = await wait_for_agents(mon, ["%1", "%2"], AgentState.IDLE, timeout=1.0)
        return [o.reached for o in outs]

    assert asyncio.run(main()) == [True, True]


def test_wait_for_agents_any_returns_on_first() -> None:
    """mode='any' returns once one pane reaches; the laggard is not reached."""

    async def main() -> list[bool]:
        mon = AgentMonitor(_FakeEngine())
        mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : idle")
        mon.ingest("%subscription-changed agentstate $0 @0 2 %2 : running")
        outs = await wait_for_agents(
            mon, ["%1", "%2"], AgentState.IDLE, mode="any", timeout=0.3
        )
        return [o.reached for o in outs]

    assert asyncio.run(main()) == [True, False]
