"""Create and clean up a session at the ordinary configured endpoint."""

from __future__ import annotations

import uuid

import libtmux

server = libtmux.Server()
with server.new_session(session_name=f"libtmux-example-{uuid.uuid4().hex}") as session:
    print(session.session_id, flush=True)
