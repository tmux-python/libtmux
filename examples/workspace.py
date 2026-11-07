"""Create or reuse a session and window at the ordinary configured endpoint."""

from __future__ import annotations

import libtmux

server = libtmux.Server().ensure_running()
session = server.find_or_create_session("libtmux-example").value
window = session.find_or_create_window("work").value
pane = window.panes[0]
print(session.session_name, window.window_name, pane.pane_id, flush=True)
