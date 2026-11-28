#!/usr/bin/env python
"""Tight-loop benchmark for a single libtmux call.

Configurable via env vars:

  BENCH_TARGET    name from BENCH_TARGETS registry (default: has_session)
  BENCH_ITERS     int (default: 1000)
  BENCH_SOCKET    socket name (default: ``microbench-<pid>`` for isolation)
  BENCH_SESSION   session name created for the run (default: bench)

The default socket name embeds the process PID so back-to-back
invocations (e.g. before/after a change in a comparison loop) get
isolated tmux servers and don't trip on leftover sessions from a prior
run whose ``kill_server`` didn't fully drain.

To add a new bench target: edit ``BENCH_TARGETS`` below — keeps the
script safe by construction (no dynamic code execution from caller
input). The dict is intentionally short and edited in source rather
than configured at runtime.
"""

from __future__ import annotations

import contextlib
import os
import sys
import typing as t

import libtmux

if t.TYPE_CHECKING:
    from collections.abc import Callable

    from libtmux.server import Server
    from libtmux.session import Session


# Registry of profile-able single calls. Each takes (server, session)
# and returns whatever the call returns. Add entries here — never accept
# caller-supplied expressions.
BENCH_TARGETS: dict[str, Callable[[Server, Session], object]] = {
    "has_session": lambda server, session: server.has_session(
        os.environ.get("BENCH_SESSION", "bench"),
    ),
    "list_sessions": lambda server, session: server.sessions,
    "list_windows": lambda server, session: session.windows,
    "session_name": lambda server, session: session.session_name,
    "show_options": lambda server, session: session.cmd("show-options", "-g"),
    "list_panes": lambda server, session: session.active_window.panes,
}


def main() -> int:
    """Run a fixed-iteration loop of the selected libtmux call."""
    target_name = os.environ.get("BENCH_TARGET", "has_session")
    if target_name not in BENCH_TARGETS:
        valid = ", ".join(sorted(BENCH_TARGETS))
        sys.stderr.write(
            f"unknown BENCH_TARGET={target_name!r}; valid: {valid}\n",
        )
        return 2

    iters = int(os.environ.get("BENCH_ITERS", "1000"))
    if iters <= 0:
        sys.stderr.write(f"BENCH_ITERS must be > 0 (got {iters})\n")
        return 2

    target = BENCH_TARGETS[target_name]
    socket_name = os.environ.get("BENCH_SOCKET", f"microbench-{os.getpid()}")
    session_name = os.environ.get("BENCH_SESSION", "bench")

    server: Server = libtmux.Server(socket_name=socket_name)
    try:
        session = server.new_session(session_name=session_name)
        for _ in range(iters):
            target(server, session)
    finally:
        with contextlib.suppress(Exception):
            server.kill_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
