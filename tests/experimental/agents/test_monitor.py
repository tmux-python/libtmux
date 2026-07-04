"""Unit tests for AgentMonitor.ingest (no live tmux)."""

from __future__ import annotations

import asyncio
import os

from libtmux.experimental.agents.monitor import AgentMonitor
from libtmux.experimental.agents.state import AgentState
from libtmux.experimental.agents.store import AgentStore
from libtmux.experimental.agents.tree import PANE_FORMAT
from libtmux.experimental.engines.base import CommandRequest, CommandResult
from libtmux.experimental.models.snapshots import PaneSnapshot


class _FakeEngine:
    async def run(self, request: object) -> None: ...

    async def subscribe(self) -> None: ...

    def add_subscription(self, spec: object) -> None: ...

    def set_attach_targets(self, ids: object) -> None: ...


class _ProbeFailEngine:
    """An engine whose own-id (``display-message``) probe raises.

    ``list-sessions`` still succeeds and reports two sessions, so the only
    reason ``_primary_session_id`` could return ``None`` is the failing
    own-session probe (the case under test).
    """

    async def run(self, request: CommandRequest) -> CommandResult:
        if request.args[:1] == ("display-message",):
            msg = "display-message failed"
            raise RuntimeError(msg)
        return CommandResult(cmd=request.args, stdout=("$0", "$1"))

    async def subscribe(self) -> None: ...

    def add_subscription(self, spec: object) -> None: ...

    def set_attach_targets(self, ids: object) -> None: ...


class _PaneRowsEngine:
    def __init__(self, rows: tuple[str, ...]) -> None:
        self.rows = rows

    async def run(self, request: CommandRequest) -> CommandResult:
        if request.args[:1] == ("list-panes",):
            return CommandResult(cmd=request.args, stdout=self.rows)
        return CommandResult(cmd=request.args, stdout=("$0",))

    async def subscribe(self) -> None: ...

    def add_subscription(self, spec: object) -> None: ...

    def set_attach_targets(self, ids: object) -> None: ...


class _MemorySink:
    def __init__(self) -> None:
        self.data: dict[str, object] | None = None

    def load(self) -> dict[str, object] | None:
        return self.data

    def save(self, data: dict[str, object]) -> None:
        self.data = data


def _pane_row(**values: str) -> str:
    """Build one tab-separated pane row in the monitor's requested field order."""
    fields = {
        "session_id": "$0",
        "session_name": "agents",
        "window_id": "@0",
        "window_index": "0",
        "window_name": "agents",
        "window_active": "1",
        "pane_id": "%1",
        "pane_index": "0",
        "pane_active": "1",
        "pane_floating_flag": "0",
        "pane_pid": str(os.getpid()),
        "pane_current_command": "claude",
        "pane_title": "",
        "@agent_state": "",
        "@agent_name": "",
    }
    fields.update(values)
    return "\t".join(fields.get(field, "") for field in PANE_FORMAT)


def test_primary_session_id_none_when_own_probe_fails() -> None:
    """A failing own-session probe skips attach (no phantom binding).

    Without the phantom's id, ``list-sessions[0]`` is tmux's own throwaway
    ``tmux -C`` session, so the monitor must decline to attach rather than
    bind to a session that holds no agent panes.
    """

    async def main() -> str | None:
        mon = AgentMonitor(_ProbeFailEngine())
        return await mon._primary_session_id()

    assert asyncio.run(main()) is None


def test_reconcile_seeds_existing_agent_state_option() -> None:
    """A pane option present before subscribe still becomes an agent record."""

    async def main() -> dict[str, str | None]:
        mon = AgentMonitor(
            _PaneRowsEngine(
                (
                    _pane_row(
                        pane_id="%7",
                        pane_current_command="claude",
                        **{"@agent_state": "running", "@agent_name": "claude"},
                    ),
                )
            )
        )
        await mon.reconcile()
        agent = {a.pane_id: a for a in mon.agents}["%7"]
        return {
            "state": agent.state.value,
            "name": agent.name,
            "source": agent.source,
        }

    assert asyncio.run(main()) == {
        "state": "running",
        "name": "claude",
        "source": "option",
    }


def test_ingest_option_line_updates_agent() -> None:
    """Option-channel %subscription-changed maps to a store entry."""
    mon = AgentMonitor(_FakeEngine())
    mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : running")
    by_pane = {a.pane_id: a for a in mon.agents}
    assert by_pane["%1"].state is AgentState.RUNNING


def test_ingest_persists_snapshot_immediately() -> None:
    """The monitor sink is current while the monitor is still running."""
    sink = _MemorySink()
    mon = AgentMonitor(_FakeEngine(), sink=sink)

    mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : running")

    data = sink.data
    assert data is not None
    assert AgentStore.from_dict(data).agents["%1"].state is AgentState.RUNNING


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


def _pane(pane_id: str, pid: int | None) -> PaneSnapshot:
    """Build a minimal PaneSnapshot carrying just the pane id and pid."""
    return PaneSnapshot(pane_id=pane_id, pid=pid)


def test_apply_health_marks_dead_local_pane_exited() -> None:
    """A local pane (pid set) whose process is dead is marked EXITED."""
    mon = AgentMonitor(_FakeEngine())
    mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : running")
    # 0x7FFFFFFE is almost certainly not a live process (see test_health).
    mon._apply_health({"%1": _pane("%1", 2_147_483_646)})
    agent = {a.pane_id: a for a in mon.agents}["%1"]
    assert agent.state is AgentState.EXITED
    assert agent.alive is False
    assert agent.pid == 2_147_483_646


def test_apply_health_refreshes_live_local_pane() -> None:
    """A local pane with a live pid keeps its state; pid/alive are refreshed."""
    mon = AgentMonitor(_FakeEngine())
    mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : running")
    mon._apply_health({"%1": _pane("%1", os.getpid())})
    agent = {a.pane_id: a for a in mon.agents}["%1"]
    assert agent.state is AgentState.RUNNING
    assert agent.alive is True
    assert agent.pid == os.getpid()


def test_apply_health_never_exits_pidless_remote_pane() -> None:
    """A PID-less (remote) pane is never auto-EXITED by the health sweep (D5)."""
    mon = AgentMonitor(_FakeEngine())
    mon.ingest("%output %2 \033]3008;state=running\033\\")
    mon._apply_health({"%2": _pane("%2", None)})
    agent = {a.pane_id: a for a in mon.agents}["%2"]
    assert agent.state is AgentState.RUNNING
    assert agent.alive is True
