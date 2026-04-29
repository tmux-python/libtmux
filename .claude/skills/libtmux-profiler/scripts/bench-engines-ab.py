#!/usr/bin/env python
"""A/B microbench across all three libtmux engines.

Runs ``display-message -p ok`` ``BENCH_ITERS`` times against a
pre-spawned tmux server under each engine in turn. The server is
bootstrapped with the subprocess engine so the imsg engine has
something to connect to (imsg cannot start a server on its own —
only attach to an existing one).

Output is one row per engine with avg / p50 / p99 / total wall.
Direct comparison of these numbers tells us where each engine sits
in the steady-state cost curve:

* ``subprocess`` pays fork+exec+connect+exit per call.
* ``imsg`` pays AF_UNIX socket + handshake per call (one-shot).
* ``control_mode`` pays one stdin write + parser dispatch (persistent
  connection — the win this branch ships).

Configurable via env vars:

  BENCH_ITERS   int (default: 50)
  BENCH_SOCKET  base socket name; each engine gets a unique suffix
                (default: ``ab-<pid>``)
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
import uuid

from libtmux import pytest_plugin
from libtmux.engines.base import CommandRequest
from libtmux.engines.control_mode.base import ControlModeEngine
from libtmux.engines.imsg import ImsgEngine
from libtmux.engines.subprocess import SubprocessEngine

CMD_ARGS = ("display-message", "-p", "ok")


def _bench_one(engine, socket_name: str, iters: int) -> dict[str, float]:
    """Time *iters* calls of CMD_ARGS through *engine* against *socket_name*."""
    full_args = ("-L", socket_name, *CMD_ARGS)
    # Prime call — pays connection-setup cost we don't want to measure.
    engine.run(CommandRequest.from_args(*full_args))

    samples: list[float] = []
    for _ in range(iters):
        t0 = time.perf_counter()
        engine.run(CommandRequest.from_args(*full_args))
        samples.append(time.perf_counter() - t0)

    samples.sort()
    return {
        "avg_ms": 1000 * sum(samples) / len(samples),
        "p50_ms": 1000 * samples[len(samples) // 2],
        "p99_ms": 1000 * samples[max(0, len(samples) - 2)],
        "total_s": sum(samples),
    }


def main() -> int:
    """Run the A/B microbench across all three engines and print one row each."""
    iters = int(os.environ.get("BENCH_ITERS", "50"))
    base_socket = os.environ.get("BENCH_SOCKET", f"ab-{os.getpid()}")

    engines: list[tuple[str, object]] = [
        ("subprocess", SubprocessEngine()),
        ("imsg", ImsgEngine(protocol_version="8")),
        ("control_mode", ControlModeEngine()),
    ]

    print(f"# A/B engine bench: {iters} iters of `display-message -p ok`")
    print(f"# {'engine':>14}  {'avg':>8}  {'p50':>8}  {'p99':>8}  {'total':>10}")
    for label, engine in engines:
        socket_name = f"libtmux_{base_socket}_{label}_{uuid.uuid4().hex[:6]}"
        # Pre-spawn the server with subprocess — imsg cannot bootstrap.
        SubprocessEngine().run(
            CommandRequest.from_args(
                "-L",
                socket_name,
                "new-session",
                "-d",
                "-s",
                "bench",
            ),
        )
        try:
            stats = _bench_one(engine, socket_name, iters)
            print(
                f"  {label:>14}  "
                f"{stats['avg_ms']:6.2f}ms  "
                f"{stats['p50_ms']:6.2f}ms  "
                f"{stats['p99_ms']:6.2f}ms  "
                f"{stats['total_s']:8.3f}s",
            )
        finally:
            if isinstance(engine, ControlModeEngine):
                with contextlib.suppress(Exception):
                    engine.close()
            pytest_plugin._reap_test_server(socket_name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
