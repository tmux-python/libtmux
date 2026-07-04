"""Unit tests for the drive verbs: lock, dedup, folding (no live tmux)."""

from __future__ import annotations

import asyncio

from libtmux.experimental.agents.drive import (
    DedupLedger,
    SendOutcome,
    pane_lock,
    send_to_agent,
    send_to_agents,
)
from libtmux.experimental.agents.monitor import AgentMonitor
from libtmux.experimental.agents.wait import WaitReason
from libtmux.experimental.engines.base import CommandRequest, CommandResult


class _RecordingEngine:
    """An async engine that records every dispatched request and succeeds."""

    def __init__(self) -> None:
        self.requests: list[CommandRequest] = []

    async def run(self, request: CommandRequest) -> CommandResult:
        self.requests.append(request)
        return CommandResult(cmd=request.args, returncode=0)


def _idle_monitor() -> tuple[AgentMonitor, _RecordingEngine]:
    engine = _RecordingEngine()
    monitor = AgentMonitor(engine)
    monitor.ingest("%subscription-changed agentstate $0 @0 1 %1 : idle")
    return monitor, engine


def test_pane_lock_is_shared_and_serializes() -> None:
    """Two senders on one pane never overlap; different panes do not block."""

    async def main() -> tuple[list[tuple[str, int]], bool]:
        order: list[tuple[str, int]] = []

        async def worker(n: int) -> None:
            async with pane_lock("%1"):
                order.append(("enter", n))
                await asyncio.sleep(0.02)
                order.append(("exit", n))

        await asyncio.gather(worker(1), worker(2))
        different = pane_lock("%9") is not pane_lock("%8")
        return order, different

    order, different = asyncio.run(main())
    # Each enter must be immediately followed by its own exit (no interleave).
    assert order[0][0] == "enter"
    assert order[1] == ("exit", order[0][1])
    assert order[2][0] == "enter"
    assert order[3] == ("exit", order[2][1])
    assert different is True


def test_dedup_ledger_ttl() -> None:
    """A key is live within the TTL and forgotten after it elapses."""
    clock = [0.0]
    ledger = DedupLedger(ttl=10.0, clock=lambda: clock[0])
    assert ledger.get("%1", "k") is None
    ledger.record("%1", "k", SendOutcome("%1", sent=True))
    assert ledger.get("%1", "k") is not None
    clock[0] = 20.0
    assert ledger.get("%1", "k") is None


def test_send_to_agent_folds_multiline_into_one_dispatch() -> None:
    """A multi-line prompt dispatches as a single folded set/paste/send call."""

    async def main() -> tuple[bool, int, CommandRequest]:
        monitor, engine = _idle_monitor()
        outcome = await send_to_agent(monitor, "%1", "line one\nline two")
        return outcome.sent, len(engine.requests), engine.requests[0]

    sent, dispatch_count, request = asyncio.run(main())
    assert sent is True
    assert dispatch_count == 1  # the whole multi-step send is one tmux call
    args = request.args
    assert "set-buffer" in args
    assert "paste-buffer" in args
    assert "send-keys" in args
    assert ";" in args  # the ops are chained into one invocation


def test_send_to_agent_skips_dispatch_when_not_ready() -> None:
    """A pane stuck RUNNING is not driven; no keystrokes are dispatched."""

    async def main() -> tuple[SendOutcome, int]:
        engine = _RecordingEngine()
        monitor = AgentMonitor(engine)
        monitor.ingest("%subscription-changed agentstate $0 @0 1 %1 : running")
        outcome = await send_to_agent(monitor, "%1", "go", timeout=0.05)
        return outcome, len(engine.requests)

    outcome, dispatch_count = asyncio.run(main())
    assert outcome.sent is False
    assert outcome.wait is not None
    assert outcome.wait.reason is WaitReason.TIMEOUT
    assert dispatch_count == 0


def test_send_to_agent_idempotency_key_is_a_no_op_on_retry() -> None:
    """A repeated send under the same key dispatches once and is flagged."""

    async def main() -> tuple[SendOutcome, SendOutcome, int]:
        monitor, engine = _idle_monitor()
        first = await send_to_agent(monitor, "%1", "hi", key="turn-1")
        second = await send_to_agent(monitor, "%1", "hi", key="turn-1")
        return first, second, len(engine.requests)

    first, second, dispatch_count = asyncio.run(main())
    assert first.sent is True
    assert first.deduplicated is False
    assert second.deduplicated is True
    assert dispatch_count == 1  # the retry did not re-send


def test_send_to_agents_folds_fleet_into_one_dispatch() -> None:
    """A broadcast to N ready panes dispatches as a single folded call."""

    async def main() -> tuple[list[bool], int]:
        engine = _RecordingEngine()
        monitor = AgentMonitor(engine)
        monitor.ingest("%subscription-changed agentstate $0 @0 1 %1 : idle")
        monitor.ingest("%subscription-changed agentstate $0 @0 2 %2 : idle")
        outs = await send_to_agents(monitor, ["%1", "%2"], "ping")
        return [o.sent for o in outs], len(engine.requests)

    sent, dispatch_count = asyncio.run(main())
    assert sent == [True, True]
    assert dispatch_count == 1  # both panes' sends folded into one tmux call
