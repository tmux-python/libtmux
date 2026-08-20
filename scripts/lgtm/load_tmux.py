"""Load-shape the tmux engines with rampa, and export the result to LGTM.

``otel_smoke.py`` answers "does telemetry flow" by running flat out for a fixed
duration. That is the wrong shape for asking where a transport stops keeping
up, because a closed loop of N workers slows down with the system: offered load
falls as latency rises, and the graph bends politely instead of breaking.

rampa supplies the shapes that expose that -- notably ``ramping-arrival-rate``,
an open model that keeps issuing commands at a target rate whether or not the
previous ones finished. Latency then climbs on its own when a transport
saturates, which is the knee worth finding.

Run it through ``just otel-load``.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import shutil
import subprocess
import sys
import typing as t
import uuid

# rampa loads this file by path, so its directory is not guaranteed to be
# importable; telemetry.py sits beside it.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import rampa
import telemetry

from libtmux.experimental.engines import (
    AsyncControlModeEngine,
    AsyncSubprocessEngine,
    instrument,
)
from libtmux.experimental.engines.base import CommandRequest, CommandSeparator
from libtmux.experimental.engines.control_mode import command_count
from libtmux.server import Server

# Transports this scenario can drive, and how to build each.
LANES = {
    "control-async": AsyncControlModeEngine.for_server,
    "subprocess-async": AsyncSubprocessEngine.for_server,
}

LANE = os.environ.get("LIBTMUX_LOAD_LANE", "control-async")
if LANE not in LANES:
    # Validated at import, before any tmux server exists. Left until the first
    # worker iteration, an unknown lane raises inside a rampa worker, which
    # counts the iteration as failed and moves on -- so the next iteration
    # builds another tmux server, and the next, for the whole run. A single
    # typo produced thousands of servers before this check existed.
    message = (
        f"LIBTMUX_LOAD_LANE={LANE!r} is not a lane; choose one of "
        f"{', '.join(sorted(LANES))}"
    )
    raise SystemExit(message)
PLAIN = CommandRequest.from_args("list-panes", "-a", "-F", "#{pane_id}")
GROUPED = CommandRequest.from_args(
    "set-option",
    "-g",
    "@load",
    "1",
    CommandSeparator(";"),
    "show-options",
    "-g",
    "@load",
)

# One tmux server and one engine per process, shared by every virtual user.
# Building them per iteration would measure process startup rather than the
# transport, which is the opposite of the point.
_STATE: dict[str, t.Any] = {}


def _server() -> tuple[Server, pathlib.Path]:
    """Create the throwaway tmux server this run drives."""
    root = pathlib.Path(f"/tmp/libtmux-load-{uuid.uuid4().hex[:8]}")
    root.mkdir(mode=0o700)
    socket_path = root / "load.sock"
    subprocess.run(
        (
            "tmux",
            "-S",
            str(socket_path),
            "-f",
            "/dev/null",
            "new-session",
            "-d",
            "-s",
            "load",
            "sleep 600",
        ),
        check=True,
    )
    subprocess.run(
        (
            "tmux",
            "-S",
            str(socket_path),
            "set-option",
            "-g",
            "destroy-unattached",
            "off",
        ),
        check=True,
    )
    return Server(socket_path=socket_path, config_file=os.devnull), root


def _engine() -> t.Any:
    """Return the shared instrumented engine, building it on first use.

    Telemetry rides on this project's own sink rather than a rampa output
    backend. rampa decides *when* each command is issued; the sink decides what
    is recorded about it. Keeping that split means the load-shaped run lands in
    Grafana under the same metric names and the same branch, worktree, and
    spike labels as every other run, so the two are directly comparable instead
    of arriving as a second, parallel account of the same work.
    """
    # A failure here is permanent for this process, so it is remembered and
    # re-raised. Building this costs a tmux server and three exporter threads,
    # and rampa correctly isolates a failing iteration and runs the next one --
    # so without the latch, a setup that cannot succeed is retried for the whole
    # run and leaves a fresh set of resources behind every time. That is what
    # once turned one bad lane name into thousands of tmux servers and ten
    # thousand threads; the executor was behaving properly, the scenario was not.
    if "error" in _STATE:
        raise _STATE["error"]
    if "engine" not in _STATE:
        os.environ.pop("TMUX", None)
        os.environ.pop("TMUX_PANE", None)
        try:
            # Resolve the factory before anything is created, so a failure here
            # cannot leave a tmux server behind.
            factory = LANES[LANE]
            server, root = _server()
            _STATE["root"] = root
            signals = telemetry.build(
                os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318"),
                run_id=os.environ.get("LIBTMUX_RUN_ID", f"load-{uuid.uuid4().hex[:8]}"),
                spike=os.environ.get("LIBTMUX_SPIKE"),
            )
            _STATE["signals"] = signals
            _STATE["engine"] = instrument(
                factory(server),
                telemetry.OTelSink(
                    signals.tracer, signals.meter, LANE, signals.metric_labels
                ),
            )
        except BaseException as error:
            _STATE["error"] = error
            raise
    return _STATE["engine"]


async def _issue(worker: rampa.Worker, request: CommandRequest) -> None:
    """Run one request and record it under rampa's metric vocabulary."""
    engine = _engine()
    tags = {"tmux_lane": LANE, "tmux_command": str(request.args[0])}
    started = asyncio.get_running_loop().time()
    result = await engine.run(request)
    elapsed_ms = (asyncio.get_running_loop().time() - started) * 1000

    worker.trend("tmux_command_duration", elapsed_ms, tags)
    worker.counter("tmux_requests", 1.0, tags)
    worker.counter("tmux_commands", float(command_count(tuple(request.args))), tags)
    worker.check(result, {"tmux accepted": lambda r: r.returncode == 0})


@rampa.scenario(executor="constant-vus", vus=8, duration="10s")
async def steady(worker: rampa.Worker) -> None:
    """Hold a fixed concurrency, the closed-loop baseline."""
    await _issue(worker, PLAIN)
    await _issue(worker, GROUPED)


@rampa.scenario(
    executor="ramping-arrival-rate",
    stages=[
        rampa.Stage(duration="8s", target=200),
        rampa.Stage(duration="8s", target=1200),
    ],
    pre_allocated_vus=32,
    max_vus=256,
)
async def ramp(worker: rampa.Worker) -> None:
    """Raise offered rate regardless of latency, so saturation shows itself."""
    await _issue(worker, PLAIN)


async def teardown() -> None:
    """Close the engine and remove the tmux server.

    rampa calls this with no arguments once the run finishes, and reports a
    failure here as ``TEARDOWN_FAILED`` rather than swallowing it.
    """
    engine = _STATE.get("engine")
    if engine is not None and hasattr(engine.inner, "aclose"):
        await engine.inner.aclose()
    signals = _STATE.get("signals")
    if signals is not None:
        signals.shutdown()
    root = _STATE.get("root")
    if root is not None:
        # Blocking work belongs off the loop, even during teardown.
        await asyncio.to_thread(
            subprocess.run,
            ("tmux", "-S", str(root / "load.sock"), "kill-server"),
            capture_output=True,
            check=False,
        )
        await asyncio.to_thread(shutil.rmtree, root, ignore_errors=True)
