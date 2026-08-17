#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["libtmux"]
#
# [tool.uv.sources]
# libtmux = { path = "..", editable = true }
# ///
"""Demonstrate decoded async control-mode pane output on an isolated server.

``scroll`` renders deterministic Python source through a grid of panes and
proves every decoded byte arrived in order. ``overload`` deliberately stalls a
size-one subscriber queue, reports dropped control-notification frames, and
then proves the same engine still accepts commands. Overload is not producer
backpressure: the engine's bounded queues discard their oldest notification.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import hashlib
import json
import os
import pathlib
import shlex
import shutil
import sys
import tempfile
import typing as t

# Never inherit an ambient client while constructing the isolated Server.
os.environ.pop("TMUX", None)
os.environ.pop("TMUX_PANE", None)

from libtmux.experimental.engines import AsyncControlModeEngine, ControlNotification
from libtmux.experimental.engines.base import CommandRequest
from libtmux.server import Server

_SESSION_NAME = "libtmux-source-scroll"
_RESPONSIVE_TEXT = "control-output-responsive"
_PRODUCER_LINGER_SECONDS = 300
_PRODUCER_CODE = """
import os
import pathlib
import subprocess
import sys
import termios
import time

tmux_bin, socket_path, gate, payload_path, done_path, delay, linger = sys.argv[1:]
subprocess.run(
    [tmux_bin, "-S", socket_path, "wait-for", gate],
    check=True,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
attrs = termios.tcgetattr(1)
attrs[1] &= ~termios.OPOST
termios.tcsetattr(1, termios.TCSANOW, attrs)
with pathlib.Path(payload_path).open("rb") as payload:
    for frame in payload:
        os.write(1, frame)
        if float(delay):
            time.sleep(float(delay))
pathlib.Path(done_path).touch()
time.sleep(float(linger))
""".strip()


@dataclasses.dataclass(frozen=True)
class SourceFile:
    """One source file selected for a producer pane.

    Attributes
    ----------
    relative_path : str
        POSIX path relative to the selected source root.
    sha256 : str
        SHA-256 digest of the complete source file.
    lines : tuple[bytes, ...]
        Source lines without newline terminators.
    """

    relative_path: str
    sha256: str
    lines: tuple[bytes, ...]


@dataclasses.dataclass
class PaneStream:
    """Expected stream and runtime identity for one producer pane.

    Attributes
    ----------
    logical_id : str
        Stable topology label, independent of tmux object allocation.
    window_index : int
        Zero-based window position.
    pane_index : int
        Zero-based pane position within the window.
    source : SourceFile
        Source assigned by the seeded selection.
    expected : bytes
        Complete framed byte stream the pane must emit.
    payload_path : pathlib.Path
        Private scratch file read by the producer.
    done_path : pathlib.Path
        Private scratch marker touched after the last write.
    gate : str
        Unique tmux ``wait-for`` channel released after subscription.
    pane_id : str
        Runtime tmux pane identifier populated during topology creation.
    """

    logical_id: str
    window_index: int
    pane_index: int
    source: SourceFile
    expected: bytes
    payload_path: pathlib.Path
    done_path: pathlib.Path
    gate: str
    pane_id: str = ""


@dataclasses.dataclass(frozen=True)
class DemoOptions:
    """Validated command-line options for one demo run.

    Attributes
    ----------
    mode : str
        Either ``scroll`` or ``overload``.
    source_root : pathlib.Path
        Root searched recursively for Python source.
    seed : int
        Seed mixed into the stable source ordering.
    windows : int
        Number of windows in the single session.
    panes : int
        Panes created in each window.
    lines : int
        Framed source lines emitted per pane.
    delay : float
        Seconds between producer frames.
    timeout : float
        Maximum seconds for setup and collection stages.
    quiet : bool
        Suppress the readable source stream when true.
    json_out : pathlib.Path or None
        Optional report destination.
    """

    mode: str
    source_root: pathlib.Path
    seed: int
    windows: int
    panes: int
    lines: int
    delay: float
    timeout: float
    quiet: bool
    json_out: pathlib.Path | None


def _selected_sources(root: pathlib.Path, seed: int, count: int) -> list[SourceFile]:
    """Return a stable seeded ordering of Python files, cycling when needed.

    Ranking each relative path by SHA-256 avoids depending on implementation
    details of :mod:`random`, so the same corpus and seed retain their order
    across supported Python versions.

    Parameters
    ----------
    root : pathlib.Path
        Source tree to scan.
    seed : int
        Stable ordering seed.
    count : int
        Number of pane assignments required.

    Returns
    -------
    list[SourceFile]
        Selected source metadata in pane-assignment order.
    """
    paths = sorted(path for path in root.rglob("*.py") if path.is_file())
    if not paths:
        msg = "source root contains no Python files"
        raise ValueError(msg)

    ranked = sorted(
        paths,
        key=lambda path: (
            hashlib.sha256(
                f"{seed}\0{path.relative_to(root).as_posix()}".encode()
            ).digest(),
            path.relative_to(root).as_posix(),
        ),
    )
    selected: list[SourceFile] = []
    for index in range(count):
        path = ranked[index % len(ranked)]
        content = path.read_bytes()
        selected.append(
            SourceFile(
                relative_path=path.relative_to(root).as_posix(),
                sha256=hashlib.sha256(content).hexdigest(),
                lines=tuple(content.splitlines()) or (b"",),
            )
        )
    return selected


def _framed_stream(logical_id: str, source: SourceFile, frames: int) -> bytes:
    """Render readable, sequence-numbered source frames for one pane.

    Parameters
    ----------
    logical_id : str
        Stable pane label.
    source : SourceFile
        Selected source metadata and lines.
    frames : int
        Number of frames to render.

    Returns
    -------
    bytes
        Exact bytes expected from the pane after PTY output processing is off.
    """
    rendered = bytearray()
    for sequence in range(frames):
        line = source.lines[sequence % len(source.lines)]
        prefix = (
            f"[{logical_id} {sequence:06d} {source.relative_path} "
            f"{source.sha256[:12]}] "
        ).encode()
        rendered.extend(prefix)
        rendered.extend(line)
        rendered.extend(b"\n")
    return bytes(rendered)


def _pane_streams(options: DemoOptions, scratch: pathlib.Path) -> list[PaneStream]:
    """Build expected streams and private producer files for the topology."""
    count = options.windows * options.panes
    sources = _selected_sources(options.source_root, options.seed, count)
    streams: list[PaneStream] = []
    for flat_index, source in enumerate(sources):
        window_index, pane_index = divmod(flat_index, options.panes)
        logical_id = f"w{window_index:02d}p{pane_index:02d}"
        expected = _framed_stream(logical_id, source, options.lines)
        payload_path = scratch / f"{logical_id}.payload"
        payload_path.write_bytes(expected)
        streams.append(
            PaneStream(
                logical_id=logical_id,
                window_index=window_index,
                pane_index=pane_index,
                source=source,
                expected=expected,
                payload_path=payload_path,
                done_path=scratch / f"{logical_id}.done",
                gate=f"libtmux-source-scroll-{logical_id}",
            )
        )
    return streams


def _producer_command(
    stream: PaneStream,
    *,
    tmux_bin: str,
    socket_path: pathlib.Path,
    delay: float,
) -> str:
    """Render one shell-safe direct pane command for the bounded producer."""
    return shlex.join(
        (
            sys.executable,
            "-c",
            _PRODUCER_CODE,
            tmux_bin,
            str(socket_path),
            stream.gate,
            str(stream.payload_path),
            str(stream.done_path),
            str(delay),
            str(_PRODUCER_LINGER_SECONDS),
        )
    )


def _require_success(result: t.Any, action: str) -> tuple[str, ...]:
    """Return stdout from a successful classic command or raise with context."""
    if result.returncode != 0:
        detail = "; ".join(result.stderr) or f"exit {result.returncode}"
        msg = f"{action} failed: {detail}"
        raise RuntimeError(msg)
    return tuple(result.stdout)


def _create_topology(
    server: Server,
    streams: list[PaneStream],
    *,
    tmux_bin: str,
    socket_path: pathlib.Path,
    delay: float,
) -> None:
    """Create one session with the requested windows and producer panes."""
    first = streams[0]
    first_output = _require_success(
        server.cmd(
            "new-session",
            "-d",
            "-x",
            "120",
            "-y",
            "40",
            "-s",
            _SESSION_NAME,
            "-P",
            "-F",
            "#{session_id} #{window_id} #{pane_id}",
            _producer_command(
                first,
                tmux_bin=tmux_bin,
                socket_path=socket_path,
                delay=delay,
            ),
        ),
        "create session",
    )
    session_id, current_window, first.pane_id = first_output[0].split()
    _require_success(
        server.cmd("set-option", "-t", session_id, "destroy-unattached", "off"),
        "disable destroy-unattached",
    )
    _require_success(
        server.cmd("set-option", "-s", "exit-empty", "off"),
        "disable exit-empty",
    )

    by_position = {
        (stream.window_index, stream.pane_index): stream for stream in streams
    }
    for window_index in range(len({stream.window_index for stream in streams})):
        if window_index:
            initial = by_position[(window_index, 0)]
            output = _require_success(
                server.cmd(
                    "new-window",
                    "-d",
                    "-t",
                    session_id,
                    "-n",
                    f"source-{window_index}",
                    "-P",
                    "-F",
                    "#{window_id} #{pane_id}",
                    _producer_command(
                        initial,
                        tmux_bin=tmux_bin,
                        socket_path=socket_path,
                        delay=delay,
                    ),
                ),
                f"create window {window_index}",
            )
            current_window, initial.pane_id = output[0].split()

        pane_count = len(
            [stream for stream in streams if stream.window_index == window_index]
        )
        for pane_index in range(1, pane_count):
            stream = by_position[(window_index, pane_index)]
            output = _require_success(
                server.cmd(
                    "split-window",
                    "-d",
                    "-t",
                    current_window,
                    "-P",
                    "-F",
                    "#{pane_id}",
                    _producer_command(
                        stream,
                        tmux_bin=tmux_bin,
                        socket_path=socket_path,
                        delay=delay,
                    ),
                ),
                f"create pane {stream.logical_id}",
            )
            stream.pane_id = output[0]
            _require_success(
                server.cmd("select-layout", "-t", current_window, "tiled"),
                f"layout window {window_index}",
            )


async def _wait_for_one_subscriber(
    engine: AsyncControlModeEngine,
    *,
    timeout: float,
) -> None:
    """Wait until the one permitted demo subscriber is registered."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        subscribers = getattr(engine, "_subscribers", ())
        if len(subscribers) == 1:
            return
        if len(subscribers) > 1:
            msg = "demo registered more than one control-output subscriber"
            raise RuntimeError(msg)
        if asyncio.get_running_loop().time() >= deadline:
            msg = "control-output subscriber registration timed out"
            raise TimeoutError(msg)
        await asyncio.sleep(0)


async def _release_producers(
    engine: AsyncControlModeEngine,
    streams: list[PaneStream],
) -> None:
    """Release every per-pane gate through the connected control engine."""
    requests = [
        CommandRequest.from_args("wait-for", "-S", stream.gate) for stream in streams
    ]
    results = await engine.run_batch(requests)
    failed = [result for result in results if result.returncode != 0]
    if failed:
        msg = "failed to release one or more source producers"
        raise RuntimeError(msg)


async def _wait_for_producers(
    streams: list[PaneStream],
    *,
    timeout: float,
) -> None:
    """Wait for every producer to record that its final write completed."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not all(stream.done_path.exists() for stream in streams):
        if asyncio.get_running_loop().time() >= deadline:
            missing = [
                stream.logical_id for stream in streams if not stream.done_path.exists()
            ]
            msg = f"source producers timed out: {', '.join(missing)}"
            raise TimeoutError(msg)
        await asyncio.sleep(0.01)


def _render_pane_report(stream: PaneStream, *, verified: bool) -> dict[str, t.Any]:
    """Return public, path-safe verification metadata for one pane."""
    return {
        "logical_id": stream.logical_id,
        "window": stream.window_index,
        "pane": stream.pane_index,
        "source": stream.source.relative_path,
        "source_sha256": stream.source.sha256,
        "stream_sha256": hashlib.sha256(stream.expected).hexdigest(),
        "frames": len(stream.expected.splitlines()),
        "first_sequence": 0,
        "last_sequence": len(stream.expected.splitlines()) - 1,
        "verified": verified,
    }


async def _next_notification(
    task: asyncio.Future[ControlNotification],
    *,
    deadline: float,
) -> ControlNotification:
    """Await a pending notification within an absolute monotonic deadline."""
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        msg = "control-output collection timed out"
        raise TimeoutError(msg)
    try:
        return await asyncio.wait_for(task, timeout=remaining)
    except asyncio.TimeoutError:
        msg = "control-output collection timed out"
        raise TimeoutError(msg) from None


async def _prove_responsive(engine: AsyncControlModeEngine) -> bool:
    """Return whether a follow-up command succeeds on the same engine."""
    result = await engine.run(
        CommandRequest.from_args("display-message", "-p", _RESPONSIVE_TEXT)
    )
    return result.returncode == 0 and result.stdout == (_RESPONSIVE_TEXT,)


async def _run_scroll(
    engine: AsyncControlModeEngine,
    stream: t.AsyncIterator[ControlNotification],
    first: asyncio.Future[ControlNotification],
    panes: list[PaneStream],
    *,
    quiet: bool,
    timeout: float,
) -> tuple[int, bool]:
    """Collect and byte-verify the complete lossless pane streams."""
    expected = {pane.pane_id: pane.expected for pane in panes}
    received = {pane.pane_id: bytearray() for pane in panes}
    deadline = asyncio.get_running_loop().time() + timeout
    pending = first
    observed = 0
    while any(bytes(received[pane_id]) != value for pane_id, value in expected.items()):
        notification = await _next_notification(pending, deadline=deadline)
        payload = notification.payload
        pane_id = notification.pane_id
        if payload is not None and pane_id in received:
            observed += 1
            if not quiet:
                sys.stdout.buffer.write(payload)
                sys.stdout.buffer.flush()
            received[pane_id].extend(payload)
            buffered = bytes(received[pane_id])
            if not expected[pane_id].startswith(buffered):
                msg = f"decoded output diverged for {pane_id}"
                raise RuntimeError(msg)
        if all(
            bytes(received[pane_id]) == value for pane_id, value in expected.items()
        ):
            break
        pending = asyncio.ensure_future(anext(stream))

    await _wait_for_producers(panes, timeout=timeout)
    if engine.dropped_notifications:
        msg = f"lossless scroll dropped {engine.dropped_notifications} frame(s)"
        raise RuntimeError(msg)
    return observed, await _prove_responsive(engine)


async def _run_overload(
    engine: AsyncControlModeEngine,
    stream: t.AsyncIterator[ControlNotification],
    first: asyncio.Future[ControlNotification],
    panes: list[PaneStream],
    *,
    timeout: float,
) -> tuple[int, bool]:
    """Stall a bounded subscriber, prove drops, then probe engine liveness."""
    await _wait_for_producers(panes, timeout=timeout)
    # Give the control reader time to offer the final PTY chunks while this
    # consumer remains deliberately stalled at a size-one queue.
    await asyncio.sleep(0.1)
    responsive = await _prove_responsive(engine)
    deadline = asyncio.get_running_loop().time() + timeout
    observed = int(
        (await _next_notification(first, deadline=deadline)).payload is not None
    )
    try:
        notification = await asyncio.wait_for(anext(stream), timeout=0.2)
    except (StopAsyncIteration, asyncio.TimeoutError):
        pass
    else:
        observed += int(notification.payload is not None)
    if engine.dropped_notifications <= 0:
        msg = "overload did not fill the bounded subscriber queue"
        raise RuntimeError(msg)
    return observed, responsive


async def _exercise_engine(
    server: Server,
    panes: list[PaneStream],
    options: DemoOptions,
) -> dict[str, t.Any]:
    """Register one subscriber, release producers, and run the selected proof."""
    queue_size = (
        1 if options.mode == "overload" else max(4096, len(panes) * options.lines)
    )
    async with AsyncControlModeEngine.for_server(
        server,
        event_queue_size=queue_size,
        timeout=options.timeout,
    ) as engine:
        notifications = engine.subscribe()
        first: asyncio.Future[ControlNotification] = asyncio.ensure_future(
            anext(notifications)
        )
        try:
            await _wait_for_one_subscriber(engine, timeout=options.timeout)
            await _release_producers(engine, panes)
            if options.mode == "scroll":
                observed, responsive = await _run_scroll(
                    engine,
                    notifications,
                    first,
                    panes,
                    quiet=options.quiet,
                    timeout=options.timeout,
                )
                lossless = True
            else:
                observed, responsive = await _run_overload(
                    engine,
                    notifications,
                    first,
                    panes,
                    timeout=options.timeout,
                )
                lossless = False
            dropped = engine.dropped_notifications
        finally:
            if not first.done():
                first.cancel()
                await asyncio.gather(first, return_exceptions=True)
            generator = t.cast(
                "t.AsyncGenerator[ControlNotification, None]",
                notifications,
            )
            with contextlib.suppress(RuntimeError):
                await generator.aclose()

    return {
        "mode": options.mode,
        "topology": {
            "windows": options.windows,
            "panes_per_window": options.panes,
            "total_panes": len(panes),
        },
        "panes": [_render_pane_report(pane, verified=lossless) for pane in panes],
        "observed_frames": observed,
        "dropped_frames": dropped,
        "lossless": lossless,
        "responsive": responsive,
    }


def run_demo(options: DemoOptions) -> dict[str, t.Any]:
    """Run one hermetic demo and return its post-cleanup report."""
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="ltout-"))
    socket_path = scratch / "tmux.sock"
    server = Server(socket_path=str(socket_path), config_file=os.devnull)
    report: dict[str, t.Any] | None = None
    server_stopped = False
    try:
        streams = _pane_streams(options, scratch)
        tmux_bin = shutil.which(server.tmux_bin or "tmux")
        if tmux_bin is None:
            msg = "tmux executable was not found"
            raise RuntimeError(msg)
        producer_delay = options.delay if options.mode == "scroll" else 0.001
        _create_topology(
            server,
            streams,
            tmux_bin=tmux_bin,
            socket_path=socket_path,
            delay=producer_delay,
        )
        report = asyncio.run(_exercise_engine(server, streams, options))
    finally:
        with contextlib.suppress(Exception):
            if server.is_alive():
                server.kill()
        with contextlib.suppress(Exception):
            server_stopped = not server.is_alive()
        shutil.rmtree(scratch, ignore_errors=True)
        scratch_removed = not scratch.exists()

    if report is None:
        msg = "demo stopped before producing a report"
        raise RuntimeError(msg)
    report["cleanup"] = {
        "scratch_removed": scratch_removed,
        "server_stopped": server_stopped,
    }
    return report


def _positive(parser: argparse.ArgumentParser, name: str, value: int) -> int:
    """Validate a strictly positive integer option."""
    if value <= 0:
        parser.error(f"{name} must be greater than zero")
    return value


def _options(parser: argparse.ArgumentParser, args: argparse.Namespace) -> DemoOptions:
    """Validate parsed arguments and build immutable demo options."""
    delay = float(args.delay)
    timeout = float(args.timeout)
    if delay < 0:
        parser.error("--delay must be non-negative")
    if timeout <= 0:
        parser.error("--timeout must be greater than zero")
    return DemoOptions(
        mode=t.cast("str", args.mode),
        source_root=pathlib.Path(args.source_root).resolve(),
        seed=int(args.seed),
        windows=_positive(parser, "--windows", int(args.windows)),
        panes=_positive(parser, "--panes", int(args.panes)),
        lines=_positive(parser, "--lines", int(args.lines)),
        delay=delay,
        timeout=timeout,
        quiet=bool(args.quiet),
        json_out=pathlib.Path(args.json_out) if args.json_out else None,
    )


def _add_common_arguments(parser: argparse.ArgumentParser, *, overload: bool) -> None:
    """Add the shared topology, corpus, timing, and report arguments."""
    default_root = pathlib.Path(__file__).parents[1] / "src" / "libtmux"
    parser.add_argument(
        "--source-root",
        default=default_root,
        help="Python source tree used as the deterministic scrolling corpus",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=2026,
        help="stable source-selection seed",
    )
    parser.add_argument("--windows", type=int, default=2, help="number of windows")
    parser.add_argument(
        "--panes",
        type=int,
        default=2,
        help="panes per window",
    )
    parser.add_argument(
        "--lines",
        type=int,
        default=2000 if overload else 120,
        help="source frames emitted by each pane",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.01,
        help="seconds between pane writes in scroll mode",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="maximum seconds for each setup or collection stage",
    )
    parser.add_argument("--json-out", help="write the verification report to this path")
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress source frames and print only the report",
    )


def _parser() -> argparse.ArgumentParser:
    """Build the two-mode command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    scroll = modes.add_parser(
        "scroll",
        help="readable lossless source scrolling with byte verification",
    )
    _add_common_arguments(scroll, overload=False)
    overload = modes.add_parser(
        "overload",
        help="intentional bounded-queue drops followed by a liveness probe",
    )
    _add_common_arguments(overload, overload=True)
    return parser


def main(argv: t.Sequence[str] | None = None) -> int:
    """Run the selected demo and emit its machine-readable verification report."""
    parser = _parser()
    options = _options(parser, parser.parse_args(argv))
    try:
        report = run_demo(options)
    except Exception as error:  # noqa: BLE001 - concise CLI error boundary
        parser.exit(1, f"error: {error}\n")
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if options.json_out is not None:
        options.json_out.write_text(f"{rendered}\n")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
