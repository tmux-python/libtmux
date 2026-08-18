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
import collections.abc as cabc
import dataclasses
import json
import math
import os
import pathlib
import resource
import statistics
import tempfile
import types
import typing as t


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
    """Reject internally inconsistent or incomplete terminal benchmark evidence.

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
