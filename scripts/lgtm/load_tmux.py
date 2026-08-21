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
import contextlib
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
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

_ROOT_PREFIX = "libtmux-load-"

# The holding command for the server's one pane. When it exits the window
# closes, the last window closing ends the session, and the server exits with
# it -- `destroy-unattached off` does not prevent that, it only survives
# *detach*. So this value is the ceiling on how long a run can last, not a
# cleanup mechanism, and it is set far above any plausible `--duration`.
# Cleanup is `teardown` plus `_reap_stale_roots`, which do not depend on it.
_HOLD_COMMAND = "sleep 86400"


def _process_identity(pid: int) -> str | None:
    """Return a pid's start time, or ``None`` when the pid is not running.

    Pairing the pid with its start time is what makes a staleness claim safe:
    pids are reused, and reaping on a bare pid check could delete a live run's
    server the moment the kernel handed its number to something else.
    """
    try:
        stat = pathlib.Path(f"/proc/{pid}/stat").read_bytes()
    except OSError:
        return None
    # `comm` is parenthesised and may itself contain spaces or parens, so the
    # fields are counted from the last ')' rather than by splitting the line.
    fields = stat[stat.rfind(b")") + 2 :].split()
    try:
        return fields[19].decode()
    except IndexError:
        return None


def _reap_stale_roots() -> None:
    """Remove load roots whose owning process is gone.

    ``teardown`` is the normal cleanup path and rampa runs it after SIGINT too.
    SIGKILL runs no user code at all, so a killed run strands its tmux server,
    that server's pane, and this directory -- each holding a pty -- with nothing
    left to reclaim them. This is the path that survives any exit, because it
    runs at the *start* of the next run rather than the end of the last one.

    A root is only removed once its owner is proven absent. A root whose owner
    is still running belongs to a concurrent run and is left alone; so is a root
    with no owner file that still has a tmux bound to it, since stealing another
    run's server would be worse than leaking this one.
    """
    reaped = 0
    for root in pathlib.Path(tempfile.gettempdir()).glob(f"{_ROOT_PREFIX}*"):
        if not root.is_dir():
            continue
        socket_path = root / "load.sock"
        owner = root / "owner"
        if owner.exists():
            try:
                pid_text, identity = owner.read_text().split()
                if _process_identity(int(pid_text)) == identity:
                    continue  # a live run owns this root
            except (OSError, ValueError):
                pass  # unreadable owner file: fall through to the socket probe
        elif _socket_has_server(socket_path):
            continue  # predates the owner file and is still in use
        with contextlib.suppress(Exception):
            subprocess.run(
                ("tmux", "-S", str(socket_path), "kill-server"),
                capture_output=True,
                check=False,
            )
            shutil.rmtree(root, ignore_errors=True)
            reaped += 1
    if reaped:
        print(f"reaped {reaped} stale load root(s)", file=sys.stderr)


def _socket_has_server(socket_path: pathlib.Path) -> bool:
    """Report whether a tmux server is answering on *socket_path*.

    ``kill-server`` and every other tmux subcommand exit 1 when no server is
    listening, so the check is the exit status of the cheapest read-only
    command rather than the presence of the socket file, which outlives its
    server.
    """
    try:
        return (
            subprocess.run(
                ("tmux", "-S", str(socket_path), "list-sessions"),
                capture_output=True,
                check=False,
                timeout=5,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


def _server() -> tuple[Server, pathlib.Path]:
    """Create the throwaway tmux server this run drives."""
    root = pathlib.Path(tempfile.gettempdir()) / f"{_ROOT_PREFIX}{uuid.uuid4().hex[:8]}"
    root.mkdir(mode=0o700)
    # Written before the server exists, so a kill between mkdir and new-session
    # still leaves a root the next run can prove stale.
    identity = _process_identity(os.getpid())
    (root / "owner").write_text(f"{os.getpid()} {identity}")
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
            _HOLD_COMMAND,
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
            # Reclaim what an earlier killed run stranded. Runs here rather than
            # at import so a scenario listing does not touch other runs' roots,
            # and behind the latch so it happens once per run, not per iteration.
            _reap_stale_roots()
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
