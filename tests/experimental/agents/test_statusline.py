"""Tests for the agent status-line writer (render the fleet in one set-option).

The renderer is pure; ``paint_status_line`` reads agent state from the store
(zero tmux calls) and writes the summary with exactly ONE ``set-option``.
"""

from __future__ import annotations

import asyncio
import typing as t

from libtmux.experimental.agents.state import Agent, AgentState
from libtmux.experimental.agents.statusline import (
    paint_status_line,
    render_status_line,
    status_line_op,
)
from libtmux.experimental.engines import AsyncConcreteEngine
from libtmux.experimental.engines.base import CommandResult
from libtmux.experimental.ops._types import SessionId

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.experimental.engines.base import CommandRequest
    from libtmux.session import Session


def _agent(pane_id: str, state: AgentState, *, name: str | None = None) -> Agent:
    """Build a synthetic Agent record."""
    return Agent(
        pane_id=pane_id,
        key=pane_id,
        name=name,
        state=state,
        since=0.0,
        source="option",
        pid=None,
        alive=True,
    )


class _Recorder:
    """An async engine that records the argv of every dispatch (acks success)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def run(self, request: CommandRequest) -> CommandResult:
        """Record the argv and ack."""
        self.calls.append(tuple(request.args))
        return CommandResult(cmd=("tmux", *request.args), returncode=0)

    async def run_batch(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Run each request in order (satisfies the AsyncTmuxEngine protocol)."""
        return [await self.run(request) for request in requests]


def test_render_tally_in_attention_order() -> None:
    """The default renderer tallies non-zero states, most-urgent first."""
    rows = [
        _agent("%1", AgentState.AWAITING_INPUT),
        _agent("%2", AgentState.RUNNING),
        _agent("%3", AgentState.RUNNING),
        _agent("%4", AgentState.IDLE),
    ]
    assert render_status_line(rows) == "wait:1 idle:1 run:2"


def test_render_empty_fleet() -> None:
    """No agents renders an empty string (nothing to show)."""
    assert render_status_line([]) == ""


def test_render_custom_labels() -> None:
    """A caller-supplied label map overrides the default look."""
    rows = [_agent("%1", AgentState.RUNNING), _agent("%2", AgentState.RUNNING)]
    assert render_status_line(rows, labels={AgentState.RUNNING: "R"}) == "R:2"


def test_status_line_op_is_a_global_set_option() -> None:
    """The op builder renders a single set-option for status-right."""
    op = status_line_op("wait:1", global_=True)
    assert op.render() == ("set-option", "-g", "status-right", "wait:1")


def test_paint_reads_store_then_writes_once() -> None:
    """Paint reads agents from the monitor (0 calls) and writes ONE set-option."""
    from libtmux.experimental.agents.monitor import AgentMonitor

    mon = AgentMonitor(AsyncConcreteEngine())
    mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : awaiting_input")
    rec = _Recorder()
    ok = asyncio.run(paint_status_line(rec, mon, global_=True))
    assert ok
    assert rec.calls == [("set-option", "-g", "status-right", "wait:1")]


def test_paint_status_line_lands_live(session: Session) -> None:
    """Paint writes a real status-right that reads back from live tmux."""
    from libtmux.experimental.engines.async_control_mode import AsyncControlModeEngine

    rows = [_agent("%1", AgentState.AWAITING_INPUT)]
    sid = session.session_id
    assert sid is not None

    async def main() -> None:
        engine = AsyncControlModeEngine.for_server(session.server)
        try:
            await paint_status_line(engine, rows, target=SessionId(sid))
        finally:
            await engine.aclose()

    asyncio.run(main())
    value = session.cmd("show-options", "-v", "status-right").stdout
    assert value == ["wait:1"]
