"""Live: a real @agent_state write becomes observable through the monitor."""

from __future__ import annotations

import asyncio
import typing as t

if t.TYPE_CHECKING:
    from libtmux.session import Session

from libtmux.experimental.agents.monitor import AgentMonitor
from libtmux.experimental.agents.state import AgentState
from libtmux.experimental.engines.async_control_mode import AsyncControlModeEngine


def test_monitor_observes_running(session: Session) -> None:
    """@agent_state option set on a real pane is observed within 3s.

    Starts the monitor — which self-attaches a session, the prerequisite for
    tmux to deliver per-pane ``%subscription-changed`` (without an attached
    control client only server-global events arrive) — then writes
    ``@agent_state running`` to the active pane's option (simulating what an
    agent hook would do) and polls up to 3s for the monitor to surface the
    update.  No manual ``attach-session`` here: this proves
    :meth:`AgentMonitor.start` attaches on its own.  Exercises the full
    subscribe→ingest→store pipeline against a real tmux server.
    """

    async def main() -> str:
        engine = AsyncControlModeEngine.for_server(session.server)
        monitor = AgentMonitor(engine)
        await monitor.start()
        # start() must have self-attached a session for the option channel.
        assert engine._attached_session is not None
        active_pane = session.active_window.active_pane
        assert active_pane is not None
        pane_id = active_pane.pane_id
        assert pane_id is not None
        # the agent hook's effect, simulated:
        session.cmd("set-option", "-p", "-t", pane_id, "@agent_state", "running")
        # tmux's subscription timer is ~1 s; poll up to 3 s
        match = None
        for _ in range(30):
            await asyncio.sleep(0.1)
            match = {a.pane_id: a for a in monitor.agents}.get(pane_id)
            if match is not None and match.state.value == "running":
                break
        await monitor.stop()
        return match.state.value if match else "missing"

    assert asyncio.run(main()) == "running"


def test_reconcile_parses_live_panes(session: Session) -> None:
    """reconcile() parses real list-panes -F output and tracks pane lifecycle.

    Verifies three things:

    1. ``_parse_pane_rows`` actually produces rows from real ``list-panes``
       output (not silently empty due to a field-separator or column-order
       mismatch).
    2. A newly-created pane appears in the monitor's internal pane map after
       a second reconcile.
    3. A killed pane that was previously observed (state in the store) is
       marked ``EXITED`` after the next reconcile — proving the ``Vanished``
       path works end to end.
    """

    async def main() -> None:
        async with AsyncControlModeEngine.for_server(session.server) as engine:
            monitor = AgentMonitor(engine)

            # First reconcile: seeds _prev_panes from live tmux output.
            await monitor.reconcile()

            # Prove _parse_pane_rows returned real rows (field sep / column order OK).
            assert len(monitor._prev_panes) > 0, (
                "_parse_pane_rows returned empty — field separator mismatch "
                "or list-panes produced no rows"
            )

            # Create a fresh window (and its default first pane).
            new_window = session.new_window(window_name="reconcile-test")
            new_pane = new_window.active_pane
            assert new_pane is not None
            new_pane_id = new_pane.pane_id
            assert new_pane_id is not None

            # Manually observe the new pane so it lands in the store — Vanished
            # only transitions panes that are already tracked.
            monitor.ingest(
                f"%subscription-changed agentstate $0 @0 1 {new_pane_id} : running"
            )
            by_pane = {a.pane_id: a for a in monitor.agents}
            assert by_pane[new_pane_id].state is AgentState.RUNNING

            # Reconcile again: new pane should appear in _prev_panes.
            await monitor.reconcile()
            assert new_pane_id in monitor._prev_panes, (
                "new pane not detected by reconcile after creation — "
                "_parse_pane_rows may be silently skipping rows"
            )

            # Kill the pane, then reconcile.  The pane was tracked, so the
            # Vanished event should transition it to EXITED in the store.
            session.cmd("kill-pane", "-t", new_pane_id)
            await monitor.reconcile()

            by_pane = {a.pane_id: a for a in monitor.agents}
            assert new_pane_id in by_pane, (
                "pane disappeared from store entirely — expected EXITED entry"
            )
            assert by_pane[new_pane_id].state is AgentState.EXITED, (
                f"expected EXITED after kill-pane, got {by_pane[new_pane_id].state}"
            )

    asyncio.run(main())
