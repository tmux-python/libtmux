"""Drive a real tmux workload through the engine seam into the local LGTM stack.

Emits all four signals from one run: spans and metrics per tmux command, logs
carrying trace context, and a CPU profile of the process.

The workload is shaped by what the dashboards need rather than by what is
convenient. Every lane runs, so per-transport panels have more than one series.
Grouped commands run, so the inlining panels are not flat zero. Commands that
tmux rejects run on purpose, so the failure panels have data -- a dashboard
whose error widget is empty is untested, not healthy.

Run it through ``just otel-smoke`` rather than directly; the recipe supplies the
endpoints.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import pathlib
import shutil
import subprocess
import sys
import time
import typing as t
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import telemetry

from libtmux.experimental.engines import (
    AsyncControlModeEngine,
    AsyncSubprocessEngine,
    ControlModeEngine,
    SubprocessEngine,
    instrument,
)
from libtmux.experimental.engines.base import (
    CommandRequest,
    CommandSeparator,
)
from libtmux.experimental.engines.instrumentation import CountingSink
from libtmux.server import Server

logger = logging.getLogger("libtmux.lgtm.smoke")

PLAIN = CommandRequest.from_args("list-panes", "-a", "-F", "#{pane_id}")
LISTING = CommandRequest.from_args("list-windows", "-a", "-F", "#{window_id}")
GROUPED = CommandRequest.from_args(
    "set-option",
    "-g",
    "@smoke",
    "1",
    CommandSeparator(";"),
    "show-options",
    "-g",
    "@smoke",
)
# tmux rejects this: the target window does not exist. It is here so the
# failure counters and the error-rate panels receive real data.
REJECTED = CommandRequest.from_args("list-panes", "-t", "@999999")

CYCLE = (PLAIN, GROUPED, LISTING, PLAIN, GROUPED, REJECTED)


def start_server(root: pathlib.Path) -> pathlib.Path:
    """Create a throwaway tmux server and return its socket path."""
    socket_path = root / "smoke.sock"
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
            "smoke",
            "sleep 300",
        ),
        check=True,
    )
    # Control mode opens a persistent client only when detaching is safe.
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
    for index in range(3):
        subprocess.run(
            (
                "tmux",
                "-S",
                str(socket_path),
                "new-window",
                "-t",
                "smoke",
                "-n",
                f"w{index}",
                "sleep 300",
            ),
            check=True,
        )
    return socket_path


def run_sync(engine: t.Any, seconds: float) -> None:
    """Issue the command cycle until the deadline passes."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        for request in CYCLE:
            engine.run(request)


async def run_async(engine: t.Any, seconds: float, concurrency: int) -> None:
    """Issue the cycle from several tasks at once.

    Overlapping tasks are the point: they exercise the async wrappers under the
    concurrency the engines are built for, and they make the span timeline show
    real overlap rather than a single serial chain.
    """
    deadline = time.monotonic() + seconds

    async def worker() -> None:
        while time.monotonic() < deadline:
            for request in CYCLE:
                await engine.run(request)

    await asyncio.gather(*(worker() for _ in range(concurrency)))


@contextlib.contextmanager
def _profile_lane(lane: str, *, enabled: bool) -> t.Iterator[None]:
    """Tag the CPU profile with the lane running inside the block.

    Pyroscope's configure-time tags describe the whole process, which is fine
    for branch or run identity but leaves the flamegraph unable to answer the
    question the other signals can: what did *this* transport cost. A dynamic
    tag around each lane makes the profile filterable the same way the metrics
    and traces already are.
    """
    if not enabled:
        yield
        return
    import pyroscope

    with pyroscope.tag_wrapper({"tmux_lane": lane}):
        yield


async def stream_lane(server: t.Any, signals: t.Any, seconds: float) -> dict[str, int]:
    """Consume control-mode notifications while commands keep flowing.

    Notifications arrive out of band, so the instrumentation seam never sees
    them: a sink wraps run(), and nothing routes a %output through run(). That
    leaves the streaming half of control mode unmeasured, including the
    engine's own count of notifications it had to drop because a subscriber
    fell behind -- which is the number that says the stream is unhealthy.

    Reading the counter costs one attribute access at the end of the lane, so
    the measurement does not disturb what it measures.
    """
    engine = AsyncControlModeEngine.for_server(server)
    # The workload's own panes run `sleep`, which ignores keystrokes and so
    # emits no output. Streaming needs something that answers, so this lane
    # gets its own shell window; without one the notification count is a
    # confident zero.
    await engine.run(
        CommandRequest.from_args("new-window", "-t", "smoke", "-n", "stream", "sh")
    )
    received = 0
    deadline = time.monotonic() + seconds

    async def consume() -> None:
        nonlocal received
        async for _ in engine.subscribe():
            received += 1
            if time.monotonic() > deadline:
                break

    consumer = asyncio.create_task(consume())
    # Let the consumer register its subscription before any output exists.
    # Started against a tight command loop it never gets scheduled, then waits
    # for notifications the shell already emitted, and reports a confident
    # zero.
    await asyncio.sleep(0.1)
    try:
        while time.monotonic() < deadline:
            await engine.run(
                CommandRequest.from_args(
                    "send-keys", "-t", "stream", "echo stream", "Enter"
                )
            )
            # Pace the sends so producer and consumer interleave. Saturating
            # the connection would measure a queue, not a stream.
            await asyncio.sleep(0.02)
        try:
            await asyncio.wait_for(consumer, timeout=5)
        except TimeoutError:
            consumer.cancel()
        dropped = engine.dropped_notifications
    finally:
        await engine.aclose()

    meter = signals.meter
    labels = {**signals.metric_labels, "tmux.lane": "control-stream"}
    meter.create_counter(
        "tmux.notifications", description="Control-mode notifications received."
    ).add(received, labels)
    meter.create_counter(
        "tmux.notifications.dropped",
        description="Notifications dropped because a subscriber fell behind.",
    ).add(dropped, labels)
    return {"received": received, "dropped": dropped}


def _log_lane(signals: t.Any, lane: str, totals: dict[str, int]) -> None:
    """Log a lane's result from inside a span, so the line links to a trace.

    A log record only carries trace context when a span is current; emitted
    between lanes it would reach Loki with the run's identity but nothing to
    click through to. Opening a short span around the record is what makes the
    Loki-to-Tempo jump in the datasource configuration actually work.
    """
    with signals.tracer.start_as_current_span("tmux lane summary") as span:
        span.set_attribute("tmux.lane", lane)
        for key, value in totals.items():
            span.set_attribute(f"tmux.{key}", value)
        logger.info("lane finished", extra={"lane": lane, **totals})


def lane_totals(counts: CountingSink) -> dict[str, int]:
    """Summarize one lane's locally observed counts."""
    return {
        "requests": counts.requests,
        "tmux_commands": counts.tmux_commands,
        "inlined": counts.inlined,
        "elapsed_ms": round(counts.elapsed_ns / 1e6),
    }


def main(argv: list[str] | None = None) -> int:
    """Run every lane under full telemetry and print the local counts."""
    parser = argparse.ArgumentParser(prog="scripts/lgtm/smoke.py", description=__doc__)
    parser.add_argument("--run-id", default=f"smoke-{uuid.uuid4().hex[:8]}")
    parser.add_argument(
        "--spike",
        default=None,
        help="name an experiment so several runs group together (or LIBTMUX_SPIKE)",
    )
    parser.add_argument(
        "--seconds", type=float, default=4.0, help="workload duration per lane"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="overlapping tasks in the async lanes",
    )
    parser.add_argument(
        "--otlp",
        default=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318"),
    )
    parser.add_argument(
        "--pyroscope",
        default=os.environ.get("PYROSCOPE_SERVER_ADDRESS", "http://127.0.0.1:4040"),
    )
    parser.add_argument(
        "--memory-profile",
        action="store_true",
        help="also collect allocation profiles (costs more than CPU sampling)",
    )
    args = parser.parse_args(argv)

    os.environ.pop("TMUX", None)
    os.environ.pop("TMUX_PANE", None)

    signals = telemetry.build(args.otlp, run_id=args.run_id, spike=args.spike)
    logging.basicConfig(level=logging.INFO, handlers=[signals.handler], force=True)

    try:
        import pyroscope

        pyroscope.configure(
            application_name=telemetry.SERVICE_NAME,
            server_address=args.pyroscope,
            sample_rate=100,
            upload_interval=3,
            # Allocation profiling answers a different question from CPU
            # sampling and costs more to collect, so it stays opt-in rather
            # than being switched on for every run.
            mem_enabled=args.memory_profile,
            # The full static identity: a profile is one process, so branch,
            # revision, worktree, and spike cost nothing extra here and make
            # two runs directly comparable in Pyroscope.
            tags=signals.profile_tags,
        )
        profiling = True
    except Exception as error:  # noqa: BLE001 - profiling is optional
        logger.warning("profiling disabled: %s", error)
        profiling = False

    root = pathlib.Path(f"/tmp/libtmux-smoke-{uuid.uuid4().hex[:8]}")
    root.mkdir(mode=0o700)
    totals: dict[str, dict[str, int]] = {}
    try:
        socket_path = start_server(root)
        server = Server(socket_path=socket_path, config_file=os.devnull)
        logger.info("smoke run started", extra={"run_id": args.run_id, "lanes": 4})

        sync_lanes = (
            ("subprocess", lambda: SubprocessEngine.for_server(server)),
            ("control", lambda: ControlModeEngine.for_server(server)),
        )
        for lane, factory in sync_lanes:
            counts = CountingSink()
            engine = instrument(
                factory(),
                counts,
                telemetry.OTelSink(
                    signals.tracer, signals.meter, lane, signals.metric_labels
                ),
            )
            with (
                telemetry.scope(**{"libtmux.phase": f"{lane}-sync"}),
                _profile_lane(lane, enabled=profiling),
            ):
                run_sync(engine, args.seconds)
            totals[lane] = lane_totals(counts)
            _log_lane(signals, lane, totals[lane])

        async_lanes = (
            ("subprocess-async", lambda: AsyncSubprocessEngine.for_server(server)),
            ("control-async", lambda: AsyncControlModeEngine.for_server(server)),
        )
        for lane, async_factory in async_lanes:
            counts = CountingSink()
            engine = instrument(
                async_factory(),
                counts,
                telemetry.OTelSink(
                    signals.tracer, signals.meter, lane, signals.metric_labels
                ),
            )

            async def drive(engine: t.Any = engine) -> None:
                try:
                    await run_async(engine, args.seconds, args.concurrency)
                finally:
                    inner = engine.inner
                    if hasattr(inner, "aclose"):
                        await inner.aclose()

            with (
                telemetry.scope(**{"libtmux.phase": f"{lane}-async"}),
                _profile_lane(lane, enabled=profiling),
            ):
                asyncio.run(drive())
            totals[lane] = lane_totals(counts)
            _log_lane(signals, lane, totals[lane])

        with telemetry.scope(**{"libtmux.phase": "control-stream"}):
            stream = asyncio.run(stream_lane(server, signals, args.seconds))
        logger.info("stream finished", extra={"lane": "control-stream", **stream})
    finally:
        subprocess.run(
            ("tmux", "-S", str(root / "smoke.sock"), "kill-server"),
            capture_output=True,
            check=False,
        )
        shutil.rmtree(root, ignore_errors=True)

    if profiling:
        # Pyroscope batches on an interval; give it one before shutting down.
        time.sleep(4)
        import pyroscope

        pyroscope.shutdown()
    signals.shutdown()

    header = (
        f"{'lane':<18}{'requests':>10}{'tmuxcmd':>10}{'inlined':>10}{'engine_ms':>11}"
    )
    print(f"\n  {header}")
    print("  " + "-" * len(header))
    for lane, row in totals.items():
        print(
            f"  {lane:<18}{row['requests']:>10}{row['tmux_commands']:>10}"
            f"{row['inlined']:>10}{row['elapsed_ms']:>11}"
        )
    ref = signals.resource_attributes.get("vcs.ref.head.name", "?")
    worktree = signals.resource_attributes.get("libtmux.worktree", "-")
    print(f"\n  run_id={args.run_id}  branch={ref}  worktree={worktree}")
    print(f"  exported to {args.otlp} and {args.pyroscope}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
