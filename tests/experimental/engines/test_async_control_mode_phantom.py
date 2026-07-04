"""Live: a control-mode connection reaps its own throwaway (phantom) session.

A bare ``tmux -C`` implies ``new-session``, so each connect spawns a phantom
session on the *target* server. The engine sets ``destroy-unattached on`` on that
phantom so tmux reaps it the moment the client attaches elsewhere or disconnects
-- control-mode never litters the server with throwaway sessions (the user's
default socket included), and a reconnect storm cannot accumulate them.
"""

from __future__ import annotations

import asyncio
import time
import typing as t

from libtmux.experimental.engines.async_control_mode import AsyncControlModeEngine
from libtmux.experimental.engines.base import CommandRequest

if t.TYPE_CHECKING:
    from libtmux.session import Session


def test_phantom_session_marked_destroy_unattached(session: Session) -> None:
    """The engine marks its own throwaway session ``destroy-unattached`` on connect."""

    async def main() -> tuple[list[str], list[str]]:
        engine = AsyncControlModeEngine.for_server(session.server)
        try:
            await engine.start()
            own = (
                await engine.run(
                    CommandRequest.from_args("display-message", "-p", "#{session_id}"),
                )
            ).stdout
            opt = (
                await engine.run(
                    CommandRequest.from_args(
                        "show-options", "-t", own[0], "-v", "destroy-unattached"
                    ),
                )
            ).stdout
            return list(own), list(opt)
        finally:
            await engine.aclose()

    own, opt = asyncio.run(main())
    assert own and own[0].startswith("$")
    assert opt == ["on"]


def test_phantom_session_reaped_on_close(session: Session) -> None:
    """No phantom session lingers once the control connection closes."""
    server = session.server
    before = len(server.sessions)

    async def main() -> int:
        engine = AsyncControlModeEngine.for_server(server)
        try:
            await engine.start()
            return len(server.sessions)  # the phantom is present during the connection
        finally:
            await engine.aclose()

    during = asyncio.run(main())
    assert during == before + 1  # the connection spawned its phantom

    # tmux reaps the unattached destroy-unattached session when the client exits;
    # poll briefly since the reap is asynchronous to the proc terminating.
    for _ in range(60):
        if len(server.sessions) == before:
            break
        time.sleep(0.05)
    assert len(server.sessions) == before
