"""Live: the sync control-mode engine reaps its own phantom session too.

The synchronous twin of ``test_async_control_mode_phantom``: a bare ``tmux -C``
connect spawns a throwaway session, and the engine marks it ``destroy-unattached``
so it is reaped on disconnect -- no litter on the target server.
"""

from __future__ import annotations

import time
import typing as t

from libtmux.experimental.engines.base import CommandRequest
from libtmux.experimental.engines.control_mode import ControlModeEngine

if t.TYPE_CHECKING:
    from libtmux.session import Session


def test_sync_phantom_marked_destroy_unattached(session: Session) -> None:
    """The sync engine marks its throwaway session ``destroy-unattached``."""
    with ControlModeEngine.for_server(session.server) as engine:
        own = engine.run(
            CommandRequest.from_args("display-message", "-p", "#{session_id}"),
        ).stdout
        opt = engine.run(
            CommandRequest.from_args(
                "show-options", "-t", own[0], "-v", "destroy-unattached"
            ),
        ).stdout
    assert own and own[0].startswith("$")
    assert list(opt) == ["on"]


def test_sync_phantom_reaped_on_close(session: Session) -> None:
    """No phantom session lingers once the sync connection closes."""
    server = session.server
    before = len(server.sessions)
    with ControlModeEngine.for_server(server) as engine:
        engine.run(CommandRequest.from_args("display-message", "-p", "#{session_id}"))
        during = len(server.sessions)
    assert during == before + 1

    for _ in range(60):
        if len(server.sessions) == before:
            break
        time.sleep(0.05)
    assert len(server.sessions) == before
