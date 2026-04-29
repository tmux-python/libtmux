"""Single-engine bench target for Tachyon.

Picks the engine from the LIBTMUX_ENGINE env var so the same script
serves all three engines. Spins up a fresh tmux server per run and
issues display-message calls in a tight loop.
"""

from __future__ import annotations

import contextlib
import os
import uuid

from libtmux import pytest_plugin
from libtmux.engines.base import CommandRequest
from libtmux.engines.control_mode.base import ControlModeEngine
from libtmux.engines.imsg import ImsgEngine
from libtmux.engines.subprocess import SubprocessEngine

ITERS = int(os.environ.get("BENCH_ITERS", "500"))
ENGINE = os.environ.get("LIBTMUX_ENGINE", "subprocess")

socket_name = f"libtmux_profile_{ENGINE}_{uuid.uuid4().hex[:6]}"

# Bootstrap with subprocess so imsg has something to connect to.
boot = SubprocessEngine()
boot.run(
    CommandRequest.from_args(
        "-L",
        socket_name,
        "new-session",
        "-d",
        "-s",
        "bench",
    ),
)

if ENGINE == "imsg":
    engine: object = ImsgEngine(protocol_version="8")
elif ENGINE == "control_mode":
    engine = ControlModeEngine()
else:
    engine = SubprocessEngine()

try:
    args = ("-L", socket_name, "display-message", "-p", "ok")
    # Prime
    engine.run(CommandRequest.from_args(*args))  # type: ignore[attr-defined]
    for _ in range(ITERS):
        engine.run(CommandRequest.from_args(*args))  # type: ignore[attr-defined]
finally:
    if isinstance(engine, ControlModeEngine):
        with contextlib.suppress(Exception):
            engine.close()
    pytest_plugin._reap_test_server(socket_name)
