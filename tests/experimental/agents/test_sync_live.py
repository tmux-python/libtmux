"""Live: wait_for_agent_state and send_to_agent against a real tmux server."""

from __future__ import annotations

import asyncio
import typing as t

if t.TYPE_CHECKING:
    from libtmux.session import Session

from libtmux.experimental.agents.drive import send_to_agent
from libtmux.experimental.agents.monitor import AgentMonitor
from libtmux.experimental.agents.state import AgentState
from libtmux.experimental.agents.wait import WaitReason, wait_for_agent_state
from libtmux.experimental.engines.async_control_mode import AsyncControlModeEngine


def test_wait_for_agent_state_resolves_on_real_option(session: Session) -> None:
    """A real @agent_state write wakes a parked wait (zero polling).

    Starts the monitor (self-attaches for the option channel), parks a wait for
    IDLE, then writes the option a beat later -- proving the wait resolves on the
    drain's ingest, not a fixed sleep.
    """

    async def main() -> WaitReason:
        engine = AsyncControlModeEngine.for_server(session.server)
        monitor = AgentMonitor(engine)
        await monitor.start()
        active = session.active_window.active_pane
        assert active is not None
        pane_id = active.pane_id
        assert pane_id is not None

        async def setter() -> None:
            await asyncio.sleep(0.2)
            session.cmd("set-option", "-p", "-t", pane_id, "@agent_state", "idle")

        task = asyncio.create_task(setter())
        outcome = await wait_for_agent_state(
            monitor, pane_id, AgentState.IDLE, timeout=6.0
        )
        await task
        await monitor.stop()
        await engine.aclose()
        return outcome.reason

    assert asyncio.run(main()) is WaitReason.REACHED


def test_send_to_agent_text_lands_in_pane(session: Session) -> None:
    """send_to_agent injects keystrokes that reach a real shell pane.

    Uses ``wait_ready=False`` because the pane runs a plain shell (no agent
    hook); the dispatched ``echo`` output must show up in a capture.
    """

    async def main() -> bool:
        engine = AsyncControlModeEngine.for_server(session.server)
        monitor = AgentMonitor(engine)
        await monitor.start()
        pane = session.active_window.active_pane
        assert pane is not None
        pane_id = pane.pane_id
        assert pane_id is not None

        marker = "libtmux_sync_marker_42"
        outcome = await send_to_agent(
            monitor, pane_id, f"echo {marker}", wait_ready=False
        )
        assert outcome.sent is True

        landed = False
        for _ in range(30):
            await asyncio.sleep(0.1)
            if any(marker in line for line in pane.capture_pane()):
                landed = True
                break
        await monitor.stop()
        await engine.aclose()
        return landed

    assert asyncio.run(main()) is True
