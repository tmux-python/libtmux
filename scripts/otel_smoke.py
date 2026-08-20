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
import logging
import os
import pathlib
import shutil
import subprocess
import sys
import time
import typing as t
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).parent / "lgtm"))

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

logger = logging.getLogger("libtmux.otel_smoke")

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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=f"smoke-{uuid.uuid4().hex[:8]}")
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
    args = parser.parse_args(argv)

    os.environ.pop("TMUX", None)
    os.environ.pop("TMUX_PANE", None)

    signals = telemetry.build(args.otlp, run_id=args.run_id)
    logging.basicConfig(level=logging.INFO, handlers=[signals.handler], force=True)

    try:
        import pyroscope

        pyroscope.configure(
            application_name=telemetry.SERVICE_NAME,
            server_address=args.pyroscope,
            sample_rate=100,
            upload_interval=3,
            tags={"run_id": args.run_id},
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
                telemetry.OTelSink(signals.tracer, signals.meter, lane),
            )
            run_sync(engine, args.seconds)
            totals[lane] = lane_totals(counts)
            logger.info("lane finished", extra={"lane": lane, **totals[lane]})

        async_lanes = (
            ("subprocess-async", lambda: AsyncSubprocessEngine.for_server(server)),
            ("control-async", lambda: AsyncControlModeEngine.for_server(server)),
        )
        for lane, factory in async_lanes:
            counts = CountingSink()
            engine = instrument(
                factory(),
                counts,
                telemetry.OTelSink(signals.tracer, signals.meter, lane),
            )

            async def drive(engine: t.Any = engine) -> None:
                try:
                    await run_async(engine, args.seconds, args.concurrency)
                finally:
                    inner = engine.inner
                    if hasattr(inner, "aclose"):
                        await inner.aclose()

            asyncio.run(drive())
            totals[lane] = lane_totals(counts)
            logger.info("lane finished", extra={"lane": lane, **totals[lane]})
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
    print(f"\n  run_id={args.run_id}  service={telemetry.SERVICE_NAME}")
    print(f"  exported to {args.otlp} and {args.pyroscope}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
