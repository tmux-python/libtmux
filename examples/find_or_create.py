"""Reuse matching objects and clean up only the objects this program creates."""

from __future__ import annotations

import libtmux

server = libtmux.Server()
with (
    server.find_or_create_session("libtmux-example") as session,
    session.find_or_create_window("worker") as window,
    window.find_or_create_pane("worker") as pane,
):
    print(pane.pane_id, flush=True)
