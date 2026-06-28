"""Tests for the floating agent HUD (renderer + monitor lifecycle)."""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.experimental.agents.hud import HudRenderer
from libtmux.experimental.agents.monitor import AgentMonitor
from libtmux.experimental.agents.state import Agent, AgentState
from libtmux.experimental.agents.store import AgentStore

if t.TYPE_CHECKING:
    from libtmux.experimental.engines.base import CommandRequest


def _agent(pane_id: str, *, state: AgentState, alive: bool, name: str) -> Agent:
    return Agent(
        pane_id=pane_id,
        key=pane_id,
        name=name,
        state=state,
        since=0.0,
        source="osc",
        pid=1,
        alive=alive,
    )


def test_render_empty_store() -> None:
    """An empty store renders the header and a placeholder."""
    frame = HudRenderer().render(AgentStore())
    assert frame.startswith("agents")
    assert "(no agents)" in frame


def test_render_lists_agents() -> None:
    """Each agent renders with its state, pane id, name, and a liveness glyph."""
    store = AgentStore(
        agents={
            "%1": _agent("%1", state=AgentState.RUNNING, alive=True, name="claude"),
            "%2": _agent("%2", state=AgentState.EXITED, alive=False, name="codex"),
        },
    )
    frame = HudRenderer().render(store)
    assert "running" in frame
    assert "%1" in frame
    assert "claude" in frame
    assert "●" in frame  # alive glyph
    assert "○" in frame  # dead glyph (the exited agent)


def test_repaint_op_targets_pane() -> None:
    """repaint_op builds a respawn-pane op carrying the rendered frame."""
    store = AgentStore(
        agents={"%1": _agent("%1", state=AgentState.IDLE, alive=True, name="claude")},
    )
    op = HudRenderer().repaint_op("%9", store)
    assert op.command == "respawn-pane"
    assert op.kill is True
    assert op.render()[:3] == ("respawn-pane", "-t", "%9")
    assert "claude" in (op.shell or "")  # the rendered frame is embedded


class _HudEngine:
    """A minimal async engine that satisfies the HUD lifecycle calls."""

    def __init__(
        self,
        pane_rows: tuple[str, ...] = (),
        *,
        respawn_returncode: int = 0,
    ) -> None:
        self._pane_rows = pane_rows
        self._respawn_returncode = respawn_returncode
        self.killed: list[str] = []

    async def run(self, request: CommandRequest) -> t.Any:
        from libtmux.experimental.engines.base import CommandResult

        cmd = request.args[0]
        if cmd == "display-message":
            return CommandResult(cmd=request.args, stdout=("$0",))
        if cmd == "list-sessions":
            return CommandResult(cmd=request.args, stdout=("$0", "$1"))
        if cmd == "list-panes":
            return CommandResult(cmd=request.args, stdout=self._pane_rows)
        if cmd == "new-pane":
            return CommandResult(cmd=request.args, stdout=("%99",))
        if cmd == "respawn-pane":
            return CommandResult(
                cmd=request.args,
                stderr=() if self._respawn_returncode == 0 else ("no such pane",),
                returncode=self._respawn_returncode,
            )
        if cmd == "kill-pane":
            self.killed.append(request.args[-1])
            return CommandResult(cmd=request.args, returncode=0)
        return CommandResult(cmd=request.args, returncode=0)


def test_ensure_and_teardown_hud() -> None:
    """The monitor creates a floating HUD pane and kills it on teardown."""
    engine = _HudEngine()
    monitor = AgentMonitor(engine, hud=True)

    async def go() -> tuple[str | None, str | None]:
        await monitor._ensure_hud()
        created = monitor._hud_pane_id
        await monitor._teardown_hud()
        return created, monitor._hud_pane_id

    created, after = asyncio.run(go())
    assert created == "%99"
    assert after is None
    assert "%99" in engine.killed


def _pane_row(pane_id: str) -> str:
    """Return a tab-joined list-panes row with *pane_id* in its slot."""
    return "\t".join(
        ["$0", "s", "@0", "0", "w", "1", pane_id, "0", "1", "0", "", "", ""],
    )


def test_reconcile_excludes_hud_pane() -> None:
    """The HUD's own pane is kept out of the tracked pane set."""
    engine = _HudEngine(pane_rows=(_pane_row("%1"), _pane_row("%99")))
    monitor = AgentMonitor(engine)
    monitor._hud_pane_id = "%99"

    asyncio.run(monitor._reconcile_once())

    assert "%1" in monitor._prev_panes
    assert "%99" not in monitor._prev_panes


class _RepaintCase(t.NamedTuple):
    """A HUD repaint outcome and whether the pane id should survive it."""

    test_id: str
    repaint_ok: bool
    expect_pane_kept: bool


_REPAINT_CASES = (
    _RepaintCase("ok_keeps_pane", repaint_ok=True, expect_pane_kept=True),
    _RepaintCase("fail_drops_pane", repaint_ok=False, expect_pane_kept=False),
)


@pytest.mark.parametrize(
    list(_RepaintCase._fields),
    _REPAINT_CASES,
    ids=[c.test_id for c in _REPAINT_CASES],
)
def test_repaint_drops_dead_pane(
    test_id: str,
    repaint_ok: bool,
    expect_pane_kept: bool,
) -> None:
    """A failed repaint drops _hud_pane_id so _run recreates the HUD."""
    engine = _HudEngine(respawn_returncode=0 if repaint_ok else 1)
    monitor = AgentMonitor(engine, hud=True)

    async def go() -> str | None:
        await monitor._ensure_hud()
        assert monitor._hud_pane_id == "%99"
        monitor._hud_dirty = True  # force a repaint
        await monitor._repaint_hud()
        return monitor._hud_pane_id

    pane_after = asyncio.run(go())
    assert (pane_after == "%99") is expect_pane_kept
    assert (pane_after is None) is not expect_pane_kept
