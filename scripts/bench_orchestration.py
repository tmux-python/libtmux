#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["rich>=13"]
# ///
"""Plan and report hermetic active-tmux orchestration benchmark runs.

The ``plan`` command intentionally depends only on host files.  It does not
import libtmux or start a tmux server.
"""

from __future__ import annotations

import argparse
import asyncio
import collections.abc as cabc
import contextlib
import dataclasses
import enum
import hashlib
import inspect
import json
import math
import os
import pathlib
import random
import resource
import shlex
import shutil
import signal
import stat
import statistics
import subprocess
import sys
import tempfile
import time
import types
import typing as t
import uuid

if t.TYPE_CHECKING:
    from libtmux.experimental.engines.base import AsyncTmuxEngine, TmuxEngine
    from libtmux.experimental.models import (
        ClientSnapshot,
        PaneSnapshot,
        SessionSnapshot,
        WindowSnapshot,
    )
    from libtmux.experimental.ops.operation import Operation
    from libtmux.experimental.ops.plan import LazyPlan
    from libtmux.experimental.ops.planner import Planner
    from libtmux.experimental.workspace import WorkspaceSet
    from libtmux.server import Server


_SENTINEL_DELAY_S = 0.05
_SENTINEL_DELAY_NS = 50_000_000


class EngineLane(str, enum.Enum):
    """Transport family used for one live benchmark server.

    Examples
    --------
    >>> EngineLane("control") is EngineLane.CONTROL
    True
    """

    SUBPROCESS = "subprocess"
    CONTROL = "control"


class ExecutionMode(str, enum.Enum):
    """Synchronous or asynchronous operation execution.

    Examples
    --------
    >>> ExecutionMode("async") is ExecutionMode.ASYNC
    True
    """

    SYNC = "sync"
    ASYNC = "async"


@dataclasses.dataclass(frozen=True)
class Topology:
    """Requested active tmux hierarchy.

    Attributes
    ----------
    sessions : int
        Number of tmux sessions.
    windows_per_session : int
        Windows created in each session.
    panes_per_window : int
        Panes created in each window.
    """

    sessions: int
    windows_per_session: int
    panes_per_window: int

    @property
    def windows(self) -> int:
        """Return the exact number of windows.

        >>> Topology(2, 3, 4).windows
        6

        Returns
        -------
        int
            Sessions multiplied by windows per session.
        """
        return self.sessions * self.windows_per_session

    @property
    def panes(self) -> int:
        """Return the exact number of panes.

        >>> Topology(2, 3, 4).panes
        24

        Returns
        -------
        int
            Total windows multiplied by panes per window.
        """
        return self.windows * self.panes_per_window

    def __str__(self) -> str:
        """Return the portable ``SxWxP`` shape.

        >>> str(Topology(2, 3, 4))
        '2x3x4'

        Returns
        -------
        str
            Lower-case ``SxWxP`` representation.
        """
        return f"{self.sessions}x{self.windows_per_session}x{self.panes_per_window}"


class Reader(t.Protocol):
    """Read host limits without binding the pure model to the live filesystem."""

    def read_text(self, path: str) -> str:
        """Return the decoded contents at ``path``.

        >>> reader: Reader = _DoctestReader({"/value": "contents"})
        >>> reader.read_text("/value")
        'contents'

        Parameters
        ----------
        path : str
            Absolute procfs or cgroup path to read.

        Returns
        -------
        str
            Decoded text from the requested path.

        Raises
        ------
        OSError
            If the host path cannot be read.
        """

    def getrlimit(self, kind: int) -> tuple[int, int]:
        """Return the current process's soft and hard limit for ``kind``.

        >>> reader: Reader = _DoctestReader({})
        >>> reader.getrlimit(resource.RLIMIT_NOFILE)
        (1, 1)

        Parameters
        ----------
        kind : int
            Platform resource-limit identifier.

        Returns
        -------
        tuple[int, int]
            Soft and hard limits for the requested resource.

        Raises
        ------
        OSError
            If the process resource limit cannot be read.
        ValueError
            If ``kind`` is not a recognized resource.
        """


class ProcessReader:
    """Read the host information used by the side-effect-free plan command."""

    def read_text(self, path: str) -> str:
        """Read a procfs or cgroup text file without starting another process.

        >>> isinstance(ProcessReader().read_text("/proc/meminfo"), str)
        True

        Parameters
        ----------
        path : str
            Absolute procfs or cgroup path to read.

        Returns
        -------
        str
            UTF-8 text read from the host path.

        Raises
        ------
        OSError
            If the path cannot be read.
        UnicodeError
            If the file is not valid UTF-8 text.
        """
        return pathlib.Path(path).read_text(encoding="utf-8")

    def getrlimit(self, kind: int) -> tuple[int, int]:
        """Return the process resource limit requested by the probe.

        >>> ProcessReader().getrlimit(resource.RLIMIT_NOFILE)[0] > 0
        True

        Parameters
        ----------
        kind : int
            Platform resource-limit identifier.

        Returns
        -------
        tuple[int, int]
            Soft and hard limits for the requested resource.

        Raises
        ------
        ValueError
            If ``kind`` is not a recognized resource.
        """
        return resource.getrlimit(kind)


@dataclasses.dataclass(frozen=True)
class HostSnapshot:
    """Resource values observed before or during one benchmark phase.

    Attributes
    ----------
    available_memory_bytes : int | None
        Host ``MemAvailable`` capacity, when procfs exposed it.
    physical_memory_bytes : int | None
        Host physical memory from ``MemTotal``.
    memory_current_bytes : int | None
        Unified-cgroup current memory consumption.
    memory_max_bytes : int | None
        Unified-cgroup memory limit; ``None`` means unknown or unlimited.
    pids_current : int | None
        Unified-cgroup current process count.
    pids_max : int | None
        Unified-cgroup PID limit; ``None`` means unknown or unlimited.
    nofile_soft_limit : int | None
        Current process soft file-descriptor limit.
    nofile_hard_limit : int | None
        Current process hard file-descriptor limit.
    memory_pressure_some_avg10 : float | None
        Ten-second cgroup memory pressure average.
    source_errors : collections.abc.Mapping[str, str]
        Source-specific errors retained instead of replacing missing data with zero.
    """

    available_memory_bytes: int | None = None
    physical_memory_bytes: int | None = None
    memory_current_bytes: int | None = None
    memory_max_bytes: int | None = None
    pids_current: int | None = None
    pids_max: int | None = None
    nofile_soft_limit: int | None = None
    nofile_hard_limit: int | None = None
    memory_pressure_some_avg10: float | None = None
    source_errors: cabc.Mapping[str, str] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze source errors independently of their caller-provided mapping.

        >>> snapshot = HostSnapshot(source_errors={"proc": "missing"})
        >>> snapshot.source_errors["proc"]
        'missing'
        """
        object.__setattr__(
            self, "source_errors", types.MappingProxyType(dict(self.source_errors))
        )


@dataclasses.dataclass(frozen=True)
class ResourcePolicy:
    """Conservative admission thresholds for a proposed topology.

    Attributes
    ----------
    persistent_clients : int
        Persistent tmux clients declared by the selected execution lane.
    pid_reserve : int | None
        Explicit remaining-PID reserve, or the documented dynamic default.
    memory_floor_bytes : int | None
        Explicit available-memory floor, or the documented dynamic default.
    """

    persistent_clients: int = 1
    pid_reserve: int | None = None
    memory_floor_bytes: int | None = None


@dataclasses.dataclass(frozen=True)
class GuardDecision:
    """The admission or runtime decision and the snapshot supporting it.

    Attributes
    ----------
    allowed : bool
        Whether the benchmark may proceed at this checkpoint.
    kind : {"ok", "predictive_refusal", "runtime_cutoff"}
        Decision category.
    rule : str | None
        Named guard that made the decision.
    observed : int | float | None
        Measured or projected value that triggered the rule.
    limit : int | float | None
        Applicable guard limit.
    forceable : bool
        Whether ``--force-extreme`` may override the decision.
    snapshot : HostSnapshot
        Resource observation used by the guard.
    """

    allowed: bool
    kind: t.Literal["ok", "predictive_refusal", "runtime_cutoff"]
    rule: str | None
    observed: int | float | None
    limit: int | float | None
    forceable: bool
    snapshot: HostSnapshot


def _source_error(errors: dict[str, str], label: str, exc: Exception) -> None:
    """Record one probe failure without substituting a fabricated numeric value.

    >>> errors: dict[str, str] = {}
    >>> _source_error(errors, "pids.current", FileNotFoundError("missing"))
    >>> "pids.current" in errors
    True

    Parameters
    ----------
    errors : dict[str, str]
        Mutable destination for source-specific probe failures.
    label : str
        Stable source name stored in the error mapping.
    exc : Exception
        Failure whose type and message are retained.
    """
    errors[label] = f"{type(exc).__name__}: {exc}"


def _parse_meminfo(text: str) -> dict[str, int]:
    r"""Parse selected ``/proc/meminfo`` values as bytes.

    >>> _parse_meminfo("MemTotal: 2 kB\nMemAvailable: 1 kB\n")
    {'MemTotal': 2048, 'MemAvailable': 1024}

    Parameters
    ----------
    text : str
        Literal contents of ``/proc/meminfo``.

    Returns
    -------
    dict[str, int]
        Recognized memory fields converted from kibibytes to bytes.
    """
    values: dict[str, int] = {}
    for line in text.splitlines():
        name, separator, raw_value = line.partition(":")
        fields = raw_value.split()
        if not separator or len(fields) < 2 or fields[1] != "kB":
            continue
        try:
            values[name] = int(fields[0]) * 1024
        except ValueError:
            continue
    return values


def _unified_cgroup_path(cgroup: str, mountinfo: str) -> str:
    r"""Resolve this process's cgroup-v2 directory from literal procfs data.

    >>> _unified_cgroup_path("0::/scope\n", "1 0 0:1 / /cg rw - cgroup2 cgroup rw\n")
    '/cg/scope'

    Parameters
    ----------
    cgroup : str
        Literal contents of ``/proc/self/cgroup``.
    mountinfo : str
        Literal contents of ``/proc/self/mountinfo``.

    Returns
    -------
    str
        Absolute path to the process's unified-cgroup directory.

    Raises
    ------
    ValueError
        If the unified hierarchy or cgroup-v2 mount cannot be resolved.
    """
    relative: str | None = None
    for line in cgroup.splitlines():
        hierarchy, separator, path = line.partition("::")
        if separator and hierarchy == "0":
            relative = path
            break
    if relative is None:
        message = "unified cgroup path is unavailable"
        raise ValueError(message)
    for line in mountinfo.splitlines():
        before, separator, after = line.partition(" - ")
        if not separator or not after.split() or after.split()[0] != "cgroup2":
            continue
        fields = before.split()
        if len(fields) < 5:
            continue
        root, mountpoint = fields[3], fields[4]
        suffix = relative.removeprefix(root).lstrip("/")
        return str(pathlib.PurePosixPath(mountpoint, suffix))
    message = "cgroup2 mount is unavailable"
    raise ValueError(message)


def _read_int(reader: Reader, path: str, errors: dict[str, str]) -> int | None:
    r"""Read a finite integer limit, preserving failures in ``errors``.

    >>> _read_int(_DoctestReader({"/value": "7\n"}), "/value", {})
    7

    Parameters
    ----------
    reader : Reader
        Injectable host-data source.
    path : str
        Absolute path containing an integer or ``max``.
    errors : dict[str, str]
        Mutable destination for a source-specific failure.

    Returns
    -------
    int | None
        Finite integer value, or ``None`` for unlimited or unreadable data.
    """
    try:
        value = reader.read_text(path).strip()
        return None if value == "max" else int(value)
    except (OSError, ValueError, KeyError) as exc:
        _source_error(errors, pathlib.PurePosixPath(path).name, exc)
        return None


class _DoctestReader:
    """Small in-memory reader used only by executable helper examples.

    Attributes
    ----------
    values : dict[str, str]
        Literal content keyed by absolute source path.
    """

    def __init__(self, values: dict[str, str]) -> None:
        """Store literal host data for an executable example.

        >>> _DoctestReader({"/value": "7"}).values["/value"]
        '7'

        Parameters
        ----------
        values : dict[str, str]
            Literal content keyed by absolute source path.
        """
        self.values = values

    def read_text(self, path: str) -> str:
        """Return a configured path's content.

        >>> _DoctestReader({"/value": "7"}).read_text("/value")
        '7'

        Parameters
        ----------
        path : str
            Configured absolute source path.

        Returns
        -------
        str
            Literal content configured for ``path``.

        Raises
        ------
        KeyError
            If ``path`` was not configured.
        """
        return self.values[path]

    def getrlimit(self, kind: int) -> tuple[int, int]:
        """Return a harmless finite descriptor limit.

        >>> _DoctestReader({}).getrlimit(resource.RLIMIT_NOFILE)
        (1, 1)

        Parameters
        ----------
        kind : int
            Resource identifier accepted for protocol compatibility.

        Returns
        -------
        tuple[int, int]
            Fixed soft and hard limits for examples.
        """
        return (1, 1)


def _pressure_some_avg10(text: str) -> float | None:
    r"""Extract the cgroup memory pressure ``some`` ten-second average.

    >>> _pressure_some_avg10("some avg10=0.25 avg60=0.1 total=2\n")
    0.25

    Parameters
    ----------
    text : str
        Literal contents of a cgroup pressure file.

    Returns
    -------
    float | None
        Ten-second ``some`` pressure average, or ``None`` when absent.

    Raises
    ------
    ValueError
        If the ``avg10`` value is not numeric.
    """
    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0] != "some":
            continue
        for field in fields[1:]:
            if field.startswith("avg10="):
                return float(field.removeprefix("avg10="))
    return None


def probe_host(reader: Reader) -> HostSnapshot:
    r"""Probe host and unified-cgroup resources through an injectable reader.

    Missing or malformed telemetry remains ``None`` and records a source error.

    >>> snapshot = probe_host(_DoctestReader({
    ...     "/proc/meminfo": "MemTotal: 2 kB\nMemAvailable: 1 kB\n",
    ...     "/proc/self/cgroup": "0::/scope\n",
    ...     "/proc/self/mountinfo": "1 0 0:1 / /cg rw - cgroup2 cgroup rw\n",
    ...     "/cg/scope/pids.current": "1\n", "/cg/scope/pids.max": "2\n",
    ...     "/cg/scope/memory.current": "3\n", "/cg/scope/memory.max": "4\n",
    ...     "/cg/scope/memory.pressure": "some avg10=0.0 total=0\n",
    ... }))
    >>> (snapshot.available_memory_bytes, snapshot.pids_max)
    (1024, 2)

    Parameters
    ----------
    reader : Reader
        Injectable source for procfs, cgroup, and process-limit data.

    Returns
    -------
    HostSnapshot
        Observed values plus source-specific errors for unavailable telemetry.
    """
    errors: dict[str, str] = {}
    memory: dict[str, int] = {}
    try:
        memory = _parse_meminfo(reader.read_text("/proc/meminfo"))
    except (OSError, ValueError, KeyError) as exc:
        _source_error(errors, "meminfo", exc)
    if "MemAvailable" not in memory:
        errors.setdefault("MemAvailable", "unavailable from /proc/meminfo")
    if "MemTotal" not in memory:
        errors.setdefault("MemTotal", "unavailable from /proc/meminfo")

    cgroup_path: str | None = None
    try:
        cgroup_path = _unified_cgroup_path(
            reader.read_text("/proc/self/cgroup"),
            reader.read_text("/proc/self/mountinfo"),
        )
    except (OSError, ValueError, KeyError) as exc:
        _source_error(errors, "cgroup2", exc)

    pids_current = pids_max = memory_current = memory_max = None
    pressure: float | None = None
    if cgroup_path is not None:
        pids_current = _read_int(reader, f"{cgroup_path}/pids.current", errors)
        pids_max = _read_int(reader, f"{cgroup_path}/pids.max", errors)
        memory_current = _read_int(reader, f"{cgroup_path}/memory.current", errors)
        memory_max = _read_int(reader, f"{cgroup_path}/memory.max", errors)
        try:
            pressure = _pressure_some_avg10(
                reader.read_text(f"{cgroup_path}/memory.pressure")
            )
            if pressure is None:
                errors["memory.pressure"] = "ValueError: missing some avg10"
        except (OSError, ValueError, KeyError) as exc:
            _source_error(errors, "memory.pressure", exc)
    nofile_soft: int | None
    nofile_hard: int | None
    try:
        nofile_soft, nofile_hard = reader.getrlimit(resource.RLIMIT_NOFILE)
    except (OSError, ValueError) as exc:
        _source_error(errors, "RLIMIT_NOFILE", exc)
        nofile_soft = nofile_hard = None
    return HostSnapshot(
        available_memory_bytes=memory.get("MemAvailable"),
        physical_memory_bytes=memory.get("MemTotal"),
        memory_current_bytes=memory_current,
        memory_max_bytes=memory_max,
        pids_current=pids_current,
        pids_max=pids_max,
        nofile_soft_limit=nofile_soft,
        nofile_hard_limit=nofile_hard,
        memory_pressure_some_avg10=pressure,
        source_errors=errors,
    )


def _default_pid_reserve(snapshot: HostSnapshot) -> int | None:
    """Return the documented dynamic PID reserve when a limit is known.

    >>> _default_pid_reserve(HostSnapshot(pids_max=10_000))
    1500

    Parameters
    ----------
    snapshot : HostSnapshot
        Host observation containing the unified-cgroup PID limit.

    Returns
    -------
    int | None
        Larger of 1,024 processes and 15 percent of the limit, or ``None``.
    """
    if snapshot.pids_max is None:
        return None
    return max(1024, math.ceil(snapshot.pids_max * 0.15))


def _default_memory_floor(snapshot: HostSnapshot) -> int | None:
    """Return the documented dynamic memory floor when physical memory is known.

    >>> _default_memory_floor(HostSnapshot(physical_memory_bytes=10 * 2**30))
    4294967296

    Parameters
    ----------
    snapshot : HostSnapshot
        Host observation containing detected physical memory.

    Returns
    -------
    int | None
        Larger of 4 GiB and 15 percent of physical memory, or ``None``.
    """
    if snapshot.physical_memory_bytes is None:
        return None
    return max(4 * 2**30, math.ceil(snapshot.physical_memory_bytes * 0.15))


def predict_resources(
    topology: Topology,
    snapshot: HostSnapshot,
    policy: ResourcePolicy | None = None,
) -> GuardDecision:
    """Apply forceable preflight guards without estimating uncalibrated memory.

    >>> snapshot = HostSnapshot(pids_current=1, pids_max=2000)
    >>> decision = predict_resources(Topology(1, 1, 1), snapshot)
    >>> decision.kind
    'ok'

    Parameters
    ----------
    topology : Topology
        Proposed active tmux hierarchy.
    snapshot : HostSnapshot
        Host resource observation used for admission.
    policy : ResourcePolicy | None
        Explicit resource thresholds, or documented dynamic defaults.

    Returns
    -------
    GuardDecision
        Predictive admission or forceable refusal with supporting evidence.
    """
    policy = policy or ResourcePolicy()
    reserve = (
        policy.pid_reserve
        if policy.pid_reserve is not None
        else _default_pid_reserve(snapshot)
    )
    if (
        snapshot.pids_current is not None
        and snapshot.pids_max is not None
        and reserve is not None
    ):
        projected = (
            snapshot.pids_current + topology.panes + 2 + policy.persistent_clients
        )
        usable_limit = snapshot.pids_max - reserve
        if projected > usable_limit:
            return GuardDecision(
                allowed=False,
                kind="predictive_refusal",
                rule="pid_reserve",
                observed=projected,
                limit=usable_limit,
                forceable=True,
                snapshot=snapshot,
            )
    floor = (
        policy.memory_floor_bytes
        if policy.memory_floor_bytes is not None
        else _default_memory_floor(snapshot)
    )
    if (
        snapshot.available_memory_bytes is not None
        and floor is not None
        and snapshot.available_memory_bytes < floor
    ):
        return GuardDecision(
            allowed=False,
            kind="predictive_refusal",
            rule="memory_floor",
            observed=snapshot.available_memory_bytes,
            limit=floor,
            forceable=True,
            snapshot=snapshot,
        )
    return GuardDecision(True, "ok", None, None, None, False, snapshot)


def check_runtime_guard(
    snapshot: HostSnapshot,
    *,
    policy: ResourcePolicy | None = None,
    processes_alive: bool = True,
    topology_verified: bool = True,
    watchdog_ok: bool = True,
    cleanup_complete: bool = True,
    force_extreme: bool = False,
) -> GuardDecision:
    """Apply non-forceable guards to live benchmark observations.

    ``force_extreme`` is accepted only to make explicit that it cannot relax a
    runtime cutoff.

    >>> check_runtime_guard(HostSnapshot(pids_current=2000, pids_max=2000)).kind
    'runtime_cutoff'

    Parameters
    ----------
    snapshot : HostSnapshot
        Live host resource observation.
    policy : ResourcePolicy | None
        Explicit resource thresholds, or documented dynamic defaults.
    processes_alive : bool
        Whether every benchmark-owned pane and fuzzer process is alive.
    topology_verified : bool
        Whether the observed tmux hierarchy exactly matches the request.
    watchdog_ok : bool
        Whether the active phase remains within its progress deadline.
    cleanup_complete : bool
        Whether terminal cleanup removed every benchmark-owned resource.
    force_extreme : bool
        Predictive override flag, accepted here but never applied at runtime.

    Returns
    -------
    GuardDecision
        Non-forceable cutoff for the first failed runtime guard, otherwise success.
    """
    del force_extreme
    policy = policy or ResourcePolicy()
    reserve = (
        policy.pid_reserve
        if policy.pid_reserve is not None
        else _default_pid_reserve(snapshot)
    )
    if (
        snapshot.pids_current is not None
        and snapshot.pids_max is not None
        and reserve is not None
    ):
        usable_limit = snapshot.pids_max - reserve
        if snapshot.pids_current > usable_limit:
            return GuardDecision(
                False,
                "runtime_cutoff",
                "pid_reserve",
                snapshot.pids_current,
                usable_limit,
                False,
                snapshot,
            )
    floor = (
        policy.memory_floor_bytes
        if policy.memory_floor_bytes is not None
        else _default_memory_floor(snapshot)
    )
    if (
        snapshot.available_memory_bytes is not None
        and floor is not None
        and snapshot.available_memory_bytes < floor
    ):
        return GuardDecision(
            False,
            "runtime_cutoff",
            "memory_floor",
            snapshot.available_memory_bytes,
            floor,
            False,
            snapshot,
        )
    for rule, valid in (
        ("dead_process", processes_alive),
        ("topology", topology_verified),
        ("watchdog", watchdog_ok),
        ("cleanup", cleanup_complete),
    ):
        if not valid:
            return GuardDecision(
                False, "runtime_cutoff", rule, None, None, False, snapshot
            )
    return GuardDecision(True, "ok", None, None, None, False, snapshot)


@dataclasses.dataclass(frozen=True)
class RawSample:
    """One timed phase result retained before statistical aggregation.

    Attributes
    ----------
    duration_ns : int | None
        Measured integer duration, if the timing completed.
    accepted : bool
        Whether phase correctness accepted this value for a summary.
    error : str | None
        Failure detail for a rejected sample.
    verified : bool
        Whether the phase's correctness check accepted this timing.
    strategy : str | None
        Strategy that produced the accepted sample.
    ordinal : int | None
        Zero-based timed ordinal within that strategy.
    resources_before : HostSnapshot | None
        Resource observation immediately before execution.
    resources_after : HostSnapshot | None
        Resource observation after typed and live validation.

    Examples
    --------
    >>> RawSample(7, True, verified=True, strategy="serial").duration_ns
    7
    """

    duration_ns: int | None
    accepted: bool
    error: str | None = None
    verified: bool = False
    strategy: str | None = None
    ordinal: int | None = None
    resources_before: HostSnapshot | None = None
    resources_after: HostSnapshot | None = None


@dataclasses.dataclass(frozen=True)
class ExecutionMetrics:
    """Logical request and transport work for one phase measurement.

    Attributes
    ----------
    operations : int
        Typed operations in the phase's measured plan or cell.
    planner_steps : int
        Planner steps used to dispatch those operations.
    engine_batches : int
        Engine dispatch calls made for the measured operations.
    tmux_requests : int
        Individually attributable tmux requests.
    process_starts : int
        Subprocess transport starts, one per request; zero for control mode.

    Examples
    --------
    >>> ExecutionMetrics(12, 1, 1, 12, 0).tmux_requests
    12
    """

    operations: int
    planner_steps: int
    engine_batches: int
    tmux_requests: int
    process_starts: int


@dataclasses.dataclass(frozen=True)
class HeartbeatObservation:
    """One run-scoped fuzzer heartbeat observed by the benchmark.

    Attributes
    ----------
    epoch : int
        Active fuzzer epoch published in the atomic heartbeat marker.
    published_monotonic_ns : int
        Fuzzer monotonic timestamp stored with that epoch.
    observed_monotonic_ns : int
        Benchmark monotonic timestamp immediately after reading the marker.

    Examples
    --------
    >>> HeartbeatObservation(4, 10, 12).epoch
    4
    """

    epoch: int
    published_monotonic_ns: int
    observed_monotonic_ns: int


@dataclasses.dataclass(frozen=True)
class SentinelRequest:
    """One unique delayed-stream request published by the benchmark.

    Attributes
    ----------
    request_id : str
        Run-local canonical marker identity.
    token : str
        Exact canonical sentinel text expected from the delayed pane.
    requested_monotonic_ns : int
        Monotonic timestamp captured immediately before atomic publication.
    configured_delay_ns : int
        Fuzzer delay added to the request timestamp.

    Examples
    --------
    >>> SentinelRequest("sample-1", "token", 7, 5).configured_delay_ns
    5
    """

    request_id: str
    token: str
    requested_monotonic_ns: int
    configured_delay_ns: int


WaitStrategy: t.TypeAlias = t.Literal["capture-poll", "control-stream"]


@dataclasses.dataclass(frozen=True)
class WaitResult:
    """Verified delayed-sentinel detection and generator timing evidence.

    Attributes
    ----------
    strategy : {"capture-poll", "control-stream"}
        Observation mechanism used for this request.
    request_id : str
        Exact run-local request identity.
    token : str
        Exact canonical sentinel matched in the selected pane.
    pane_id : str
        Concrete delayed pane ID observed by the waiter.
    configured_delay_ns : int
        Fuzzer delay applied after request publication.
    requested_monotonic_ns : int
        Benchmark timestamp immediately before atomic request publication.
    scheduled_monotonic_ns : int
        Requested timestamp plus the configured delay.
    emitted_monotonic_ns : int
        Fuzzer timestamp immediately before the durable stream append.
    detected_monotonic_ns : int
        Benchmark timestamp when the exact sentinel bytes were detected.
    scheduling_lateness_ns : int
        Emitted timestamp minus scheduled timestamp.
    detection_overhead_ns : int
        Detected timestamp minus emitted timestamp.
    poll_count : int
        Typed capture requests issued by capture polling.
    frame_count : int
        Matching-pane control output frames consumed by stream waiting.
    timeout_s : float
        Configured monotonic wait deadline in seconds.
    timed_out : bool
        Whether the returned result represents a timeout; successful waits are false.
    dropped_notification_delta : int
        Control-engine notification drops observed during this request.
    verified : bool
        Whether exact token, evidence, timing, pane, and drop checks passed.

    Examples
    --------
    >>> result = WaitResult(
    ...     "capture-poll", "sample-1", "token", "%1", 5, 7, 12, 14, 17,
    ...     2, 3, 1, 0, 1.0, False, 0, True,
    ... )
    >>> result.duration_ns
    3
    """

    strategy: WaitStrategy
    request_id: str
    token: str
    pane_id: str
    configured_delay_ns: int
    requested_monotonic_ns: int
    scheduled_monotonic_ns: int
    emitted_monotonic_ns: int
    detected_monotonic_ns: int
    scheduling_lateness_ns: int
    detection_overhead_ns: int
    poll_count: int
    frame_count: int
    timeout_s: float
    timed_out: bool
    dropped_notification_delta: int
    verified: bool

    @property
    def duration_ns(self) -> int:
        """Return waiter overhead with the deliberate delay excluded.

        >>> WaitResult(
        ...     "control-stream", "r", "t", "%1", 5, 7, 12, 14, 18,
        ...     2, 4, 0, 1, 1.0, False, 0, True,
        ... ).duration_ns
        4

        Returns
        -------
        int
            Detection timestamp minus actual emission timestamp.
        """
        return self.detection_overhead_ns


@dataclasses.dataclass(frozen=True)
class MutationResult:
    """Verified and restored bulk mutation measurement.

    Attributes
    ----------
    duration_ns : int
        Mutation plan duration excluding verification and restoration.
    metrics : ExecutionMetrics
        Logical operation, planning, request, and transport counts.
    session_id : str
        Concrete session ID selected by maximum window cardinality.
    window_ids : tuple[str, ...]
        Concrete window IDs renamed by the plan.
    pane_ids : tuple[str, ...]
        Concrete pane IDs titled by the plan.
    generation : str
        Exact generation option value set during verification.
    verified : bool
        Whether all mutated live values matched the plan.
    restored : bool
        Whether canonical names, titles, and option state were restored.
    restoration_verified_monotonic_ns : int
        Local timestamp taken after restored-state verification.
    activity_baseline : HeartbeatObservation
        Fresh heartbeat read only after restoration verification.
    activity_after : HeartbeatObservation
        Strictly later heartbeat proving continued activity.

    Examples
    --------
    >>> result = MutationResult(
    ...     5, ExecutionMetrics(3, 1, 1, 3, 0), "$1", ("@2",), ("%3",),
    ...     "7", True, True, 9, HeartbeatObservation(4, 8, 10),
    ...     HeartbeatObservation(5, 11, 12),
    ... )
    >>> result.restored and result.activity_after.epoch > result.activity_baseline.epoch
    True
    """

    duration_ns: int
    metrics: ExecutionMetrics
    session_id: str
    window_ids: tuple[str, ...]
    pane_ids: tuple[str, ...]
    generation: str
    verified: bool
    restored: bool
    restoration_verified_monotonic_ns: int
    activity_baseline: HeartbeatObservation
    activity_after: HeartbeatObservation


EnumerationKind: t.TypeAlias = t.Literal["sessions", "windows", "panes"]


@dataclasses.dataclass(frozen=True)
class EnumerationResult:
    """One exact typed hierarchy enumeration.

    Attributes
    ----------
    duration_ns : int
        Time spent executing and parsing the typed list operation.
    metrics : ExecutionMetrics
        One-operation dispatch counts for this list level.
    kind : {"sessions", "windows", "panes"}
        Hierarchy level enumerated.
    row_count : int
        Exact number of typed rows returned.
    ids : tuple[str, ...]
        Concrete IDs in verified stable order.
    id_checksum : str
        SHA-256 over NUL-separated concrete IDs.
    verified : bool
        Whether row count, IDs, and checksum match the live run context.

    Examples
    --------
    >>> EnumerationResult(
    ...     3, ExecutionMetrics(1, 1, 1, 1, 0), "sessions", 1,
    ...     ("$0",), "digest", True,
    ... ).row_count
    1
    """

    duration_ns: int
    metrics: ExecutionMetrics
    kind: EnumerationKind
    row_count: int
    ids: tuple[str, ...]
    id_checksum: str
    verified: bool


@dataclasses.dataclass(frozen=True)
class PaneCapture:
    """Retained typed capture lines for one concrete pane.

    Attributes
    ----------
    pane_id : str
        Concrete pane ID captured.
    lines : tuple[str, ...]
        Typed capture lines in display order.

    Examples
    --------
    >>> PaneCapture("%1", ("line",)).lines
    ('line',)
    """

    pane_id: str
    lines: tuple[str, ...]


CaptureStrategy: t.TypeAlias = t.Literal["serial", "batched"]


@dataclasses.dataclass(frozen=True)
class CaptureResult:
    """All-pane capture measurement retaining content for later search.

    Attributes
    ----------
    duration_ns : int
        Time spent executing the identical capture operation graph.
    metrics : ExecutionMetrics
        Planner and transport counts for the selected strategy.
    strategy : {"serial", "batched"}
        Planner policy used for the operation graph.
    operations : tuple[Operation, ...]
        Exact immutable capture operations used by the planner.
    captures : tuple[PaneCapture, ...]
        Typed content associated with each concrete pane ID.
    line_count : int
        Total typed lines returned across panes.
    byte_count : int
        Total UTF-8 bytes in those lines, excluding removed delimiters.
    epoch : int
        Current activity epoch found in every pane.
    verified : bool
        Whether every capture succeeded and contained the current marker.

    Examples
    --------
    >>> CaptureResult(
    ...     2, ExecutionMetrics(1, 1, 1, 1, 0), "batched", (),
    ...     (PaneCapture("%1", ("x",)),), 1, 1, 4, True,
    ... ).byte_count
    1
    """

    duration_ns: int
    metrics: ExecutionMetrics
    strategy: CaptureStrategy
    operations: tuple[Operation[t.Any], ...]
    captures: tuple[PaneCapture, ...]
    line_count: int
    byte_count: int
    epoch: int
    verified: bool


SearchFamily: t.TypeAlias = t.Literal["classic", "snapshot", "end-to-end", "contents"]


@dataclasses.dataclass(frozen=True)
class SearchResult:
    """One semantically explicit metadata or retained-content search.

    Attributes
    ----------
    duration_ns : int
        Time spent in the named search family only.
    family : {"classic", "snapshot", "end-to-end", "contents"}
        Search source and timing boundary.
    kind : {"sessions", "windows", "panes"}
        Object kind scanned or returned.
    scanned_count : int
        Candidate rows or panes scanned.
    target : str
        Exact concrete ID required from the result.
    matched_ids : tuple[str, ...]
        Exact concrete IDs returned by the search.
    token : str | None
        Exact retained content token, only for content search.
    verified : bool
        Whether exactly the requested ID or token matched.

    Examples
    --------
    >>> SearchResult(4, "snapshot", "panes", 2, "%1", ("%1",), verified=True).verified
    True
    """

    duration_ns: int
    family: SearchFamily
    kind: EnumerationKind
    scanned_count: int
    target: str
    matched_ids: tuple[str, ...]
    token: str | None = None
    verified: bool = False


@dataclasses.dataclass(frozen=True)
class RepeatablePhaseFailure:
    """Failure metadata that terminates deterministic phase execution.

    Attributes
    ----------
    stage : {"warmup", "timed"}
        Whether failure happened before or during timed sampling.
    strategy : str
        Strategy whose callable or postcondition failed.
    ordinal : int
        Zero-based ordinal within the stage.
    error : str
        Exception type and message without a fabricated duration.

    Examples
    --------
    >>> RepeatablePhaseFailure("timed", "serial", 2, "RuntimeError: failed").ordinal
    2
    """

    stage: t.Literal["warmup", "timed"]
    strategy: str
    ordinal: int
    error: str


@dataclasses.dataclass(frozen=True)
class RepeatablePhaseResult:
    """Accepted samples, deterministic call order, and terminal failure.

    Attributes
    ----------
    samples : tuple[RawSample, ...]
        Accepted timed rows only; warmups and failures never appear.
    order : tuple[str, ...]
        Strategy names in actual warmup-then-timed invocation order.
    failure : RepeatablePhaseFailure | None
        First failure metadata, or ``None`` when every invocation passed.

    Examples
    --------
    >>> RepeatablePhaseResult((), ("serial",), None).failure is None
    True
    """

    samples: tuple[RawSample, ...]
    order: tuple[str, ...]
    failure: RepeatablePhaseFailure | None = None


@dataclasses.dataclass(frozen=True)
class PhaseReport:
    """Raw and summarized evidence for one named benchmark cell.

    Attributes
    ----------
    name : str
        Stable phase and strategy name.
    requested_topology : Topology
        Shape requested for this phase.
    observed_topology : Topology | None
        Shape verified at the phase boundary.
    samples : tuple[RawSample, ...]
        Timed results, including explicitly rejected rows.
    summary : collections.abc.Mapping[str, int | float] | None
        Statistics recomputed from accepted rows only.
    """

    name: str
    requested_topology: Topology
    observed_topology: Topology | None
    samples: tuple[RawSample, ...] = ()
    summary: cabc.Mapping[str, int | float] | None = None

    def __post_init__(self) -> None:
        """Freeze a copied summary so callers cannot alter recorded evidence.

        >>> report = PhaseReport(
        ...     "x", Topology(1, 1, 1), Topology(1, 1, 1), summary={"count": 1}
        ... )
        >>> report.summary["count"] if report.summary is not None else None
        1
        """
        if self.summary is not None:
            object.__setattr__(
                self, "summary", types.MappingProxyType(dict(self.summary))
            )


@dataclasses.dataclass(frozen=True)
class CleanupReport:
    """Evidence that all resources owned by a run were removed.

    Attributes
    ----------
    complete : bool
        Whether process, socket, and scratch cleanup verification passed.
    errors : tuple[str, ...]
        Cleanup verification failures.
    """

    complete: bool
    errors: tuple[str, ...] = ()


class SetupCleanupError(RuntimeError):
    """A setup failure whose required cleanup also failed.

    Attributes
    ----------
    setup_error : BaseException
        Original setup exception retained as the chained cause.
    cleanup_report : CleanupReport
        Structured evidence from the unsuccessful cleanup attempt.

    Examples
    --------
    >>> cause = ValueError("setup")
    >>> error = SetupCleanupError(cause, CleanupReport(False, ("socket remains",)))
    >>> error.setup_error is cause, error.cleanup_report.complete
    (True, False)
    """

    def __init__(
        self,
        setup_error: BaseException,
        cleanup_report: CleanupReport,
    ) -> None:
        """Retain the original setup error and cleanup evidence.

        >>> error = SetupCleanupError(
        ...     RuntimeError("build"), CleanupReport(False, ("pid remains",))
        ... )
        >>> str(error)
        'setup failed with RuntimeError; cleanup incomplete: pid remains'

        Parameters
        ----------
        setup_error : BaseException
            Failure that triggered partial-run cleanup.
        cleanup_report : CleanupReport
            Incomplete cleanup result with accessible error evidence.

        Raises
        ------
        ValueError
            If the supplied cleanup report claims completion.
        """
        if cleanup_report.complete:
            message = "setup cleanup error requires an incomplete cleanup report"
            raise ValueError(message)
        self.setup_error = setup_error
        self.cleanup_report = cleanup_report
        detail = "; ".join(cleanup_report.errors) or "unspecified cleanup failure"
        super().__init__(
            f"setup failed with {type(setup_error).__name__}; "
            f"cleanup incomplete: {detail}"
        )


class PrivateDirectoryAcquisitionError(RuntimeError):
    """A private directory failed acquisition and exact rollback.

    Attributes
    ----------
    directory : pathlib.Path
        Exact newly created directory whose rollback failed.
    acquisition_error : BaseException
        Original chmod, stat, or mode-verification failure.
    rollback_error : BaseException
        Failure raised by exact non-recursive ``Path.rmdir`` rollback.

    Examples
    --------
    >>> acquire = OSError("chmod")
    >>> rollback = OSError("not empty")
    >>> error = PrivateDirectoryAcquisitionError(
    ...     pathlib.Path("run"), acquire, rollback
    ... )
    >>> error.acquisition_error is acquire, error.rollback_error is rollback
    (True, True)
    """

    def __init__(
        self,
        directory: pathlib.Path,
        acquisition_error: BaseException,
        rollback_error: BaseException,
    ) -> None:
        """Retain the exact directory and both acquisition failures.

        >>> error = PrivateDirectoryAcquisitionError(
        ...     pathlib.Path("run"), OSError("stat"), OSError("rmdir")
        ... )
        >>> "acquisition failed for run" in str(error)
        True

        Parameters
        ----------
        directory : pathlib.Path
            Exact directory created by the failed acquisition.
        acquisition_error : BaseException
            Failure that prevented mode-0700 verification.
        rollback_error : BaseException
            Failure from exact non-recursive rollback.
        """
        self.directory = directory
        self.acquisition_error = acquisition_error
        self.rollback_error = rollback_error
        super().__init__(
            f"private directory acquisition failed for {directory}: "
            f"{type(acquisition_error).__name__}: {acquisition_error}; "
            "exact rollback failed: "
            f"{type(rollback_error).__name__}: {rollback_error}"
        )


@dataclasses.dataclass(frozen=True)
class ProcessIdentity:
    """One benchmark-owned process protected against PID reuse.

    Attributes
    ----------
    role : str
        Stable owner label such as ``fuzzer``, ``server``, or ``pane``.
    pid : int
        Positive process identifier.
    start_time : int
        Linux procfs start-time tick from field 22 of ``/proc/PID/stat``.

    Examples
    --------
    >>> ProcessIdentity("pane", 42, 100).role
    'pane'
    """

    role: str
    pid: int
    start_time: int


@dataclasses.dataclass(frozen=True)
class TopologyTotals:
    """Flat session, window, and pane totals used in mismatch evidence.

    Attributes
    ----------
    sessions : int
        Number of observed or requested sessions.
    windows : int
        Number of observed or requested windows.
    panes : int
        Number of observed or requested panes.

    Examples
    --------
    >>> TopologyTotals.from_topology(Topology(2, 3, 4))
    TopologyTotals(sessions=2, windows=6, panes=24)
    """

    sessions: int
    windows: int
    panes: int

    @classmethod
    def from_topology(cls, topology: Topology) -> TopologyTotals:
        """Return the exact flat totals for a requested topology.

        >>> TopologyTotals.from_topology(Topology(1, 2, 3)).panes
        6

        Parameters
        ----------
        topology : Topology
            Requested hierarchy dimensions.

        Returns
        -------
        TopologyTotals
            Sessions, windows, and panes after multiplication.
        """
        return cls(topology.sessions, topology.windows, topology.panes)


@dataclasses.dataclass(frozen=True)
class TopologySnapshot:
    """Concrete typed snapshots returned by all three list operations.

    Attributes
    ----------
    sessions : tuple[SessionSnapshot, ...]
        Rows returned by typed ``ListSessions``.
    windows : tuple[WindowSnapshot, ...]
        Rows returned by typed ``ListWindows(all_windows=True)``.
    panes : tuple[PaneSnapshot, ...]
        Rows returned by typed ``ListPanes(all_panes=True)``.

    Examples
    --------
    >>> TopologySnapshot((), (), ()).totals
    TopologyTotals(sessions=0, windows=0, panes=0)
    """

    sessions: tuple[SessionSnapshot, ...]
    windows: tuple[WindowSnapshot, ...]
    panes: tuple[PaneSnapshot, ...]

    @property
    def totals(self) -> TopologyTotals:
        """Return flat counts without contacting tmux.

        >>> TopologySnapshot((), (), ()).totals.panes
        0

        Returns
        -------
        TopologyTotals
            Counts derived from the stored immutable rows.
        """
        return TopologyTotals(len(self.sessions), len(self.windows), len(self.panes))


class TopologyVerificationError(RuntimeError):
    """Exact topology verification failed.

    Examples
    --------
    >>> error = TopologyVerificationError(
    ...     TopologyTotals(2, 4, 8), TopologyTotals(2, 4, 7), "pane count"
    ... )
    >>> error.requested.panes, error.observed.panes
    (8, 7)
    """

    def __init__(
        self,
        requested: TopologyTotals,
        observed: TopologyTotals,
        detail: str,
    ) -> None:
        """Retain both totals and the failed invariant.

        >>> str(TopologyVerificationError(
        ...     TopologyTotals(1, 1, 1), TopologyTotals(1, 1, 0), "missing pane"
        ... ))
        'topology verification failed: missing pane; requested=1/1/1 observed=1/1/0'

        Parameters
        ----------
        requested : TopologyTotals
            Exact totals required by the run.
        observed : TopologyTotals
            Flat totals returned by the live server.
        detail : str
            First failed topology invariant.
        """
        self.requested = requested
        self.observed = observed
        self.detail = detail
        super().__init__(
            "topology verification failed: "
            f"{detail}; requested={requested.sessions}/{requested.windows}/"
            f"{requested.panes} observed={observed.sessions}/{observed.windows}/"
            f"{observed.panes}"
        )


@dataclasses.dataclass
class RunContext:
    """Single owner for one live topology and all disposable resources.

    Attributes
    ----------
    topology : Topology
        Requested hierarchy.
    lane : EngineLane
        Selected transport family.
    mode : ExecutionMode
        Sync or async dispatch mode.
    run_id : str
        Identity carried by fuzzer control markers.
    scratch : pathlib.Path
        Exclusive directory removed during cleanup.
    socket_path : pathlib.Path
        Explicit isolated tmux socket path.
    socket_root : pathlib.Path or None
        Short private directory owned only when the socket path is implicit.
    server : Server
        Classic server value used only to bind engines to the socket.
    engine : TmuxEngine or AsyncTmuxEngine
        Active transport engine.
    fuzzer : subprocess.Popen[bytes]
        Paused central stream generator.
    streams : tuple[pathlib.Path, ...]
        Precreated activity streams in mode order.
    delayed_ordinal : int
        Global pane ordinal assigned the delayed-match stream.
    sentinel_delay_ns : int
        Configured fuzzer delay for every request-scoped sentinel.
    expected_session_names : tuple[str, ...]
        Exact declared session names.
    expected_window_names : tuple[str, ...]
        Exact declared window names.
    expected_window_parents : tuple[tuple[str, str], ...]
        Declared window-name to session-name ownership pairs.
    setup_duration_ns : int
        Timed construction duration excluding activity stabilization.
    processes : tuple[ProcessIdentity, ...]
        Fuzzer, server, and pane-follower identities.
    session_ids : tuple[str, ...]
        Verified stable session identifiers.
    window_ids : tuple[str, ...]
        Verified stable window identifiers.
    pane_ids : tuple[str, ...]
        Verified stable pane identifiers.
    session_bindings : tuple[tuple[str, str], ...]
        Verified session-name to session-ID bindings.
    window_bindings : tuple[tuple[str, str, str], ...]
        Verified window-name, window-ID, and parent-session-ID bindings.
    delayed_pane_id : str or None
        Verified pane following the unique delayed stream.
    topology_verified : bool
        Whether exact live verification succeeded.
    activity_epoch : int or None
        Released run-scoped activity epoch.
    activity_marker : str or None
        Exact marker required in every pane.
    activity_pane_ids : tuple[str, ...]
        Panes that captured the released marker.
    heartbeat_epoch : int
        Last monotonic fuzzer heartbeat epoch observed.
    heartbeat_monotonic_ns : int
        Last fuzzer monotonic publication timestamp observed.
    ambient_tmux_environment : tuple[str | None, str | None]
        Original ``TMUX`` and ``TMUX_PANE`` values restored after cleanup.

    Examples
    --------
    >>> required = {"session_ids", "pane_ids", "processes", "activity_epoch"}
    >>> required <= {field.name for field in dataclasses.fields(RunContext)}
    True
    """

    topology: Topology
    lane: EngineLane
    mode: ExecutionMode
    run_id: str
    scratch: pathlib.Path
    socket_path: pathlib.Path
    socket_root: pathlib.Path | None
    server: Server
    engine: TmuxEngine | AsyncTmuxEngine
    fuzzer: subprocess.Popen[bytes]
    streams: tuple[pathlib.Path, ...]
    delayed_ordinal: int
    sentinel_delay_ns: int
    expected_session_names: tuple[str, ...]
    expected_window_names: tuple[str, ...]
    expected_window_parents: tuple[tuple[str, str], ...]
    setup_duration_ns: int
    processes: tuple[ProcessIdentity, ...]
    session_ids: tuple[str, ...] = ()
    window_ids: tuple[str, ...] = ()
    pane_ids: tuple[str, ...] = ()
    session_bindings: tuple[tuple[str, str], ...] = ()
    window_bindings: tuple[tuple[str, str, str], ...] = ()
    delayed_pane_id: str | None = None
    topology_verified: bool = False
    activity_epoch: int | None = None
    activity_marker: str | None = None
    activity_pane_ids: tuple[str, ...] = ()
    heartbeat_epoch: int = -1
    heartbeat_monotonic_ns: int = -1
    ambient_tmux_environment: tuple[str | None, str | None] = (None, None)


@dataclasses.dataclass(frozen=True)
class RampStep:
    """Outcome recorded for one canonical ramp shape.

    Attributes
    ----------
    shape : Topology
        Declared ramp shape.
    status : {"completed", "refused", "failed", "cutoff", "not_attempted"}
        Terminal result for the step.
    reason : str | None
        Required reason for an unattempted shape after a terminal step.
    """

    shape: Topology
    status: t.Literal["completed", "refused", "failed", "cutoff", "not_attempted"]
    reason: str | None = None


@dataclasses.dataclass(frozen=True)
class RunReport:
    """Machine-readable evidence for one benchmark run or plan.

    Attributes
    ----------
    requested_topology : Topology
        Topology selected by the user.
    observed_topology : Topology | None
        Last exact topology verified by the worker.
    status : {"in_progress", "completed", "refused", "failed", "cutoff"}
        Current report lifecycle status.
    phases : tuple[PhaseReport, ...]
        Named phase records.
    cleanup : CleanupReport
        Cleanup evidence; required complete for terminal status.
    maximum_completed : bool
        True only after exact requested and observed ``100x100x4`` completion.
    ramp : tuple[RampStep, ...]
        Ordered ramp outcomes, if this is a ramp run.
    requested_shapes : tuple[Topology, ...]
        Exact selected ramp sequence, including valid custom smoke ramps.
    ramp_kind : {"none", "canonical", "custom"}
        Whether this record is a single run, canonical ramp, or declared custom ramp.
    guard_decision : GuardDecision | None
        Effective decision after an optional predictive override.
    original_guard_decision : GuardDecision | None
        Decision before an optional predictive override.
    schema_version : int
        Stable artifact schema version.
    """

    requested_topology: Topology
    observed_topology: Topology | None = None
    status: t.Literal["in_progress", "completed", "refused", "failed", "cutoff"] = (
        "in_progress"
    )
    phases: tuple[PhaseReport, ...] = ()
    cleanup: CleanupReport = CleanupReport(complete=False)
    maximum_completed: bool = False
    ramp: tuple[RampStep, ...] = ()
    requested_shapes: tuple[Topology, ...] = ()
    ramp_kind: t.Literal["none", "canonical", "custom"] = "none"
    guard_decision: GuardDecision | None = None
    original_guard_decision: GuardDecision | None = None
    schema_version: int = 1


def _json_value(value: object) -> object:
    """Convert frozen report records to JSON-native values with stable keys.

    >>> _json_value(Topology(1, 2, 3))
    {'sessions': 1, 'windows_per_session': 2, 'panes_per_window': 3}

    Parameters
    ----------
    value : object
        Dataclass, tuple, mapping, or already JSON-native scalar to convert.

    Returns
    -------
    object
        Equivalent value composed from JSON-native containers and scalars.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _json_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, cabc.Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def write_json_atomic(
    path: pathlib.Path,
    value: object,
    *,
    fsync: t.Callable[[int], None] = os.fsync,
    replace: t.Callable[[str | pathlib.Path, str | pathlib.Path], None] = os.replace,
) -> None:
    r"""Atomically replace ``path`` with one complete JSON value.

    >>> with tempfile.TemporaryDirectory() as directory:
    ...     target = pathlib.Path(directory) / "value.json"
    ...     write_json_atomic(target, {"schema_version": 1})
    ...     target.read_text(encoding="utf-8")
    '{"schema_version":1}\n'

    Parameters
    ----------
    path : pathlib.Path
        Artifact destination in an existing or creatable parent directory.
    value : object
        JSON-native value or immutable report record.
    fsync : collections.abc.Callable[[int], None]
        Injectable durability boundary for the temporary file and parent directory.
    replace : collections.abc.Callable[[str | pathlib.Path, str | pathlib.Path], None]
        Injectable atomic replacement boundary.

    Raises
    ------
    OSError
        If directory creation, writing, synchronization, or replacement fails.
    TypeError
        If ``value`` cannot be serialized to JSON.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(_json_value(value), separators=(",", ":"), sort_keys=True) + "\n"
    )
    temporary_path: pathlib.Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = pathlib.Path(temporary.name)
            temporary.write(encoded)
            temporary.flush()
            fsync(temporary.fileno())
        replace(temporary_path, path)
        temporary_path = None
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def validate_report(report: RunReport) -> None:
    """Reject internally inconsistent benchmark evidence.

    >>> report = RunReport(Topology(1, 1, 1))
    >>> validate_report(report)

    Parameters
    ----------
    report : RunReport
        Immutable run artifact to validate before publication.

    Raises
    ------
    ValueError
        If a discriminator, phase, cleanup, ramp, or maximum claim is inconsistent.
    """
    if report.schema_version != 1:
        message = "unsupported report schema_version"
        raise ValueError(message)
    report_statuses = {"in_progress", "completed", "refused", "failed", "cutoff"}
    if report.status not in report_statuses:
        message = "invalid report status"
        raise ValueError(message)
    guard_kinds = {"ok", "predictive_refusal", "runtime_cutoff"}
    for decision in (report.guard_decision, report.original_guard_decision):
        if decision is not None and decision.kind not in guard_kinds:
            message = "invalid guard decision kind"
            raise ValueError(message)
    terminal = {"completed", "refused", "failed", "cutoff"}
    if report.status in terminal and not report.cleanup.complete:
        message = "terminal report requires complete cleanup"
        raise ValueError(message)
    for phase in report.phases:
        accepted: list[int] = []
        for sample in phase.samples:
            if sample.accepted and (sample.error is not None or not sample.verified):
                message = "accepted sample requires verified success without an error"
                raise ValueError(message)
            if sample.accepted and (
                sample.duration_ns is None or sample.duration_ns < 0
            ):
                message = "accepted sample requires a nonnegative duration"
                raise ValueError(message)
            if sample.accepted:
                assert sample.duration_ns is not None
                accepted.append(sample.duration_ns)
        if (accepted or report.status == "completed") and (
            phase.observed_topology is None
            or phase.observed_topology != phase.requested_topology
        ):
            message = "accepted or completed phase requires exact observed topology"
            raise ValueError(message)
        if phase.summary is not None and (
            not accepted or phase.summary != summarize_ns(accepted)
        ):
            message = "phase summary must match accepted samples"
            raise ValueError(message)
    ramp_kinds = {"none", "canonical", "custom"}
    terminal_statuses = {"refused", "cutoff", "failed"}
    attempt_statuses = {"completed", "not_attempted", *terminal_statuses}
    if report.ramp_kind not in ramp_kinds:
        message = "invalid ramp_kind"
        raise ValueError(message)
    if report.ramp_kind == "none" and (report.ramp or report.requested_shapes):
        message = "none ramp kind must not carry attempts or requested shapes"
        raise ValueError(message)
    if report.ramp_kind == "canonical" and report.requested_shapes != canonical_ramp():
        message = "canonical ramp kind requires canonical requested shapes"
        raise ValueError(message)
    if report.ramp_kind == "custom" and (
        not report.requested_shapes
        or len(set(report.requested_shapes)) != len(report.requested_shapes)
    ):
        message = "custom ramp kind requires nonempty unique requested shapes"
        raise ValueError(message)
    if report.ramp_kind != "none" and len(report.ramp) != len(report.requested_shapes):
        message = "ramp attempts must match requested shapes cardinality"
        raise ValueError(message)
    for shape, step in zip(report.requested_shapes, report.ramp, strict=True):
        if step.shape != shape:
            message = "ramp attempts must match requested shapes in order"
            raise ValueError(message)
        if step.status not in attempt_statuses:
            message = "invalid ramp attempt status"
            raise ValueError(message)
    if report.ramp_kind != "none" and report.status == "in_progress":
        pending = False
        for step in report.ramp:
            if step.status in terminal_statuses:
                message = "in-progress ramp cannot contain a terminal attempt"
                raise ValueError(message)
            if step.status == "not_attempted":
                if step.reason is not None:
                    message = "in-progress pending attempt reason must be None"
                    raise ValueError(message)
                pending = True
            elif pending:
                message = "in-progress ramp requires a completed prefix"
                raise ValueError(message)
    if (
        report.ramp_kind != "none"
        and report.status == "completed"
        and any(step.status != "completed" for step in report.ramp)
    ):
        message = "completed report may contain completed ramp attempts only"
        raise ValueError(message)
    if report.ramp_kind != "none" and report.status in terminal_statuses:
        terminals = [step for step in report.ramp if step.status in terminal_statuses]
        if len(terminals) != 1 or terminals[0].status != report.status:
            message = "terminal report requires exactly one matching terminal attempt"
            raise ValueError(message)
        terminal_index = report.ramp.index(terminals[0])
        reason = terminals[0].reason
        if (
            reason is None
            or any(step.status != "completed" for step in report.ramp[:terminal_index])
            or any(
                step.status != "not_attempted" or step.reason != reason
                for step in report.ramp[terminal_index + 1 :]
            )
        ):
            message = (
                "invalid terminal ramp sequence: later attempts must be not_attempted"
            )
            raise ValueError(message)
    maximum = Topology(100, 100, 4)
    if report.maximum_completed and (
        report.status != "completed"
        or report.requested_topology != maximum
        or report.observed_topology != maximum
    ):
        message = "maximum_completed requires exact requested and observed 100x100x4"
        raise ValueError(message)


def _forced_decision(decision: GuardDecision, force_extreme: bool) -> GuardDecision:
    """Return the only allowed override: a predictive preflight admission.

    >>> original = GuardDecision(
    ...     False, "predictive_refusal", "pid_reserve", 2, 1, True, HostSnapshot()
    ... )
    >>> _forced_decision(original, True).allowed
    True

    Parameters
    ----------
    decision : GuardDecision
        Original predictive admission result.
    force_extreme : bool
        Whether to override a forceable predictive refusal.

    Returns
    -------
    GuardDecision
        Effective decision, preserving runtime cutoffs and non-forceable results.
    """
    if force_extreme and decision.kind == "predictive_refusal" and decision.forceable:
        return dataclasses.replace(
            decision, allowed=True, kind="ok", rule="force_extreme"
        )
    return decision


def plan_payload(
    topology: Topology,
    snapshot: HostSnapshot,
    *,
    force_extreme: bool = False,
) -> dict[str, object]:
    """Build the side-effect-free JSON payload emitted by the plan command.

    >>> plan_payload(Topology(1, 1, 1), HostSnapshot())["predicted_pane_processes"]
    1

    Parameters
    ----------
    topology : Topology
        Proposed active tmux hierarchy.
    snapshot : HostSnapshot
        Host observation used for predictive admission.
    force_extreme : bool
        Whether to override a forceable predictive refusal in the effective result.

    Returns
    -------
    dict[str, object]
        JSON-native plan containing original and effective guard decisions.
    """
    original = predict_resources(topology, snapshot)
    decision = _forced_decision(original, force_extreme)
    return t.cast(
        dict[str, object],
        _json_value(
            {
                "schema_version": 1,
                "command": "plan",
                "requested_topology": topology,
                "predicted_pane_processes": topology.panes,
                "guard_decision": decision,
                "original_guard_decision": original,
                "force_extreme": force_extreme,
            }
        ),
    )


def run_plan(shape: str, output: pathlib.Path | None, force_extreme: bool) -> int:
    """Print one host-only plan and optionally persist its JSON evidence.

    >>> import contextlib, io
    >>> captured = io.StringIO()
    >>> with contextlib.redirect_stdout(captured):
    ...     result = run_plan("1x1x1", None, False)
    >>> result
    0

    Parameters
    ----------
    shape : str
        Topology in lower-case ``SxWxP`` notation.
    output : pathlib.Path | None
        Optional destination for atomic JSON plan evidence.
    force_extreme : bool
        Whether to override a forceable predictive refusal in the displayed plan.

    Returns
    -------
    int
        Zero after the plan is printed and optional evidence is written.

    Raises
    ------
    ValueError
        If ``shape`` is malformed or has a nonpositive dimension.
    OSError
        If the optional output path cannot be written.
    """
    from rich.console import Console
    from rich.table import Table

    topology = parse_topology(shape)
    payload = plan_payload(
        topology, probe_host(ProcessReader()), force_extreme=force_extreme
    )
    decision = t.cast(dict[str, object], payload["guard_decision"])
    table = Table(title="Orchestration benchmark plan")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Sessions", str(topology.sessions))
    table.add_row("Windows", str(topology.windows))
    table.add_row("Panes", str(topology.panes))
    table.add_row("Guard decision", str(decision["kind"]))
    table.add_row("Allowed", str(decision["allowed"]))
    Console().print(table)
    if output is not None:
        write_json_atomic(output, payload)
    return 0


def _process_start_time(pid: int) -> int | None:
    """Read one Linux process start-time tick without following a PID blindly.

    >>> value = _process_start_time(os.getpid())
    >>> isinstance(value, int) and value > 0
    True

    Parameters
    ----------
    pid : int
        Positive process identifier.

    Returns
    -------
    int | None
        Procfs field 22, or ``None`` if the identity is absent or unreadable.
    """
    if pid <= 0:
        return None
    try:
        stat = pathlib.Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        close = stat.rindex(")")
        fields = stat[close + 2 :].split()
        return int(fields[19])
    except (FileNotFoundError, OSError, ValueError, IndexError):
        return None


def _record_process(role: str, pid: int) -> ProcessIdentity:
    """Capture a positive PID and its current procfs start time.

    >>> _record_process("self", os.getpid()).role
    'self'

    Parameters
    ----------
    role : str
        Stable resource-owner label.
    pid : int
        Process identifier to bind.

    Returns
    -------
    ProcessIdentity
        Identity safe to compare before later escalation.

    Raises
    ------
    RuntimeError
        If procfs cannot prove the process identity.
    """
    start_time = _process_start_time(pid)
    if start_time is None:
        message = f"cannot record {role} process identity for pid {pid}"
        raise RuntimeError(message)
    return ProcessIdentity(role, pid, start_time)


def process_identity_matches(identity: ProcessIdentity) -> bool:
    """Return whether a PID still names the exact process that was recorded.

    >>> current = _record_process("self", os.getpid())
    >>> process_identity_matches(current)
    True
    >>> process_identity_matches(dataclasses.replace(current, start_time=-1))
    False

    Parameters
    ----------
    identity : ProcessIdentity
        PID and start time captured while the process was owned by this run.

    Returns
    -------
    bool
        True only while both PID and procfs start time still match.
    """
    return _process_start_time(identity.pid) == identity.start_time


_UNIX_SOCKET_PATH_MAX_BYTES = 107


def _validate_socket_path(path: pathlib.Path) -> pathlib.Path:
    """Validate one pathname against the Linux Unix-socket ABI ceiling.

    Linux defines ``sockaddr_un.sun_path`` as 108 bytes. Pathname sockets need
    one trailing NUL byte, leaving 107 encoded filesystem bytes for tmux's
    socket path.

    >>> boundary = pathlib.Path("/" + "é" * 53)
    >>> len(os.fsencode(boundary)), _validate_socket_path(boundary) == boundary
    (107, True)

    Parameters
    ----------
    path : pathlib.Path
        Candidate tmux socket pathname.

    Returns
    -------
    pathlib.Path
        The accepted path unchanged.

    Raises
    ------
    ValueError
        If the encoded path contains NUL or exceeds 107 bytes.
    """
    encoded = os.fsencode(path)
    if b"\0" in encoded:
        message = "tmux socket path must not contain NUL"
        raise ValueError(message)
    if len(encoded) > _UNIX_SOCKET_PATH_MAX_BYTES:
        message = f"tmux socket path exceeds 107 encoded bytes: {len(encoded)} bytes"
        raise ValueError(message)
    return path


def _acquire_private_directory(directory: pathlib.Path) -> pathlib.Path:
    """Create and verify an exclusively acquired mode-0700 directory.

    >>> with tempfile.TemporaryDirectory() as temporary:
    ...     run_dir = pathlib.Path(temporary) / "run"
    ...     acquired = _acquire_private_directory(run_dir)
    ...     oct(stat.S_IMODE(acquired.stat().st_mode))
    '0o700'

    Parameters
    ----------
    directory : pathlib.Path
        New directory whose pre-existence rejects acquisition.

    Returns
    -------
    pathlib.Path
        The verified private directory.

    Raises
    ------
    FileExistsError
        If another owner already created the directory.
    OSError
        If mode 0700 cannot be applied or verified.
    PrivateDirectoryAcquisitionError
        If mode acquisition and exact non-recursive rollback both fail.
    """
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    try:
        directory.chmod(0o700)
        _verify_private_directory_mode(directory)
    except BaseException as acquisition_error:
        try:
            directory.rmdir()
        except Exception as rollback_error:  # noqa: BLE001
            raise PrivateDirectoryAcquisitionError(
                directory,
                acquisition_error,
                rollback_error,
            ) from acquisition_error
        raise
    else:
        return directory


def _verify_private_directory_mode(directory: pathlib.Path) -> None:
    """Require one acquired directory to have exact mode 0700.

    >>> with tempfile.TemporaryDirectory() as temporary:
    ...     directory = pathlib.Path(temporary)
    ...     directory.chmod(0o700)
    ...     _verify_private_directory_mode(directory)

    Parameters
    ----------
    directory : pathlib.Path
        Existing directory whose effective permission bits are verified.

    Returns
    -------
    None
        After exact mode 0700 is observed.

    Raises
    ------
    OSError
        If stat fails or the observed permission bits differ from 0700.
    """
    observed_mode = stat.S_IMODE(directory.stat().st_mode)
    if observed_mode != 0o700:
        message = f"private run directory mode is {oct(observed_mode)}, expected 0o700"
        raise OSError(message)


def _stop_owned_process(
    process: subprocess.Popen[bytes] | subprocess.Popen[str],
    identity: ProcessIdentity,
    *,
    grace_s: float = 1.0,
) -> CleanupReport:
    """Boundedly stop and reap one child without signaling a reused PID.

    >>> child = subprocess.Popen((sys.executable, "-c", "pass"))
    >>> child.wait(timeout=1.0)
    0
    >>> _stop_owned_process(
    ...     child, ProcessIdentity("finished", child.pid, -1), grace_s=0.01
    ... ).complete
    True

    Parameters
    ----------
    process : subprocess.Popen[bytes] or subprocess.Popen[str]
        Directly owned child handle used for bounded waits and reaping.
    identity : ProcessIdentity
        PID and procfs start time recorded immediately after spawn.
    grace_s : float
        Maximum wait after TERM and again after identity-checked KILL.

    Returns
    -------
    CleanupReport
        Complete only when the child is reaped and its identity is absent.

    Raises
    ------
    ValueError
        If the cleanup grace is not positive.
    """
    if grace_s <= 0:
        message = "process cleanup grace must be positive"
        raise ValueError(message)
    errors: list[str] = []
    process.poll()
    if process.returncode is None:
        if process_identity_matches(identity):
            try:
                os.kill(identity.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except OSError as error:
                errors.append(
                    f"{identity.role} pid {identity.pid} SIGTERM: "
                    f"{type(error).__name__}: {error}"
                )
        else:
            errors.append(
                f"{identity.role} pid {identity.pid} identity changed before SIGTERM"
            )
        try:
            process.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            if process_identity_matches(identity):
                try:
                    os.kill(identity.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError as error:
                    errors.append(
                        f"{identity.role} pid {identity.pid} SIGKILL: "
                        f"{type(error).__name__}: {error}"
                    )
            else:
                errors.append(
                    f"{identity.role} pid {identity.pid} identity changed "
                    "before SIGKILL"
                )
            try:
                process.wait(timeout=grace_s)
            except subprocess.TimeoutExpired:
                errors.append(f"{identity.role} pid {identity.pid} was not reaped")
    if process_identity_matches(identity):
        errors.append(
            f"{identity.role} pid {identity.pid} with start time "
            f"{identity.start_time} remains"
        )
    return CleanupReport(complete=not errors, errors=tuple(errors))


def _stream_name(ordinal: int, delayed_ordinal: int) -> str:
    """Return the Task 1 stream name for one global stable pane ordinal.

    >>> [_stream_name(index, 2) for index in range(4)]
    ['editor', 'dev-server', 'delayed-match', 'installer']

    Parameters
    ----------
    ordinal : int
        Zero-based pane position across every session and window.
    delayed_ordinal : int
        Position reserved for the unique delayed stream.

    Returns
    -------
    str
        One fuzzer stream basename without its ``.log`` suffix.
    """
    if ordinal == delayed_ordinal:
        return "delayed-match"
    shared = ("editor", "dev-server", "installer")
    compacted = ordinal - int(ordinal > delayed_ordinal)
    return shared[compacted % len(shared)]


def _tail_command(stream: pathlib.Path) -> str:
    """Render the portable follower command as one shell-safe string.

    >>> _tail_command(pathlib.Path("a stream.log"))
    "exec tail -n 0 -f 'a stream.log'"

    Parameters
    ----------
    stream : pathlib.Path
        Precreated append-only activity file.

    Returns
    -------
    str
        ``exec tail -n 0 -f`` plus a safely quoted path.
    """
    return shlex.join(("exec", "tail", "-n", "0", "-f", str(stream)))


def _session_name(run_id: str, index: int) -> str:
    """Return one globally distinct, stable benchmark session name.

    >>> _session_name("run-7", 2)
    'bench-run-7-s002'

    Parameters
    ----------
    run_id : str
        Validated run identity.
    index : int
        Zero-based session ordinal.

    Returns
    -------
    str
        Exact tmux session name.
    """
    return f"bench-{run_id}-s{index:03d}"


def _window_name(run_id: str, session_index: int, window_index: int) -> str:
    """Return one globally distinct, stable benchmark window name.

    >>> _window_name("run-7", 2, 3)
    'bench-run-7-s002-w003'

    Parameters
    ----------
    run_id : str
        Validated run identity.
    session_index : int
        Zero-based session ordinal.
    window_index : int
        Zero-based window ordinal within the session.

    Returns
    -------
    str
        Exact tmux window name.
    """
    return f"{_session_name(run_id, session_index)}-w{window_index:03d}"


def _only_control_client_name(clients: tuple[ClientSnapshot, ...]) -> str:
    """Return the sole client attached to an isolated control server.

    >>> try:
    ...     _only_control_client_name(())
    ... except RuntimeError as error:
    ...     print(error)
    isolated control server must have one attached client

    Parameters
    ----------
    clients : tuple[ClientSnapshot, ...]
        Concrete rows returned by typed ``ListClients``.

    Returns
    -------
    str
        Exact tmux client name accepted by ``SwitchClient``.

    Raises
    ------
    RuntimeError
        If bootstrap did not leave exactly one persistent control client.
    """
    if len(clients) != 1:
        message = "isolated control server must have one attached client"
        raise RuntimeError(message)
    return clients[0].name


def _only_process_identity(
    identities: list[ProcessIdentity],
) -> ProcessIdentity:
    """Return the sole process identity transferred by a child starter.

    >>> identity = ProcessIdentity("fuzzer", 42, 100)
    >>> _only_process_identity([identity]) is identity
    True

    Parameters
    ----------
    identities : list[ProcessIdentity]
        Mutable handoff populated before child startup returns.

    Returns
    -------
    ProcessIdentity
        The single transferred owner identity.

    Raises
    ------
    RuntimeError
        If startup did not transfer exactly one identity.
    """
    if len(identities) != 1:
        message = "child startup did not transfer exactly one process identity"
        raise RuntimeError(message)
    return identities[0]


def build_workspaces(
    topology: Topology,
    streams_dir: pathlib.Path,
    run_id: str,
    *,
    delayed_ordinal: int,
) -> WorkspaceSet:
    """Declare one workspace per session with active commands in every pane.

    The returned set is one compilation unit. Every first pane receives its
    command through ``Window.window_shell`` and every split receives the same
    command through ``Pane.shell``.

    Examples
    --------
    >>> with tempfile.TemporaryDirectory() as directory:
    ...     streams = pathlib.Path(directory)
    ...     for name in ("editor", "dev-server", "installer", "delayed-match"):
    ...         (streams / f"{name}.log").touch()
    ...     workspace_set = build_workspaces(
    ...         Topology(1, 1, 2), streams, "run-7", delayed_ordinal=1
    ...     )
    ...     len(workspace_set.workspaces[0].windows[0].panes)
    2

    Parameters
    ----------
    topology : Topology
        Positive hierarchy to declare.
    streams_dir : pathlib.Path
        Directory containing all four precreated Task 1 streams.
    run_id : str
        Run identity used in stable tmux names.
    delayed_ordinal : int
        Unique global pane ordinal assigned the delayed stream.

    Returns
    -------
    WorkspaceSet
        All sessions wrapped in one declarative collection.

    Raises
    ------
    ValueError
        If the delayed ordinal is outside the requested pane range.
    FileNotFoundError
        If any selected stream was not precreated by the fuzzer.
    """
    from libtmux.experimental.workspace import Pane, Window, Workspace, WorkspaceSet

    if not 0 <= delayed_ordinal < topology.panes:
        message = "delayed pane ordinal must identify a requested pane"
        raise ValueError(message)
    workspaces: list[Workspace] = []
    ordinal = 0
    for session_index in range(topology.sessions):
        windows: list[Window] = []
        for window_index in range(topology.windows_per_session):
            panes: list[Pane] = []
            commands: list[str] = []
            for _pane_index in range(topology.panes_per_window):
                stream = streams_dir / f"{_stream_name(ordinal, delayed_ordinal)}.log"
                if not stream.is_file():
                    raise FileNotFoundError(stream)
                command = _tail_command(stream)
                commands.append(command)
                panes.append(Pane(shell=command))
                ordinal += 1
            windows.append(
                Window(
                    name=_window_name(run_id, session_index, window_index),
                    window_shell=commands[0],
                    panes=tuple(panes),
                )
            )
        workspaces.append(
            Workspace(
                name=_session_name(run_id, session_index),
                windows=tuple(windows),
            )
        )
    return WorkspaceSet(workspaces)


def _wait_for_fuzzer_ready(
    process: subprocess.Popen[bytes],
    ready: pathlib.Path,
    run_id: str,
    *,
    timeout_s: float,
) -> None:
    """Wait boundedly for one exact fuzzer readiness marker.

    >>> finished = subprocess.Popen((sys.executable, "-c", "pass"))
    >>> finished.wait(timeout=1.0)
    0
    >>> try:
    ...     _wait_for_fuzzer_ready(
    ...         finished, pathlib.Path("missing.json"), "run-7", timeout_s=0.01
    ...     )
    ... except RuntimeError as error:
    ...     print(str(error).startswith("fuzzer exited before ready"))
    True

    Parameters
    ----------
    process : subprocess.Popen[bytes]
        Live central fuzzer child.
    ready : pathlib.Path
        Atomic readiness marker path.
    run_id : str
        Exact owner required in the marker.
    timeout_s : float
        Maximum monotonic wait.

    Returns
    -------
    None
        After the exact marker is visible.

    Raises
    ------
    RuntimeError
        If the child exits or the marker misses its deadline.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if process.poll() is not None:
            message = f"fuzzer exited before ready with code {process.returncode}"
            raise RuntimeError(message)
        try:
            marker = json.loads(ready.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            time.sleep(0.01)
            continue
        if marker == {"schema_version": 1, "run_id": run_id}:
            return
        time.sleep(0.01)
    message = f"fuzzer did not become ready within {timeout_s}s"
    raise RuntimeError(message)


def start_fuzzer(
    scratch: pathlib.Path,
    run_id: str,
    *,
    ready_timeout_s: float = 5.0,
    frame_rate_hz: float = 40.0,
    duration_s: float = 300.0,
    _identity_out: list[ProcessIdentity] | None = None,
) -> subprocess.Popen[bytes]:
    """Start the paused Task 1 service and wait for its exact ready marker.

    Examples
    --------
    >>> try:
    ...     start_fuzzer(pathlib.Path("."), "", ready_timeout_s=1.0)
    ... except ValueError as error:
    ...     print(error)
    run_id must be nonempty

    Parameters
    ----------
    scratch : pathlib.Path
        Existing exclusive directory that will own ``fuzzer/``.
    run_id : str
        Identity required in every lifecycle marker.
    ready_timeout_s : float
        Maximum wait for the service's completed ready marker.
    frame_rate_hz : float
        Active frames per stream per second after gate release.
    duration_s : float
        Maximum active service duration.
    _identity_out : list[ProcessIdentity] | None
        Internal ownership handoff populated with the identity captured at
        spawn time before this function returns.

    Returns
    -------
    subprocess.Popen[bytes]
        Paused fuzzer process whose PID remains owned by the caller.

    Raises
    ------
    ValueError
        If the run identity or timeout is invalid.
    RuntimeError
        If the service exits or misses its ready deadline.
    SetupCleanupError
        If a startup failure is followed by incomplete child cleanup.
    """
    if not run_id:
        message = "run_id must be nonempty"
        raise ValueError(message)
    if ready_timeout_s <= 0:
        message = "ready timeout must be positive"
        raise ValueError(message)
    output_dir = scratch / "fuzzer"
    script = pathlib.Path(__file__).with_name("orchestration_fuzzer.py")
    environment = os.environ.copy()
    environment.pop("TMUX", None)
    environment.pop("TMUX_PANE", None)
    environment.pop("VIRTUAL_ENV", None)
    process = subprocess.Popen(
        (
            sys.executable,
            str(script),
            "serve",
            "--output-dir",
            str(output_dir),
            "--run-id",
            run_id,
            "--source-root",
            str(pathlib.Path(__file__).parents[1]),
            "--seed",
            "11",
            "--frame-rate",
            str(frame_rate_hz),
            "--duration",
            str(duration_s),
            "--delayed-match-after",
            str(_SENTINEL_DELAY_S),
            "--sentinel-prefix",
            "READY",
            "--heartbeat-interval",
            "0.02",
        ),
        cwd=pathlib.Path(__file__).parents[1],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    ready = output_dir / "ready.json"
    identity: ProcessIdentity | None = None
    try:
        identity = _record_process("fuzzer", process.pid)
        _wait_for_fuzzer_ready(
            process,
            ready,
            run_id,
            timeout_s=ready_timeout_s,
        )
        if _identity_out is not None:
            _identity_out.append(identity)
    except BaseException as startup_error:
        if identity is None:
            start_time = _process_start_time(process.pid)
            if start_time is not None:
                identity = ProcessIdentity("fuzzer", process.pid, start_time)
        if identity is None:
            process.poll()
            if process.returncode is None:
                process.terminate()
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    cleanup_error = (
                        f"fuzzer pid {process.pid} identity unavailable; "
                        "child was not reaped"
                    )
                    cleanup_report = CleanupReport(
                        complete=False,
                        errors=(cleanup_error,),
                    )
                else:
                    cleanup_report = CleanupReport(complete=True)
            else:
                process.wait()
                cleanup_report = CleanupReport(complete=True)
        else:
            cleanup_report = _stop_owned_process(process, identity)
        if not cleanup_report.complete:
            raise SetupCleanupError(startup_error, cleanup_report) from startup_error
        raise
    else:
        return process


def _prepare_context(
    topology: Topology,
    lane: EngineLane,
    mode: ExecutionMode,
    scratch: pathlib.Path,
    *,
    socket_path: pathlib.Path | None,
    run_id: str,
    delayed_ordinal: int,
) -> RunContext:
    """Create isolated host resources and an engine without starting setup timing.

    >>> try:
    ...     _prepare_context(
    ...         Topology(1, 1, 1), EngineLane.SUBPROCESS, ExecutionMode.SYNC,
    ...         pathlib.Path("unused"), socket_path=None, run_id="run-7",
    ...         delayed_ordinal=2,
    ...     )
    ... except ValueError as error:
    ...     print(error)
    delayed pane ordinal must identify a requested pane

    Parameters
    ----------
    topology : Topology
        Requested live hierarchy.
    lane : EngineLane
        Selected engine transport.
    mode : ExecutionMode
        Sync or async dispatch.
    scratch : pathlib.Path
        New exclusive directory for this run.
    socket_path : pathlib.Path | None
        Explicit scratch-contained path, or ``None`` for a short owned root.
    run_id : str
        Safe identifier used in markers and tmux names.
    delayed_ordinal : int
        Unique pane assigned the delayed stream.

    Returns
    -------
    RunContext
        Paused fuzzer, isolated server value, and unstarted engine.

    Raises
    ------
    ValueError
        If identifiers, paths, or the delayed ordinal are invalid.
    FileExistsError
        If ``scratch`` or the generated socket root already exists.
    OSError
        If a private mode cannot be applied or resources cannot be created.
    SetupCleanupError
        If partial resource acquisition cannot be completely cleaned.
    """
    if not 0 <= delayed_ordinal < topology.panes:
        message = "delayed pane ordinal must identify a requested pane"
        raise ValueError(message)
    if not run_id or any(
        not (character.isascii() and (character.isalnum() or character in "-_"))
        for character in run_id
    ):
        message = (
            "run_id must contain only ASCII letters, digits, hyphens, or underscores"
        )
        raise ValueError(message)
    resolved_scratch = scratch.resolve()
    socket_root: pathlib.Path | None
    if socket_path is None:
        socket_root = pathlib.Path(tempfile.gettempdir()).resolve() / (
            f"libtmux-bench-{os.getpid():x}-{uuid.uuid4().hex[:8]}"
        )
        resolved_socket = _validate_socket_path(socket_root / "tmux.sock")
    else:
        socket_root = None
        resolved_socket = _validate_socket_path(socket_path.resolve())
        if not resolved_socket.is_relative_to(resolved_scratch):
            message = "explicit socket path must stay inside the run scratch directory"
            raise ValueError(message)
    ambient_tmux_environment = (
        os.environ.pop("TMUX", None),
        os.environ.pop("TMUX_PANE", None),
    )
    scratch_created = False
    socket_root_created = False
    fuzzer: subprocess.Popen[bytes] | None = None
    fuzzer_identity: ProcessIdentity | None = None
    try:
        from libtmux.experimental.engines import (
            AsyncControlModeEngine,
            AsyncSubprocessEngine,
            ControlModeEngine,
            SubprocessEngine,
        )
        from libtmux.server import Server

        _acquire_private_directory(resolved_scratch)
        scratch_created = True
        if socket_root is not None:
            _acquire_private_directory(socket_root)
            socket_root_created = True
        fuzzer_identities: list[ProcessIdentity] = []
        fuzzer = start_fuzzer(
            resolved_scratch,
            run_id,
            _identity_out=fuzzer_identities,
        )
        fuzzer_identity = _only_process_identity(fuzzer_identities)
        server = Server(socket_path=resolved_socket, config_file=os.devnull)
        if mode is ExecutionMode.SYNC:
            engine: TmuxEngine | AsyncTmuxEngine
            engine = (
                SubprocessEngine.for_server(server)
                if lane is EngineLane.SUBPROCESS
                else ControlModeEngine.for_server(server)
            )
        else:
            engine = (
                AsyncSubprocessEngine.for_server(server)
                if lane is EngineLane.SUBPROCESS
                else AsyncControlModeEngine.for_server(server)
            )
        streams_dir = resolved_scratch / "fuzzer" / "streams"
        streams = tuple(
            streams_dir / f"{name}.log"
            for name in ("editor", "dev-server", "installer", "delayed-match")
        )
        return RunContext(
            topology=topology,
            lane=lane,
            mode=mode,
            run_id=run_id,
            scratch=resolved_scratch,
            socket_path=resolved_socket,
            socket_root=socket_root,
            server=server,
            engine=engine,
            fuzzer=fuzzer,
            streams=streams,
            delayed_ordinal=delayed_ordinal,
            sentinel_delay_ns=_SENTINEL_DELAY_NS,
            expected_session_names=tuple(
                _session_name(run_id, index) for index in range(topology.sessions)
            ),
            expected_window_names=tuple(
                _window_name(run_id, session_index, window_index)
                for session_index in range(topology.sessions)
                for window_index in range(topology.windows_per_session)
            ),
            expected_window_parents=tuple(
                (
                    _window_name(run_id, session_index, window_index),
                    _session_name(run_id, session_index),
                )
                for session_index in range(topology.sessions)
                for window_index in range(topology.windows_per_session)
            ),
            setup_duration_ns=0,
            processes=(fuzzer_identity,),
            ambient_tmux_environment=ambient_tmux_environment,
        )
    except BaseException as setup_error:
        cleanup_errors: list[str] = []
        if fuzzer is not None and fuzzer_identity is not None:
            cleanup_errors.extend(_stop_owned_process(fuzzer, fuzzer_identity).errors)
        for label, directory, acquired in (
            ("socket root", socket_root, socket_root_created),
            ("scratch", resolved_scratch, scratch_created),
        ):
            if directory is None or not acquired:
                continue
            try:
                shutil.rmtree(directory)
            except OSError as cleanup_error:
                cleanup_errors.append(
                    f"{label} removal: {type(cleanup_error).__name__}: {cleanup_error}"
                )
            if directory.exists():
                cleanup_errors.append(f"{label} remains: {directory}")
        for name, value in zip(
            ("TMUX", "TMUX_PANE"), ambient_tmux_environment, strict=True
        ):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        if cleanup_errors:
            cleanup_report = CleanupReport(
                complete=False,
                errors=tuple(cleanup_errors),
            )
            raise SetupCleanupError(setup_error, cleanup_report) from setup_error
        raise


def setup_sync(
    topology: Topology,
    lane: EngineLane,
    scratch: pathlib.Path,
    *,
    socket_path: pathlib.Path | None = None,
    run_id: str = "run-0",
    delayed_ordinal: int = 0,
) -> RunContext:
    """Build and exactly verify one synchronous live topology.

    Control mode attaches to a disposable keepalive before timing. The returned
    ``setup_duration_ns`` ends after that keepalive is removed and excludes the
    activity gate and stabilization polls.

    Examples
    --------
    >>> try:
    ...     setup_sync(
    ...         Topology(1, 1, 1), EngineLane.SUBPROCESS, pathlib.Path("unused"),
    ...         delayed_ordinal=2,
    ...     )
    ... except ValueError as error:
    ...     print(error)
    delayed pane ordinal must identify a requested pane

    Parameters
    ----------
    topology : Topology
        Requested hierarchy.
    lane : EngineLane
        Synchronous subprocess or control transport.
    scratch : pathlib.Path
        New exclusive run directory.
    socket_path : pathlib.Path | None
        Explicit socket path inside ``scratch``.
    run_id : str
        Marker and topology identity.
    delayed_ordinal : int
        Unique pane assigned the delayed stream.

    Returns
    -------
    RunContext
        Verified topology with stable IDs and process identities.

    Raises
    ------
    ValueError
        If topology identity, socket path, or delayed ordinal is invalid.
    FileExistsError
        If the run cannot exclusively acquire its scratch directory.
    SetupCleanupError
        If setup fails and cleanup also reports errors.
    """
    from libtmux.experimental.engines import SubprocessEngine
    from libtmux.experimental.ops import (
        BatchingPlanner,
        DisplayMessage,
        KillSession,
        ListClients,
        ListSessions,
        NameRef,
        NewSession,
        SetOption,
        SwitchClient,
        run,
    )

    context = _prepare_context(
        topology,
        lane,
        ExecutionMode.SYNC,
        scratch,
        socket_path=socket_path,
        run_id=run_id,
        delayed_ordinal=delayed_ordinal,
    )
    engine = t.cast("TmuxEngine", context.engine)
    keepalive = f"bench-{run_id}-keepalive"
    try:
        if lane is EngineLane.CONTROL:
            bootstrap = SubprocessEngine.for_server(context.server)
            run(
                NewSession(
                    session_name=keepalive,
                    window_shell="exec tail -n 0 -f /dev/null",
                ),
                bootstrap,
            ).raise_for_status()
            run(
                SetOption(server=True, option="exit-empty", value="off"),
                bootstrap,
            ).raise_for_status()
            run(ListSessions(), engine).raise_for_status()

        workspaces = build_workspaces(
            topology,
            context.scratch / "fuzzer" / "streams",
            run_id,
            delayed_ordinal=delayed_ordinal,
        )
        started_ns = time.perf_counter_ns()
        build_result = workspaces.build(
            engine,
            preflight=False,
            planner=BatchingPlanner(),
        ).raise_for_status()
        if lane is EngineLane.CONTROL:
            clients = run(ListClients(), engine).raise_for_status().clients
            run(
                SwitchClient(
                    client=_only_control_client_name(clients),
                    to_session=build_result.bindings[0],
                ),
                engine,
            ).raise_for_status()
            run(KillSession(target=NameRef(keepalive)), engine).raise_for_status()
        context.setup_duration_ns = time.perf_counter_ns() - started_ns
        server_pid_result = run(DisplayMessage(message="#{pid}"), engine)
        server_pid_result.raise_for_status()
        server_pid = int(server_pid_result.text)
        context.processes = (*context.processes, _record_process("server", server_pid))
        verify_topology(context, snapshot_topology_sync(context))
    except BaseException as setup_error:
        try:
            cleanup_report = asyncio.run(cleanup_run(context))
        except BaseException as cleanup_error:  # noqa: BLE001
            cleanup_report = CleanupReport(
                complete=False,
                errors=(
                    f"cleanup raised {type(cleanup_error).__name__}: {cleanup_error}",
                ),
            )
        if not cleanup_report.complete:
            raise SetupCleanupError(setup_error, cleanup_report) from setup_error
        raise
    else:
        return context


async def setup_async(
    topology: Topology,
    lane: EngineLane,
    scratch: pathlib.Path,
    *,
    socket_path: pathlib.Path | None = None,
    run_id: str = "run-0",
    delayed_ordinal: int = 0,
) -> RunContext:
    """Build and exactly verify one asynchronous live topology.

    Examples
    --------
    >>> async def invalid_setup():
    ...     try:
    ...         await setup_async(
    ...             Topology(1, 1, 1), EngineLane.SUBPROCESS,
    ...             pathlib.Path("unused"), delayed_ordinal=2,
    ...         )
    ...     except ValueError as error:
    ...         return str(error)
    >>> asyncio.run(invalid_setup())
    'delayed pane ordinal must identify a requested pane'

    Parameters
    ----------
    topology : Topology
        Requested hierarchy.
    lane : EngineLane
        Asynchronous subprocess or control transport.
    scratch : pathlib.Path
        New exclusive run directory.
    socket_path : pathlib.Path | None
        Explicit socket path inside ``scratch``.
    run_id : str
        Marker and topology identity.
    delayed_ordinal : int
        Unique pane assigned the delayed stream.

    Returns
    -------
    RunContext
        Verified topology with stable IDs and process identities.

    Raises
    ------
    ValueError
        If topology identity, socket path, or delayed ordinal is invalid.
    FileExistsError
        If the run cannot exclusively acquire its scratch directory.
    SetupCleanupError
        If setup fails and cleanup also reports errors.
    """
    from libtmux.experimental.engines import (
        AsyncControlModeEngine,
        AsyncSubprocessEngine,
    )
    from libtmux.experimental.ops import (
        BatchingPlanner,
        DisplayMessage,
        KillSession,
        ListClients,
        ListSessions,
        NameRef,
        NewSession,
        SetOption,
        SwitchClient,
        arun,
    )

    context = _prepare_context(
        topology,
        lane,
        ExecutionMode.ASYNC,
        scratch,
        socket_path=socket_path,
        run_id=run_id,
        delayed_ordinal=delayed_ordinal,
    )
    engine = t.cast("AsyncTmuxEngine", context.engine)
    keepalive = f"bench-{run_id}-keepalive"
    try:
        if lane is EngineLane.CONTROL:
            bootstrap = AsyncSubprocessEngine.for_server(context.server)
            (
                await arun(
                    NewSession(
                        session_name=keepalive,
                        window_shell="exec tail -n 0 -f /dev/null",
                    ),
                    bootstrap,
                )
            ).raise_for_status()
            (
                await arun(
                    SetOption(server=True, option="exit-empty", value="off"),
                    bootstrap,
                )
            ).raise_for_status()
            control = t.cast(AsyncControlModeEngine, engine)
            await control.start()
            (await arun(ListSessions(), engine)).raise_for_status()

        workspaces = build_workspaces(
            topology,
            context.scratch / "fuzzer" / "streams",
            run_id,
            delayed_ordinal=delayed_ordinal,
        )
        started_ns = time.perf_counter_ns()
        build_result = (
            await workspaces.abuild(
                engine,
                preflight=False,
                planner=BatchingPlanner(),
            )
        ).raise_for_status()
        if lane is EngineLane.CONTROL:
            clients = (await arun(ListClients(), engine)).raise_for_status().clients
            real_session_id = build_result.bindings[0]
            (
                await arun(
                    SwitchClient(
                        client=_only_control_client_name(clients),
                        to_session=real_session_id,
                    ),
                    engine,
                )
            ).raise_for_status()
            control.set_attach_targets([real_session_id])
            (
                await arun(KillSession(target=NameRef(keepalive)), engine)
            ).raise_for_status()
        context.setup_duration_ns = time.perf_counter_ns() - started_ns
        server_pid_result = await arun(DisplayMessage(message="#{pid}"), engine)
        server_pid_result.raise_for_status()
        server_pid = int(server_pid_result.text)
        context.processes = (*context.processes, _record_process("server", server_pid))
        verify_topology(context, await snapshot_topology_async(context))
    except BaseException as setup_error:
        try:
            cleanup_report = await cleanup_run(context)
        except BaseException as cleanup_error:  # noqa: BLE001
            cleanup_report = CleanupReport(
                complete=False,
                errors=(
                    f"cleanup raised {type(cleanup_error).__name__}: {cleanup_error}",
                ),
            )
        if not cleanup_report.complete:
            raise SetupCleanupError(setup_error, cleanup_report) from setup_error
        raise
    else:
        return context


def snapshot_topology_sync(context: RunContext) -> TopologySnapshot:
    """Read exact sync session, window, and pane snapshots through typed ops.

    >>> wrong_mode = types.SimpleNamespace(mode=ExecutionMode.ASYNC)
    >>> try:
    ...     snapshot_topology_sync(wrong_mode)
    ... except ValueError as error:
    ...     print(error)
    sync snapshot requires a synchronous run context

    Parameters
    ----------
    context : RunContext
        Synchronous live run.

    Returns
    -------
    TopologySnapshot
        Concrete typed rows from three independent list operations.

    Raises
    ------
    ValueError
        If called with an asynchronous context.
    ~libtmux.experimental.ops.exc.TmuxCommandError
        If a list operation fails.
    """
    from libtmux.experimental.ops import ListPanes, ListSessions, ListWindows, run

    if context.mode is not ExecutionMode.SYNC:
        message = "sync snapshot requires a synchronous run context"
        raise ValueError(message)
    engine = t.cast("TmuxEngine", context.engine)
    sessions = run(ListSessions(), engine).raise_for_status().sessions
    windows = run(ListWindows(all_windows=True), engine).raise_for_status().windows
    panes = run(ListPanes(all_panes=True), engine).raise_for_status().panes
    return TopologySnapshot(sessions, windows, panes)


async def snapshot_topology_async(context: RunContext) -> TopologySnapshot:
    """Read exact async session, window, and pane snapshots through typed ops.

    >>> wrong_mode = types.SimpleNamespace(mode=ExecutionMode.SYNC)
    >>> try:
    ...     asyncio.run(snapshot_topology_async(wrong_mode))
    ... except ValueError as error:
    ...     print(error)
    async snapshot requires an asynchronous run context

    Parameters
    ----------
    context : RunContext
        Asynchronous live run.

    Returns
    -------
    TopologySnapshot
        Concrete typed rows from three independent list operations.

    Raises
    ------
    ValueError
        If called with a synchronous context.
    ~libtmux.experimental.ops.exc.TmuxCommandError
        If a list operation fails.
    """
    from libtmux.experimental.ops import ListPanes, ListSessions, ListWindows, arun

    if context.mode is not ExecutionMode.ASYNC:
        message = "async snapshot requires an asynchronous run context"
        raise ValueError(message)
    engine = t.cast("AsyncTmuxEngine", context.engine)
    sessions = (await arun(ListSessions(), engine)).raise_for_status().sessions
    windows = (
        (await arun(ListWindows(all_windows=True), engine)).raise_for_status().windows
    )
    panes = (await arun(ListPanes(all_panes=True), engine)).raise_for_status().panes
    return TopologySnapshot(sessions, windows, panes)


def verify_topology(
    context: RunContext,
    snapshot: TopologySnapshot,
) -> TopologySnapshot:
    """Verify exact shape, names, liveness, process identities, and delayed pane.

    >>> empty_context = types.SimpleNamespace(topology=Topology(1, 1, 1))
    >>> try:
    ...     verify_topology(empty_context, TopologySnapshot((), (), ()))
    ... except TopologyVerificationError as error:
    ...     print(error.detail)
    flat totals differ

    Parameters
    ----------
    context : RunContext
        Run whose declared shape and names are authoritative.
    snapshot : TopologySnapshot
        Typed live rows to verify.

    Returns
    -------
    TopologySnapshot
        The accepted snapshot for fluent callers.

    Raises
    ------
    TopologyVerificationError
        If any exact topology or process invariant differs.
    """
    requested = TopologyTotals.from_topology(context.topology)
    observed = snapshot.totals

    def fail(detail: str) -> t.NoReturn:
        raise TopologyVerificationError(requested, observed, detail)

    if observed != requested:
        fail("flat totals differ")
    session_ids = tuple(session.session_id for session in snapshot.sessions)
    window_ids = tuple(window.window_id for window in snapshot.windows)
    pane_ids = tuple(pane.pane_id for pane in snapshot.panes)
    if len(set(session_ids)) != requested.sessions or any(
        not value.startswith("$") for value in session_ids
    ):
        fail("session identifiers are not unique concrete ids")
    if len(set(window_ids)) != requested.windows or any(
        not value.startswith("@") for value in window_ids
    ):
        fail("window identifiers are not unique concrete ids")
    if len(set(pane_ids)) != requested.panes or any(
        not value.startswith("%") for value in pane_ids
    ):
        fail("pane identifiers are not unique concrete ids")
    if tuple(session.name for session in snapshot.sessions) != (
        context.expected_session_names
    ):
        fail("session names differ from the declaration")
    if {window.name for window in snapshot.windows} != set(
        context.expected_window_names
    ):
        fail("window names differ from the declaration")

    session_ids_by_name = {
        t.cast(str, session.name): session.session_id for session in snapshot.sessions
    }
    expected_window_parents = dict(context.expected_window_parents)
    windows_by_name = {t.cast(str, window.name): window for window in snapshot.windows}
    for window_name, expected_session_name in context.expected_window_parents:
        window = windows_by_name[window_name]
        if window.session_id != session_ids_by_name[expected_session_name]:
            fail("window parent differs from the declaration")

    window_counts = dict.fromkeys(session_ids, 0)
    for window in snapshot.windows:
        if window.session_id not in window_counts:
            fail("window refers to an unknown session")
        window_counts[window.session_id] += 1
    if set(window_counts.values()) != {context.topology.windows_per_session}:
        fail("a session has the wrong window count")
    pane_counts = dict.fromkeys(window_ids, 0)
    windows_by_id = {window.window_id: window for window in snapshot.windows}
    for pane in snapshot.panes:
        if pane.window_id not in pane_counts or pane.session_id not in window_counts:
            fail("pane refers to an unknown owner")
        if pane.session_id != windows_by_id[pane.window_id].session_id:
            fail("pane session differs from its window parent")
        pane_counts[pane.window_id] += 1
    if set(pane_counts.values()) != {context.topology.panes_per_window}:
        fail("a window has the wrong pane count")

    pane_pids = tuple(pane.pid for pane in snapshot.panes)
    if any(pid is None or pid <= 0 for pid in pane_pids):
        fail("a pane has no positive follower pid")
    positive_pids = t.cast(tuple[int, ...], pane_pids)
    if len(set(positive_pids)) != requested.panes:
        fail("pane follower pids are not unique")
    if any(pane.fields.get("pane_dead") != "0" for pane in snapshot.panes):
        fail("a pane is dead")
    delayed_path = str(context.streams[-1])
    delayed = tuple(
        pane
        for pane in snapshot.panes
        if delayed_path in pane.fields.get("pane_start_command", "")
    )
    if len(delayed) != 1:
        fail("delayed stream does not have exactly one follower")
    if any(
        "exec tail -n 0 -f" not in pane.fields.get("pane_start_command", "")
        for pane in snapshot.panes
    ):
        fail("a pane is not running the portable follower command")
    try:
        pane_processes = tuple(_record_process("pane", pid) for pid in positive_pids)
    except RuntimeError as error:
        fail(str(error))
    if context.fuzzer.poll() is not None:
        fail("fuzzer exited before activity release")

    context.session_ids = session_ids
    context.window_ids = window_ids
    context.pane_ids = pane_ids
    context.session_bindings = tuple(
        (name, session_ids_by_name[name]) for name in context.expected_session_names
    )
    context.window_bindings = tuple(
        (
            name,
            windows_by_name[name].window_id,
            session_ids_by_name[expected_window_parents[name]],
        )
        for name in context.expected_window_names
    )
    context.delayed_pane_id = delayed[0].pane_id
    context.processes = (
        *(process for process in context.processes if process.role != "pane"),
        *pane_processes,
    )
    context.topology_verified = True
    return snapshot


def _read_run_marker(path: pathlib.Path, run_id: str) -> dict[str, t.Any] | None:
    """Return a complete schema-v1 marker owned by ``run_id``.

    >>> _read_run_marker(pathlib.Path("missing.json"), "run-7") is None
    True

    Parameters
    ----------
    path : pathlib.Path
        Candidate JSON marker.
    run_id : str
        Required owner identity.

    Returns
    -------
    dict[str, typing.Any] | None
        Matching mapping, or ``None`` for missing, malformed, or foreign data.
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


def _heartbeat_epoch(context: RunContext) -> tuple[str | None, int | None]:
    """Return the current matching fuzzer state and integer epoch.

    >>> with tempfile.TemporaryDirectory() as temporary:
    ...     scratch = pathlib.Path(temporary)
    ...     (scratch / "fuzzer").mkdir()
    ...     write_json_atomic(
    ...         scratch / "fuzzer" / "heartbeat.json",
    ...         {"schema_version": 1, "run_id": "run-7", "state": "active",
    ...          "epoch": 3},
    ...     )
    ...     _heartbeat_epoch(types.SimpleNamespace(scratch=scratch, run_id="run-7"))
    ('active', 3)

    Parameters
    ----------
    context : RunContext
        Run whose heartbeat marker is authoritative.

    Returns
    -------
    tuple[str | None, int | None]
        Marker state and epoch, or two ``None`` values before publication.
    """
    marker = _read_run_marker(
        context.scratch / "fuzzer" / "heartbeat.json", context.run_id
    )
    if marker is None:
        return None, None
    state = marker.get("state")
    epoch = marker.get("epoch")
    return (
        state if isinstance(state, str) else None,
        epoch if type(epoch) is int and epoch >= 0 else None,
    )


def release_activity_gate(context: RunContext) -> int:
    """Atomically release one verified topology and publish its shared epoch.

    The fuzzer's heartbeat independently proves continuing activity. The shared
    run marker establishes one exact stabilization target across streams whose
    ordinary frame prefixes otherwise differ by mode.

    >>> try:
    ...     release_activity_gate(types.SimpleNamespace(topology_verified=False))
    ... except RuntimeError as error:
    ...     print(error)
    activity cannot start before exact topology verification

    Parameters
    ----------
    context : RunContext
        Exact verified live topology.

    Returns
    -------
    int
        Monotonic epoch carried by the shared pane marker.

    Raises
    ------
    RuntimeError
        If topology verification has not completed or the fuzzer exited.
    """
    if not context.topology_verified:
        message = "activity cannot start before exact topology verification"
        raise RuntimeError(message)
    if context.fuzzer.poll() is not None:
        message = "fuzzer exited before activity release"
        raise RuntimeError(message)
    if context.activity_epoch is not None:
        return context.activity_epoch
    _state, observed_epoch = _heartbeat_epoch(context)
    epoch = max(context.heartbeat_epoch, observed_epoch or 0) + 1
    marker = f"LIBTMUX_EPOCH run={context.run_id} epoch={epoch}"
    write_json_atomic(
        context.scratch / "fuzzer" / "gate.json",
        {"schema_version": 1, "run_id": context.run_id, "epoch": epoch},
    )
    encoded = f"{marker}\n".encode()
    for stream in context.streams:
        with stream.open("ab") as destination:
            destination.write(encoded)
            destination.flush()
            os.fsync(destination.fileno())
    context.activity_epoch = epoch
    context.activity_marker = marker
    context.heartbeat_epoch = observed_epoch or 0
    return epoch


def verify_activity_sync(
    context: RunContext,
    *,
    timeout_s: float = 8.0,
    no_progress_timeout_s: float = 3.0,
    poll_interval_s: float = 0.02,
) -> int:
    """Poll typed pane captures until every pane contains the released marker.

    >>> try:
    ...     verify_activity_sync(types.SimpleNamespace(mode=ExecutionMode.ASYNC))
    ... except ValueError as error:
    ...     print(error)
    sync activity verification requires a synchronous context

    Parameters
    ----------
    context : RunContext
        Released synchronous live run.
    timeout_s : float
        Overall stabilization deadline.
    no_progress_timeout_s : float
        Deadline reset whenever another pane verifies.
    poll_interval_s : float
        Delay between incomplete capture passes.

    Returns
    -------
    int
        Verified shared activity epoch.

    Raises
    ------
    ValueError
        If the context mode or timeout values are invalid.
    RuntimeError
        If the gate is absent, the fuzzer exits, or heartbeat epochs regress.
    TimeoutError
        If overall or no-progress stabilization expires.
    """
    from libtmux.experimental.ops import CapturePane, PaneId, run

    if context.mode is not ExecutionMode.SYNC:
        message = "sync activity verification requires a synchronous context"
        raise ValueError(message)
    if context.activity_epoch is None or context.activity_marker is None:
        message = "activity gate has not been released"
        raise RuntimeError(message)
    if timeout_s <= 0 or no_progress_timeout_s <= 0 or poll_interval_s <= 0:
        message = "activity verification timeouts and cadence must be positive"
        raise ValueError(message)
    engine = t.cast("TmuxEngine", context.engine)
    remaining = set(context.pane_ids)
    deadline = time.monotonic() + timeout_s
    progress_deadline = time.monotonic() + no_progress_timeout_s
    heartbeat_active = False
    while remaining or not heartbeat_active:
        if context.fuzzer.poll() is not None:
            message = "fuzzer exited during activity stabilization"
            raise RuntimeError(message)
        state, heartbeat_epoch = _heartbeat_epoch(context)
        if heartbeat_epoch is not None:
            if heartbeat_epoch < context.heartbeat_epoch:
                message = "fuzzer heartbeat epoch moved backwards"
                raise RuntimeError(message)
            context.heartbeat_epoch = heartbeat_epoch
        heartbeat_active = (
            state == "active"
            and heartbeat_epoch is not None
            and heartbeat_epoch >= context.activity_epoch
        )
        before = len(remaining)
        for pane_id in tuple(remaining):
            result = run(
                CapturePane(target=PaneId(pane_id), start=-5000),
                engine,
            ).raise_for_status()
            if context.activity_marker in "\n".join(result.lines):
                remaining.remove(pane_id)
        now = time.monotonic()
        if len(remaining) < before:
            progress_deadline = now + no_progress_timeout_s
        if not remaining and heartbeat_active:
            break
        if now >= deadline:
            message = (
                f"activity stabilization timed out with {len(remaining)} panes pending"
            )
            raise TimeoutError(message)
        if now >= progress_deadline:
            message = (
                "activity stabilization made no progress with "
                f"{len(remaining)} panes pending"
            )
            raise TimeoutError(message)
        time.sleep(poll_interval_s)
    context.activity_pane_ids = context.pane_ids
    return context.activity_epoch


async def verify_activity_async(
    context: RunContext,
    *,
    timeout_s: float = 8.0,
    no_progress_timeout_s: float = 3.0,
    poll_interval_s: float = 0.02,
) -> int:
    """Async sibling of :func:`verify_activity_sync` over typed captures.

    >>> wrong_mode = types.SimpleNamespace(mode=ExecutionMode.SYNC)
    >>> try:
    ...     asyncio.run(verify_activity_async(wrong_mode))
    ... except ValueError as error:
    ...     print(error)
    async activity verification requires an asynchronous context

    Parameters
    ----------
    context : RunContext
        Released asynchronous live run.
    timeout_s : float
        Overall stabilization deadline.
    no_progress_timeout_s : float
        Deadline reset whenever another pane verifies.
    poll_interval_s : float
        Delay between incomplete capture passes.

    Returns
    -------
    int
        Verified shared activity epoch.

    Raises
    ------
    ValueError
        If the context mode or timeout values are invalid.
    RuntimeError
        If the gate is absent, the fuzzer exits, or heartbeat epochs regress.
    TimeoutError
        If overall or no-progress stabilization expires.
    """
    from libtmux.experimental.ops import CapturePane, PaneId, arun

    if context.mode is not ExecutionMode.ASYNC:
        message = "async activity verification requires an asynchronous context"
        raise ValueError(message)
    if context.activity_epoch is None or context.activity_marker is None:
        message = "activity gate has not been released"
        raise RuntimeError(message)
    if timeout_s <= 0 or no_progress_timeout_s <= 0 or poll_interval_s <= 0:
        message = "activity verification timeouts and cadence must be positive"
        raise ValueError(message)
    engine = t.cast("AsyncTmuxEngine", context.engine)
    remaining = set(context.pane_ids)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    progress_deadline = loop.time() + no_progress_timeout_s
    heartbeat_active = False
    while remaining or not heartbeat_active:
        if context.fuzzer.poll() is not None:
            message = "fuzzer exited during activity stabilization"
            raise RuntimeError(message)
        state, heartbeat_epoch = _heartbeat_epoch(context)
        if heartbeat_epoch is not None:
            if heartbeat_epoch < context.heartbeat_epoch:
                message = "fuzzer heartbeat epoch moved backwards"
                raise RuntimeError(message)
            context.heartbeat_epoch = heartbeat_epoch
        heartbeat_active = (
            state == "active"
            and heartbeat_epoch is not None
            and heartbeat_epoch >= context.activity_epoch
        )
        before = len(remaining)
        for pane_id in tuple(remaining):
            result = (
                await arun(
                    CapturePane(target=PaneId(pane_id), start=-5000),
                    engine,
                )
            ).raise_for_status()
            if context.activity_marker in "\n".join(result.lines):
                remaining.remove(pane_id)
        now = loop.time()
        if len(remaining) < before:
            progress_deadline = now + no_progress_timeout_s
        if not remaining and heartbeat_active:
            break
        if now >= deadline:
            message = (
                f"activity stabilization timed out with {len(remaining)} panes pending"
            )
            raise TimeoutError(message)
        if now >= progress_deadline:
            message = (
                "activity stabilization made no progress with "
                f"{len(remaining)} panes pending"
            )
            raise TimeoutError(message)
        await asyncio.sleep(poll_interval_s)
    context.activity_pane_ids = context.pane_ids
    return context.activity_epoch


_GENERATION_OPTION = "@libtmux_bench_generation"


def _phase_metrics(
    context: RunContext,
    *,
    operations: int,
    planner_steps: int,
) -> ExecutionMetrics:
    """Derive comparable logical and transport counts for one measured cell.

    >>> context = types.SimpleNamespace(lane=EngineLane.SUBPROCESS)
    >>> _phase_metrics(context, operations=4, planner_steps=1).process_starts
    4

    Parameters
    ----------
    context : RunContext
        Live run whose transport determines modeled process starts.
    operations : int
        Individually attributable tmux requests.
    planner_steps : int
        Engine dispatch groups selected by the planner.

    Returns
    -------
    ExecutionMetrics
        Separate operation, planning, request, and process-start quantities.
    """
    return ExecutionMetrics(
        operations=operations,
        planner_steps=planner_steps,
        engine_batches=planner_steps,
        tmux_requests=operations,
        process_starts=(operations if context.lane is EngineLane.SUBPROCESS else 0),
    )


def _require_active_phase_context(
    context: RunContext,
    mode: ExecutionMode,
) -> None:
    """Reject phase work before exact topology and activity verification.

    >>> inactive = types.SimpleNamespace(
    ...     mode=ExecutionMode.SYNC, topology_verified=False,
    ...     activity_epoch=None, activity_marker=None,
    ... )
    >>> try:
    ...     _require_active_phase_context(inactive, ExecutionMode.SYNC)
    ... except RuntimeError as error:
    ...     print(error)
    measured phases require verified active topology

    Parameters
    ----------
    context : RunContext
        Candidate live run context.
    mode : ExecutionMode
        Required synchronous or asynchronous execution mode.

    Raises
    ------
    ValueError
        If the context belongs to the other execution mode.
    RuntimeError
        If topology or activity stabilization has not completed.
    """
    if context.mode is not mode:
        message = f"{mode.value} phase requires a {mode.value} run context"
        raise ValueError(message)
    if (
        not context.topology_verified
        or context.activity_epoch is None
        or context.activity_marker is None
    ):
        message = "measured phases require verified active topology"
        raise RuntimeError(message)


def _current_activity_heartbeat(
    context: RunContext,
    *,
    max_age_s: float,
) -> HeartbeatObservation:
    """Read one fresh active heartbeat with epoch and monotonic timestamps.

    >>> context = types.SimpleNamespace(fuzzer=types.SimpleNamespace(poll=lambda: 1))
    >>> try:
    ...     _current_activity_heartbeat(context, max_age_s=1)
    ... except RuntimeError as error:
    ...     print(error)
    fuzzer exited during measured phase

    Parameters
    ----------
    context : RunContext
        Active run whose heartbeat is authoritative.
    max_age_s : float
        Maximum permitted age of the fuzzer publication timestamp.

    Returns
    -------
    HeartbeatObservation
        Current active epoch with publication and local observation times.

    Raises
    ------
    RuntimeError
        If the fuzzer exited, heartbeat is inactive, stale, or regressed.
    ValueError
        If ``max_age_s`` is not positive.
    """
    if max_age_s <= 0:
        message = "heartbeat maximum age must be positive"
        raise ValueError(message)
    if context.fuzzer.poll() is not None:
        message = "fuzzer exited during measured phase"
        raise RuntimeError(message)
    marker = _read_run_marker(
        context.scratch / "fuzzer" / "heartbeat.json", context.run_id
    )
    if marker is None or marker.get("state") != "active":
        message = "fuzzer heartbeat is not active during measured phase"
        raise RuntimeError(message)
    epoch = marker.get("epoch")
    published_monotonic_ns = marker.get("monotonic_ns")
    if (
        type(epoch) is not int
        or epoch < 0
        or type(published_monotonic_ns) is not int
        or published_monotonic_ns < 0
    ):
        message = "fuzzer heartbeat has invalid activity evidence"
        raise RuntimeError(message)
    observed_monotonic_ns = time.monotonic_ns()
    age_ns = observed_monotonic_ns - published_monotonic_ns
    if age_ns < 0:
        message = "fuzzer heartbeat publication is in the future"
        raise RuntimeError(message)
    if age_ns > int(max_age_s * 1_000_000_000):
        message = "fuzzer heartbeat is stale during measured phase"
        raise RuntimeError(message)
    if epoch < context.heartbeat_epoch:
        message = "fuzzer heartbeat epoch moved backwards"
        raise RuntimeError(message)
    previous_monotonic_ns = getattr(context, "heartbeat_monotonic_ns", -1)
    if published_monotonic_ns < previous_monotonic_ns:
        message = "fuzzer heartbeat timestamp moved backwards"
        raise RuntimeError(message)
    context.heartbeat_epoch = epoch
    context.heartbeat_monotonic_ns = published_monotonic_ns
    return HeartbeatObservation(
        epoch=epoch,
        published_monotonic_ns=published_monotonic_ns,
        observed_monotonic_ns=observed_monotonic_ns,
    )


def _wait_activity_advance_sync(
    context: RunContext,
    baseline: HeartbeatObservation,
    *,
    timeout_s: float = 2.0,
) -> HeartbeatObservation:
    """Wait until the live fuzzer heartbeat advances past ``baseline``.

    >>> try:
    ...     _wait_activity_advance_sync(types.SimpleNamespace(), 0, timeout_s=0)
    ... except ValueError as error:
    ...     print(error)
    activity advance timeout must be positive

    Parameters
    ----------
    context : RunContext
        Active synchronous run.
    baseline : HeartbeatObservation
        Post-restoration heartbeat that the fuzzer must surpass.
    timeout_s : float
        Maximum monotonic wait.

    Returns
    -------
    HeartbeatObservation
        First observation with a later epoch and publication timestamp.

    Raises
    ------
    ValueError
        If ``timeout_s`` is not positive.
    TimeoutError
        If activity does not advance before the deadline.
    """
    if timeout_s <= 0:
        message = "activity advance timeout must be positive"
        raise ValueError(message)
    deadline_ns = time.monotonic_ns() + int(timeout_s * 1_000_000_000)
    maximum_age_s = (
        timeout_s
        + (baseline.observed_monotonic_ns - baseline.published_monotonic_ns)
        / 1_000_000_000
    )
    while time.monotonic_ns() < deadline_ns:
        heartbeat = _current_activity_heartbeat(context, max_age_s=maximum_age_s)
        if (
            heartbeat.epoch > baseline.epoch
            and heartbeat.published_monotonic_ns > baseline.published_monotonic_ns
            and heartbeat.observed_monotonic_ns > baseline.observed_monotonic_ns
            and heartbeat.observed_monotonic_ns <= deadline_ns
        ):
            return heartbeat
        time.sleep(0.005)
    message = f"activity did not advance past epoch {baseline.epoch}"
    raise TimeoutError(message)


async def _wait_activity_advance_async(
    context: RunContext,
    baseline: HeartbeatObservation,
    *,
    timeout_s: float = 2.0,
) -> HeartbeatObservation:
    """Asynchronously wait for a later active heartbeat epoch.

    >>> async def invalid_wait():
    ...     try:
    ...         await _wait_activity_advance_async(
    ...             types.SimpleNamespace(), 0, timeout_s=0
    ...         )
    ...     except ValueError as error:
    ...         return str(error)
    >>> asyncio.run(invalid_wait())
    'activity advance timeout must be positive'

    Parameters
    ----------
    context : RunContext
        Active asynchronous run.
    baseline : HeartbeatObservation
        Post-restoration heartbeat that the fuzzer must surpass.
    timeout_s : float
        Maximum event-loop wait.

    Returns
    -------
    HeartbeatObservation
        First observation with a later epoch and publication timestamp.

    Raises
    ------
    ValueError
        If ``timeout_s`` is not positive.
    TimeoutError
        If activity does not advance before the deadline.
    """
    if timeout_s <= 0:
        message = "activity advance timeout must be positive"
        raise ValueError(message)
    deadline_ns = time.monotonic_ns() + int(timeout_s * 1_000_000_000)
    maximum_age_s = (
        timeout_s
        + (baseline.observed_monotonic_ns - baseline.published_monotonic_ns)
        / 1_000_000_000
    )
    while time.monotonic_ns() < deadline_ns:
        heartbeat = _current_activity_heartbeat(context, max_age_s=maximum_age_s)
        if (
            heartbeat.epoch > baseline.epoch
            and heartbeat.published_monotonic_ns > baseline.published_monotonic_ns
            and heartbeat.observed_monotonic_ns > baseline.observed_monotonic_ns
            and heartbeat.observed_monotonic_ns <= deadline_ns
        ):
            return heartbeat
        await asyncio.sleep(0.005)
    message = f"activity did not advance past epoch {baseline.epoch}"
    raise TimeoutError(message)


def request_sentinel(
    context: RunContext,
    *,
    request_id: str,
    value: str = "READY",
) -> SentinelRequest:
    """Atomically publish one unique request for the active delayed stream.

    Examples
    --------
    >>> with tempfile.TemporaryDirectory() as temporary:
    ...     scratch = pathlib.Path(temporary)
    ...     (scratch / "fuzzer" / "requests").mkdir(parents=True)
    ...     (scratch / "fuzzer" / "sentinels").mkdir()
    ...     context = types.SimpleNamespace(
    ...         run_id="run-7", scratch=scratch, sentinel_delay_ns=5,
    ...         delayed_pane_id="%1", fuzzer=types.SimpleNamespace(poll=lambda: None),
    ...     )
    ...     request = request_sentinel(context, request_id="sample-1", value="GO")
    ...     request.request_id, request.token.endswith("value=GO")
    ('sample-1', True)

    Parameters
    ----------
    context : RunContext
        Active topology whose fuzzer owns the request directory.
    request_id : str
        Unique ASCII identifier containing only letters, digits, hyphens, or
        underscores.
    value : str
        Nonempty single-line value embedded in the canonical sentinel.

    Returns
    -------
    SentinelRequest
        Exact request identity, token, publication time, and configured delay.

    Raises
    ------
    ValueError
        If request identity, value, delay, or delayed pane is invalid.
    FileExistsError
        If the request or its evidence path already exists.
    RuntimeError
        If the fuzzer has exited.
    OSError
        If atomic marker publication fails.
    """
    if (
        not request_id
        or len(request_id) > 128
        or any(
            not (character.isascii() and (character.isalnum() or character in "-_"))
            for character in request_id
        )
    ):
        message = (
            "request_id must contain 1-128 ASCII letters, digits, hyphens, "
            "or underscores"
        )
        raise ValueError(message)
    if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
        message = "sentinel value must be a nonempty single line"
        raise ValueError(message)
    delay_ns = context.sentinel_delay_ns
    if type(delay_ns) is not int or delay_ns < 0:
        message = "sentinel delay must be a nonnegative integer nanosecond value"
        raise ValueError(message)
    if not isinstance(context.delayed_pane_id, str) or not context.delayed_pane_id:
        message = "wait requires a verified delayed pane ID"
        raise ValueError(message)
    if context.fuzzer.poll() is not None:
        message = "fuzzer exited before sentinel request"
        raise RuntimeError(message)
    requests = context.scratch / "fuzzer" / "requests"
    sentinels = context.scratch / "fuzzer" / "sentinels"
    request_path = requests / f"{request_id}.json"
    evidence_path = sentinels / f"{request_id}.json"
    if request_path.exists() or evidence_path.exists():
        message = f"sentinel request already exists: {request_id}"
        raise FileExistsError(message)
    token = f"LIBTMUX_SENTINEL run={context.run_id} request={request_id} value={value}"
    requested_ns = time.monotonic_ns()
    write_json_atomic(
        request_path,
        {
            "schema_version": 1,
            "run_id": context.run_id,
            "request_id": request_id,
            "requested_monotonic_ns": requested_ns,
            "value": value,
        },
    )
    return SentinelRequest(request_id, token, requested_ns, delay_ns)


def _validated_sentinel_evidence(
    context: RunContext,
    request: SentinelRequest,
    marker: cabc.Mapping[str, t.Any],
) -> tuple[int, int, int]:
    r"""Validate exact request evidence and return its derived timing fields.

    Examples
    --------
    >>> token = "LIBTMUX_SENTINEL run=run-7 request=sample-1 value=GO"
    >>> request = SentinelRequest("sample-1", token, 7, 5)
    >>> marker = {
    ...     "schema_version": 1, "run_id": "run-7", "request_id": "sample-1",
    ...     "requested_monotonic_ns": 7, "configured_delay_ns": 5,
    ...     "scheduled_monotonic_ns": 12, "emitted_monotonic_ns": 14,
    ...     "scheduling_lateness_ns": 2, "sentinel": token,
    ...     "sentinel_sha256": hashlib.sha256(f"{token}\n".encode()).hexdigest(),
    ... }
    >>> _validated_sentinel_evidence(
    ...     types.SimpleNamespace(run_id="run-7"), request, marker
    ... )
    (12, 14, 2)

    Parameters
    ----------
    context : RunContext
        Run identity required in the marker.
    request : SentinelRequest
        Exact request whose stream token was detected.
    marker : collections.abc.Mapping[str, typing.Any]
        Parsed atomic schema-v1 evidence.

    Returns
    -------
    tuple[int, int, int]
        Scheduled timestamp, emitted timestamp, and scheduling lateness.

    Raises
    ------
    RuntimeError
        If identity, token, hash, integer types, or timing arithmetic differs.
    """
    integer_fields = (
        "requested_monotonic_ns",
        "configured_delay_ns",
        "scheduled_monotonic_ns",
        "emitted_monotonic_ns",
        "scheduling_lateness_ns",
    )
    if (
        type(marker.get("schema_version")) is not int
        or marker.get("schema_version") != 1
        or marker.get("run_id") != context.run_id
        or marker.get("request_id") != request.request_id
        or marker.get("sentinel") != request.token
        or any(
            type(marker.get(field)) is not int or marker[field] < 0
            for field in integer_fields
        )
    ):
        message = "sentinel evidence does not match request"
        raise RuntimeError(message)
    requested_ns = t.cast(int, marker["requested_monotonic_ns"])
    configured_delay_ns = t.cast(int, marker["configured_delay_ns"])
    scheduled_ns = t.cast(int, marker["scheduled_monotonic_ns"])
    emitted_ns = t.cast(int, marker["emitted_monotonic_ns"])
    scheduling_lateness_ns = t.cast(int, marker["scheduling_lateness_ns"])
    expected_hash = hashlib.sha256(f"{request.token}\n".encode()).hexdigest()
    if (
        requested_ns != request.requested_monotonic_ns
        or configured_delay_ns != request.configured_delay_ns
        or scheduled_ns != requested_ns + configured_delay_ns
        or emitted_ns < scheduled_ns
        or scheduling_lateness_ns != emitted_ns - scheduled_ns
        or marker.get("sentinel_sha256") != expected_hash
    ):
        message = "sentinel evidence does not match request"
        raise RuntimeError(message)
    return scheduled_ns, emitted_ns, scheduling_lateness_ns


def _read_sentinel_evidence(
    context: RunContext,
    request: SentinelRequest,
) -> cabc.Mapping[str, t.Any] | None:
    """Read absent evidence as ``None`` and reject every completed mismatch.

    >>> _read_sentinel_evidence(
    ...     types.SimpleNamespace(scratch=pathlib.Path("missing"), run_id="run-7"),
    ...     SentinelRequest("sample-1", "token", 7, 5),
    ... ) is None
    True

    Parameters
    ----------
    context : RunContext
        Run whose evidence directory is authoritative.
    request : SentinelRequest
        Exact request already detected in pane output.

    Returns
    -------
    collections.abc.Mapping[str, typing.Any] | None
        Valid matching evidence, or ``None`` before its atomic publication.

    Raises
    ------
    RuntimeError
        If a published file is malformed or does not match the request.
    TypeError
        If a published JSON value is not a mapping.
    """
    path = context.scratch / "fuzzer" / "sentinels" / f"{request.request_id}.json"
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as error:
        message = "sentinel evidence is not a complete JSON marker"
        raise RuntimeError(message) from error
    if not isinstance(parsed, dict):
        message = "sentinel evidence is not a mapping"
        raise TypeError(message)
    marker = t.cast(dict[str, t.Any], parsed)
    _validated_sentinel_evidence(context, request, marker)
    return marker


def _completed_wait_result(
    context: RunContext,
    request: SentinelRequest,
    evidence: cabc.Mapping[str, t.Any],
    *,
    strategy: WaitStrategy,
    detected_monotonic_ns: int,
    poll_count: int,
    frame_count: int,
    timeout_s: float,
    dropped_notification_delta: int,
) -> WaitResult:
    r"""Combine exact evidence with detection facts and reject invalid samples.

    Examples
    --------
    >>> token = "LIBTMUX_SENTINEL run=run-7 request=sample-1 value=GO"
    >>> request = SentinelRequest("sample-1", token, 7, 5)
    >>> evidence = {
    ...     "schema_version": 1, "run_id": "run-7", "request_id": "sample-1",
    ...     "requested_monotonic_ns": 7, "configured_delay_ns": 5,
    ...     "scheduled_monotonic_ns": 12, "emitted_monotonic_ns": 14,
    ...     "scheduling_lateness_ns": 2, "sentinel": token,
    ...     "sentinel_sha256": hashlib.sha256(f"{token}\n".encode()).hexdigest(),
    ... }
    >>> result = _completed_wait_result(
    ...     types.SimpleNamespace(run_id="run-7", delayed_pane_id="%1"),
    ...     request, evidence, strategy="capture-poll", detected_monotonic_ns=17,
    ...     poll_count=1, frame_count=0, timeout_s=1.0,
    ...     dropped_notification_delta=0,
    ... )
    >>> result.detection_overhead_ns
    3

    Parameters
    ----------
    context : RunContext
        Run containing the concrete delayed pane ID.
    request : SentinelRequest
        Request whose exact token was detected.
    evidence : collections.abc.Mapping[str, typing.Any]
        Matching schema-v1 fuzzer evidence.
    strategy : {"capture-poll", "control-stream"}
        Detection mechanism used.
    detected_monotonic_ns : int
        Local exact-match timestamp.
    poll_count : int
        Typed capture operations issued.
    frame_count : int
        Matching-pane output notifications consumed.
    timeout_s : float
        Configured monotonic timeout.
    dropped_notification_delta : int
        Engine drop-counter change during the wait.

    Returns
    -------
    WaitResult
        Verified timing and request evidence.

    Raises
    ------
    RuntimeError
        If timing, counters, pane identity, or notification integrity is invalid.
    """
    scheduled_ns, emitted_ns, scheduling_lateness_ns = _validated_sentinel_evidence(
        context, request, evidence
    )
    if detected_monotonic_ns < emitted_ns:
        message = "sentinel detection predates fuzzer emission"
        raise RuntimeError(message)
    if dropped_notification_delta != 0:
        message = f"control stream dropped {dropped_notification_delta} notification(s)"
        raise RuntimeError(message)
    if strategy == "capture-poll":
        valid_counts = poll_count > 0 and frame_count == 0
    else:
        valid_counts = poll_count == 0 and frame_count > 0
    if not valid_counts:
        message = "wait counters do not match the selected strategy"
        raise RuntimeError(message)
    pane_id = context.delayed_pane_id
    if not isinstance(pane_id, str) or not pane_id:
        message = "wait lacks a concrete delayed pane ID"
        raise RuntimeError(message)
    return WaitResult(
        strategy=strategy,
        request_id=request.request_id,
        token=request.token,
        pane_id=pane_id,
        configured_delay_ns=request.configured_delay_ns,
        requested_monotonic_ns=request.requested_monotonic_ns,
        scheduled_monotonic_ns=scheduled_ns,
        emitted_monotonic_ns=emitted_ns,
        detected_monotonic_ns=detected_monotonic_ns,
        scheduling_lateness_ns=scheduling_lateness_ns,
        detection_overhead_ns=detected_monotonic_ns - emitted_ns,
        poll_count=poll_count,
        frame_count=frame_count,
        timeout_s=float(timeout_s),
        timed_out=False,
        dropped_notification_delta=dropped_notification_delta,
        verified=True,
    )


def wait_capture_poll_sync(
    context: RunContext,
    *,
    request_id: str,
    value: str = "READY",
    timeout_s: float = 3.0,
    poll_interval_s: float = 0.01,
) -> WaitResult:
    """Request and detect one exact sentinel through typed sync captures.

    Examples
    --------
    >>> try:
    ...     wait_capture_poll_sync(types.SimpleNamespace(mode=ExecutionMode.ASYNC),
    ...                            request_id="sample-1")
    ... except ValueError as error:
    ...     print(error)
    sync capture wait requires a synchronous run context

    Parameters
    ----------
    context : RunContext
        Active synchronous topology with one verified delayed pane.
    request_id : str
        Unique request identity.
    value : str
        Unique request value embedded in the exact token.
    timeout_s : float
        Overall monotonic timeout including configured fuzzer delay.
    poll_interval_s : float
        Maximum sleep between typed capture operations.

    Returns
    -------
    WaitResult
        Exact detection and matching fuzzer timing evidence.

    Raises
    ------
    ValueError
        If mode, timeout, cadence, or request data is invalid.
    TimeoutError
        If exact detection or matching evidence misses the deadline.
    RuntimeError
        If the fuzzer exits or matching evidence is invalid.
    ~libtmux.experimental.ops.exc.TmuxCommandError
        If a typed capture fails.
    """
    from libtmux.experimental.ops import CapturePane, PaneId, run

    if context.mode is not ExecutionMode.SYNC:
        message = "sync capture wait requires a synchronous run context"
        raise ValueError(message)
    if timeout_s <= 0 or poll_interval_s <= 0:
        message = "capture wait timeout and cadence must be positive"
        raise ValueError(message)
    engine = t.cast("TmuxEngine", context.engine)
    pane_id = context.delayed_pane_id
    if not isinstance(pane_id, str) or not pane_id:
        message = "capture wait requires a concrete delayed pane ID"
        raise ValueError(message)
    request = request_sentinel(context, request_id=request_id, value=value)
    deadline_ns = request.requested_monotonic_ns + int(timeout_s * 1_000_000_000)
    operation = CapturePane(target=PaneId(pane_id), start=-5000, join_wrapped=True)
    needle = f"{request.token}\n".encode()
    poll_count = 0
    detected_ns: int | None = None
    while time.monotonic_ns() < deadline_ns:
        if context.fuzzer.poll() is not None:
            message = "fuzzer exited during capture wait"
            raise RuntimeError(message)
        result = run(operation, engine).raise_for_status()
        poll_count += 1
        captured = ("\n".join(result.lines) + "\n").encode()
        observed_ns = time.monotonic_ns()
        if needle in captured and observed_ns <= deadline_ns:
            detected_ns = observed_ns
            break
        remaining_ns = deadline_ns - time.monotonic_ns()
        if remaining_ns > 0:
            time.sleep(min(poll_interval_s, remaining_ns / 1_000_000_000))
    if detected_ns is None:
        message = f"capture wait timed out for request {request.request_id}"
        raise TimeoutError(message)
    evidence = _read_sentinel_evidence(context, request)
    while evidence is None and time.monotonic_ns() < deadline_ns:
        if context.fuzzer.poll() is not None:
            message = "fuzzer exited before sentinel evidence"
            raise RuntimeError(message)
        time.sleep(0.001)
        evidence = _read_sentinel_evidence(context, request)
    if evidence is None:
        message = f"sentinel evidence timed out for request {request.request_id}"
        raise TimeoutError(message)
    return _completed_wait_result(
        context,
        request,
        evidence,
        strategy="capture-poll",
        detected_monotonic_ns=detected_ns,
        poll_count=poll_count,
        frame_count=0,
        timeout_s=timeout_s,
        dropped_notification_delta=0,
    )


async def wait_capture_poll_async(
    context: RunContext,
    *,
    request_id: str,
    value: str = "READY",
    timeout_s: float = 3.0,
    poll_interval_s: float = 0.01,
) -> WaitResult:
    """Request and detect one exact sentinel through typed async captures.

    Examples
    --------
    >>> async def invalid_wait():
    ...     try:
    ...         await wait_capture_poll_async(
    ...             types.SimpleNamespace(mode=ExecutionMode.SYNC),
    ...             request_id="sample-1",
    ...         )
    ...     except ValueError as error:
    ...         return str(error)
    >>> asyncio.run(invalid_wait())
    'async capture wait requires an asynchronous run context'

    Parameters
    ----------
    context : RunContext
        Active asynchronous topology with one verified delayed pane.
    request_id : str
        Unique request identity.
    value : str
        Unique request value embedded in the exact token.
    timeout_s : float
        Overall monotonic timeout including configured fuzzer delay.
    poll_interval_s : float
        Maximum event-loop sleep between typed capture operations.

    Returns
    -------
    WaitResult
        Exact detection and matching fuzzer timing evidence.

    Raises
    ------
    ValueError
        If mode, timeout, cadence, or request data is invalid.
    TimeoutError
        If exact detection or matching evidence misses the deadline.
    RuntimeError
        If the fuzzer exits or matching evidence is invalid.
    ~libtmux.experimental.ops.exc.TmuxCommandError
        If a typed capture fails.
    """
    from libtmux.experimental.ops import CapturePane, PaneId, arun

    if context.mode is not ExecutionMode.ASYNC:
        message = "async capture wait requires an asynchronous run context"
        raise ValueError(message)
    if timeout_s <= 0 or poll_interval_s <= 0:
        message = "capture wait timeout and cadence must be positive"
        raise ValueError(message)
    engine = t.cast("AsyncTmuxEngine", context.engine)
    pane_id = context.delayed_pane_id
    if not isinstance(pane_id, str) or not pane_id:
        message = "capture wait requires a concrete delayed pane ID"
        raise ValueError(message)
    request = request_sentinel(context, request_id=request_id, value=value)
    deadline_ns = request.requested_monotonic_ns + int(timeout_s * 1_000_000_000)
    operation = CapturePane(target=PaneId(pane_id), start=-5000, join_wrapped=True)
    needle = f"{request.token}\n".encode()
    poll_count = 0
    detected_ns: int | None = None
    while time.monotonic_ns() < deadline_ns:
        if context.fuzzer.poll() is not None:
            message = "fuzzer exited during capture wait"
            raise RuntimeError(message)
        result = (await arun(operation, engine)).raise_for_status()
        poll_count += 1
        captured = ("\n".join(result.lines) + "\n").encode()
        observed_ns = time.monotonic_ns()
        if needle in captured and observed_ns <= deadline_ns:
            detected_ns = observed_ns
            break
        remaining_ns = deadline_ns - time.monotonic_ns()
        if remaining_ns > 0:
            await asyncio.sleep(min(poll_interval_s, remaining_ns / 1_000_000_000))
    if detected_ns is None:
        message = f"capture wait timed out for request {request.request_id}"
        raise TimeoutError(message)
    evidence = _read_sentinel_evidence(context, request)
    while evidence is None and time.monotonic_ns() < deadline_ns:
        if context.fuzzer.poll() is not None:
            message = "fuzzer exited before sentinel evidence"
            raise RuntimeError(message)
        await asyncio.sleep(0.001)
        evidence = _read_sentinel_evidence(context, request)
    if evidence is None:
        message = f"sentinel evidence timed out for request {request.request_id}"
        raise TimeoutError(message)
    return _completed_wait_result(
        context,
        request,
        evidence,
        strategy="capture-poll",
        detected_monotonic_ns=detected_ns,
        poll_count=poll_count,
        frame_count=0,
        timeout_s=timeout_s,
        dropped_notification_delta=0,
    )


async def wait_control_stream(
    context: RunContext,
    *,
    request_id: str,
    value: str = "READY",
    timeout_s: float = 3.0,
) -> WaitResult:
    """Detect one exact sentinel in decoded async control output.

    The subscription is advanced before request publication. Only decoded
    ``%output`` and ``%extended-output`` bytes for the concrete delayed pane
    participate in matching. A suffix of at most ``len(token) - 1`` bytes
    carries a possible partial match across notification boundaries.

    Examples
    --------
    >>> async def invalid_wait():
    ...     try:
    ...         await wait_control_stream(
    ...             types.SimpleNamespace(
    ...                 mode=ExecutionMode.SYNC, lane=EngineLane.CONTROL
    ...             ),
    ...             request_id="sample-1",
    ...         )
    ...     except ValueError as error:
    ...         return str(error)
    >>> asyncio.run(invalid_wait())
    'control stream wait requires an asynchronous context'

    Parameters
    ----------
    context : RunContext
        Active asynchronous control-mode topology.
    request_id : str
        Unique request identity.
    value : str
        Unique request value embedded in the exact token.
    timeout_s : float
        Overall monotonic timeout including configured fuzzer delay.

    Returns
    -------
    WaitResult
        Exact decoded detection and matching fuzzer timing evidence.

    Raises
    ------
    ValueError
        If mode, lane, timeout, or request data is invalid.
    TypeError
        If the context engine is not :class:`AsyncControlModeEngine`.
    TimeoutError
        If exact detection or matching evidence misses the deadline.
    RuntimeError
        If the stream ends, the fuzzer exits, evidence differs, or output drops.
    """
    from libtmux.experimental.engines.async_control_mode import (
        AsyncControlModeEngine,
    )

    if context.mode is not ExecutionMode.ASYNC:
        message = "control stream wait requires an asynchronous context"
        raise ValueError(message)
    if context.lane is not EngineLane.CONTROL:
        message = "control stream wait requires the control engine lane"
        raise ValueError(message)
    if timeout_s <= 0:
        message = "control stream wait timeout must be positive"
        raise ValueError(message)
    if not isinstance(context.engine, AsyncControlModeEngine):
        message = "control stream wait requires AsyncControlModeEngine"
        raise TypeError(message)
    pane_id = context.delayed_pane_id
    if not isinstance(pane_id, str) or not pane_id:
        message = "control stream wait requires a concrete delayed pane ID"
        raise ValueError(message)
    engine = context.engine
    dropped_before = engine.dropped_notifications
    subscription = t.cast(t.AsyncGenerator[t.Any, None], engine.subscribe())
    next_notification: asyncio.Task[t.Any] | None = asyncio.create_task(
        anext(subscription),
        name=f"bench-control-wait-{request_id}",
    )
    request: SentinelRequest | None = None
    evidence: cabc.Mapping[str, t.Any] | None = None
    detected_ns: int | None = None
    frame_count = 0
    try:
        await asyncio.sleep(0)
        assert next_notification is not None
        if next_notification.done() and not next_notification.cancelled():
            failure = next_notification.exception()
            if failure is not None:
                message = "control notification stream ended before request"
                raise RuntimeError(message) from failure
        request = request_sentinel(context, request_id=request_id, value=value)
        deadline_ns = request.requested_monotonic_ns + int(timeout_s * 1_000_000_000)
        needle = request.token.encode()
        suffix = b""
        suffix_limit = max(0, len(needle) - 1)
        while time.monotonic_ns() < deadline_ns:
            if context.fuzzer.poll() is not None:
                message = "fuzzer exited during control stream wait"
                raise RuntimeError(message)
            remaining_s = (deadline_ns - time.monotonic_ns()) / 1_000_000_000
            if remaining_s <= 0:
                break
            assert next_notification is not None
            try:
                notification = await asyncio.wait_for(
                    next_notification,
                    timeout=remaining_s,
                )
            except asyncio.TimeoutError:
                next_notification = None
                break
            except StopAsyncIteration as error:
                next_notification = None
                message = "control notification stream ended during wait"
                raise RuntimeError(message) from error
            next_notification = None
            if (
                notification.kind in {"output", "extended-output"}
                and notification.pane_id == pane_id
                and notification.payload is not None
            ):
                frame_count += 1
                combined = suffix + notification.payload
                observed_ns = time.monotonic_ns()
                if needle in combined and observed_ns <= deadline_ns:
                    detected_ns = observed_ns
                    break
                suffix = combined[-suffix_limit:] if suffix_limit else b""
            next_notification = asyncio.create_task(
                anext(subscription),
                name=f"bench-control-wait-{request_id}",
            )
        if detected_ns is None:
            message = f"control stream wait timed out for request {request.request_id}"
            raise TimeoutError(message)
        evidence = _read_sentinel_evidence(context, request)
        while evidence is None and time.monotonic_ns() < deadline_ns:
            if context.fuzzer.poll() is not None:
                message = "fuzzer exited before sentinel evidence"
                raise RuntimeError(message)
            await asyncio.sleep(0.001)
            evidence = _read_sentinel_evidence(context, request)
        if evidence is None:
            message = f"sentinel evidence timed out for request {request.request_id}"
            raise TimeoutError(message)
    finally:
        if next_notification is not None:
            if not next_notification.done():
                next_notification.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await next_notification
        await subscription.aclose()
    assert request is not None
    assert evidence is not None
    assert detected_ns is not None
    dropped_delta = engine.dropped_notifications - dropped_before
    return _completed_wait_result(
        context,
        request,
        evidence,
        strategy="control-stream",
        detected_monotonic_ns=detected_ns,
        poll_count=0,
        frame_count=frame_count,
        timeout_s=timeout_s,
        dropped_notification_delta=dropped_delta,
    )


def _mutation_targets(
    context: RunContext,
    snapshot: TopologySnapshot,
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """Select one largest session and its stable concrete descendants.

    >>> from libtmux.experimental.models import SessionSnapshot
    >>> context = types.SimpleNamespace(
    ...     session_ids=("$0", "$1"), window_ids=(), pane_ids=()
    ... )
    >>> snapshot = TopologySnapshot(
    ...     (SessionSnapshot(session_id="$0"), SessionSnapshot(session_id="$1")),
    ...     (), (),
    ... )
    >>> _mutation_targets(context, snapshot)
    ('$0', (), ())

    Parameters
    ----------
    context : RunContext
        Verified stable ID order.
    snapshot : TopologySnapshot
        Current typed hierarchy ownership rows.

    Returns
    -------
    tuple[str, tuple[str, ...], tuple[str, ...]]
        Session ID, owned window IDs, and owned pane IDs in stable order.
    """
    window_counts = dict.fromkeys(context.session_ids, 0)
    for window in snapshot.windows:
        if window.session_id in window_counts:
            window_counts[window.session_id] += 1
    session_id = max(context.session_ids, key=window_counts.__getitem__)
    window_id_set = {
        window.window_id
        for window in snapshot.windows
        if window.session_id == session_id
    }
    window_ids = tuple(
        window_id for window_id in context.window_ids if window_id in window_id_set
    )
    pane_id_set = {
        pane.pane_id for pane in snapshot.panes if pane.window_id in window_id_set
    }
    pane_ids = tuple(pane_id for pane_id in context.pane_ids if pane_id in pane_id_set)
    return session_id, window_ids, pane_ids


def _build_mutation_plans(
    context: RunContext,
    *,
    generation: str,
    session_id: str,
    window_ids: tuple[str, ...],
    pane_ids: tuple[str, ...],
) -> tuple[LazyPlan, LazyPlan, dict[str, str], dict[str, str]]:
    """Build the shared mutation graph and its untimed restoration graph.

    >>> context = types.SimpleNamespace(
    ...     run_id="run-7", window_bindings=(("canonical", "@1", "$0"),)
    ... )
    >>> mutation, restoration, names, titles = _build_mutation_plans(
    ...     context, generation="3", session_id="$0", window_ids=("@1",),
    ...     pane_ids=("%2",),
    ... )
    >>> len(mutation), len(restoration), names["@1"], titles["%2"]
    (3, 3, 'canonical-g3', 'bench-run-7-g3-p000')

    Parameters
    ----------
    context : RunContext
        Run whose canonical window bindings and identity are authoritative.
    generation : str
        Exact user-option value and mutation suffix.
    session_id : str
        Concrete target session.
    window_ids : tuple[str, ...]
        Concrete windows to rename.
    pane_ids : tuple[str, ...]
        Concrete panes to title.

    Returns
    -------
    tuple[LazyPlan, LazyPlan, dict[str, str], dict[str, str]]
        Mutation, restoration, expected mutated names, and expected titles.
    """
    from libtmux.experimental.ops import (
        LazyPlan,
        PaneId,
        RenameWindow,
        SelectPane,
        SessionId,
        SetOption,
        WindowId,
    )

    canonical_names = {
        window_id: name for name, window_id, _session_id in context.window_bindings
    }
    mutated_names = {
        window_id: f"{canonical_names[window_id]}-g{generation}"
        for window_id in window_ids
    }
    titles = {
        pane_id: f"bench-{context.run_id}-g{generation}-p{ordinal:03d}"
        for ordinal, pane_id in enumerate(pane_ids)
    }
    mutation = LazyPlan()
    mutation.add(
        SetOption(
            target=SessionId(session_id),
            option=_GENERATION_OPTION,
            value=generation,
        )
    )
    for window_id in window_ids:
        mutation.add(
            RenameWindow(
                target=WindowId(window_id),
                name=mutated_names[window_id],
            )
        )
    for pane_id in pane_ids:
        mutation.add(SelectPane(target=PaneId(pane_id), title=titles[pane_id]))

    restoration = LazyPlan()
    restoration.add(
        SetOption(
            target=SessionId(session_id),
            option=_GENERATION_OPTION,
            unset=True,
        )
    )
    for window_id in window_ids:
        restoration.add(
            RenameWindow(
                target=WindowId(window_id),
                name=canonical_names[window_id],
            )
        )
    for pane_id in pane_ids:
        restoration.add(SelectPane(target=PaneId(pane_id), title=""))
    return mutation, restoration, mutated_names, titles


def _verify_mutation_state(
    snapshot: TopologySnapshot,
    *,
    generation: str,
    options: cabc.Mapping[str, str],
    mutated_names: cabc.Mapping[str, str],
    titles: cabc.Mapping[str, str],
) -> None:
    """Require every generation, window-name, and pane-title mutation.

    >>> from libtmux.experimental.models import PaneSnapshot, WindowSnapshot
    >>> snapshot = TopologySnapshot(
    ...     (), (WindowSnapshot(window_id="@1", name="renamed"),),
    ...     (PaneSnapshot(pane_id="%1", title="t", fields={"pane_title": "t"}),),
    ... )
    >>> _verify_mutation_state(
    ...     snapshot, generation="4", options={_GENERATION_OPTION: "4"},
    ...     mutated_names={"@1": "renamed"}, titles={"%1": "t"},
    ... )

    Parameters
    ----------
    snapshot : TopologySnapshot
        Typed live state read after the timed plan.
    generation : str
        Exact expected generation option value.
    options : collections.abc.Mapping[str, str]
        Typed ``ShowOptions`` mapping for the selected session.
    mutated_names : collections.abc.Mapping[str, str]
        Expected window names keyed by concrete ID.
    titles : collections.abc.Mapping[str, str]
        Expected pane titles keyed by concrete ID.

    Raises
    ------
    RuntimeError
        If any mutation is absent or partial.
    """
    if options.get(_GENERATION_OPTION) != generation:
        message = "generation option did not match the mutation"
        raise RuntimeError(message)
    observed_names = {window.window_id: window.name for window in snapshot.windows}
    if any(observed_names.get(key) != value for key, value in mutated_names.items()):
        message = "window rename verification failed"
        raise RuntimeError(message)
    observed_titles = {
        pane.pane_id: pane.fields.get("pane_title", pane.title)
        for pane in snapshot.panes
    }
    if any(observed_titles.get(key) != value for key, value in titles.items()):
        message = "pane title verification failed"
        raise RuntimeError(message)


def _verify_restored_state(
    context: RunContext,
    snapshot: TopologySnapshot,
    *,
    options: cabc.Mapping[str, str],
    window_ids: tuple[str, ...],
    pane_ids: tuple[str, ...],
) -> None:
    """Require canonical names, cleared titles, and an absent generation option.

    >>> from libtmux.experimental.models import PaneSnapshot, WindowSnapshot
    >>> context = types.SimpleNamespace(
    ...     window_bindings=(("canonical", "@1", "$0"),)
    ... )
    >>> snapshot = TopologySnapshot(
    ...     (), (WindowSnapshot(window_id="@1", name="canonical"),),
    ...     (PaneSnapshot(pane_id="%1", fields={"pane_title": ""}),),
    ... )
    >>> _verify_restored_state(
    ...     context, snapshot, options={}, window_ids=("@1",),
    ...     pane_ids=("%1",),
    ... )

    Parameters
    ----------
    context : RunContext
        Run containing canonical window bindings.
    snapshot : TopologySnapshot
        Typed live state after the restoration plan.
    options : collections.abc.Mapping[str, str]
        Typed options after unsetting the generation marker.
    window_ids : tuple[str, ...]
        Windows that must have canonical names.
    pane_ids : tuple[str, ...]
        Panes whose explicit titles must be absent or empty.

    Raises
    ------
    RuntimeError
        If restoration is absent or partial.
    """
    if _GENERATION_OPTION in options:
        message = "generation option remained after restoration"
        raise RuntimeError(message)
    canonical_names = {
        window_id: name for name, window_id, _session_id in context.window_bindings
    }
    observed_names = {window.window_id: window.name for window in snapshot.windows}
    if any(
        observed_names.get(window_id) != canonical_names[window_id]
        for window_id in window_ids
    ):
        message = "canonical window restoration failed"
        raise RuntimeError(message)
    observed_titles = {
        pane.pane_id: pane.fields.get("pane_title", pane.title)
        for pane in snapshot.panes
    }
    title_mismatches = {
        pane_id: observed_titles.get(pane_id)
        for pane_id in pane_ids
        if observed_titles.get(pane_id) not in {None, ""}
    }
    if title_mismatches:
        message = f"pane title restoration failed: {title_mismatches!r}"
        raise RuntimeError(message)


def mutate_sync(context: RunContext, *, generation: int | str) -> MutationResult:
    """Mutate one largest session through a batched plan, verify, and restore.

    >>> try:
    ...     mutate_sync(types.SimpleNamespace(mode=ExecutionMode.ASYNC), generation=1)
    ... except ValueError as error:
    ...     print(error)
    sync phase requires a sync run context

    Parameters
    ----------
    context : RunContext
        Verified active synchronous topology.
    generation : int | str
        Exact nonempty marker value for this mutation iteration.

    Returns
    -------
    MutationResult
        Timed plan duration plus verified restoration and activity evidence.

    Raises
    ------
    ValueError
        If context mode or generation is invalid.
    RuntimeError
        If mutation, restoration, or live activity verification fails.
    """
    from libtmux.experimental.ops import BatchingPlanner, SessionId, ShowOptions, run

    _require_active_phase_context(context, ExecutionMode.SYNC)
    generation_text = str(generation)
    if not generation_text:
        message = "mutation generation must be nonempty"
        raise ValueError(message)
    engine = t.cast("TmuxEngine", context.engine)
    initial = snapshot_topology_sync(context)
    session_id, window_ids, pane_ids = _mutation_targets(context, initial)
    mutation, restoration, mutated_names, titles = _build_mutation_plans(
        context,
        generation=generation_text,
        session_id=session_id,
        window_ids=window_ids,
        pane_ids=pane_ids,
    )
    planner = BatchingPlanner()
    verified = False
    restored = False
    restoration_verified_monotonic_ns = 0
    duration_ns = 0
    try:
        started_ns = time.perf_counter_ns()
        mutation_result = mutation.execute(engine, planner=planner)
        duration_ns = time.perf_counter_ns() - started_ns
        mutation_result.raise_for_status()
        mutated_snapshot = snapshot_topology_sync(context)
        option_result = run(
            ShowOptions(target=SessionId(session_id)), engine
        ).raise_for_status()
        _verify_mutation_state(
            mutated_snapshot,
            generation=generation_text,
            options=option_result.options,
            mutated_names=mutated_names,
            titles=titles,
        )
        verified = True
    finally:
        restoration.execute(engine, planner=planner).raise_for_status()
        restored_snapshot = snapshot_topology_sync(context)
        restored_options = run(
            ShowOptions(target=SessionId(session_id)), engine
        ).raise_for_status()
        _verify_restored_state(
            context,
            restored_snapshot,
            options=restored_options.options,
            window_ids=window_ids,
            pane_ids=pane_ids,
        )
        restored = True
        restoration_verified_monotonic_ns = time.monotonic_ns()
    activity_baseline = _current_activity_heartbeat(context, max_age_s=2.0)
    activity_after = _wait_activity_advance_sync(context, activity_baseline)
    steps = len(mutation.explain(planner))
    return MutationResult(
        duration_ns=duration_ns,
        metrics=_phase_metrics(context, operations=len(mutation), planner_steps=steps),
        session_id=session_id,
        window_ids=window_ids,
        pane_ids=pane_ids,
        generation=generation_text,
        verified=verified,
        restored=restored,
        restoration_verified_monotonic_ns=restoration_verified_monotonic_ns,
        activity_baseline=activity_baseline,
        activity_after=activity_after,
    )


async def _restore_mutation_async(
    context: RunContext,
    restoration: LazyPlan,
    planner: Planner,
    *,
    session_id: str,
    window_ids: tuple[str, ...],
    pane_ids: tuple[str, ...],
) -> int:
    """Execute and verify async restoration within one owned task.

    >>> async def invalid_restoration():
    ...     try:
    ...         await _restore_mutation_async(
    ...             types.SimpleNamespace(mode=ExecutionMode.SYNC),
    ...             t.cast("LazyPlan", None), t.cast("Planner", None),
    ...             session_id="$0", window_ids=(), pane_ids=(),
    ...         )
    ...     except ValueError as error:
    ...         return str(error)
    >>> asyncio.run(invalid_restoration())
    'async restoration requires an async run context'

    Parameters
    ----------
    context : RunContext
        Async live run containing canonical topology bindings.
    restoration : LazyPlan
        Fully constructed canonical-name, option, and title restoration graph.
    planner : Planner
        Planner used by the corresponding mutation graph.
    session_id : str
        Concrete session whose generation option must be absent afterward.
    window_ids : tuple[str, ...]
        Mutated windows that must regain canonical names.
    pane_ids : tuple[str, ...]
        Mutated panes whose explicit titles must be cleared.

    Returns
    -------
    int
        Local monotonic timestamp taken after restored-state verification.

    Raises
    ------
    ValueError
        If the context is not asynchronous.
    RuntimeError
        If restoration execution or typed live verification fails.
    """
    from libtmux.experimental.ops import SessionId, ShowOptions, arun

    if context.mode is not ExecutionMode.ASYNC:
        message = "async restoration requires an async run context"
        raise ValueError(message)
    engine = t.cast("AsyncTmuxEngine", context.engine)
    (await restoration.aexecute(engine, planner=planner)).raise_for_status()
    restored_snapshot = await snapshot_topology_async(context)
    restored_options = (
        await arun(ShowOptions(target=SessionId(session_id)), engine)
    ).raise_for_status()
    _verify_restored_state(
        context,
        restored_snapshot,
        options=restored_options.options,
        window_ids=window_ids,
        pane_ids=pane_ids,
    )
    return time.monotonic_ns()


async def mutate_async(
    context: RunContext,
    *,
    generation: int | str,
) -> MutationResult:
    """Async sibling of :func:`mutate_sync` over the identical operation graph.

    >>> async def invalid_mutation():
    ...     try:
    ...         await mutate_async(
    ...             types.SimpleNamespace(mode=ExecutionMode.SYNC), generation=1
    ...         )
    ...     except ValueError as error:
    ...         return str(error)
    >>> asyncio.run(invalid_mutation())
    'async phase requires a async run context'

    Parameters
    ----------
    context : RunContext
        Verified active asynchronous topology.
    generation : int | str
        Exact nonempty marker value for this mutation iteration.

    Returns
    -------
    MutationResult
        Timed plan duration plus verified restoration and activity evidence.

    Raises
    ------
    ValueError
        If context mode or generation is invalid.
    RuntimeError
        If mutation, restoration, or live activity verification fails.
    """
    from libtmux.experimental.ops import BatchingPlanner, SessionId, ShowOptions, arun

    _require_active_phase_context(context, ExecutionMode.ASYNC)
    generation_text = str(generation)
    if not generation_text:
        message = "mutation generation must be nonempty"
        raise ValueError(message)
    engine = t.cast("AsyncTmuxEngine", context.engine)
    initial = await snapshot_topology_async(context)
    session_id, window_ids, pane_ids = _mutation_targets(context, initial)
    mutation, restoration, mutated_names, titles = _build_mutation_plans(
        context,
        generation=generation_text,
        session_id=session_id,
        window_ids=window_ids,
        pane_ids=pane_ids,
    )
    planner = BatchingPlanner()
    verified = False
    restored = False
    duration_ns = 0
    primary_error: BaseException | None = None
    try:
        started_ns = time.perf_counter_ns()
        mutation_result = await mutation.aexecute(engine, planner=planner)
        duration_ns = time.perf_counter_ns() - started_ns
        mutation_result.raise_for_status()
        mutated_snapshot = await snapshot_topology_async(context)
        option_result = (
            await arun(ShowOptions(target=SessionId(session_id)), engine)
        ).raise_for_status()
        _verify_mutation_state(
            mutated_snapshot,
            generation=generation_text,
            options=option_result.options,
            mutated_names=mutated_names,
            titles=titles,
        )
        verified = True
    except BaseException as error:  # noqa: BLE001
        primary_error = error

    restoration_task = asyncio.create_task(
        _restore_mutation_async(
            context,
            restoration,
            planner,
            session_id=session_id,
            window_ids=window_ids,
            pane_ids=pane_ids,
        ),
        name="libtmux-mutation-restoration",
    )
    while not restoration_task.done():
        try:
            await asyncio.shield(restoration_task)
        except asyncio.CancelledError as cancellation:  # noqa: PERF203
            if not restoration_task.cancelled() and primary_error is None:
                primary_error = cancellation
        except BaseException:  # noqa: BLE001
            break
    restoration_error: BaseException | None = None
    restoration_verified_monotonic_ns = 0
    try:
        restoration_verified_monotonic_ns = restoration_task.result()
    except BaseException as error:  # noqa: BLE001
        restoration_error = error
    if restoration_error is not None:
        if primary_error is not None:
            raise primary_error from restoration_error
        raise restoration_error
    restored = True
    if primary_error is not None:
        raise primary_error
    activity_baseline = _current_activity_heartbeat(context, max_age_s=2.0)
    activity_after = await _wait_activity_advance_async(context, activity_baseline)
    steps = len(mutation.explain(planner))
    return MutationResult(
        duration_ns=duration_ns,
        metrics=_phase_metrics(context, operations=len(mutation), planner_steps=steps),
        session_id=session_id,
        window_ids=window_ids,
        pane_ids=pane_ids,
        generation=generation_text,
        verified=verified,
        restored=restored,
        restoration_verified_monotonic_ns=restoration_verified_monotonic_ns,
        activity_baseline=activity_baseline,
        activity_after=activity_after,
    )


def _id_checksum(ids: tuple[str, ...]) -> str:
    """Return SHA-256 over an unambiguous ordered concrete-ID encoding.

    >>> len(_id_checksum(("$0", "$1")))
    64

    Parameters
    ----------
    ids : tuple[str, ...]
        Stable concrete IDs in accepted hierarchy order.

    Returns
    -------
    str
        Lower-case hexadecimal SHA-256 digest over NUL-separated IDs.
    """
    return hashlib.sha256("\0".join(ids).encode()).hexdigest()


def _enumeration_expected(
    context: RunContext,
    kind: EnumerationKind,
) -> tuple[str, ...]:
    """Return the verified ID tuple for one hierarchy level.

    >>> context = types.SimpleNamespace(
    ...     session_ids=("$0",), window_ids=("@0",), pane_ids=("%0",)
    ... )
    >>> _enumeration_expected(context, "windows")
    ('@0',)

    Parameters
    ----------
    context : RunContext
        Verified topology context.
    kind : {"sessions", "windows", "panes"}
        Hierarchy level requested.

    Returns
    -------
    tuple[str, ...]
        Stable concrete IDs captured during topology verification.

    Raises
    ------
    ValueError
        If ``kind`` is outside the closed hierarchy vocabulary.
    """
    if kind == "sessions":
        return context.session_ids
    if kind == "windows":
        return context.window_ids
    if kind == "panes":
        return context.pane_ids
    message = f"unknown enumeration kind: {kind}"
    raise ValueError(message)


def _enumeration_operation(kind: EnumerationKind) -> object:
    """Build the one typed list operation for a hierarchy level.

    >>> _enumeration_operation("panes").kind
    'list_panes'

    Parameters
    ----------
    kind : {"sessions", "windows", "panes"}
        Hierarchy level requested.

    Returns
    -------
    object
        ``ListSessions``, ``ListWindows``, or ``ListPanes`` operation.
    """
    from libtmux.experimental.ops import ListPanes, ListSessions, ListWindows

    if kind == "sessions":
        return ListSessions()
    if kind == "windows":
        return ListWindows(all_windows=True)
    return ListPanes(all_panes=True)


def _enumeration_ids(result: t.Any, kind: EnumerationKind) -> tuple[str, ...]:
    """Extract concrete IDs from a successful typed list result.

    >>> from libtmux.experimental.ops import ListSessions
    >>> result = ListSessions().build_result(returncode=0, stdout=())
    >>> _enumeration_ids(result, "sessions")
    ()

    Parameters
    ----------
    result : object
        Successful specialized typed operation result.
    kind : {"sessions", "windows", "panes"}
        Hierarchy level represented by ``result``.

    Returns
    -------
    tuple[str, ...]
        Concrete IDs in the result's stable row order.
    """
    if kind == "sessions":
        return tuple(row.session_id for row in result.sessions)
    if kind == "windows":
        return tuple(row.window_id for row in result.windows)
    return tuple(row.pane_id for row in result.panes)


def _accepted_enumeration(
    context: RunContext,
    kind: EnumerationKind,
    ids: tuple[str, ...],
    duration_ns: int,
) -> EnumerationResult:
    """Validate exact row identity before constructing an enumeration sample.

    >>> context = types.SimpleNamespace(
    ...     lane=EngineLane.CONTROL, session_ids=("$0",),
    ...     window_ids=(), pane_ids=(),
    ... )
    >>> _accepted_enumeration(context, "sessions", ("$0",), 4).verified
    True

    Parameters
    ----------
    context : RunContext
        Verified concrete ID authority.
    kind : {"sessions", "windows", "panes"}
        Enumerated hierarchy level.
    ids : tuple[str, ...]
        IDs returned by the typed list operation.
    duration_ns : int
        Measured typed execution duration.

    Returns
    -------
    EnumerationResult
        Accepted exact rows and stable checksum.

    Raises
    ------
    RuntimeError
        If row count, stable order, or checksum differs from verified topology.
    """
    expected = _enumeration_expected(context, kind)
    observed_checksum = _id_checksum(ids)
    expected_checksum = _id_checksum(expected)
    if len(ids) != len(expected):
        message = f"{kind} enumeration row count mismatch"
        raise RuntimeError(message)
    if ids != expected or observed_checksum != expected_checksum:
        message = f"{kind} enumeration stable ID checksum mismatch"
        raise RuntimeError(message)
    return EnumerationResult(
        duration_ns=duration_ns,
        metrics=_phase_metrics(context, operations=1, planner_steps=1),
        kind=kind,
        row_count=len(ids),
        ids=ids,
        id_checksum=observed_checksum,
        verified=True,
    )


def enumerate_sync(
    context: RunContext,
    *,
    kind: EnumerationKind,
) -> EnumerationResult:
    """Execute and validate one synchronous typed hierarchy list operation.

    >>> try:
    ...     enumerate_sync(
    ...         types.SimpleNamespace(mode=ExecutionMode.ASYNC), kind="panes"
    ...     )
    ... except ValueError as error:
    ...     print(error)
    sync phase requires a sync run context

    Parameters
    ----------
    context : RunContext
        Verified active synchronous topology.
    kind : {"sessions", "windows", "panes"}
        One hierarchy cell to enumerate.

    Returns
    -------
    EnumerationResult
        Exact row count, concrete IDs, checksum, and timing.
    """
    from libtmux.experimental.ops import run

    _require_active_phase_context(context, ExecutionMode.SYNC)
    _enumeration_expected(context, kind)
    engine = t.cast("TmuxEngine", context.engine)
    operation = t.cast("Operation[t.Any]", _enumeration_operation(kind))
    started_ns = time.perf_counter_ns()
    result = run(operation, engine)
    duration_ns = time.perf_counter_ns() - started_ns
    result.raise_for_status()
    return _accepted_enumeration(
        context,
        kind,
        _enumeration_ids(result, kind),
        duration_ns,
    )


async def enumerate_async(
    context: RunContext,
    *,
    kind: EnumerationKind,
) -> EnumerationResult:
    """Execute and validate one asynchronous typed hierarchy list operation.

    >>> async def invalid_enumeration():
    ...     try:
    ...         await enumerate_async(
    ...             types.SimpleNamespace(mode=ExecutionMode.SYNC), kind="panes"
    ...         )
    ...     except ValueError as error:
    ...         return str(error)
    >>> asyncio.run(invalid_enumeration())
    'async phase requires a async run context'

    Parameters
    ----------
    context : RunContext
        Verified active asynchronous topology.
    kind : {"sessions", "windows", "panes"}
        One hierarchy cell to enumerate.

    Returns
    -------
    EnumerationResult
        Exact row count, concrete IDs, checksum, and timing.
    """
    from libtmux.experimental.ops import arun

    _require_active_phase_context(context, ExecutionMode.ASYNC)
    _enumeration_expected(context, kind)
    engine = t.cast("AsyncTmuxEngine", context.engine)
    operation = t.cast("Operation[t.Any]", _enumeration_operation(kind))
    started_ns = time.perf_counter_ns()
    result = await arun(operation, engine)
    duration_ns = time.perf_counter_ns() - started_ns
    result.raise_for_status()
    return _accepted_enumeration(
        context,
        kind,
        _enumeration_ids(result, kind),
        duration_ns,
    )


def _capture_plan(context: RunContext) -> LazyPlan:
    """Build the transport-independent all-pane capture operation graph.

    >>> context = types.SimpleNamespace(pane_ids=("%1", "%2"))
    >>> [operation.target.value for operation in _capture_plan(context).operations]
    ['%1', '%2']

    Parameters
    ----------
    context : RunContext
        Verified stable pane ID authority.

    Returns
    -------
    LazyPlan
        One bounded ``CapturePane`` operation per concrete pane.
    """
    from libtmux.experimental.ops import CapturePane, LazyPlan, PaneId

    plan = LazyPlan()
    for pane_id in context.pane_ids:
        plan.add(CapturePane(target=PaneId(pane_id), start=-5000))
    return plan


def _capture_planner(strategy: CaptureStrategy) -> object:
    """Return the planner policy named by one capture strategy.

    >>> type(_capture_planner("serial")).__name__
    'SequentialPlanner'
    >>> type(_capture_planner("batched")).__name__
    'BatchingPlanner'

    Parameters
    ----------
    strategy : {"serial", "batched"}
        Planner policy name.

    Returns
    -------
    object
        ``SequentialPlanner`` or ``BatchingPlanner``.

    Raises
    ------
    ValueError
        If ``strategy`` is outside the closed vocabulary.
    """
    from libtmux.experimental.ops import BatchingPlanner, SequentialPlanner

    if strategy == "serial":
        return SequentialPlanner()
    if strategy == "batched":
        return BatchingPlanner()
    message = f"unknown capture strategy: {strategy}"
    raise ValueError(message)


def _activity_frame_epochs(lines: tuple[str, ...]) -> tuple[int, ...]:
    """Extract fuzzer frame epochs from retained pane lines.

    >>> _activity_frame_epochs(("[editor epoch=3] x", "other"))
    (3,)

    Parameters
    ----------
    lines : tuple[str, ...]
        Captured pane lines in display order.

    Returns
    -------
    tuple[int, ...]
        Nonnegative epochs from complete bracketed fuzzer frame prefixes.
    """
    epochs: list[int] = []
    for line in lines:
        prefix, separator, remainder = line.partition(" epoch=")
        epoch_text, closing, _tail = remainder.partition("]")
        if prefix.startswith("[") and separator and closing and epoch_text.isdigit():
            epochs.append(int(epoch_text))
    return tuple(epochs)


def _streams_reached_epoch(context: RunContext, epoch: int) -> bool:
    r"""Return whether every source stream has emitted ``epoch`` or newer.

    >>> with tempfile.TemporaryDirectory() as temporary:
    ...     stream = pathlib.Path(temporary) / "stream.log"
    ...     _ = stream.write_text("[editor epoch=3] x\n", encoding="utf-8")
    ...     _streams_reached_epoch(types.SimpleNamespace(streams=(stream,)), 3)
    True

    Parameters
    ----------
    context : RunContext
        Active run owning the source streams.
    epoch : int
        Exact observed heartbeat epoch required in every stream.

    Returns
    -------
    bool
        Whether every stream contains an epoch greater than or equal to target.
    """
    for stream in context.streams:
        try:
            lines = tuple(stream.read_text(encoding="utf-8").splitlines())
        except OSError:
            return False
        if max(_activity_frame_epochs(lines), default=-1) < epoch:
            return False
    return True


def _wait_stream_epoch_sync(
    context: RunContext,
    epoch: int,
    *,
    timeout_s: float = 2.0,
) -> None:
    """Wait outside capture timing until every source emitted ``epoch``.

    >>> try:
    ...     _wait_stream_epoch_sync(types.SimpleNamespace(), 1, timeout_s=0)
    ... except ValueError as error:
    ...     print(error)
    stream epoch timeout must be positive

    Parameters
    ----------
    context : RunContext
        Active run owning the source streams and fuzzer.
    epoch : int
        Exact observed heartbeat epoch required before capture.
    timeout_s : float
        Maximum monotonic wait outside the measured capture cell.

    Raises
    ------
    ValueError
        If ``timeout_s`` is not positive.
    RuntimeError
        If the fuzzer exits before source readiness.
    TimeoutError
        If a source stream does not reach the epoch in time.
    """
    if timeout_s <= 0:
        message = "stream epoch timeout must be positive"
        raise ValueError(message)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if context.fuzzer.poll() is not None:
            message = "fuzzer exited before current capture epoch"
            raise RuntimeError(message)
        if _streams_reached_epoch(context, epoch):
            return
        time.sleep(0.005)
    message = f"source streams did not reach capture epoch {epoch}"
    raise TimeoutError(message)


async def _wait_stream_epoch_async(
    context: RunContext,
    epoch: int,
    *,
    timeout_s: float = 2.0,
) -> None:
    """Asynchronously wait outside timing for the observed source epoch.

    >>> async def invalid_stream_wait():
    ...     try:
    ...         await _wait_stream_epoch_async(
    ...             types.SimpleNamespace(), 1, timeout_s=0
    ...         )
    ...     except ValueError as error:
    ...         return str(error)
    >>> asyncio.run(invalid_stream_wait())
    'stream epoch timeout must be positive'

    Parameters
    ----------
    context : RunContext
        Active run owning the source streams and fuzzer.
    epoch : int
        Exact observed heartbeat epoch required before capture.
    timeout_s : float
        Maximum event-loop wait outside the measured capture cell.

    Raises
    ------
    ValueError
        If ``timeout_s`` is not positive.
    RuntimeError
        If the fuzzer exits before source readiness.
    TimeoutError
        If a source stream does not reach the epoch in time.
    """
    if timeout_s <= 0:
        message = "stream epoch timeout must be positive"
        raise ValueError(message)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if context.fuzzer.poll() is not None:
            message = "fuzzer exited before current capture epoch"
            raise RuntimeError(message)
        if _streams_reached_epoch(context, epoch):
            return
        await asyncio.sleep(0.005)
    message = f"source streams did not reach capture epoch {epoch}"
    raise TimeoutError(message)


def _accepted_capture(
    context: RunContext,
    plan: LazyPlan,
    plan_result: t.Any,
    strategy: CaptureStrategy,
    duration_ns: int,
) -> CaptureResult:
    """Validate typed current-epoch captures before returning measurement data.

    >>> from libtmux.experimental.ops import CapturePane, LazyPlan, PaneId
    >>> plan = LazyPlan()
    >>> operation = CapturePane(target=PaneId("%1"))
    >>> _ = plan.add(operation)
    >>> raw = operation.build_result(
    ...     returncode=0, stdout=("epoch", "[editor epoch=2] current")
    ... )
    >>> context = types.SimpleNamespace(
    ...     pane_ids=("%1",), activity_marker="epoch", activity_epoch=2,
    ...     heartbeat_epoch=2, lane=EngineLane.CONTROL,
    ... )
    >>> _accepted_capture(
    ...     context, plan, types.SimpleNamespace(results=(raw,)), "serial", 4
    ... ).line_count
    2

    Parameters
    ----------
    context : RunContext
        Active run containing exact pane IDs and current activity marker.
    plan : LazyPlan
        Identical operation graph used for either planner.
    plan_result : object
        Successful ``PlanResult`` with specialized capture results.
    strategy : {"serial", "batched"}
        Planner strategy used for dispatch.
    duration_ns : int
        Measured graph execution duration.

    Returns
    -------
    CaptureResult
        Retained lines, totals, counts, and epoch verification.

    Raises
    ------
    RuntimeError
        If result attribution, cardinality, content, or current epoch is invalid.
    """
    from libtmux.experimental.ops import (
        BatchingPlanner,
        CapturePane,
        CapturePaneResult,
        PaneId,
    )

    captures: list[PaneCapture] = []
    results = tuple(plan_result.results)
    operations = tuple(plan.operations)
    if len(operations) != len(context.pane_ids) or len(results) != len(operations):
        message = "capture result count did not match stable pane IDs"
        raise RuntimeError(message)
    expected_targets = tuple(
        operation.target.value
        if isinstance(operation, CapturePane) and isinstance(operation.target, PaneId)
        else None
        for operation in operations
    )
    result_targets = tuple(
        result.operation.target.value
        if isinstance(result, CapturePaneResult)
        and isinstance(result.operation, CapturePane)
        and isinstance(result.operation.target, PaneId)
        else None
        for result in results
    )
    if expected_targets != context.pane_ids or result_targets != context.pane_ids:
        message = "capture result target order did not match stable pane IDs"
        raise RuntimeError(message)
    current_epoch = context.heartbeat_epoch
    if type(current_epoch) is not int or current_epoch < 0:
        message = "capture has no observed current heartbeat epoch"
        raise RuntimeError(message)
    for pane_id, result in zip(context.pane_ids, results, strict=True):
        if not isinstance(result, CapturePaneResult):
            message = f"capture for {pane_id} did not return typed lines"
            raise TypeError(message)
        result.raise_for_status()
        if not result.lines:
            message = f"capture for {pane_id} returned no lines"
            raise RuntimeError(message)
        marker = t.cast(str, context.activity_marker)
        if marker not in "\n".join(result.lines):
            message = f"capture for {pane_id} lacks its run-scoped activity marker"
            raise RuntimeError(message)
        if max(_activity_frame_epochs(result.lines), default=-1) < current_epoch:
            message = f"capture for {pane_id} lacks current activity epoch"
            raise RuntimeError(message)
        captures.append(PaneCapture(pane_id, result.lines))
    line_count = sum(len(capture.lines) for capture in captures)
    byte_count = sum(
        len(line.encode("utf-8")) for capture in captures for line in capture.lines
    )
    if line_count <= 0 or byte_count <= 0:
        message = "all-pane capture produced no typed content"
        raise RuntimeError(message)
    planner_steps = (
        len(plan.explain(BatchingPlanner())) if strategy == "batched" else len(plan)
    )
    return CaptureResult(
        duration_ns=duration_ns,
        metrics=_phase_metrics(
            context,
            operations=len(plan),
            planner_steps=planner_steps,
        ),
        strategy=strategy,
        operations=plan.operations,
        captures=tuple(captures),
        line_count=line_count,
        byte_count=byte_count,
        epoch=current_epoch,
        verified=True,
    )


def capture_all_sync(
    context: RunContext,
    *,
    strategy: CaptureStrategy,
) -> CaptureResult:
    """Capture every pane synchronously with serial or batched planning.

    >>> try:
    ...     capture_all_sync(
    ...         types.SimpleNamespace(mode=ExecutionMode.ASYNC), strategy="serial"
    ...     )
    ... except ValueError as error:
    ...     print(error)
    sync phase requires a sync run context

    Parameters
    ----------
    context : RunContext
        Verified active synchronous topology.
    strategy : {"serial", "batched"}
        Planner policy; operation graph remains identical.

    Returns
    -------
    CaptureResult
        Retained typed lines and exact work counts.
    """
    _require_active_phase_context(context, ExecutionMode.SYNC)
    plan = _capture_plan(context)
    planner = t.cast("Planner", _capture_planner(strategy))
    engine = t.cast("TmuxEngine", context.engine)
    heartbeat = _current_activity_heartbeat(context, max_age_s=2.0)
    _wait_stream_epoch_sync(context, heartbeat.epoch)
    started_ns = time.perf_counter_ns()
    result = plan.execute(engine, planner=planner)
    duration_ns = time.perf_counter_ns() - started_ns
    result.raise_for_status()
    return _accepted_capture(context, plan, result, strategy, duration_ns)


async def capture_all_async(
    context: RunContext,
    *,
    strategy: CaptureStrategy,
) -> CaptureResult:
    """Capture every pane asynchronously over the same operation graph.

    >>> async def invalid_capture():
    ...     try:
    ...         await capture_all_async(
    ...             types.SimpleNamespace(mode=ExecutionMode.SYNC), strategy="serial"
    ...         )
    ...     except ValueError as error:
    ...         return str(error)
    >>> asyncio.run(invalid_capture())
    'async phase requires a async run context'

    Parameters
    ----------
    context : RunContext
        Verified active asynchronous topology.
    strategy : {"serial", "batched"}
        Planner policy; operation graph remains identical.

    Returns
    -------
    CaptureResult
        Retained typed lines and exact work counts.
    """
    _require_active_phase_context(context, ExecutionMode.ASYNC)
    plan = _capture_plan(context)
    planner = t.cast("Planner", _capture_planner(strategy))
    engine = t.cast("AsyncTmuxEngine", context.engine)
    heartbeat = _current_activity_heartbeat(context, max_age_s=2.0)
    await _wait_stream_epoch_async(context, heartbeat.epoch)
    started_ns = time.perf_counter_ns()
    result = await plan.aexecute(engine, planner=planner)
    duration_ns = time.perf_counter_ns() - started_ns
    result.raise_for_status()
    return _accepted_capture(context, plan, result, strategy, duration_ns)


def _search_ids(context: RunContext, kind: EnumerationKind) -> tuple[str, ...]:
    """Return stable concrete IDs for one metadata search kind.

    >>> context = types.SimpleNamespace(
    ...     session_ids=("$0",), window_ids=("@0",), pane_ids=("%0",)
    ... )
    >>> _search_ids(context, "panes")
    ('%0',)

    Parameters
    ----------
    context : RunContext
        Verified topology ID authority.
    kind : {"sessions", "windows", "panes"}
        Search object kind.

    Returns
    -------
    tuple[str, ...]
        Stable candidate IDs.
    """
    return _enumeration_expected(context, kind)


def _row_id(row: object, kind: EnumerationKind) -> str:
    """Read the concrete ID attribute shared by snapshot and classic rows.

    >>> _row_id(types.SimpleNamespace(window_id="@2"), "windows")
    '@2'

    Parameters
    ----------
    row : object
        Typed snapshot or classic ORM object.
    kind : {"sessions", "windows", "panes"}
        Object kind controlling the concrete ID attribute.

    Returns
    -------
    str
        Concrete object ID.
    """
    attribute = {
        "sessions": "session_id",
        "windows": "window_id",
        "panes": "pane_id",
    }[kind]
    value = getattr(row, attribute)
    if not isinstance(value, str):
        message = f"{kind} row has no concrete ID"
        raise TypeError(message)
    return value


def _search_result(
    *,
    family: SearchFamily,
    kind: EnumerationKind,
    scanned_count: int,
    target: str,
    matches: cabc.Iterable[object],
    duration_ns: int,
    token: str | None = None,
) -> SearchResult:
    """Accept only one exact metadata or content search match.

    >>> _search_result(
    ...     family="snapshot", kind="sessions", scanned_count=2, target="$1",
    ...     matches=(types.SimpleNamespace(session_id="$1"),), duration_ns=3,
    ... ).matched_ids
    ('$1',)

    Parameters
    ----------
    family : {"classic", "snapshot", "end-to-end", "contents"}
        Explicit search timing boundary.
    kind : {"sessions", "windows", "panes"}
        Result object kind.
    scanned_count : int
        Candidate cardinality scanned.
    target : str
        Exact concrete ID required.
    matches : collections.abc.Iterable[object]
        Snapshot or classic rows returned by the search.
    duration_ns : int
        Search-only duration.
    token : str | None
        Exact content token for retained capture search.

    Returns
    -------
    SearchResult
        Verified exact match and scan cardinality.

    Raises
    ------
    RuntimeError
        If the search did not return exactly the requested ID.
    """
    matched_ids = tuple(_row_id(row, kind) for row in matches)
    if matched_ids != (target,):
        message = f"{family} {kind} search expected {(target,)!r}, got {matched_ids!r}"
        raise RuntimeError(message)
    return SearchResult(
        duration_ns=duration_ns,
        family=family,
        kind=kind,
        scanned_count=scanned_count,
        target=target,
        matched_ids=matched_ids,
        token=token,
        verified=True,
    )


def search_server_side(
    context: RunContext,
    *,
    kind: EnumerationKind,
    target: str,
) -> SearchResult:
    """Use classic tmux ``-f`` filtering for one exact concrete metadata ID.

    >>> try:
    ...     search_server_side(
    ...         types.SimpleNamespace(session_ids=("$0",), window_ids=(), pane_ids=()),
    ...         kind="sessions", target="$9",
    ...     )
    ... except ValueError as error:
    ...     print(error)
    target '$9' is not a verified sessions ID

    Parameters
    ----------
    context : RunContext
        Verified isolated server and stable IDs.
    kind : {"sessions", "windows", "panes"}
        Classic server-side search level.
    target : str
        Exact concrete ID included in the tmux format filter.

    Returns
    -------
    SearchResult
        One exact match, full candidate cardinality, and search duration.
    """
    candidates = _search_ids(context, kind)
    if target not in candidates:
        message = f"target {target!r} is not a verified {kind} ID"
        raise ValueError(message)
    format_name = {
        "sessions": "session_id",
        "windows": "window_id",
        "panes": "pane_id",
    }[kind]
    filter_expression = f"#{{==:#{{{format_name}}},{target}}}"
    search = {
        "sessions": context.server.search_sessions,
        "windows": context.server.search_windows,
        "panes": context.server.search_panes,
    }[kind]
    started_ns = time.perf_counter_ns()
    matches = t.cast(cabc.Iterable[object], search(filter=filter_expression))
    duration_ns = time.perf_counter_ns() - started_ns
    return _search_result(
        family="classic",
        kind=kind,
        scanned_count=len(candidates),
        target=target,
        matches=matches,
        duration_ns=duration_ns,
    )


def search_snapshot(
    rows: object,
    *,
    kind: EnumerationKind,
    target: str,
) -> SearchResult:
    """Time only ``QueryList.filter`` over caller-prematerialized snapshot rows.

    >>> from libtmux._internal.query_list import QueryList
    >>> from libtmux.experimental.models import SessionSnapshot
    >>> rows = QueryList([SessionSnapshot(session_id="$0")])
    >>> search_snapshot(rows, kind="sessions", target="$0").scanned_count
    1

    Parameters
    ----------
    rows : object
        Prematerialized :class:`~libtmux._internal.query_list.QueryList`.
    kind : {"sessions", "windows", "panes"}
        Snapshot object kind.
    target : str
        Exact concrete ID required.

    Returns
    -------
    SearchResult
        In-memory filter timing and exact scan cardinality.

    Raises
    ------
    TypeError
        If ``rows`` is not already a ``QueryList``.
    """
    from libtmux._internal.query_list import QueryList

    if not isinstance(rows, QueryList):
        message = "snapshot search requires a prematerialized QueryList"
        raise TypeError(message)
    field = {
        "sessions": "session_id",
        "windows": "window_id",
        "panes": "pane_id",
    }[kind]
    started_ns = time.perf_counter_ns()
    matches = rows.filter(**{field: target})
    duration_ns = time.perf_counter_ns() - started_ns
    return _search_result(
        family="snapshot",
        kind=kind,
        scanned_count=len(rows),
        target=target,
        matches=matches,
        duration_ns=duration_ns,
    )


def search_end_to_end(
    context: RunContext,
    *,
    kind: EnumerationKind,
    target: str,
) -> SearchResult:
    """Time classic list materialization plus Python ``QueryList`` filtering.

    >>> context = types.SimpleNamespace(session_ids=("$0",), window_ids=(), pane_ids=())
    >>> try:
    ...     search_end_to_end(context, kind="sessions", target="$9")
    ... except ValueError as error:
    ...     print(error)
    target '$9' is not a verified sessions ID

    Parameters
    ----------
    context : RunContext
        Verified isolated classic server and stable IDs.
    kind : {"sessions", "windows", "panes"}
        Object kind to list and filter.
    target : str
        Exact concrete ID required.

    Returns
    -------
    SearchResult
        End-to-end materialization and Python-filter timing.
    """
    candidates = _search_ids(context, kind)
    if target not in candidates:
        message = f"target {target!r} is not a verified {kind} ID"
        raise ValueError(message)
    field = {
        "sessions": "session_id",
        "windows": "window_id",
        "panes": "pane_id",
    }[kind]
    started_ns = time.perf_counter_ns()
    rows = getattr(context.server, kind)
    matches = rows.filter(**{field: target})
    duration_ns = time.perf_counter_ns() - started_ns
    return _search_result(
        family="end-to-end",
        kind=kind,
        scanned_count=len(rows),
        target=target,
        matches=matches,
        duration_ns=duration_ns,
    )


def search_contents(
    captures: CaptureResult,
    *,
    token: str,
    expected_pane_id: str | None,
) -> SearchResult:
    """Search retained typed capture lines for one exact sentinel token.

    >>> captures = CaptureResult(
    ...     1, ExecutionMetrics(1, 1, 1, 1, 0), "serial", (),
    ...     (PaneCapture("%1", ("token",)), PaneCapture("%2", ("other",))),
    ...     2, 10, 1, True,
    ... )
    >>> search_contents(
    ...     captures, token="token", expected_pane_id="%1"
    ... ).matched_ids
    ('%1',)

    Parameters
    ----------
    captures : CaptureResult
        Prematerialized typed pane lines; no tmux I/O occurs here.
    token : str
        Exact sentinel line to match.
    expected_pane_id : str | None
        Concrete delayed-pane ID required as the sole match.

    Returns
    -------
    SearchResult
        Retained-content scan timing and exact token/ID evidence.

    Raises
    ------
    ValueError
        If token or expected pane ID is absent.
    RuntimeError
        If zero or multiple captures contain the exact sentinel line.
    """
    if not token:
        message = "content search token must be nonempty"
        raise ValueError(message)
    if expected_pane_id is None:
        message = "content search requires a concrete expected pane ID"
        raise ValueError(message)
    started_ns = time.perf_counter_ns()
    matches = tuple(capture for capture in captures.captures if token in capture.lines)
    duration_ns = time.perf_counter_ns() - started_ns
    return _search_result(
        family="contents",
        kind="panes",
        scanned_count=len(captures.captures),
        target=expected_pane_id,
        matches=matches,
        duration_ns=duration_ns,
        token=token,
    )


PhaseMeasurement: t.TypeAlias = (
    MutationResult | EnumerationResult | CaptureResult | SearchResult | WaitResult
)


def _validated_phase_measurement(value: object) -> PhaseMeasurement:
    """Require a typed successful measurement with positive integer timing.

    >>> result = SearchResult(
    ...     3, "snapshot", "sessions", 1, "$0", ("$0",), verified=True
    ... )
    >>> _validated_phase_measurement(result) is result
    True

    Parameters
    ----------
    value : object
        Strategy callable result.

    Returns
    -------
    MutationResult | EnumerationResult | CaptureResult | SearchResult | WaitResult
        Valid typed measurement.

    Raises
    ------
    TypeError
        If the callable returned another type or non-integer duration.
    RuntimeError
        If typed verification was false or duration was nonpositive.
    """
    accepted_types = (
        MutationResult,
        EnumerationResult,
        CaptureResult,
        SearchResult,
        WaitResult,
    )
    if not isinstance(value, accepted_types):
        message = "phase callable did not return a typed measurement"
        raise TypeError(message)
    if type(value.duration_ns) is not int:
        message = "phase duration must be integer nanoseconds"
        raise TypeError(message)
    if value.duration_ns <= 0:
        message = "phase duration must be positive"
        raise RuntimeError(message)
    if not value.verified:
        message = "phase typed result was not verified"
        raise RuntimeError(message)
    return value


async def _await_if_needed(value: object) -> object:
    """Await an awaitable strategy value and pass synchronous values through.

    >>> asyncio.run(_await_if_needed(4))
    4
    >>> asyncio.run(_await_if_needed(asyncio.sleep(0, result=5)))
    5

    Parameters
    ----------
    value : object
        Immediate value or awaitable.

    Returns
    -------
    object
        Resolved value.
    """
    if inspect.isawaitable(value):
        return await value
    return value


def _require_live_postcondition(value: object) -> None:
    """Require an exact true live postcondition result.

    >>> _require_live_postcondition(True)
    >>> try:
    ...     _require_live_postcondition(False)
    ... except RuntimeError as error:
    ...     print(error)
    live postcondition rejected the phase result

    Parameters
    ----------
    value : object
        Resolved live-postcondition return value.

    Raises
    ------
    RuntimeError
        If the postcondition did not return exactly ``True``.
    """
    if value is not True:
        message = "live postcondition rejected the phase result"
        raise RuntimeError(message)


async def run_repeatable_phase(
    strategies: cabc.Mapping[str, cabc.Callable[[], object]],
    *,
    warmup: int,
    runs: int,
    seed: int,
    live_postcondition: cabc.Callable[[PhaseMeasurement], object],
    snapshot_resources: cabc.Callable[[], HostSnapshot] | None = None,
) -> RepeatablePhaseResult:
    """Deterministically interleave strategies and retain accepted timed rows.

    The seed shuffles one base strategy order. Each subsequent warmup or timed
    ordinal rotates that base order by one, giving a deterministic round robin.
    Resource observations bracket every invocation. A typed result and its live
    postcondition must pass before a timed :class:`RawSample` is appended.

    >>> async def example():
    ...     def measured():
    ...         return SearchResult(
    ...             3, "snapshot", "sessions", 1, "$0", ("$0",), verified=True
    ...         )
    ...     return await run_repeatable_phase(
    ...         {"one": measured}, warmup=0, runs=1, seed=2,
    ...         live_postcondition=lambda measurement: measurement.verified,
    ...         snapshot_resources=lambda: HostSnapshot(),
    ...     )
    >>> len(asyncio.run(example()).samples)
    1

    Parameters
    ----------
    strategies : collections.abc.Mapping[str, collections.abc.Callable]
        Nonempty named sync or async phase callables.
    warmup : int
        Untimed invocation count per strategy.
    runs : int
        Timed accepted invocation count requested per strategy.
    seed : int
        Deterministic base-order shuffle seed.
    live_postcondition : collections.abc.Callable
        Required independent sync or async live check run after typed validation.
    snapshot_resources : collections.abc.Callable[[], HostSnapshot] | None
        Injectable resource sampler; defaults to the live process/cgroup probe.

    Returns
    -------
    RepeatablePhaseResult
        Accepted rows, invocation order, and first failure metadata if any.

    Raises
    ------
    ValueError
        If strategies are empty, names are invalid, or counts are invalid.
    """
    if not strategies or any(not name for name in strategies):
        message = "repeatable phase requires nonempty named strategies"
        raise ValueError(message)
    if warmup < 0 or runs <= 0:
        message = "warmup must be nonnegative and runs must be positive"
        raise ValueError(message)
    sampler = snapshot_resources or (lambda: probe_host(ProcessReader()))
    base_order = list(strategies)
    random.Random(seed).shuffle(base_order)
    samples: list[RawSample] = []
    order: list[str] = []
    total_cycles = warmup + runs
    for cycle in range(total_cycles):
        stage: t.Literal["warmup", "timed"] = "warmup" if cycle < warmup else "timed"
        ordinal = cycle if stage == "warmup" else cycle - warmup
        rotation = cycle % len(base_order)
        cycle_order = (*base_order[rotation:], *base_order[:rotation])
        for strategy in cycle_order:
            order.append(strategy)
            try:
                resources_before = sampler()
                produced = strategies[strategy]()
                measurement = _validated_phase_measurement(
                    await _await_if_needed(produced)
                )
                postcondition = await _await_if_needed(live_postcondition(measurement))
                _require_live_postcondition(postcondition)
                resources_after = sampler()
                if stage == "timed":
                    samples.append(
                        RawSample(
                            duration_ns=measurement.duration_ns,
                            accepted=True,
                            verified=True,
                            strategy=strategy,
                            ordinal=ordinal,
                            resources_before=resources_before,
                            resources_after=resources_after,
                        )
                    )
            except Exception as error:  # noqa: BLE001
                return RepeatablePhaseResult(
                    samples=tuple(samples),
                    order=tuple(order),
                    failure=RepeatablePhaseFailure(
                        stage=stage,
                        strategy=strategy,
                        ordinal=ordinal,
                        error=f"{type(error).__name__}: {error}",
                    ),
                )
    return RepeatablePhaseResult(tuple(samples), tuple(order))


async def _wait_for_process_absence(
    identities: tuple[ProcessIdentity, ...],
    *,
    timeout_s: float,
    poll_child: cabc.Callable[[], object] | None = None,
) -> tuple[ProcessIdentity, ...]:
    """Wait for recorded identities to disappear without broad process scans.

    >>> asyncio.run(_wait_for_process_absence((), timeout_s=0.01))
    ()

    Parameters
    ----------
    identities : tuple[ProcessIdentity, ...]
        Exact PID and procfs start-time pairs owned by one run.
    timeout_s : float
        Maximum monotonic wait before returning survivors.
    poll_child : collections.abc.Callable[[], object] | None
        Optional child poll used to reap the directly owned fuzzer process.

    Returns
    -------
    tuple[ProcessIdentity, ...]
        Identity-matched processes still alive at the deadline.
    """
    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        if poll_child is not None:
            poll_child()
        remaining = tuple(
            identity for identity in identities if process_identity_matches(identity)
        )
        if not remaining or asyncio.get_running_loop().time() >= deadline:
            return remaining
        await asyncio.sleep(0.02)


async def cleanup_run(
    context: RunContext,
    *,
    grace_s: float = 2.0,
) -> CleanupReport:
    """Close one engine and remove only identity-matched run resources.

    Cleanup first requests a graceful fuzzer stop, closes a persistent engine,
    kills the server through its configured ``Server`` connection, and waits for
    every recorded identity. Escalation sends signals only after re-reading an
    equal procfs start time.

    >>> try:
    ...     asyncio.run(cleanup_run(types.SimpleNamespace(), grace_s=0))
    ... except ValueError as error:
    ...     print(error)
    cleanup grace must be positive

    Parameters
    ----------
    context : RunContext
        Single owner of fuzzer, engine, server, pane followers, socket, and scratch.
    grace_s : float
        Wait after each graceful or escalated cleanup step.

    Returns
    -------
    CleanupReport
        Complete only when all identities and filesystem resources are absent.

    Raises
    ------
    ValueError
        If the cleanup grace is not positive.
    """
    if grace_s <= 0:
        message = "cleanup grace must be positive"
        raise ValueError(message)
    errors: list[str] = []
    stop_path = context.scratch / "fuzzer" / "stop.json"
    if stop_path.parent.exists():
        try:
            write_json_atomic(
                stop_path,
                {"schema_version": 1, "run_id": context.run_id},
            )
        except Exception as error:  # noqa: BLE001
            errors.append(f"fuzzer stop marker: {type(error).__name__}: {error}")

    async_closer = getattr(context.engine, "aclose", None)
    sync_closer = getattr(context.engine, "close", None)
    try:
        if callable(async_closer):
            await async_closer()
        elif callable(sync_closer):
            sync_closer()
    except Exception as error:  # noqa: BLE001
        errors.append(f"engine close: {type(error).__name__}: {error}")

    try:
        context.server.kill()
    except Exception as error:  # noqa: BLE001
        errors.append(f"server kill: {type(error).__name__}: {error}")

    survivors = await _wait_for_process_absence(
        context.processes,
        timeout_s=grace_s,
        poll_child=context.fuzzer.poll,
    )
    for signal_number in (signal.SIGTERM, signal.SIGKILL):
        if not survivors:
            break
        for identity in survivors:
            if not process_identity_matches(identity):
                continue
            try:
                os.kill(identity.pid, signal_number)
            except ProcessLookupError:
                continue
            except OSError as error:
                errors.append(
                    f"{identity.role} pid {identity.pid} signal "
                    f"{signal_number}: {type(error).__name__}: {error}"
                )
        survivors = await _wait_for_process_absence(
            context.processes,
            timeout_s=grace_s,
            poll_child=context.fuzzer.poll,
        )

    with contextlib.suppress(subprocess.TimeoutExpired):
        context.fuzzer.wait(timeout=0.1)
    errors.extend(
        f"{identity.role} pid {identity.pid} with start time "
        f"{identity.start_time} remains"
        for identity in survivors
        if process_identity_matches(identity)
    )
    try:
        if context.scratch.exists():
            shutil.rmtree(context.scratch)
    except OSError as error:
        errors.append(f"scratch removal: {type(error).__name__}: {error}")
    try:
        if context.socket_root is not None and context.socket_root.exists():
            shutil.rmtree(context.socket_root)
    except OSError as error:
        errors.append(f"socket root removal: {type(error).__name__}: {error}")
    if context.socket_path.exists():
        errors.append(f"socket remains: {context.socket_path}")
    if context.scratch.exists():
        errors.append(f"scratch remains: {context.scratch}")
    if context.socket_root is not None and context.socket_root.exists():
        errors.append(f"socket root remains: {context.socket_root}")
    for identity in context.processes:
        if process_identity_matches(identity) and not any(
            f"pid {identity.pid} " in error for error in errors
        ):
            errors.append(
                f"{identity.role} pid {identity.pid} with start time "
                f"{identity.start_time} remains"
            )
    for name, value in zip(
        ("TMUX", "TMUX_PANE"), context.ambient_tmux_environment, strict=True
    ):
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    return CleanupReport(complete=not errors, errors=tuple(errors))


def parse_topology(shape: str) -> Topology:
    """Parse a positive ``SxWxP`` topology string.

    >>> parse_topology("2x3x4")
    Topology(sessions=2, windows_per_session=3, panes_per_window=4)

    Parameters
    ----------
    shape : str
        Topology in lower-case ``SxWxP`` notation.

    Returns
    -------
    Topology
        Parsed topology with every dimension positive.

    Raises
    ------
    ValueError
        If the shape is malformed or has a nonpositive dimension.
    """
    pieces = shape.split("x")
    if len(pieces) != 3:
        message = "topology must use SxWxP notation"
        raise ValueError(message)
    try:
        values = tuple(int(piece) for piece in pieces)
    except ValueError as exc:
        message = "topology must use SxWxP notation"
        raise ValueError(message) from exc
    if any(value <= 0 for value in values):
        message = "topology dimensions must be positive"
        raise ValueError(message)
    return Topology(*values)


def canonical_ramp() -> tuple[Topology, ...]:
    """Return the specified progression ordered by expected pane pressure.

    >>> tuple(str(shape) for shape in canonical_ramp())[:3]
    ('80x20x1', '100x20x1', '80x20x2')

    Returns
    -------
    tuple[Topology, ...]
        Exact canonical progression ordered by expected live-pane pressure.
    """
    return (
        Topology(80, 20, 1),
        Topology(100, 20, 1),
        Topology(80, 20, 2),
        Topology(80, 50, 1),
        Topology(80, 20, 4),
        Topology(80, 100, 1),
        Topology(100, 50, 2),
        Topology(100, 100, 2),
        Topology(100, 100, 4),
    )


def summarize_ns(samples: t.Sequence[int]) -> dict[str, int | float]:
    """Return descriptive statistics for accepted integer-nanosecond samples.

    Percentiles use the nearest-rank index ``ceil(p * count) - 1``.

    >>> summarize_ns((1, 2, 3, 4))["p90_ns"]
    4

    Parameters
    ----------
    samples : collections.abc.Sequence[int]
        Accepted duration measurements in nanoseconds.

    Returns
    -------
    dict[str, int | float]
        Count, extrema, mean, median, and p90/p95/p99 values.

    Raises
    ------
    ValueError
        If no samples were accepted.
    """
    if not samples:
        message = "cannot summarize empty samples"
        raise ValueError(message)
    ordered = sorted(samples)

    count = len(ordered)
    return {
        "count": count,
        "min_ns": ordered[0],
        "mean_ns": statistics.mean(ordered),
        "median_ns": statistics.median(ordered),
        "p90_ns": ordered[math.ceil(0.90 * count) - 1],
        "p95_ns": ordered[math.ceil(0.95 * count) - 1],
        "p99_ns": ordered[math.ceil(0.99 * count) - 1],
        "max_ns": ordered[-1],
    }


def main(argv: t.Sequence[str] | None = None) -> int:
    """Run the side-effect-free benchmark planning command.

    >>> import contextlib, io
    >>> captured = io.StringIO()
    >>> with contextlib.redirect_stdout(captured):
    ...     result = main(["plan", "--shape", "1x1x1"])
    >>> result
    0

    Parameters
    ----------
    argv : collections.abc.Sequence[str] | None
        Explicit command arguments, or process arguments when omitted.

    Returns
    -------
    int
        Zero after the selected command completes.

    Raises
    ------
    SystemExit
        If command-line arguments are invalid.
    ValueError
        If the selected plan topology is malformed or nonpositive.
    OSError
        If the selected plan output cannot be written.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan_parser = commands.add_parser("plan", help="inspect topology and host limits")
    plan_parser.add_argument("--shape", required=True)
    plan_parser.add_argument("--output", type=pathlib.Path)
    plan_parser.add_argument("--force-extreme", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.command == "plan":
        return run_plan(arguments.shape, arguments.output, arguments.force_extreme)
    message = "argparse selected an unsupported command"
    raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
