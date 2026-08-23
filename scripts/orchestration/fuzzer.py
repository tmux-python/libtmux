#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["rich>=13"]
# ///
"""Generate deterministic append-only streams for orchestration benchmarks."""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import enum
import hashlib
import json
import os
import pathlib
import random
import signal
import stat
import tempfile
import time
import typing as t

# Sentinel components are printable ASCII terminal atoms. Spaces and every
# control byte are excluded so a captured token remains one literal field.
_TERMINAL_SAFE_COMPONENT_ALPHABET = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-"
)
SENTINEL_COMPONENT_MAX_BYTES = 128
SENTINEL_RECORD_MAX_BYTES = 422
ACTIVITY_RECORD_MAX_BYTES = 2_048
DELAYED_ACTIVITY_RECORD_MAX_BYTES = 128
EPOCH_PULSE_MAX_BYTES = 64


class StreamMode(str, enum.Enum):
    """A deterministic active-output stream category."""

    EDITOR = "editor"
    DEV_SERVER = "dev-server"
    INSTALLER = "installer"
    DELAYED_MATCH = "delayed-match"


@dataclasses.dataclass(frozen=True)
class WorkloadOptions:
    """Configuration for one fuzzer process.

    Attributes
    ----------
    output_dir : pathlib.Path
        Directory used for markers and append-only streams.
    run_id : str
        Run identity carried by every control marker.
    source_root : pathlib.Path
        Repository root containing ``src/libtmux`` source files.
    seed : int
        Seed that fixes corpus and frame selection.
    frame_rate_hz : float
        Number of frames emitted per stream each second.
    duration_s : float
        Maximum serving duration after activation.
    delayed_match_after_s : float
        Delay between an accepted request and its sentinel emission.
    sentinel_prefix : str
        Human-readable prefix for each unique sentinel.
    heartbeat_interval_s : float
        Maximum interval between heartbeat marker updates.
    """

    output_dir: pathlib.Path
    run_id: str
    source_root: pathlib.Path
    seed: int
    frame_rate_hz: float
    duration_s: float
    delayed_match_after_s: float
    sentinel_prefix: str
    heartbeat_interval_s: float


@dataclasses.dataclass(frozen=True)
class WorkloadPaths:
    """Filesystem locations owned by one fuzzer process.

    Attributes
    ----------
    root : pathlib.Path
        Exclusive output directory.
    streams : pathlib.Path
        Directory containing mode-specific append-only streams.
    requests : pathlib.Path
        Directory containing benchmark request markers.
    sentinels : pathlib.Path
        Directory containing request-specific emission evidence.
    ready : pathlib.Path
        Marker published after all service paths exist.
    gate : pathlib.Path
        Marker that releases the paused service.
    heartbeat : pathlib.Path
        Current fuzzer liveness marker.
    stop : pathlib.Path
        Marker requesting a graceful stop.
    """

    root: pathlib.Path
    streams: pathlib.Path
    requests: pathlib.Path
    sentinels: pathlib.Path
    ready: pathlib.Path
    gate: pathlib.Path
    heartbeat: pathlib.Path
    stop: pathlib.Path


@dataclasses.dataclass(frozen=True)
class Frame:
    """One rendered stream record and its adjacent activity pulse.

    Attributes
    ----------
    mode : StreamMode
        Stream receiving the record.
    epoch : int
        Monotonic frame sequence number.
    text : str
        Bounded newline-terminated ordinary record followed by its epoch pulse.
    """

    mode: StreamMode
    epoch: int
    text: str


@dataclasses.dataclass(frozen=True)
class SentinelEvidence:
    """Request-specific sentinel scheduling and emission facts.

    Attributes
    ----------
    schema_version : int
        Marker schema version.
    run_id : str
        Run identity that owns the evidence.
    request_id : str
        Unique request identity.
    requested_monotonic_ns : int
        Request receipt timestamp supplied by the benchmark.
    configured_delay_ns : int
        Configured delay applied to the request timestamp.
    scheduled_monotonic_ns : int
        Requested emission deadline on the monotonic clock.
    emitted_monotonic_ns : int
        Timestamp immediately before the append on the monotonic clock.
    scheduling_lateness_ns : int
        Difference between the actual append time and the scheduled deadline.
    sentinel : str
        Canonical text appended to the delayed stream.
    sentinel_sha256 : str
        SHA-256 of the exact newline-terminated UTF-8 bytes appended.
    """

    schema_version: int
    run_id: str
    request_id: str
    requested_monotonic_ns: int
    configured_delay_ns: int
    scheduled_monotonic_ns: int
    emitted_monotonic_ns: int
    scheduling_lateness_ns: int
    sentinel: str
    sentinel_sha256: str


@dataclasses.dataclass(frozen=True)
class _PendingRequest:
    """One accepted request awaiting its scheduled sentinel emission.

    The fuzzer exclusively owns a mode-0700 output tree, and its trusted
    benchmark producer publishes markers by atomic replacement. Under that
    model, device and inode identity are sufficient to detect a newer marker
    before consuming the accepted pathname.

    Attributes
    ----------
    request_id : str
        Canonical request identity.
    requested_monotonic_ns : int
        Producer timestamp for the request.
    configured_delay_ns : int
        Delay applied before sentinel emission.
    scheduled_monotonic_ns : int
        Monotonic deadline for sentinel emission.
    sentinel : str
        Exact terminal-safe sentinel without its trailing newline.
    path : pathlib.Path
        Canonical request marker pathname.
    device : int
        Device identity observed while reading the stable marker.
    inode : int
        Inode identity observed while reading the stable marker.

    Examples
    --------
    >>> pending = _PendingRequest(
    ...     "sample", 1, 2, 3, "READY", pathlib.Path("sample.json"), 4, 5
    ... )
    >>> pending.request_id
    'sample'
    """

    request_id: str
    requested_monotonic_ns: int
    configured_delay_ns: int
    scheduled_monotonic_ns: int
    sentinel: str
    path: pathlib.Path
    device: int
    inode: int


def stream_for_pane(ordinal: int, delayed_ordinal: int) -> StreamMode:
    """Return the stable stream assignment for a pane ordinal.

    >>> stream_for_pane(2, 2)
    <StreamMode.DELAYED_MATCH: 'delayed-match'>
    >>> stream_for_pane(3, 2)
    <StreamMode.INSTALLER: 'installer'>
    """
    if ordinal == delayed_ordinal:
        return StreamMode.DELAYED_MATCH
    shared = (StreamMode.EDITOR, StreamMode.DEV_SERVER, StreamMode.INSTALLER)
    compacted = ordinal - int(ordinal > delayed_ordinal)
    return shared[compacted % len(shared)]


def _is_terminal_safe_component(value: object) -> bool:
    """Return whether *value* is one bounded printable ASCII component.

    Components contain 1-128 encoded bytes drawn only from letters, digits,
    ``.``, ``_``, ``:``, and ``-``. The bound keeps a complete sentinel within
    :data:`SENTINEL_RECORD_MAX_BYTES`.

    >>> _is_terminal_safe_component("run.uuid:sample_1-2")
    True
    >>> _is_terminal_safe_component("unsafe value")
    False
    """
    return (
        isinstance(value, str)
        and value.isascii()
        and 0 < len(value.encode()) <= SENTINEL_COMPONENT_MAX_BYTES
        and all(character in _TERMINAL_SAFE_COMPONENT_ALPHABET for character in value)
    )


def sentinel_text(run_id: str, request_id: str, value: str) -> str:
    """Return a bounded terminal-safe sentinel for one run and request.

    >>> sentinel_text("run-7", "sample-03", "READY")
    'LIBTMUX_SENTINEL run=run-7 request=sample-03 value=READY'

    Raises
    ------
    ValueError
        If any component is not a 1-128 byte terminal-safe ASCII atom or the
        complete newline-terminated record exceeds 422 encoded bytes.
    """
    components = {"run_id": run_id, "request_id": request_id, "value": value}
    for name, component in components.items():
        if not _is_terminal_safe_component(component):
            message = (
                f"{name} must be a 1-{SENTINEL_COMPONENT_MAX_BYTES} byte "
                "terminal-safe ASCII component using letters, digits, '.', '_', "
                "':', or '-'"
            )
            raise ValueError(message)
    sentinel = f"LIBTMUX_SENTINEL run={run_id} request={request_id} value={value}"
    if len(f"{sentinel}\n".encode()) > SENTINEL_RECORD_MAX_BYTES:
        message = (
            f"sentinel record must be at most {SENTINEL_RECORD_MAX_BYTES} encoded bytes"
        )
        raise ValueError(message)
    return sentinel


def _validate_workload_identity(options: WorkloadOptions) -> None:
    """Reject unsafe service identity before creating output or rendering UI.

    >>> _validate_workload_identity(
    ...     WorkloadOptions(
    ...         pathlib.Path("out"), "run-7", pathlib.Path("."), 0, 1.0, 1.0,
    ...         0.0, "READY", 1.0,
    ...     )
    ... )

    Raises
    ------
    ValueError
        If the run identity or default sentinel value is not terminal-safe.
    """
    sentinel_text(options.run_id, "request", options.sentinel_prefix)


def source_lines(source_root: pathlib.Path, seed: int) -> tuple[str, ...]:
    """Read and stably shuffle labeled ``src/libtmux`` source lines.

    >>> source_lines(pathlib.Path("missing"), seed=1)
    ()
    """
    source_dir = source_root / "src" / "libtmux"
    lines: list[str] = []
    for path in sorted(source_dir.rglob("*.py")):
        relative = path.relative_to(source_root)
        decoded = path.read_bytes().decode("utf-8", errors="replace")
        lines.extend(
            f"{relative}:{number}: {line}"
            for number, line in enumerate(decoded.splitlines(), start=1)
        )
    random.Random(seed).shuffle(lines)
    return tuple(lines)


def _bounded_activity_record(
    text: str,
    *,
    max_bytes: int = ACTIVITY_RECORD_MAX_BYTES,
) -> str:
    r"""Return one printable newline-terminated record within the byte ceiling.

    >>> len(_bounded_activity_record("é" * 2_048 + "\n").encode("utf-8")) <= 2_048
    True
    >>> len(_bounded_activity_record("é" * 128 + "\n", max_bytes=128).encode())
    127
    >>> _bounded_activity_record("short\n")
    'short\n'
    >>> _bounded_activity_record("tab\tπ\n")
    'tab\\tπ\n'

    Parameters
    ----------
    text : str
        Newline-terminated record to bound without splitting UTF-8 code points.
    max_bytes : int
        Positive encoded-byte ceiling including the trailing newline.

    Raises
    ------
    ValueError
        If the record is unterminated or the byte ceiling is not positive.
    """
    if not text.endswith("\n"):
        message = "activity record must be newline-terminated"
        raise ValueError(message)
    if type(max_bytes) is not int or max_bytes <= 0:
        message = "activity record byte ceiling must be a positive integer"
        raise ValueError(message)
    body = "".join(
        character
        if character.isprintable()
        else character.encode("unicode_escape").decode("ascii")
        for character in text[:-1]
    )
    text = f"{body}\n"
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    payload = encoded[: max_bytes - 1].decode(
        "utf-8",
        errors="ignore",
    )
    return f"{payload}\n"


def _epoch_pulse(epoch: int) -> str:
    r"""Return one exact bounded ASCII pulse for a completed activity epoch.

    >>> _epoch_pulse(7)
    'LIBTMUX_EPOCH epoch=7\n'

    Raises
    ------
    ValueError
        If ``epoch`` is not a nonnegative integer or its pulse exceeds 64 bytes.
    """
    if type(epoch) is not int or epoch < 0:
        message = "activity epoch must be a nonnegative integer"
        raise ValueError(message)
    pulse = f"LIBTMUX_EPOCH epoch={epoch}\n"
    if len(pulse.encode("ascii")) > EPOCH_PULSE_MAX_BYTES:
        message = f"activity epoch pulse must be at most {EPOCH_PULSE_MAX_BYTES} bytes"
        raise ValueError(message)
    return pulse


def render_frame(
    mode: StreamMode,
    epoch: int,
    corpus: tuple[str, ...],
    seed: int,
) -> Frame:
    r"""Render one deterministic newline-terminated activity record.

    >>> render_frame(StreamMode.DEV_SERVER, 4, (), 11).text
    '[dev-server epoch=4] recovery service=api state=ready\nLIBTMUX_EPOCH epoch=4\n'
    """
    if mode is StreamMode.EDITOR:
        source = corpus[(seed + epoch) % len(corpus)] if corpus else "<empty source>"
        text = f"[editor epoch={epoch}] {source}\n"
    elif mode is StreamMode.DEV_SERVER:
        records = (
            "request=GET /sessions status=200 elapsed_ms=5",
            "rebuild target=workspace state=complete modules=12",
            "warning code=W001 source=watcher action=retry",
            "recovery service=api state=ready",
        )
        text = f"[dev-server epoch={epoch}] {records[(seed + epoch) % len(records)]}\n"
    elif mode is StreamMode.INSTALLER:
        phases = ("resolve", "download", "build", "install")
        phase = phases[(seed + epoch) % len(phases)]
        text = f"[installer epoch={epoch}] install phase={phase} unit={epoch + 1}/8\n"
    else:
        text = f"[delayed-match epoch={epoch}] scan state=waiting cursor={epoch}\n"
    return Frame(
        mode=mode,
        epoch=epoch,
        text=_bounded_activity_record(
            text,
            max_bytes=(
                DELAYED_ACTIVITY_RECORD_MAX_BYTES
                if mode is StreamMode.DELAYED_MATCH
                else ACTIVITY_RECORD_MAX_BYTES
            ),
        )
        + _epoch_pulse(epoch),
    )


def prepare_output(options: WorkloadOptions) -> WorkloadPaths:
    """Create the exclusive marker tree and empty append-only stream files.

    Examples
    --------
    >>> with tempfile.TemporaryDirectory() as temporary:
    ...     root = pathlib.Path(temporary)
    ...     options = WorkloadOptions(
    ...         root / "output", "run-7", root, 0, 1.0, 1.0, 0.0, "READY", 1.0
    ...     )
    ...     paths = prepare_output(options)
    ...     sorted(path.name for path in paths.streams.iterdir())
    ['delayed-match.log', 'dev-server.log', 'editor.log', 'installer.log']

    Raises
    ------
    FileExistsError
        If another process already owns the requested output directory.
    """
    _validate_workload_identity(options)
    root = options.output_dir
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    streams = root / "streams"
    requests = root / "requests"
    sentinels = root / "sentinels"
    for directory in (streams, requests, sentinels):
        directory.mkdir()
    for mode in StreamMode:
        (streams / f"{mode.value}.log").touch(exist_ok=False)
    return WorkloadPaths(
        root=root,
        streams=streams,
        requests=requests,
        sentinels=sentinels,
        ready=root / "ready.json",
        gate=root / "gate.json",
        heartbeat=root / "heartbeat.json",
        stop=root / "stop.json",
    )


def _fsync_directory(path: pathlib.Path) -> None:
    """Make prior directory-entry changes durable.

    Examples
    --------
    >>> with tempfile.TemporaryDirectory() as temporary:
    ...     _fsync_directory(pathlib.Path(temporary))
    """
    directory_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY
    directory_fd = os.open(path, directory_flags)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def write_json_atomic(path: pathlib.Path, data: t.Mapping[str, t.Any]) -> None:
    r"""Replace a marker only after its JSON bytes are durable on disk.

    The sibling temporary file and replacement make readers see either the
    previous complete marker or the next complete marker, never a partial one.

    Examples
    --------
    >>> with tempfile.TemporaryDirectory() as temporary:
    ...     marker = pathlib.Path(temporary) / "marker.json"
    ...     write_json_atomic(marker, {"schema_version": 1})
    ...     marker.read_text(encoding="utf-8")
    '{"schema_version":1}\n'
    """
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        temporary_path = pathlib.Path(temporary.name)
        json.dump(data, temporary, sort_keys=True, separators=(",", ":"))
        temporary.write("\n")
        temporary.flush()
        os.fsync(temporary.fileno())
    try:
        os.replace(temporary_path, path)  # noqa: PTH105
        _fsync_directory(path.parent)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temporary_path.unlink()
        raise


def read_control_marker(path: pathlib.Path, run_id: str) -> dict[str, t.Any] | None:
    """Return a matching schema-v1 marker, ignoring absent or malformed files.

    >>> read_control_marker(pathlib.Path("missing.json"), "run-7") is None
    True
    """
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(parsed, dict):
        return None
    marker = t.cast(dict[str, t.Any], parsed)
    version = marker.get("schema_version")
    if type(version) is not int or version != 1 or marker.get("run_id") != run_id:
        return None
    return marker


def _gate_epoch(marker: dict[str, t.Any] | None) -> int | None:
    """Return the exact bounded epoch carried by a valid gate marker.

    >>> _gate_epoch({"epoch": 7})
    7
    >>> _gate_epoch({"epoch": True}) is None
    True
    """
    if marker is None:
        return None
    epoch = marker.get("epoch")
    if type(epoch) is not int or epoch < 0:
        return None
    try:
        _epoch_pulse(epoch)
    except ValueError:
        return None
    return epoch


def _stream_path(paths: WorkloadPaths, mode: StreamMode) -> pathlib.Path:
    """Return the append-only stream path for one mode."""
    return paths.streams / f"{mode.value}.log"


def _append_text(path: pathlib.Path, text: str, *, durable: bool = False) -> int:
    r"""Append one complete text record and return its UTF-8 byte count.

    Examples
    --------
    >>> with tempfile.TemporaryDirectory() as temporary:
    ...     stream = pathlib.Path(temporary) / "stream.log"
    ...     _append_text(stream, "pi\n"), stream.read_text(encoding="utf-8")
    (3, 'pi\n')

    Parameters
    ----------
    path : pathlib.Path
        Existing append-only stream.
    text : str
        Exact text to encode as UTF-8 and append.
    durable : bool
        Flush and fsync the append before returning when true.

    Returns
    -------
    int
        Number of exact encoded bytes appended.
    """
    encoded = text.encode("utf-8")
    with path.open("ab") as stream:
        stream.write(encoded)
        stream.flush()
        if durable:
            os.fsync(stream.fileno())
    return len(encoded)


def _request_from_marker(
    marker: dict[str, t.Any],
    path: pathlib.Path,
    options: WorkloadOptions,
    *,
    seen_request_ids: t.Container[str] = (),
) -> tuple[str, int, str] | None:
    """Validate one request marker and return its delayed sentinel inputs.

    Examples
    --------
    >>> options = WorkloadOptions(
    ...     pathlib.Path("out"), "run-7", pathlib.Path("."), 0, 1.0, 1.0,
    ...     0.0, "READY", 1.0,
    ... )
    >>> _request_from_marker(
    ...     {"request_id": "sample", "requested_monotonic_ns": 7},
    ...     pathlib.Path("sample.json"),
    ...     options,
    ...     seen_request_ids=set(),
    ... )
    ('sample', 7, 'READY')
    """
    request_id = marker.get("request_id")
    requested = marker.get("requested_monotonic_ns")
    value = marker.get("value", options.sentinel_prefix)
    if (
        not isinstance(request_id, str)
        or not request_id
        or not _is_terminal_safe_component(request_id)
        or path.name != f"{request_id}.json"
        or request_id in seen_request_ids
        or isinstance(requested, bool)
        or not isinstance(requested, int)
        or requested < 0
        or isinstance(value, bool)
        or not isinstance(value, str)
        or not _is_terminal_safe_component(value)
    ):
        return None
    try:
        sentinel_text(options.run_id, request_id, value)
    except ValueError:
        return None
    return request_id, requested, value


def _read_stable_request(
    path: pathlib.Path,
    options: WorkloadOptions,
    *,
    delay_ns: int,
    seen_request_ids: t.Container[str] = (),
) -> _PendingRequest | None:
    """Read one regular request whose pathname identity stays stable.

    The lstat sandwich relies on the private mode-0700 tree and trusted producer
    using atomic replacement; request markers are never edited in place.

    Examples
    --------
    >>> with tempfile.TemporaryDirectory() as temporary:
    ...     root = pathlib.Path(temporary)
    ...     marker = root / "sample.json"
    ...     write_json_atomic(marker, {
    ...         "schema_version": 1, "run_id": "run-7", "request_id": "sample",
    ...         "requested_monotonic_ns": 7,
    ...     })
    ...     options = WorkloadOptions(
    ...         root / "out", "run-7", root, 0, 1.0, 1.0, 0.0, "READY", 1.0
    ...     )
    ...     pending = _read_stable_request(marker, options, delay_ns=3)
    ...     pending.scheduled_monotonic_ns if pending is not None else None
    10
    """
    try:
        before = path.lstat()
    except OSError:
        return None
    if not stat.S_ISREG(before.st_mode):
        return None
    marker = read_control_marker(path, options.run_id)
    if marker is None:
        return None
    try:
        after = path.lstat()
    except OSError:
        return None
    if (
        not stat.S_ISREG(after.st_mode)
        or before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
    ):
        return None
    request = _request_from_marker(
        marker,
        path,
        options,
        seen_request_ids=seen_request_ids,
    )
    if request is None:
        return None
    request_id, requested_ns, value = request
    return _PendingRequest(
        request_id=request_id,
        requested_monotonic_ns=requested_ns,
        configured_delay_ns=delay_ns,
        scheduled_monotonic_ns=requested_ns + delay_ns,
        sentinel=sentinel_text(options.run_id, request_id, value),
        path=path,
        device=after.st_dev,
        inode=after.st_ino,
    )


def _consume_request(pending: _PendingRequest) -> None:
    """Remove the still-matching accepted marker and persist its deletion.

    Examples
    --------
    >>> with tempfile.TemporaryDirectory() as temporary:
    ...     request = pathlib.Path(temporary) / "sample.json"
    ...     _ = request.write_text("{}", encoding="utf-8")
    ...     identity = request.lstat()
    ...     pending = _PendingRequest(
    ...         "sample", 1, 0, 1, "READY", request,
    ...         identity.st_dev, identity.st_ino,
    ...     )
    ...     _consume_request(pending)
    ...     request.exists()
    False
    """
    try:
        current = pending.path.lstat()
    except FileNotFoundError as error:
        message = (
            f"accepted request marker removed before consumption: {pending.path.name}"
        )
        raise RuntimeError(message) from error
    if (
        not stat.S_ISREG(current.st_mode)
        or current.st_dev != pending.device
        or current.st_ino != pending.inode
    ):
        message = (
            f"accepted request marker replaced before consumption: {pending.path.name}"
        )
        raise RuntimeError(message)
    pending.path.unlink()
    _fsync_directory(pending.path.parent)


def run_serve(options: WorkloadOptions) -> int:
    """Serve paused deterministic streams until a matching stop or lifecycle exit.

    Examples
    --------
    >>> with tempfile.TemporaryDirectory() as temporary:
    ...     root = pathlib.Path(temporary)
    ...     import threading
    ...     options = WorkloadOptions(
    ...         root / "output", "run-7", root, 0, 1000.0, 0.001, 0.0,
    ...         "READY", 0.001,
    ...     )
    ...     def release_gate() -> None:
    ...         while not options.output_dir.exists():
    ...             time.sleep(0.001)
    ...         write_json_atomic(
    ...             options.output_dir / "gate.json",
    ...             {"schema_version": 1, "run_id": "run-7", "epoch": 0},
    ...         )
    ...     release = threading.Thread(target=release_gate)
    ...     release.start()
    ...     result = run_serve(options)
    ...     release.join()
    ...     result
    0

    Notes
    -----
    The service owns signals and a real marker tree, so its gate, timing, and
    shutdown behavior is exercised in ``tests/scripts/orchestration/test_fuzzer.py``.
    """
    _validate_workload_identity(options)
    if options.frame_rate_hz <= 0:
        message = "frame_rate_hz must be positive"
        raise ValueError(message)
    if options.duration_s <= 0:
        message = "duration_s must be positive"
        raise ValueError(message)
    if options.delayed_match_after_s < 0:
        message = "delayed_match_after_s must be non-negative"
        raise ValueError(message)
    if options.heartbeat_interval_s <= 0:
        message = "heartbeat_interval_s must be positive"
        raise ValueError(message)

    paths = prepare_output(options)
    corpus = source_lines(options.source_root, options.seed)
    write_json_atomic(paths.ready, {"schema_version": 1, "run_id": options.run_id})

    stopping = False

    def request_stop(_signal_number: int, _frame: t.Any) -> None:
        """Record a process signal for the serving loop."""
        nonlocal stopping
        stopping = True

    previous_sigint = signal.signal(signal.SIGINT, request_stop)
    previous_sigterm = signal.signal(signal.SIGTERM, request_stop)
    frame_interval_ns = max(1, int(1_000_000_000 / options.frame_rate_hz))
    delay_ns = int(options.delayed_match_after_s * 1_000_000_000)
    heartbeat_interval_ns = int(options.heartbeat_interval_s * 1_000_000_000)
    bytes_since_heartbeat = 0
    last_heartbeat_ns = 0
    activated_at_ns: int | None = None
    next_frame_ns: int | None = None
    epoch = 0
    seen_request_ids: set[str] = set()
    pending_request: _PendingRequest | None = None

    def publish_heartbeat(state: str, now_ns: int, force: bool = False) -> None:
        """Publish bounded liveness state when time or emitted bytes require it."""
        nonlocal bytes_since_heartbeat, last_heartbeat_ns
        if not force and (
            now_ns - last_heartbeat_ns < heartbeat_interval_ns
            and bytes_since_heartbeat < 65536
        ):
            return
        completed_epoch = epoch if activated_at_ns is None else max(0, epoch - 1)
        write_json_atomic(
            paths.heartbeat,
            {
                "schema_version": 1,
                "run_id": options.run_id,
                "state": state,
                "epoch": completed_epoch,
                "monotonic_ns": now_ns,
                "bytes_written": bytes_since_heartbeat,
            },
        )
        bytes_since_heartbeat = 0
        last_heartbeat_ns = now_ns

    try:
        while not stopping:
            now_ns = time.monotonic_ns()
            if read_control_marker(paths.stop, options.run_id) is not None:
                break

            if activated_at_ns is None:
                gate = read_control_marker(paths.gate, options.run_id)
                released_epoch = _gate_epoch(gate)
                if released_epoch is not None:
                    epoch = released_epoch
                    activated_at_ns = now_ns
                    next_frame_ns = now_ns
                else:
                    publish_heartbeat("paused", now_ns)
                    time.sleep(0.005)
                    continue

            assert activated_at_ns is not None
            assert next_frame_ns is not None
            if now_ns - activated_at_ns >= int(options.duration_s * 1_000_000_000):
                break

            while now_ns >= next_frame_ns:
                for mode in StreamMode:
                    frame = render_frame(mode, epoch, corpus, options.seed)
                    bytes_since_heartbeat += _append_text(
                        _stream_path(paths, mode),
                        frame.text,
                    )
                epoch += 1
                next_frame_ns += frame_interval_ns

            if pending_request is None:
                for request_path in sorted(paths.requests.glob("*.json")):
                    candidate = _read_stable_request(
                        request_path,
                        options,
                        delay_ns=delay_ns,
                        seen_request_ids=seen_request_ids,
                    )
                    if candidate is None:
                        continue
                    if (paths.sentinels / f"{candidate.request_id}.json").exists():
                        seen_request_ids.add(candidate.request_id)
                        continue
                    pending_request = candidate
                    seen_request_ids.add(candidate.request_id)
                    break

            if (
                pending_request is not None
                and now_ns >= pending_request.scheduled_monotonic_ns
            ):
                sentinel_record = f"{pending_request.sentinel}\n"
                sentinel_bytes = sentinel_record.encode()
                emitted_ns = time.monotonic_ns()
                bytes_since_heartbeat += _append_text(
                    _stream_path(paths, StreamMode.DELAYED_MATCH),
                    sentinel_record,
                    durable=True,
                )
                evidence = SentinelEvidence(
                    schema_version=1,
                    run_id=options.run_id,
                    request_id=pending_request.request_id,
                    requested_monotonic_ns=pending_request.requested_monotonic_ns,
                    configured_delay_ns=pending_request.configured_delay_ns,
                    scheduled_monotonic_ns=pending_request.scheduled_monotonic_ns,
                    emitted_monotonic_ns=emitted_ns,
                    scheduling_lateness_ns=(
                        emitted_ns - pending_request.scheduled_monotonic_ns
                    ),
                    sentinel=pending_request.sentinel,
                    sentinel_sha256=hashlib.sha256(sentinel_bytes).hexdigest(),
                )
                write_json_atomic(
                    paths.sentinels / f"{pending_request.request_id}.json",
                    dataclasses.asdict(evidence),
                )
                _consume_request(pending_request)
                pending_request = None

            publish_heartbeat("active", now_ns)
            sleep_ns = max(0, next_frame_ns - time.monotonic_ns())
            time.sleep(min(0.005, sleep_ns / 1_000_000_000))
    finally:
        now_ns = time.monotonic_ns()
        publish_heartbeat("stopped", now_ns, force=True)
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)
    return 0


def run_preview(options: WorkloadOptions) -> int:
    """Render deterministic frames interactively without importing Rich at load.

    Examples
    --------
    >>> with tempfile.TemporaryDirectory() as temporary:
    ...     root = pathlib.Path(temporary)
    ...     import io
    ...     options = WorkloadOptions(
    ...         root / "output", "run-7", root, 0, 1000.0, 0.001, 0.0,
    ...         "READY", 0.001,
    ...     )
    ...     with contextlib.redirect_stdout(io.StringIO()):
    ...         result = run_preview(options)
    ...     result
    0

    Notes
    -----
    This terminal UI requires a live Rich console. Its import boundary is
    exercised by the module-import tests; service rendering is covered by the
    dedicated functional test file.
    """
    _validate_workload_identity(options)
    if options.frame_rate_hz <= 0:
        message = "frame_rate_hz must be positive"
        raise ValueError(message)
    import rich.live
    import rich.text

    corpus = source_lines(options.source_root, options.seed)
    deadline = time.monotonic() + options.duration_s
    epoch = 0
    with rich.live.Live(refresh_per_second=10) as live:
        while time.monotonic() < deadline:
            rendered = [
                render_frame(mode, epoch, corpus, options.seed).text.rstrip()
                for mode in StreamMode
            ]
            live.update(rich.text.Text("\n".join(rendered)))
            epoch += 1
            time.sleep(1 / options.frame_rate_hz)
    return 0


def _options_from_namespace(arguments: argparse.Namespace) -> WorkloadOptions:
    """Convert parsed command-line values into the typed workload configuration.

    Examples
    --------
    >>> arguments = argparse.Namespace(
    ...     output_dir="out", run_id="run-7", source_root=".", seed=3,
    ...     frame_rate=2.0, duration=4.0, delayed_match_after=0.5,
    ...     sentinel_prefix="READY", heartbeat_interval=1.0,
    ... )
    >>> _options_from_namespace(arguments).run_id
    'run-7'
    """
    return WorkloadOptions(
        output_dir=pathlib.Path(arguments.output_dir),
        run_id=arguments.run_id,
        source_root=pathlib.Path(arguments.source_root),
        seed=arguments.seed,
        frame_rate_hz=arguments.frame_rate,
        duration_s=arguments.duration,
        delayed_match_after_s=arguments.delayed_match_after,
        sentinel_prefix=arguments.sentinel_prefix,
        heartbeat_interval_s=arguments.heartbeat_interval,
    )


def main(argv: t.Sequence[str] | None = None) -> int:
    """Run the ``serve`` or Rich ``preview`` command.

    Examples
    --------
    >>> with tempfile.TemporaryDirectory() as temporary:
    ...     root = pathlib.Path(temporary)
    ...     import io
    ...     with contextlib.redirect_stdout(io.StringIO()):
    ...         result = main([
    ...             "preview", "--output-dir", str(root / "output"),
    ...             "--run-id", "run-7", "--source-root", str(root),
    ...             "--frame-rate", "1000", "--duration", "0.001",
    ...             "--delayed-match-after", "0", "--heartbeat-interval", "0.001",
    ...         ])
    ...     result
    0

    Notes
    -----
    The real ``serve`` command is invoked through ``sys.executable`` in the
    dedicated functional test file so its process lifecycle stays observable.
    """
    parser = argparse.ArgumentParser(
        prog="scripts/orchestration/fuzzer.py",
        description=(
            "Render deterministic frames into append-only stream files. One "
            "process serves every stream, and benchmark panes follow one "
            "stream each, so a large topology stays active under a single "
            "workload clock."
        ),
        epilog=(
            "Modes are assigned round-robin by stable pane ordinal: editor, "
            "dev-server, installer, and delayed-match. The delayed-match "
            "stream appends a unique sentinel after each request's monotonic "
            "delay."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    descriptions = {
        "serve": (
            "Start paused, publish a ready marker, and emit frames only after "
            "the benchmark releases its activity gate."
        ),
        "preview": "Render the same frames interactively without serving them.",
    }
    for command in ("serve", "preview"):
        command_parser = commands.add_parser(
            command,
            help=descriptions[command],
            description=descriptions[command],
        )
        command_parser.add_argument(
            "--output-dir",
            default="orchestration-fuzzer",
            help="directory used for markers and append-only streams",
        )
        command_parser.add_argument(
            "--run-id",
            default="run-0",
            help="run identity carried by every control marker",
        )
        command_parser.add_argument(
            "--source-root",
            default=".",
            help="repository root containing src/libtmux source files",
        )
        command_parser.add_argument(
            "--seed",
            type=int,
            default=0,
            help="seed that fixes corpus and frame selection",
        )
        command_parser.add_argument(
            "--frame-rate",
            type=float,
            default=10.0,
            help="number of frames emitted per stream each second",
        )
        command_parser.add_argument(
            "--duration",
            type=float,
            default=60.0,
            help="maximum serving duration after activation",
        )
        command_parser.add_argument(
            "--delayed-match-after",
            type=float,
            default=1.0,
            help="delay between an accepted request and its sentinel emission",
        )
        command_parser.add_argument(
            "--sentinel-prefix",
            default="READY",
            help="human-readable prefix for each unique sentinel",
        )
        command_parser.add_argument(
            "--heartbeat-interval",
            type=float,
            default=0.25,
            help="maximum interval between heartbeat marker updates",
        )
    arguments = parser.parse_args(argv)
    options = _options_from_namespace(arguments)
    if arguments.command == "serve":
        return run_serve(options)
    return run_preview(options)


if __name__ == "__main__":
    raise SystemExit(main())
