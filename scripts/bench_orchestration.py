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
import json
import math
import os
import pathlib
import resource
import shlex
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import types
import typing as t

if t.TYPE_CHECKING:
    from libtmux.experimental.engines.base import AsyncTmuxEngine, TmuxEngine
    from libtmux.experimental.models import (
        ClientSnapshot,
        PaneSnapshot,
        SessionSnapshot,
        WindowSnapshot,
    )
    from libtmux.experimental.workspace import WorkspaceSet
    from libtmux.server import Server


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
    """

    duration_ns: int | None
    accepted: bool
    error: str | None = None
    verified: bool = False


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
    expected_session_names : tuple[str, ...]
        Exact declared session names.
    expected_window_names : tuple[str, ...]
        Exact declared window names.
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
    server: Server
    engine: TmuxEngine | AsyncTmuxEngine
    fuzzer: subprocess.Popen[bytes]
    streams: tuple[pathlib.Path, ...]
    delayed_ordinal: int
    expected_session_names: tuple[str, ...]
    expected_window_names: tuple[str, ...]
    setup_duration_ns: int
    processes: tuple[ProcessIdentity, ...]
    session_ids: tuple[str, ...] = ()
    window_ids: tuple[str, ...] = ()
    pane_ids: tuple[str, ...] = ()
    delayed_pane_id: str | None = None
    topology_verified: bool = False
    activity_epoch: int | None = None
    activity_marker: str | None = None
    activity_pane_ids: tuple[str, ...] = ()
    heartbeat_epoch: int = -1
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


def start_fuzzer(
    scratch: pathlib.Path,
    run_id: str,
    *,
    ready_timeout_s: float = 5.0,
    frame_rate_hz: float = 40.0,
    duration_s: float = 300.0,
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
            "0.05",
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
    deadline = time.monotonic() + ready_timeout_s
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
            return process
        time.sleep(0.01)
    if process.poll() is None:
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=1.0)
    message = f"fuzzer did not become ready within {ready_timeout_s}s"
    raise RuntimeError(message)


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
        Explicit socket path, defaulting inside ``scratch``.
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
        If ``scratch`` already exists.
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
    resolved_socket = (socket_path or scratch / "tmux.sock").resolve()
    if not resolved_socket.is_relative_to(resolved_scratch):
        message = "socket path must stay inside the run scratch directory"
        raise ValueError(message)
    ambient_tmux_environment = (
        os.environ.pop("TMUX", None),
        os.environ.pop("TMUX_PANE", None),
    )
    scratch_created = False
    fuzzer: subprocess.Popen[bytes] | None = None
    try:
        from libtmux.experimental.engines import (
            AsyncControlModeEngine,
            AsyncSubprocessEngine,
            ControlModeEngine,
            SubprocessEngine,
        )
        from libtmux.server import Server

        scratch.mkdir(parents=True, exist_ok=False)
        scratch_created = True
        fuzzer = start_fuzzer(scratch, run_id)
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
        streams_dir = scratch / "fuzzer" / "streams"
        streams = tuple(
            streams_dir / f"{name}.log"
            for name in ("editor", "dev-server", "installer", "delayed-match")
        )
        return RunContext(
            topology=topology,
            lane=lane,
            mode=mode,
            run_id=run_id,
            scratch=scratch,
            socket_path=resolved_socket,
            server=server,
            engine=engine,
            fuzzer=fuzzer,
            streams=streams,
            delayed_ordinal=delayed_ordinal,
            expected_session_names=tuple(
                _session_name(run_id, index) for index in range(topology.sessions)
            ),
            expected_window_names=tuple(
                _window_name(run_id, session_index, window_index)
                for session_index in range(topology.sessions)
                for window_index in range(topology.windows_per_session)
            ),
            setup_duration_ns=0,
            processes=(_record_process("fuzzer", fuzzer.pid),),
            ambient_tmux_environment=ambient_tmux_environment,
        )
    except BaseException:
        if fuzzer is not None and fuzzer.poll() is None:
            fuzzer.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                fuzzer.wait(timeout=1.0)
        if scratch_created:
            shutil.rmtree(scratch, ignore_errors=True)
        for name, value in zip(
            ("TMUX", "TMUX_PANE"), ambient_tmux_environment, strict=True
        ):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
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
    except BaseException:
        asyncio.run(cleanup_run(context))
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
    except BaseException:
        await cleanup_run(context)
        raise
    else:
        return context


def snapshot_topology_sync(context: RunContext) -> TopologySnapshot:
    """Read exact sync session, window, and pane snapshots through typed ops.

    >>> snapshot_topology_sync.__name__
    'snapshot_topology_sync'

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

    >>> snapshot_topology_async.__name__
    'snapshot_topology_async'

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

    >>> verify_topology.__name__
    'verify_topology'

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

    window_counts = dict.fromkeys(session_ids, 0)
    for window in snapshot.windows:
        if window.session_id not in window_counts:
            fail("window refers to an unknown session")
        window_counts[window.session_id] += 1
    if set(window_counts.values()) != {context.topology.windows_per_session}:
        fail("a session has the wrong window count")
    pane_counts = dict.fromkeys(window_ids, 0)
    for pane in snapshot.panes:
        if pane.window_id not in pane_counts or pane.session_id not in window_counts:
            fail("pane refers to an unknown owner")
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

    >>> _heartbeat_epoch.__name__
    '_heartbeat_epoch'

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

    >>> release_activity_gate.__name__
    'release_activity_gate'

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

    >>> verify_activity_sync.__name__
    'verify_activity_sync'

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

    >>> verify_activity_async.__name__
    'verify_activity_async'

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

    >>> cleanup_run.__name__
    'cleanup_run'

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
    if context.socket_path.exists():
        errors.append(f"socket remains: {context.socket_path}")
    if context.scratch.exists():
        errors.append(f"scratch remains: {context.scratch}")
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
