#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["rich>=13"]
# ///
"""Plan, run, validate, and render hermetic active-tmux benchmark evidence.

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
import functools
import hashlib
import html
import inspect
import json
import math
import os
import pathlib
import platform
import random
import re
import resource
import shlex
import shutil
import signal
import stat
import statistics
import subprocess
import sys
import tempfile
import threading
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
_TERMINAL_SAFE_COMPONENT_ALPHABET = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-"
)
_SENTINEL_COMPONENT_MAX_BYTES = 128
_SENTINEL_RECORD_MAX_BYTES = 422
_WAIT_TIMEOUT_MAX_S = 3.0
# Longest a `--_test-stall-after` worker waits to be cancelled before giving up.
# The cancellation tests assert within seconds; this only has to outlast them.
_STALL_MAX_S = 120.0
# tmux exits 1 when no server is listening on the socket -- "no server running
# on <path>", or "error connecting to <path>" when the socket is gone too. For
# a teardown that is the goal state, not a failure, and a server can finish
# exiting on its own between the ownership check and the kill landing. The
# larger the topology the likelier that race: an 80x20x1 rung loses it
# routinely, which used to record a cleanup error for a cleanup that had
# succeeded and, because complete cleanup requires an empty error list, failed
# the whole rung -- stopping the escalating stress harness and understating the
# ceiling it exists to measure. Absence of the owning process is the evidence
# that settles it.
_TMUX_NO_SERVER_STATUS = 1
_WAIT_FRAME_RATE_MAX_HZ = 40.0
_REPORT_SCHEMA_VERSION = 3
_PROGRESS_SCHEMA_VERSION = 2
_MIN_PANE_WIDTH = 64
_PANE_CAPTURE_CHUNK_SIZE = 64
_READINESS_CAPTURE_HISTORY_LINES = 8
_MEASURED_CAPTURE_HISTORY_LINES = 64
_EPOCH_PULSE_MAX_BYTES = 64
_WAIT_SENTINEL_ROWS_MAX = 7
_WAIT_DELAYED_RECORD_ROWS_MAX = 2
_WAIT_EPOCH_PULSE_ROWS = 1
_WAIT_POST_SENTINEL_RECORDS_MAX = int(_WAIT_TIMEOUT_MAX_S * _WAIT_FRAME_RATE_MAX_HZ) + 1
_WAIT_RETENTION_ROWS_REQUIRED = _WAIT_SENTINEL_ROWS_MAX + (
    _WAIT_POST_SENTINEL_RECORDS_MAX
    * (_WAIT_DELAYED_RECORD_ROWS_MAX + _WAIT_EPOCH_PULSE_ROWS)
)
_WAIT_CAPTURE_HISTORY_LINES = 512
_SEARCH_POSITIONS = ("first", "middle", "last")
_ENUMERATION_KINDS = ("sessions", "windows", "panes")
_SEARCH_FAMILIES = ("classic", "snapshot", "end-to-end")
_RUNNER_REPEATABLE_PHASES = (
    "mutation.bulk",
    "wait.capture-poll",
    *tuple(f"enumeration.{kind}" for kind in _ENUMERATION_KINDS),
    "capture.serial",
    "capture.batched",
    *tuple(
        f"search.{family}.{kind}.{position}"
        for family in _SEARCH_FAMILIES
        for kind in _ENUMERATION_KINDS
        for position in _SEARCH_POSITIONS
    ),
    "search.contents",
)
_ORM_ENUMERATION_PHASES = tuple(
    f"enumeration.orm.{kind}" for kind in _ENUMERATION_KINDS
)
_RUNNER_PHASES = (
    "setup",
    "stabilization",
    "mutation.bulk",
    "wait.capture-poll",
    "wait.control-stream",
    *_RUNNER_REPEATABLE_PHASES[2:],
)


def runner_repeatable_phases(*, orm: bool) -> tuple[str, ...]:
    """Return the repeatable phase names for a run, honouring the ORM opt-in.

    Examples
    --------
    >>> runner_repeatable_phases(orm=False) == _RUNNER_REPEATABLE_PHASES
    True
    >>> "enumeration.orm.panes" in runner_repeatable_phases(orm=True)
    True
    """
    if not orm:
        return _RUNNER_REPEATABLE_PHASES
    index = _RUNNER_REPEATABLE_PHASES.index("enumeration.panes") + 1
    return (
        *_RUNNER_REPEATABLE_PHASES[:index],
        *_ORM_ENUMERATION_PHASES,
        *_RUNNER_REPEATABLE_PHASES[index:],
    )


def runner_phases(*, orm: bool) -> tuple[str, ...]:
    """Return the complete phase graph for a run, honouring the ORM opt-in.

    Examples
    --------
    >>> runner_phases(orm=False) == _RUNNER_PHASES
    True
    >>> len(runner_phases(orm=True)) - len(runner_phases(orm=False))
    3
    """
    if not orm:
        return _RUNNER_PHASES
    index = _RUNNER_PHASES.index("enumeration.panes") + 1
    return (
        *_RUNNER_PHASES[:index],
        *_ORM_ENUMERATION_PHASES,
        *_RUNNER_PHASES[index:],
    )


_RUNNER_PHASE_GROUPS = (
    ("setup",),
    ("stabilization",),
    ("mutation.bulk",),
    ("wait.capture-poll", "wait.control-stream"),
    tuple(f"enumeration.{kind}" for kind in _ENUMERATION_KINDS),
    ("capture.serial", "capture.batched"),
    (
        *(
            f"search.{family}.{kind}.{position}"
            for family in _SEARCH_FAMILIES
            for kind in _ENUMERATION_KINDS
            for position in _SEARCH_POSITIONS
        ),
        "search.contents",
    ),
)


def runner_phase_groups(*, orm: bool) -> tuple[tuple[str, ...], ...]:
    """Return the interleaving groups for a run, honouring the ORM opt-in.

    The reference cells join the enumeration group, because they are
    interleaved against the typed cells they are compared with.

    Examples
    --------
    >>> runner_phase_groups(orm=False) == _RUNNER_PHASE_GROUPS
    True
    >>> len(runner_phase_groups(orm=True)[4])
    6
    """
    if not orm:
        return _RUNNER_PHASE_GROUPS
    return tuple(
        (*group, *_ORM_ENUMERATION_PHASES)
        if group == _RUNNER_PHASE_GROUPS[4]
        else group
        for group in _RUNNER_PHASE_GROUPS
    )


def _is_terminal_safe_component(value: object) -> bool:
    """Return whether *value* is one bounded printable ASCII component.

    Components contain 1-128 encoded bytes drawn only from letters, digits,
    ``.``, ``_``, ``:``, and ``-``.

    >>> _is_terminal_safe_component("run.uuid:sample_1-2")
    True
    >>> _is_terminal_safe_component("unsafe value")
    False
    """
    return (
        isinstance(value, str)
        and value.isascii()
        and 0 < len(value.encode()) <= _SENTINEL_COMPONENT_MAX_BYTES
        and all(character in _TERMINAL_SAFE_COMPONENT_ALPHABET for character in value)
    )


def _sentinel_token(run_id: str, request_id: str, value: str) -> str:
    """Build one terminal-safe sentinel within the capture-history contract.

    >>> _sentinel_token("run-7", "sample-1", "READY")
    'LIBTMUX_SENTINEL run=run-7 request=sample-1 value=READY'

    Raises
    ------
    ValueError
        If a component is not terminal-safe or the complete record is too long.
    """
    components = {"run_id": run_id, "request_id": request_id, "value": value}
    for name, component in components.items():
        if not _is_terminal_safe_component(component):
            message = (
                f"{name} must be a 1-{_SENTINEL_COMPONENT_MAX_BYTES} byte "
                "terminal-safe ASCII component using letters, digits, '.', '_', "
                "':', or '-'"
            )
            raise ValueError(message)
    token = f"LIBTMUX_SENTINEL run={run_id} request={request_id} value={value}"
    if len(f"{token}\n".encode()) > _SENTINEL_RECORD_MAX_BYTES:
        message = (
            f"sentinel record must be at most {_SENTINEL_RECORD_MAX_BYTES} "
            "encoded bytes"
        )
        raise ValueError(message)
    return token


def _validated_wait_timeout(timeout_s: float) -> float:
    """Return one finite wait duration covered by retained capture history.

    >>> _validated_wait_timeout(3.0)
    3.0

    Raises
    ------
    ValueError
        If the timeout is not finite, positive, or at most three seconds.
    """
    if (
        isinstance(timeout_s, bool)
        or not isinstance(timeout_s, (int, float))
        or not math.isfinite(timeout_s)
        or timeout_s <= 0
        or timeout_s > _WAIT_TIMEOUT_MAX_S
    ):
        message = (
            f"wait timeout must be positive and at most {_WAIT_TIMEOUT_MAX_S} seconds"
        )
        raise ValueError(message)
    return float(timeout_s)


def _validated_poll_interval(poll_interval_s: float) -> float:
    """Return one finite positive capture-poll cadence.

    >>> _validated_poll_interval(0.01)
    0.01

    Raises
    ------
    ValueError
        If the cadence is not finite and positive.
    """
    if (
        isinstance(poll_interval_s, bool)
        or not isinstance(poll_interval_s, (int, float))
        or not math.isfinite(poll_interval_s)
        or poll_interval_s <= 0
    ):
        message = "capture wait cadence must be finite and positive"
        raise ValueError(message)
    return float(poll_interval_s)


def _validated_pane_epoch_timing(
    timeout_s: float,
    no_progress_timeout_s: float,
    poll_interval_s: float,
) -> tuple[float, float, float]:
    """Return finite positive pane-consumer barrier timing values.

    >>> _validated_pane_epoch_timing(8.0, 3.0, 0.005)
    (8.0, 3.0, 0.005)

    Raises
    ------
    ValueError
        If any timing value cannot form a finite positive deadline.
    """
    validated: list[float] = []
    for value in (timeout_s, no_progress_timeout_s, poll_interval_s):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            message = "pane epoch timeouts and cadence must be finite and positive"
            raise ValueError(message)  # noqa: TRY004
        try:
            seconds = float(value)
        except OverflowError as error:
            message = "pane epoch timeouts and cadence must be finite and positive"
            raise ValueError(message) from error
        if not math.isfinite(seconds) or seconds <= 0:
            message = "pane epoch timeouts and cadence must be finite and positive"
            raise ValueError(message)
        validated.append(seconds)
    return validated[0], validated[1], validated[2]


def _validated_watchdog_seconds(value: object) -> float:
    """Return one exact finite positive supervisor watchdog interval.

    >>> _validated_watchdog_seconds(12)
    12.0

    Raises
    ------
    ValueError
        If the value cannot form a finite positive interval.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        message = "watchdog interval must be finite and positive"
        raise ValueError(message)  # noqa: TRY004
    try:
        seconds = float(value)
    except OverflowError as error:
        message = "watchdog interval must be finite and positive"
        raise ValueError(message) from error
    if not math.isfinite(seconds) or seconds <= 0:
        message = "watchdog interval must be finite and positive"
        raise ValueError(message)
    return seconds


def _pane_epoch_overall_timeout_s(pane_count: int, watchdog_s: object) -> float:
    """Bound pane readiness by chunk scale and the supervisor watchdog.

    >>> _pane_epoch_overall_timeout_s(130, 120.0)
    9.0

    Raises
    ------
    ValueError
        If the pane count or watchdog cannot form a bounded deadline.
    """
    if type(pane_count) is not int or pane_count <= 0:
        message = "pane epoch wait requires a positive pane count"
        raise ValueError(message)
    watchdog_seconds = _validated_watchdog_seconds(watchdog_s)
    chunk_count = (
        pane_count + _PANE_CAPTURE_CHUNK_SIZE - 1
    ) // _PANE_CAPTURE_CHUNK_SIZE
    scaled_seconds = max(8, chunk_count * 3)
    if scaled_seconds >= watchdog_seconds:
        return watchdog_seconds
    return float(scaled_seconds)


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


def _fuzzer_duration_budget_s(
    *,
    lane: EngineLane,
    mode: ExecutionMode,
    runs: int,
    warmup: int,
    watchdog_s: float,
    cleanup_grace_s: float,
    orm: bool = False,
) -> float:
    """Return the finite active-service budget allowed by the supervisor.

    Every repeatable invocation publishes a boundary checkpoint and a result
    checkpoint. The remaining gaps cover stabilization, the non-control wait
    disposition when applicable, final verification, and one final margin.

    >>> _fuzzer_duration_budget_s(
    ...     lane=EngineLane.CONTROL, mode=ExecutionMode.ASYNC,
    ...     runs=2, warmup=1, watchdog_s=10.0, cleanup_grace_s=0.5,
    ... )
    2190.5

    Parameters
    ----------
    lane : EngineLane
        Selected transport lane.
    mode : ExecutionMode
        Selected dispatch mode.
    runs : int
        Timed invocations per repeatable cell.
    warmup : int
        Untimed invocations per repeatable cell.
    watchdog_s : float
        Maximum interval between increasing progress sequences.
    cleanup_grace_s : float
        Final bounded cleanup allowance.

    Returns
    -------
    float
        Finite positive fuzzer lifetime in seconds.

    Raises
    ------
    ValueError
        If inputs are invalid or their exact budget is not a finite float.
    """
    if type(runs) is not int or runs <= 0 or type(warmup) is not int or warmup < 0:
        message = "fuzzer service budget requires positive runs and nonnegative warmup"
        raise ValueError(message)
    timeout_values = (watchdog_s, cleanup_grace_s)
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        for value in timeout_values
    ):
        message = "fuzzer service budget requires finite positive timeouts"
        raise ValueError(message)
    try:
        watchdog_seconds, cleanup_grace_seconds = (
            float(value) for value in timeout_values
        )
    except OverflowError as error:
        message = "fuzzer service budget requires finite positive timeouts"
        raise ValueError(message) from error
    if any(
        not math.isfinite(value) or value <= 0
        for value in (watchdog_seconds, cleanup_grace_seconds)
    ):
        message = "fuzzer service budget requires finite positive timeouts"
        raise ValueError(message)
    control_applicable = lane is EngineLane.CONTROL and mode is ExecutionMode.ASYNC
    cell_count = len(runner_repeatable_phases(orm=orm)) + int(control_applicable)
    progress_gaps = (
        2 * (runs + warmup) * cell_count + 1 + int(not control_applicable) + 1 + 1
    )
    try:
        duration_s = watchdog_seconds * progress_gaps + cleanup_grace_seconds
    except OverflowError as error:
        message = "benchmark requires a finite fuzzer service duration"
        raise ValueError(message) from error
    if not math.isfinite(duration_s) or duration_s <= 0:
        message = "benchmark requires a finite fuzzer service duration"
        raise ValueError(message)
    return duration_s


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
        Whether every capture succeeded and contained the frozen current epoch.

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
class PhaseObservation:
    """Recomputable correctness and work counts for one accepted timing.

    Attributes
    ----------
    ordinal : int
        Zero-based timed sample ordinal within the cell.
    strategy : str
        Stable cell name that produced the observation.
    duration_ns : int
        Raw integer timing associated with this observation.
    metrics : ExecutionMetrics | None
        Typed operation and transport counts when the cell contacts tmux.
    row_count : int | None
        Exact hierarchy rows returned by enumeration.
    byte_count : int | None
        UTF-8 bytes retained by an all-pane capture.
    line_count : int | None
        Typed lines retained by an all-pane capture.
    poll_count : int | None
        Capture requests issued by a delayed-output wait.
    frame_count : int | None
        Matching control notifications consumed by a delayed-output wait.
    dropped_notification_delta : int | None
        Control notification drops observed during a delayed-output wait.
    configured_delay_ns : int | None
        Intentional fuzzer delay excluded from waiter overhead.
    scheduling_lateness_ns : int | None
        Fuzzer emission lateness beyond its requested schedule.
    detection_overhead_ns : int | None
        Waiter detection time after actual fuzzer emission.
    scanned_count : int | None
        Candidate cardinality scanned by a search.
    matched_count : int | None
        Exact accepted match cardinality for a search.
    target : str | None
        Concrete search target or delayed pane identifier.
    session_count : int | None
        Sessions verified or mutated by this observation.
    window_count : int | None
        Windows verified or mutated by this observation.
    pane_count : int | None
        Panes verified, mutated, or captured by this observation.
    verified : bool
        Whether typed and live checks accepted the observation.

    Examples
    --------
    >>> PhaseObservation(0, "enumeration.sessions", 7, row_count=1).row_count
    1
    """

    ordinal: int
    strategy: str
    duration_ns: int
    metrics: ExecutionMetrics | None = None
    row_count: int | None = None
    byte_count: int | None = None
    line_count: int | None = None
    poll_count: int | None = None
    frame_count: int | None = None
    dropped_notification_delta: int | None = None
    configured_delay_ns: int | None = None
    scheduling_lateness_ns: int | None = None
    detection_overhead_ns: int | None = None
    scanned_count: int | None = None
    matched_count: int | None = None
    target: str | None = None
    session_count: int | None = None
    window_count: int | None = None
    pane_count: int | None = None
    verified: bool = True


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
    status : {"in_progress", "completed", "failed", "not_applicable"}
        Lifecycle or applicability state of this benchmark cell.
    warmup : int
        Untimed invocations requested for a repeatable cell.
    runs : int
        Timed invocations requested for a repeatable cell.
    warmup_observations : tuple[PhaseObservation, ...]
        Typed counts retained for every untimed warmup invocation.
    observations : tuple[PhaseObservation, ...]
        Typed counts corresponding one-to-one with accepted timed samples.
    """

    name: str
    requested_topology: Topology
    observed_topology: Topology | None
    samples: tuple[RawSample, ...] = ()
    summary: cabc.Mapping[str, int | float] | None = None
    status: t.Literal["in_progress", "completed", "failed", "not_applicable"] = (
        "completed"
    )
    warmup: int = 0
    runs: int = 0
    warmup_observations: tuple[PhaseObservation, ...] = ()
    observations: tuple[PhaseObservation, ...] = ()

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
    processes_absent : bool | None
        Whether every recorded PID/start-time identity was absent.
    socket_absent : bool | None
        Whether the exact isolated socket path was absent.
    scratch_absent : bool | None
        Whether the exact private scratch directory was absent.
    """

    complete: bool
    errors: tuple[str, ...] = ()
    processes_absent: bool | None = None
    socket_absent: bool | None = None
    scratch_absent: bool | None = None


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
class SocketIdentity:
    """Immutable filesystem identity of one owned Unix socket.

    Attributes
    ----------
    st_dev : int
        Device containing the socket node.
    st_ino : int
        Inode of the socket node.
    st_uid : int
        User that owns the socket node.
    st_mode : int
        Complete mode captured by ``lstat``; its file type must remain a socket.
    st_mtime_ns : int
        Captured nanosecond modification timestamp used with device and inode.

    Examples
    --------
    >>> identity = SocketIdentity(1, 2, os.getuid(), stat.S_IFSOCK | 0o600, 3)
    >>> stat.S_ISSOCK(identity.st_mode)
    True
    """

    st_dev: int
    st_ino: int
    st_uid: int
    st_mode: int
    st_mtime_ns: int

    def matches(self, other: SocketIdentity) -> bool:
        """Report whether *other* is the same node this fingerprint captured.

        Device, inode, owner, file type, and modification time all decide
        identity. Modification time is load-bearing because a filesystem may
        reuse an inode number, and a replacement node created later carries a
        later timestamp.

        Permission bits are the sole exclusion. tmux's ``server_update_socket()``
        sets the socket's execute bits while any session is attached and clears
        them when none is, so an owned socket legitimately changes mode while
        the run holds it. Comparing whole modes therefore reads an ordinary
        attach or detach as a different socket.

        Parameters
        ----------
        other : SocketIdentity
            Fingerprint observed later for the same path.

        Returns
        -------
        bool
            True only when both fingerprints name one socket node.

        Examples
        --------
        An attach flips the execute bit but keeps the node:

        >>> attached = SocketIdentity(1, 2, 3, stat.S_IFSOCK | 0o700, 10)
        >>> detached = SocketIdentity(1, 2, 3, stat.S_IFSOCK | 0o600, 10)
        >>> attached.matches(detached)
        True

        A reused inode number, a replaced node, and a different file type are
        all rejected:

        >>> attached.matches(SocketIdentity(1, 2, 3, stat.S_IFSOCK | 0o700, 99))
        False
        >>> attached.matches(SocketIdentity(1, 9, 3, stat.S_IFSOCK | 0o700, 10))
        False
        >>> attached.matches(SocketIdentity(1, 2, 3, stat.S_IFREG | 0o700, 10))
        False
        """
        return (
            self.st_dev == other.st_dev
            and self.st_ino == other.st_ino
            and self.st_uid == other.st_uid
            and self.st_mtime_ns == other.st_mtime_ns
            and stat.S_IFMT(self.st_mode) == stat.S_IFMT(other.st_mode)
        )


@dataclasses.dataclass(frozen=True)
class _SocketOwnership:
    """Bind one tmux process identity to its original socket inode.

    Attributes
    ----------
    process : ProcessIdentity
        Exact tmux server PID and procfs start time.
    socket : SocketIdentity
        Socket fingerprint observed around the owner query.

    Examples
    --------
    >>> owner = ProcessIdentity("server", 2, 3)
    >>> socket_id = SocketIdentity(1, 2, os.getuid(), stat.S_IFSOCK | 0o600, 4)
    >>> _SocketOwnership(owner, socket_id).process is owner
    True
    """

    process: ProcessIdentity
    socket: SocketIdentity


@dataclasses.dataclass(frozen=True)
class ProgressEvent:
    """One append-only worker checkpoint observed by the supervisor.

    Attributes
    ----------
    run_id : str
        Exact run identity shared with the checkpoint report.
    sequence : int
        Strictly increasing worker-local progress sequence.
    checkpoint : str
        Stable lifecycle or phase checkpoint name.
    monotonic_ns : int
        Worker monotonic publication time.
    processes : tuple[ProcessIdentity, ...]
        Exact identities first learned at this checkpoint; never cumulative.
    socket_ownership : _SocketOwnership | None
        Exact server/socket capability first learned at this checkpoint.
    schema_version : int
        Progress stream schema version.

    Examples
    --------
    >>> ProgressEvent("run-7", 2, "setup", 10).sequence
    2
    """

    run_id: str
    sequence: int
    checkpoint: str
    monotonic_ns: int
    processes: tuple[ProcessIdentity, ...] = ()
    socket_ownership: _SocketOwnership | None = None
    schema_version: int = _PROGRESS_SCHEMA_VERSION


@dataclasses.dataclass(frozen=True)
class EnvironmentReport:
    """Descriptive local environment attached to one benchmark artifact.

    Attributes
    ----------
    python_version : str
        Running Python implementation version.
    tmux_version : str | None
        ``tmux -V`` output when the executable was available.
    cpu_count : int | None
        Logical CPU count exposed to Python.
    seed : int
        Deterministic phase-order seed.
    command_line : tuple[str, ...]
        Exact worker-independent public invocation arguments.
    git_revision : str | None
        Current checkout revision when Git could resolve it.

    Examples
    --------
    >>> EnvironmentReport("3.10", "tmux 3.4", 4, 11, ("run",), "abc").seed
    11
    """

    python_version: str
    tmux_version: str | None
    cpu_count: int | None
    seed: int
    command_line: tuple[str, ...]
    git_revision: str | None


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
    watchdog_s : float
        Finite supervisor progress interval bounding pane readiness.
    processes : tuple[ProcessIdentity, ...]
        Fuzzer, server, and pane-follower identities.
    socket_ownership : _SocketOwnership | None
        Immutable server/socket capability captured during bootstrap.
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
        One-time marker required in every pane during initial stabilization.
    activity_pane_ids : tuple[str, ...]
        Panes that captured the released marker.
    heartbeat_epoch : int
        Last monotonic fuzzer heartbeat epoch observed.
    heartbeat_monotonic_ns : int
        Last fuzzer monotonic publication timestamp observed.
    ambient_tmux_environment : tuple[str | None, str | None]
        Original ``TMUX`` and ``TMUX_PANE`` values restored after cleanup.
    setup_metrics : ExecutionMetrics | None
        Exact construction operation and dispatch counts.
    process_identity_callback : collections.abc.Callable | None
        Private worker hook called as owned identities become known.
    process_handles : _PidfdRegistry
        Worker-owned stable handles retained as identities become known.

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
    watchdog_s: float
    processes: tuple[ProcessIdentity, ...]
    socket_ownership: _SocketOwnership | None = None
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
    setup_metrics: ExecutionMetrics | None = None
    process_identity_callback: (
        cabc.Callable[[tuple[ProcessIdentity, ...]], None] | None
    ) = None
    process_handles: _PidfdRegistry | None = None


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
    run_id : str | None
        Fresh run identity for an attempted shape.
    report_path : str | None
        Per-shape validated JSON artifact.
    scratch_path : str | None
        Fresh private scratch path, absent after cleanup.
    socket_path : str | None
        Fresh isolated socket path, absent after cleanup.
    """

    shape: Topology
    status: t.Literal["completed", "refused", "failed", "cutoff", "not_attempted"]
    reason: str | None = None
    run_id: str | None = None
    report_path: str | None = None
    scratch_path: str | None = None
    socket_path: str | None = None


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
    run_id : str | None
        Fresh terminal-safe identity for an executable scenario.
    lane : {"subprocess", "control"} | None
        Selected transport lane for a single executable scenario.
    mode : {"sync", "async"} | None
        Selected dispatch mode for a single executable scenario.
    warmup : int | None
        Untimed invocation count per repeatable cell.
    runs : int | None
        Timed invocation count per repeatable cell.
    failed_phase : str | None
        Phase or boundary that produced a terminal non-success status.
    error : str | None
        Concise terminal reason retained by the supervisor.
    processes : tuple[ProcessIdentity, ...]
        Exact worker, fuzzer, server, and pane identities observed by progress.
    socket_ownership : _SocketOwnership | None
        Durable server/socket capability observed in worker progress.
    scratch_path : str | None
        Exact private run path whose absence cleanup verified.
    socket_path : str | None
        Exact isolated socket path whose absence cleanup verified.
    progress_path : str | None
        Append-only JSONL progress artifact owned by the supervisor.
    progress_sequence : int
        Highest worker sequence incorporated into this checkpoint.
    environment : EnvironmentReport | None
        Descriptive local environment; never a causal performance claim.
    orm : bool
        Whether the optional classic ORM reference cells were measured. The
        phase graph a validator requires depends on this declaration.
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
    schema_version: int = _REPORT_SCHEMA_VERSION
    run_id: str | None = None
    lane: t.Literal["subprocess", "control"] | None = None
    mode: t.Literal["sync", "async"] | None = None
    warmup: int | None = None
    runs: int | None = None
    failed_phase: str | None = None
    error: str | None = None
    processes: tuple[ProcessIdentity, ...] = ()
    socket_ownership: _SocketOwnership | None = None
    scratch_path: str | None = None
    socket_path: str | None = None
    progress_path: str | None = None
    progress_sequence: int = -1
    environment: EnvironmentReport | None = None
    orm: bool = False


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


def _json_mapping(value: object, label: str) -> dict[str, t.Any]:
    """Return one string-keyed JSON mapping or reject the artifact.

    >>> _json_mapping({"value": 1}, "example")["value"]
    1

    Parameters
    ----------
    value : object
        Parsed JSON value.
    label : str
        Human-readable field name used in errors.

    Returns
    -------
    dict[str, typing.Any]
        Mapping copied from the parsed artifact.

    Raises
    ------
    ValueError
        If the value is not a mapping with string keys.
    """
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        message = f"{label} must be a JSON object"
        raise ValueError(message)
    return t.cast(dict[str, t.Any], value)


def _topology_from_json(value: object) -> Topology:
    """Decode one exact topology mapping.

    >>> _topology_from_json(
    ...     {"sessions": 1, "windows_per_session": 2, "panes_per_window": 3}
    ... )
    Topology(sessions=1, windows_per_session=2, panes_per_window=3)
    """
    row = _json_mapping(value, "topology")
    try:
        topology = Topology(
            sessions=row["sessions"],
            windows_per_session=row["windows_per_session"],
            panes_per_window=row["panes_per_window"],
        )
    except KeyError as error:
        message = f"topology lacks {error.args[0]}"
        raise ValueError(message) from error
    if any(
        type(dimension) is not int or dimension <= 0
        for dimension in (
            topology.sessions,
            topology.windows_per_session,
            topology.panes_per_window,
        )
    ):
        message = "topology dimensions must be positive integers"
        raise ValueError(message)
    return topology


def _host_snapshot_from_json(value: object | None) -> HostSnapshot | None:
    """Decode an optional host-resource snapshot.

    >>> _host_snapshot_from_json(None) is None
    True
    """
    if value is None:
        return None
    row = _json_mapping(value, "host snapshot")
    return HostSnapshot(
        available_memory_bytes=row.get("available_memory_bytes"),
        physical_memory_bytes=row.get("physical_memory_bytes"),
        memory_current_bytes=row.get("memory_current_bytes"),
        memory_max_bytes=row.get("memory_max_bytes"),
        pids_current=row.get("pids_current"),
        pids_max=row.get("pids_max"),
        nofile_soft_limit=row.get("nofile_soft_limit"),
        nofile_hard_limit=row.get("nofile_hard_limit"),
        memory_pressure_some_avg10=row.get("memory_pressure_some_avg10"),
        source_errors=_json_mapping(row.get("source_errors", {}), "source errors"),
    )


def _guard_from_json(value: object | None) -> GuardDecision | None:
    """Decode an optional guard decision.

    >>> _guard_from_json(None) is None
    True
    """
    if value is None:
        return None
    row = _json_mapping(value, "guard decision")
    snapshot = _host_snapshot_from_json(row.get("snapshot"))
    if snapshot is None:
        message = "guard decision requires a host snapshot"
        raise ValueError(message)
    return GuardDecision(
        allowed=t.cast(bool, row.get("allowed")),
        kind=t.cast(
            t.Literal["ok", "predictive_refusal", "runtime_cutoff"],
            row.get("kind"),
        ),
        rule=t.cast(str | None, row.get("rule")),
        observed=t.cast(int | None, row.get("observed")),
        limit=t.cast(int | None, row.get("limit")),
        forceable=t.cast(bool, row.get("forceable")),
        snapshot=snapshot,
    )


def _metrics_from_json(value: object | None) -> ExecutionMetrics | None:
    """Decode optional operation and transport counts.

    >>> _metrics_from_json(None) is None
    True
    """
    if value is None:
        return None
    row = _json_mapping(value, "execution metrics")
    return ExecutionMetrics(
        operations=t.cast(int, row.get("operations")),
        planner_steps=t.cast(int, row.get("planner_steps")),
        engine_batches=t.cast(int, row.get("engine_batches")),
        tmux_requests=t.cast(int, row.get("tmux_requests")),
        process_starts=t.cast(int, row.get("process_starts")),
    )


def _sample_from_json(value: object) -> RawSample:
    """Decode one raw timing sample.

    >>> _sample_from_json({"duration_ns": 3, "accepted": True}).duration_ns
    3
    """
    row = _json_mapping(value, "raw sample")
    return RawSample(
        duration_ns=t.cast(int | None, row.get("duration_ns")),
        accepted=t.cast(bool, row.get("accepted")),
        error=t.cast(str | None, row.get("error")),
        verified=t.cast(bool, row.get("verified", False)),
        strategy=t.cast(str | None, row.get("strategy")),
        ordinal=t.cast(int | None, row.get("ordinal")),
        resources_before=_host_snapshot_from_json(row.get("resources_before")),
        resources_after=_host_snapshot_from_json(row.get("resources_after")),
    )


def _observation_from_json(value: object) -> PhaseObservation:
    """Decode one typed phase observation.

    >>> _observation_from_json(
    ...     {"ordinal": 0, "strategy": "x", "duration_ns": 2}
    ... ).strategy
    'x'
    """
    row = _json_mapping(value, "phase observation")
    return PhaseObservation(
        ordinal=t.cast(int, row.get("ordinal")),
        strategy=t.cast(str, row.get("strategy")),
        duration_ns=t.cast(int, row.get("duration_ns")),
        metrics=_metrics_from_json(row.get("metrics")),
        row_count=row.get("row_count"),
        byte_count=row.get("byte_count"),
        line_count=row.get("line_count"),
        poll_count=row.get("poll_count"),
        frame_count=row.get("frame_count"),
        dropped_notification_delta=row.get("dropped_notification_delta"),
        configured_delay_ns=row.get("configured_delay_ns"),
        scheduling_lateness_ns=row.get("scheduling_lateness_ns"),
        detection_overhead_ns=row.get("detection_overhead_ns"),
        scanned_count=row.get("scanned_count"),
        matched_count=row.get("matched_count"),
        target=row.get("target"),
        session_count=row.get("session_count"),
        window_count=row.get("window_count"),
        pane_count=row.get("pane_count"),
        verified=t.cast(bool, row.get("verified", False)),
    )


def _phase_from_json(value: object) -> PhaseReport:
    """Decode one phase report and its raw observations.

    >>> _phase_from_json({
    ...     "name": "stabilization",
    ...     "requested_topology": {
    ...         "sessions": 1, "windows_per_session": 1, "panes_per_window": 1
    ...     },
    ...     "observed_topology": None,
    ... }).name
    'stabilization'
    """
    row = _json_mapping(value, "phase")
    observed = row.get("observed_topology")
    summary = row.get("summary")
    return PhaseReport(
        name=t.cast(str, row.get("name")),
        requested_topology=_topology_from_json(row.get("requested_topology")),
        observed_topology=(None if observed is None else _topology_from_json(observed)),
        samples=tuple(_sample_from_json(item) for item in row.get("samples", [])),
        summary=(None if summary is None else _json_mapping(summary, "phase summary")),
        status=t.cast(
            t.Literal["in_progress", "completed", "failed", "not_applicable"],
            row.get("status", "completed"),
        ),
        warmup=t.cast(int, row.get("warmup", 0)),
        runs=t.cast(int, row.get("runs", 0)),
        warmup_observations=tuple(
            _observation_from_json(item) for item in row.get("warmup_observations", [])
        ),
        observations=tuple(
            _observation_from_json(item) for item in row.get("observations", [])
        ),
    )


def _cleanup_from_json(value: object) -> CleanupReport:
    """Decode exact cleanup evidence.

    >>> _cleanup_from_json({"complete": True, "errors": []}).complete
    True
    """
    row = _json_mapping(value, "cleanup")
    errors = row.get("errors", [])
    if not isinstance(errors, list):
        message = "cleanup errors must be a JSON array"
        raise ValueError(message)  # noqa: TRY004
    return CleanupReport(
        complete=t.cast(bool, row.get("complete")),
        errors=tuple(t.cast(list[str], errors)),
        processes_absent=t.cast(bool | None, row.get("processes_absent")),
        socket_absent=t.cast(bool | None, row.get("socket_absent")),
        scratch_absent=t.cast(bool | None, row.get("scratch_absent")),
    )


def _identity_from_json(value: object) -> ProcessIdentity:
    """Decode one PID/start-time identity.

    >>> _identity_from_json({"role": "worker", "pid": 2, "start_time": 3}).pid
    2
    """
    row = _json_mapping(value, "process identity")
    return ProcessIdentity(
        t.cast(str, row.get("role")),
        t.cast(int, row.get("pid")),
        t.cast(int, row.get("start_time")),
    )


def _socket_identity_from_json(value: object) -> SocketIdentity:
    """Decode one exact socket fingerprint.

    >>> _socket_identity_from_json({
    ...     "st_dev": 1, "st_ino": 2, "st_uid": 3,
    ...     "st_mode": stat.S_IFSOCK | 0o600,
    ...     "st_mtime_ns": 4,
    ... }).st_ino
    2
    """
    row = _json_mapping(value, "socket identity")
    return SocketIdentity(
        st_dev=t.cast(int, row.get("st_dev")),
        st_ino=t.cast(int, row.get("st_ino")),
        st_uid=t.cast(int, row.get("st_uid")),
        st_mode=t.cast(int, row.get("st_mode")),
        st_mtime_ns=t.cast(int, row.get("st_mtime_ns")),
    )


def _socket_ownership_from_json(value: object | None) -> _SocketOwnership | None:
    """Decode an optional process/socket ownership capability.

    >>> _socket_ownership_from_json(None) is None
    True
    """
    if value is None:
        return None
    row = _json_mapping(value, "socket ownership")
    ownership = _SocketOwnership(
        process=_identity_from_json(row.get("process")),
        socket=_socket_identity_from_json(row.get("socket")),
    )
    _validate_socket_ownership(ownership)
    return ownership


def _validate_socket_ownership(ownership: _SocketOwnership) -> None:
    """Reject a capability that cannot identify one same-user tmux socket.

    Examples
    --------
    >>> owner = ProcessIdentity("server", 2, 3)
    >>> socket_id = SocketIdentity(1, 2, os.getuid(), stat.S_IFSOCK | 0o600, 4)
    >>> _validate_socket_ownership(_SocketOwnership(owner, socket_id))

    Parameters
    ----------
    ownership : _SocketOwnership
        Process and filesystem identity decoded from durable evidence.

    Returns
    -------
    None
        After every identity component has its exact JSON-domain type and range.

    Raises
    ------
    ValueError
        If the process or socket fingerprint is malformed.
    """
    process = ownership.process
    socket_identity = ownership.socket
    if (
        process.role != "server"
        or type(process.pid) is not int
        or process.pid <= 0
        or type(process.start_time) is not int
        or process.start_time <= 0
        or type(socket_identity.st_dev) is not int
        or socket_identity.st_dev < 0
        or type(socket_identity.st_ino) is not int
        or socket_identity.st_ino <= 0
        or type(socket_identity.st_uid) is not int
        or socket_identity.st_uid != os.getuid()
        or type(socket_identity.st_mode) is not int
        or not stat.S_ISSOCK(socket_identity.st_mode)
        or type(socket_identity.st_mtime_ns) is not int
        or socket_identity.st_mtime_ns <= 0
    ):
        message = "invalid socket ownership capability"
        raise ValueError(message)


def _environment_from_json(value: object | None) -> EnvironmentReport | None:
    """Decode optional descriptive environment evidence.

    >>> _environment_from_json(None) is None
    True
    """
    if value is None:
        return None
    row = _json_mapping(value, "environment")
    command_line = row.get("command_line", [])
    if not isinstance(command_line, list):
        message = "environment command_line must be a JSON array"
        raise ValueError(message)  # noqa: TRY004
    return EnvironmentReport(
        python_version=t.cast(str, row.get("python_version")),
        tmux_version=t.cast(str | None, row.get("tmux_version")),
        cpu_count=t.cast(int | None, row.get("cpu_count")),
        seed=t.cast(int, row.get("seed")),
        command_line=tuple(t.cast(list[str], command_line)),
        git_revision=t.cast(str | None, row.get("git_revision")),
    )


def run_report_from_json(value: object) -> RunReport:
    """Decode a JSON-native report into immutable typed evidence.

    >>> report = run_report_from_json({
    ...     "schema_version": 3,
    ...     "requested_topology": {
    ...         "sessions": 1, "windows_per_session": 1, "panes_per_window": 1
    ...     },
    ...     "cleanup": {"complete": False, "errors": []},
    ... })
    >>> report.status
    'in_progress'

    Parameters
    ----------
    value : object
        Parsed JSON report object.

    Returns
    -------
    RunReport
        Immutable artifact suitable for :func:`validate_report`.
    """
    row = _json_mapping(value, "run report")
    if row.get("schema_version") != _REPORT_SCHEMA_VERSION:
        message = "unsupported report schema_version"
        raise ValueError(message)
    observed = row.get("observed_topology")
    ramp_rows = []
    for item in row.get("ramp", []):
        ramp_row = _json_mapping(item, "ramp step")
        ramp_rows.append(
            RampStep(
                shape=_topology_from_json(ramp_row.get("shape")),
                status=t.cast(
                    t.Literal[
                        "completed",
                        "refused",
                        "failed",
                        "cutoff",
                        "not_attempted",
                    ],
                    ramp_row.get("status"),
                ),
                reason=ramp_row.get("reason"),
                run_id=ramp_row.get("run_id"),
                report_path=ramp_row.get("report_path"),
                scratch_path=ramp_row.get("scratch_path"),
                socket_path=ramp_row.get("socket_path"),
            )
        )
    return RunReport(
        requested_topology=_topology_from_json(row.get("requested_topology")),
        observed_topology=(None if observed is None else _topology_from_json(observed)),
        status=row.get("status", "in_progress"),
        phases=tuple(_phase_from_json(item) for item in row.get("phases", [])),
        cleanup=_cleanup_from_json(
            row.get("cleanup", {"complete": False, "errors": []})
        ),
        maximum_completed=row.get("maximum_completed", False),
        ramp=tuple(ramp_rows),
        requested_shapes=tuple(
            _topology_from_json(item) for item in row.get("requested_shapes", [])
        ),
        ramp_kind=row.get("ramp_kind", "none"),
        guard_decision=_guard_from_json(row.get("guard_decision")),
        original_guard_decision=_guard_from_json(row.get("original_guard_decision")),
        schema_version=t.cast(int, row.get("schema_version")),
        run_id=row.get("run_id"),
        lane=row.get("lane"),
        mode=row.get("mode"),
        warmup=row.get("warmup"),
        runs=row.get("runs"),
        failed_phase=row.get("failed_phase"),
        error=row.get("error"),
        processes=tuple(_identity_from_json(item) for item in row.get("processes", [])),
        socket_ownership=_socket_ownership_from_json(row.get("socket_ownership")),
        scratch_path=row.get("scratch_path"),
        socket_path=row.get("socket_path"),
        progress_path=row.get("progress_path"),
        progress_sequence=row.get("progress_sequence", -1),
        environment=_environment_from_json(row.get("environment")),
        orm=bool(row.get("orm", False)),
    )


def load_run_report(path: pathlib.Path) -> RunReport:
    """Load one complete JSON report without accepting partial bytes.

    >>> with tempfile.TemporaryDirectory() as directory:
    ...     path = pathlib.Path(directory) / "report.json"
    ...     write_json_atomic(path, RunReport(Topology(1, 1, 1)))
    ...     load_run_report(path).requested_topology.panes
    1
    """
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, RecursionError) as error:
        message = f"report is not complete JSON: {path}"
        raise ValueError(message) from error
    try:
        return run_report_from_json(value)
    except TypeError as error:
        message = f"report has invalid JSON structure: {path}"
        raise ValueError(message) from error


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
    if report.schema_version != _REPORT_SCHEMA_VERSION:
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
    cleanup_facts_complete = (
        report.cleanup.complete is True
        and report.cleanup.processes_absent is True
        and report.cleanup.socket_absent is True
        and report.cleanup.scratch_absent is True
        and not report.cleanup.errors
    )
    if report.cleanup.complete is True and not cleanup_facts_complete:
        message = "cleanup complete requires all absence flags and no errors"
        raise ValueError(message)
    if report.status in {"completed", "refused", "cutoff"} and not (
        cleanup_facts_complete
    ):
        message = "terminal report requires complete cleanup"
        raise ValueError(message)
    phase_statuses = {"in_progress", "completed", "failed", "not_applicable"}
    if len({phase.name for phase in report.phases}) != len(report.phases):
        message = "phase names must be unique"
        raise ValueError(message)
    if report.status in terminal:
        unfinished_seen = False
        for phase in report.phases:
            if phase.status in {"failed", "in_progress"}:
                unfinished_seen = True
            elif unfinished_seen and phase.status in {"completed", "not_applicable"}:
                message = "terminal report has an invalid phase status prefix"
                raise ValueError(message)
    for phase in report.phases:
        if phase.status not in phase_statuses:
            message = "invalid phase status"
            raise ValueError(message)
        if (
            type(phase.warmup) is not int
            or phase.warmup < 0
            or type(phase.runs) is not int
            or phase.runs < 0
        ):
            message = "phase warmup and runs must be nonnegative integers"
            raise ValueError(message)
        if phase.status == "not_applicable" and (
            phase.samples
            or phase.summary is not None
            or phase.warmup_observations
            or phase.observations
        ):
            message = "not_applicable phase cannot carry timing evidence"
            raise ValueError(message)
        if phase.name == "setup" and phase.status == "completed":
            setup_sample = phase.samples[0] if len(phase.samples) == 1 else None
            setup_observation = (
                phase.observations[0] if len(phase.observations) == 1 else None
            )
            if (
                setup_sample is None
                or setup_observation is None
                or setup_sample.accepted is not True
                or setup_sample.verified is not True
                or setup_sample.error is not None
                or setup_sample.ordinal != 0
                or setup_sample.strategy != "setup"
                or setup_observation.verified is not True
                or setup_observation.ordinal != 0
                or setup_observation.strategy != "setup"
                or setup_sample.duration_ns != setup_observation.duration_ns
            ):
                message = "completed setup requires one accepted verified observation"
                raise ValueError(message)
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
        for observation in phase.observations:
            if (
                type(observation.ordinal) is not int
                or observation.ordinal < 0
                or not observation.strategy
                or type(observation.duration_ns) is not int
                or observation.duration_ns <= 0
                or not observation.verified
            ):
                message = "phase observation requires verified positive evidence"
                raise ValueError(message)
        for observation in phase.warmup_observations:
            if (
                type(observation.ordinal) is not int
                or observation.ordinal < 0
                or not observation.strategy
                or type(observation.duration_ns) is not int
                or observation.duration_ns <= 0
                or not observation.verified
            ):
                message = "warmup observation requires verified positive evidence"
                raise ValueError(message)
        if phase.name == "wait.control-stream" and any(
            type(observation.dropped_notification_delta) is not int
            or observation.dropped_notification_delta != 0
            for observation in (*phase.warmup_observations, *phase.observations)
        ):
            message = "control-stream observations require exact zero drop evidence"
            raise ValueError(message)
        if (
            phase.runs > 0
            and phase.name not in {"setup", "stabilization"}
            and (phase.status != "not_applicable")
        ):
            timed_ordinals = tuple(sample.ordinal for sample in phase.samples)
            observation_ordinals = tuple(
                observation.ordinal for observation in phase.observations
            )
            expected_timed = tuple(
                range(phase.runs if phase.status == "completed" else len(phase.samples))
            )
            if (
                timed_ordinals != expected_timed
                or observation_ordinals != expected_timed
                or any(sample.strategy != phase.name for sample in phase.samples)
                or any(
                    observation.strategy != phase.name
                    for observation in phase.observations
                )
            ):
                message = f"phase {phase.name} has invalid timed ordinals"
                raise ValueError(message)
            warmup_ordinals = tuple(
                observation.ordinal for observation in phase.warmup_observations
            )
            expected_warmup = tuple(
                range(
                    phase.warmup
                    if phase.status == "completed"
                    else len(phase.warmup_observations)
                )
            )
            if warmup_ordinals != expected_warmup or any(
                observation.strategy != phase.name
                for observation in phase.warmup_observations
            ):
                message = f"phase {phase.name} has invalid warmup ordinals"
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
    if (
        report.ramp_kind != "none"
        and report.status == "completed"
        and (report.error is not None or report.failed_phase is not None)
    ):
        message = "completed ramp cannot carry terminal failure metadata"
        raise ValueError(message)
    if report.ramp_kind != "none" and report.status in terminal_statuses:
        terminals = [step for step in report.ramp if step.status in terminal_statuses]
        aggregate_cutoff = report.status == "cutoff" and not terminals
        if aggregate_cutoff:
            pending = False
            if not report.error:
                message = "aggregate cutoff requires an interruption reason"
                raise ValueError(message)
            for step in report.ramp:
                if step.status == "completed" and not pending:
                    continue
                if step.status == "not_attempted" and step.reason == report.error:
                    pending = True
                    continue
                message = "aggregate cutoff requires a completed prefix"
                raise ValueError(message)
        elif len(terminals) != 1 or terminals[0].status != report.status:
            message = "terminal report requires exactly one matching terminal attempt"
            raise ValueError(message)
        else:
            terminal_index = report.ramp.index(terminals[0])
            reason = terminals[0].reason
            if report.error != reason:
                message = "aggregate terminal reason must match its terminal attempt"
                raise ValueError(message)
            if (
                reason is None
                or any(
                    step.status != "completed" for step in report.ramp[:terminal_index]
                )
                or any(
                    step.status != "not_attempted" or step.reason != reason
                    for step in report.ramp[terminal_index + 1 :]
                )
            ):
                message = (
                    "invalid terminal ramp sequence: "
                    "later attempts must be not_attempted"
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
    if report.run_id is not None:
        _validate_executable_report(report)
    if report.ramp_kind != "none" and report.environment is not None:
        _validate_executable_ramp(report)


def _validate_artifact_scalar_types(report: RunReport) -> None:
    """Reject decoded scalar values outside their declared JSON domains.

    Pure in-memory validation remains independent from this path boundary.

    >>> invalid = RunReport(
    ...     Topology(1, 1, 1), status="failed", error=t.cast(str, {"x": 1})
    ... )
    >>> _validate_artifact_scalar_types(invalid)
    Traceback (most recent call last):
    ...
    ValueError: report error must be a string or None

    Parameters
    ----------
    report : RunReport
        Report decoded from a JSON artifact.

    Returns
    -------
    None
        After every rendered string and cleanup scalar has an exact type.

    Raises
    ------
    ValueError
        If a decoded scalar is outside its declared domain.
    """
    required_strings: list[tuple[str, object]] = [
        ("status", report.status),
        ("ramp_kind", report.ramp_kind),
    ]
    optional_strings: list[tuple[str, object]] = [
        ("run_id", report.run_id),
        ("lane", report.lane),
        ("mode", report.mode),
        ("failed_phase", report.failed_phase),
        ("error", report.error),
        ("scratch_path", report.scratch_path),
        ("socket_path", report.socket_path),
        ("progress_path", report.progress_path),
    ]
    for phase in report.phases:
        required_strings.extend(
            (("phase name", phase.name), ("phase status", phase.status))
        )
        optional_strings.extend(
            ("sample error", sample.error) for sample in phase.samples
        )
    required_strings.extend(
        ("process role", identity.role) for identity in report.processes
    )
    for step in report.ramp:
        required_strings.append(("ramp step status", step.status))
        optional_strings.extend(
            (
                ("ramp step reason", step.reason),
                ("ramp step run_id", step.run_id),
                ("ramp step report_path", step.report_path),
                ("ramp step scratch_path", step.scratch_path),
                ("ramp step socket_path", step.socket_path),
            )
        )
    for decision in (report.guard_decision, report.original_guard_decision):
        if decision is not None:
            required_strings.append(("guard kind", decision.kind))
            optional_strings.append(("guard rule", decision.rule))
    for label, value in required_strings:
        if not isinstance(value, str):
            message = f"report {label} must be a string"
            raise ValueError(message)  # noqa: TRY004
    for label, value in optional_strings:
        if value is not None and not isinstance(value, str):
            message = f"report {label} must be a string or None"
            raise ValueError(message)

    if type(report.maximum_completed) is not bool:
        message = "report maximum_completed must be a bool"
        raise ValueError(message)
    for phase in report.phases:
        for sample in phase.samples:
            for label, value in (
                ("accepted", sample.accepted),
                ("verified", sample.verified),
            ):
                if type(value) is not bool:
                    message = f"raw sample {label} must be a bool"
                    raise ValueError(message)
            for label, value in (
                ("duration_ns", sample.duration_ns),
                ("ordinal", sample.ordinal),
            ):
                if value is not None and type(value) is not int:
                    message = f"raw sample {label} must be an int or None"
                    raise ValueError(message)
        for observation in (*phase.warmup_observations, *phase.observations):
            if type(observation.verified) is not bool:
                message = "phase observation verified must be a bool"
                raise ValueError(message)

    cleanup = report.cleanup
    if type(cleanup.complete) is not bool:
        message = "cleanup complete must be a bool"
        raise ValueError(message)
    for label, value in (
        ("processes_absent", cleanup.processes_absent),
        ("socket_absent", cleanup.socket_absent),
        ("scratch_absent", cleanup.scratch_absent),
    ):
        if value is not None and type(value) is not bool:
            message = f"cleanup {label} must be a bool or None"
            raise ValueError(message)
    if any(not isinstance(error, str) for error in cleanup.errors):
        message = "cleanup errors must contain strings"
        raise ValueError(message)

    environment = report.environment
    if environment is not None:
        if not isinstance(environment.python_version, str):
            message = "environment python_version must be a string"
            raise ValueError(message)
        for label, value in (
            ("tmux_version", environment.tmux_version),
            ("git_revision", environment.git_revision),
        ):
            if value is not None and not isinstance(value, str):
                message = f"environment {label} must be a string or None"
                raise ValueError(message)
        if environment.cpu_count is not None and type(environment.cpu_count) is not int:
            message = "environment cpu_count must be an int or None"
            raise ValueError(message)
        if type(environment.seed) is not int:
            message = "environment seed must be an int"
            raise ValueError(message)
        if any(not isinstance(argument, str) for argument in environment.command_line):
            message = "environment command_line must contain strings"
            raise ValueError(message)


def _aggregate_ramp_cleanup(
    children: t.Sequence[tuple[Topology, CleanupReport]],
) -> CleanupReport:
    """Combine child cleanup evidence without collapsing independent facts.

    >>> cleanup = CleanupReport(
    ...     False, ("socket remains",), processes_absent=True,
    ...     socket_absent=False, scratch_absent=None,
    ... )
    >>> combined = _aggregate_ramp_cleanup(((Topology(1, 1, 1), cleanup),))
    >>> combined.errors
    ('1x1x1: socket remains',)
    >>> combined.processes_absent, combined.socket_absent, combined.scratch_absent
    (True, False, None)

    Parameters
    ----------
    children : collections.abc.Sequence[tuple[Topology, CleanupReport]]
        Attempted child shapes and their validated cleanup evidence.

    Returns
    -------
    CleanupReport
        Deterministic aggregate with shape-scoped errors and tri-state facts.
    """

    def aggregate_fact(attribute: str) -> bool | None:
        values = tuple(getattr(cleanup, attribute) for _shape, cleanup in children)
        if all(value is True for value in values):
            return True
        if any(value is False for value in values):
            return False
        return None

    return CleanupReport(
        complete=all(cleanup.complete is True for _shape, cleanup in children),
        errors=tuple(
            f"{shape}: {error}"
            for shape, cleanup in children
            for error in cleanup.errors
        ),
        processes_absent=aggregate_fact("processes_absent"),
        socket_absent=aggregate_fact("socket_absent"),
        scratch_absent=aggregate_fact("scratch_absent"),
    )


def validate_report_artifact(path: pathlib.Path) -> RunReport:
    """Load and validate one complete report artifact tree exactly once.

    Ramp children must use parent-relative paths beneath the aggregate's
    sibling ``<stem>.runs`` directory.  The pure :func:`validate_report`
    contract remains usable for in-memory checkpoints and fixtures.

    >>> with tempfile.TemporaryDirectory() as directory:
    ...     path = pathlib.Path(directory) / "report.json"
    ...     report = RunReport(
    ...         Topology(1, 1, 1), status="refused",
    ...         cleanup=CleanupReport(
    ...             True, processes_absent=True, socket_absent=True,
    ...             scratch_absent=True,
    ...         ),
    ...         run_id="run-7", lane="control", mode="async", warmup=0,
    ...         runs=1, failed_phase="preflight", error="predictive refusal",
    ...         guard_decision=GuardDecision(
    ...             False, "predictive_refusal", "pid_reserve", 2, 1, True,
    ...             HostSnapshot(),
    ...         ),
    ...     )
    ...     write_json_atomic(path, report)
    ...     validate_report_artifact(path).status
    'refused'

    Parameters
    ----------
    path : pathlib.Path
        Root JSON report to load and validate.

    Returns
    -------
    RunReport
        Validated root report.

    Raises
    ------
    ValueError
        If the root or any referenced child is missing, malformed, unsafe, or
        inconsistent with the aggregate.
    """
    try:
        aggregate_path = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        message = f"report is missing or inaccessible: {path}"
        raise ValueError(message) from error
    aggregate = load_run_report(aggregate_path)
    _validate_artifact_scalar_types(aggregate)
    validate_report(aggregate)
    if aggregate.ramp_kind == "none":
        if aggregate.status != "in_progress" and aggregate.run_id is None:
            message = "terminal artifact requires executable run identity"
            raise ValueError(message)
        return aggregate

    if aggregate.lane not in {lane.value for lane in EngineLane}:
        message = "ramp aggregate requires a valid lane"
        raise ValueError(message)
    if aggregate.mode not in {mode.value for mode in ExecutionMode}:
        message = "ramp aggregate requires a valid mode"
        raise ValueError(message)
    if type(aggregate.runs) is not int or aggregate.runs <= 0:
        message = "ramp aggregate requires positive runs"
        raise ValueError(message)
    if type(aggregate.warmup) is not int or aggregate.warmup < 0:
        message = "ramp aggregate requires nonnegative warmup"
        raise ValueError(message)
    if aggregate.environment is None or type(aggregate.environment.seed) is not int:
        message = "ramp aggregate requires an integer seed"
        raise ValueError(message)

    for step in aggregate.ramp:
        if step.status == "not_attempted" and any(
            value is not None
            for value in (
                step.run_id,
                step.report_path,
                step.scratch_path,
                step.socket_path,
            )
        ):
            message = (
                "not_attempted ramp step cannot carry a child artifact or "
                "resource identity"
            )
            raise ValueError(message)
    attempted_steps = tuple(
        step for step in aggregate.ramp if step.status != "not_attempted"
    )
    resolved_child_root: pathlib.Path | None = None
    if attempted_steps:
        child_root = aggregate_path.with_name(f"{aggregate_path.stem}.runs")
        try:
            resolved_child_root = child_root.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            message = f"ramp child directory is missing: {child_root.name}"
            raise ValueError(message) from error
        if child_root.is_symlink() or not resolved_child_root.is_dir():
            message = "ramp child directory must be a real sibling directory"
            raise ValueError(message)

    seen: set[pathlib.Path] = set()
    loaded_children: list[tuple[RampStep, RunReport]] = []
    for step_index, step in enumerate(aggregate.ramp):
        if step.status == "not_attempted":
            continue
        if not isinstance(step.report_path, str) or not step.report_path:
            message = "attempted ramp step requires a string child report_path"
            raise ValueError(message)
        serialized = pathlib.Path(step.report_path)
        if serialized.is_absolute() or ".." in serialized.parts:
            message = "ramp child report path escapes the sibling ramp runs directory"
            raise ValueError(message)
        candidate = aggregate_path.parent / serialized
        try:
            child_path = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            message = f"ramp child report is missing: {step.report_path}"
            raise ValueError(message) from error
        if child_path == aggregate_path:
            message = "artifact cycle detected"
            raise ValueError(message)
        assert resolved_child_root is not None
        if not child_path.is_relative_to(resolved_child_root):
            message = (
                "ramp child report path is outside the sibling ramp runs directory"
            )
            raise ValueError(message)
        if child_path in seen:
            message = "duplicate canonical ramp child report path"
            raise ValueError(message)
        seen.add(child_path)
        child = load_run_report(child_path)
        _validate_artifact_scalar_types(child)
        validate_report(child)
        if child.ramp_kind != "none":
            message = "nested ramp child reports are not allowed"
            raise ValueError(message)
        if child.status not in {"completed", "refused", "failed", "cutoff"}:
            message = "ramp child report must be terminal"
            raise ValueError(message)
        if child.requested_topology != step.shape:
            message = "ramp child topology differs from its aggregate step"
            raise ValueError(message)
        if child.status != step.status:
            message = "ramp child status differs from its aggregate step"
            raise ValueError(message)
        if child.error != step.reason:
            message = "ramp child reason differs from its aggregate step"
            raise ValueError(message)
        for attribute in ("run_id", "scratch_path", "socket_path"):
            if getattr(child, attribute) != getattr(step, attribute):
                message = f"ramp child {attribute} differs from its aggregate step"
                raise ValueError(message)
        for attribute in ("lane", "mode", "runs", "warmup"):
            if getattr(child, attribute) != getattr(aggregate, attribute):
                message = f"ramp child {attribute} differs from its aggregate"
                raise ValueError(message)
        expected_seed = aggregate.environment.seed + step_index
        if child.environment is None or child.environment.seed != expected_seed:
            message = "ramp child seed differs from its aggregate step"
            raise ValueError(message)
        loaded_children.append((step, child))

    completed_children = tuple(
        child for step, child in loaded_children if step.status == "completed"
    )
    expected_observed = (
        completed_children[-1].observed_topology if completed_children else None
    )
    if aggregate.observed_topology != expected_observed:
        message = "aggregate observed topology differs from completed child evidence"
        raise ValueError(message)
    expected_cleanup = _aggregate_ramp_cleanup(
        tuple((step.shape, child.cleanup) for step, child in loaded_children)
    )
    if aggregate.cleanup != expected_cleanup:
        message = "aggregate cleanup differs from child cleanup evidence"
        raise ValueError(message)
    return aggregate


def _reachable_group_signatures(
    strategy_names: tuple[str, ...],
    *,
    warmup: int,
    runs: int,
    seed: int,
) -> frozenset[tuple[tuple[str, str, int, int], ...]]:
    """Return report snapshots reachable at durable group boundaries.

    >>> signatures = _reachable_group_signatures(
    ...     ("a", "b"), warmup=1, runs=1, seed=1
    ... )
    >>> (("b", "in_progress", 0, 0),) in signatures
    True

    Parameters
    ----------
    strategy_names : tuple[str, ...]
        Applicable strategies in production mapping order.
    warmup : int
        Untimed calls per strategy.
    runs : int
        Timed calls per strategy.
    seed : int
        Exact group schedule seed.

    Returns
    -------
    frozenset[tuple[tuple[str, str, int, int], ...]]
        Phase name, status, warmup count, and timed count for every snapshot
        reachable before or after one scheduled invocation. Failed variants
        represent an exception attributed to the current strategy.
    """
    states: dict[str, tuple[str, int, int]] = {}
    reachable: set[tuple[tuple[str, str, int, int], ...]] = set()

    def snapshot(strategy: str) -> tuple[tuple[str, str, int, int], ...]:
        completed = tuple(
            (name, status, warmup_count, timed_count)
            for name, (status, warmup_count, timed_count) in states.items()
            if status == "completed"
        )
        status, warmup_count, timed_count = states[strategy]
        active = (
            ()
            if status == "completed"
            else ((strategy, status, warmup_count, timed_count),)
        )
        if all(state[0] == "completed" for state in states.values()) and len(
            states
        ) == len(strategy_names):
            return tuple((name, *states[name]) for name in strategy_names)
        return (*completed, *active)

    def retain(
        current: str,
        observed: tuple[tuple[str, str, int, int], ...],
    ) -> None:
        reachable.add(observed)
        completed = tuple(
            (name, status, warmup_count, timed_count)
            for name, (status, warmup_count, timed_count) in states.items()
            if name != current and status == "completed"
        )
        _status, warmup_count, timed_count = states[current]
        reachable.add((*completed, (current, "failed", warmup_count, timed_count)))

    for stage, strategy, ordinal in _repeatable_schedule(
        strategy_names,
        warmup=warmup,
        runs=runs,
        seed=seed,
    ):
        states.setdefault(strategy, ("in_progress", 0, 0))
        retain(strategy, snapshot(strategy))
        status, warmup_count, timed_count = states[strategy]
        if stage == "warmup":
            warmup_count = ordinal + 1
        else:
            timed_count = ordinal + 1
            if ordinal == runs - 1:
                status = "completed"
        states[strategy] = (status, warmup_count, timed_count)
        retain(strategy, snapshot(strategy))
    return frozenset(reachable)


def _interleaved_suffix_is_reachable(
    report: RunReport,
    group_index: int,
    suffix: tuple[PhaseReport, ...],
) -> bool:
    """Return whether an executable suffix occurs in its exact seeded schedule.

    The non-async-control wait group ends with one synthetic disposition after
    capture polling completes.

    >>> topology = Topology(1, 1, 1)
    >>> capture = PhaseReport(
    ...     "wait.capture-poll", topology, topology,
    ...     samples=(RawSample(1, True),), status="completed", runs=1,
    ... )
    >>> disposition = PhaseReport(
    ...     "wait.control-stream", topology, topology,
    ...     status="not_applicable", runs=1,
    ... )
    >>> report = RunReport(
    ...     topology, lane="subprocess", mode="sync", warmup=0, runs=1,
    ...     environment=EnvironmentReport("3.10", None, 1, 11, ("run",), None),
    ... )
    >>> _interleaved_suffix_is_reachable(
    ...     report, 3, (capture, disposition)
    ... )
    True
    """
    assert report.environment is not None
    assert report.warmup is not None
    assert report.runs is not None
    group = _RUNNER_PHASE_GROUPS[group_index]
    strategy_names: tuple[str, ...]
    if group == _RUNNER_PHASE_GROUPS[3] and not (
        report.lane == EngineLane.CONTROL.value
        and report.mode == ExecutionMode.ASYNC.value
    ):
        strategy_names = ("wait.capture-poll",)
        if suffix and suffix[-1].name == "wait.control-stream":
            disposition = suffix[-1]
            if (
                disposition.status != "not_applicable"
                or disposition.requested_topology != report.requested_topology
                or disposition.observed_topology != report.requested_topology
                or disposition.warmup != report.warmup
                or disposition.runs != report.runs
                or disposition.samples
                or disposition.summary is not None
                or disposition.warmup_observations
                or disposition.observations
            ):
                return False
            suffix = suffix[:-1]
    else:
        strategy_names = group
    observed = tuple(
        (
            phase.name,
            phase.status,
            len(phase.warmup_observations),
            len(phase.samples),
        )
        for phase in suffix
    )
    return observed in _reachable_group_signatures(
        strategy_names,
        warmup=report.warmup,
        runs=report.runs,
        seed=report.environment.seed + group_index - 2,
    )


def _validate_executable_report(report: RunReport) -> None:
    """Validate the stronger contract for a supervisor-owned scenario.

    >>> refused = RunReport(
    ...     Topology(1, 1, 1), status="refused", cleanup=CleanupReport(
    ...         True, processes_absent=True, socket_absent=True,
    ...         scratch_absent=True,
    ...     ), run_id="run-7", lane="control", mode="async", warmup=0,
    ...     runs=1, failed_phase="preflight", error="predictive refusal",
    ...     guard_decision=GuardDecision(
    ...         False, "predictive_refusal", "pid_reserve", 2, 1, True,
    ...         HostSnapshot(),
    ...     ),
    ... )
    >>> _validate_executable_report(refused)

    Parameters
    ----------
    report : RunReport
        Single-scenario report carrying a non-null run identity.

    Returns
    -------
    None
        After exact metadata, phase, count, and cleanup checks pass.

    Raises
    ------
    ValueError
        If executable evidence is incomplete or contradictory.
    """
    if not _is_terminal_safe_component(report.run_id):
        message = "executable report requires a terminal-safe run_id"
        raise ValueError(message)
    if report.lane not in {lane.value for lane in EngineLane}:
        message = "executable report requires a valid lane"
        raise ValueError(message)
    if report.mode not in {mode.value for mode in ExecutionMode}:
        message = "executable report requires a valid mode"
        raise ValueError(message)
    if (
        type(report.warmup) is not int
        or report.warmup < 0
        or type(report.runs) is not int
        or report.runs <= 0
    ):
        message = "executable report requires nonnegative warmup and positive runs"
        raise ValueError(message)
    if report.ramp_kind != "none":
        message = "one executable scenario cannot also be a ramp report"
        raise ValueError(message)
    if report.status in {"completed", "refused", "cutoff"} and (
        report.cleanup.processes_absent is not True
        or report.cleanup.socket_absent is not True
        or report.cleanup.scratch_absent is not True
    ):
        message = "terminal executable report requires exact cleanup evidence"
        raise ValueError(message)
    for identity in report.processes:
        if (
            not identity.role
            or type(identity.pid) is not int
            or identity.pid <= 0
            or type(identity.start_time) is not int
            or identity.start_time <= 0
        ):
            message = "executable report has an invalid process identity"
            raise ValueError(message)
    ownership = report.socket_ownership
    if ownership is not None:
        try:
            _validate_socket_ownership(ownership)
        except ValueError as error:
            message = "executable report has an invalid socket ownership capability"
            raise ValueError(message) from error
        if ownership.process not in report.processes:
            message = "executable report has an invalid socket ownership capability"
            raise ValueError(message)
    if report.status == "refused":
        if (
            report.failed_phase != "preflight"
            or not report.error
            or report.observed_topology is not None
            or report.phases
            or report.processes
            or report.socket_ownership is not None
            or report.scratch_path is not None
            or report.socket_path is not None
            or report.progress_path is not None
            or report.guard_decision is None
            or report.guard_decision.kind != "predictive_refusal"
            or report.guard_decision.allowed
        ):
            message = "refused executable report contains live-run evidence"
            raise ValueError(message)
        return
    if report.environment is None:
        message = "attempted executable report requires environment evidence"
        raise ValueError(message)
    if type(report.environment.seed) is not int:
        message = "attempted executable report requires an integer schedule seed"
        raise ValueError(message)
    if not report.scratch_path or not report.socket_path or not report.progress_path:
        message = "attempted executable report requires owned resource paths"
        raise ValueError(message)
    server_identities = tuple(
        identity for identity in report.processes if identity.role == "server"
    )
    if (
        report.status == "completed" or (report.cleanup.complete and server_identities)
    ) and (
        ownership is None
        or len(server_identities) != 1
        or ownership.process != server_identities[0]
    ):
        message = "attempted executable report lacks exact socket ownership"
        raise ValueError(message)
    terminal_unsuccessful = report.status in {"failed", "cutoff"}
    phase_names = tuple(phase.name for phase in report.phases)
    expected_graph = runner_phases(orm=report.orm)
    canonical_prefix = phase_names == expected_graph[: len(phase_names)]
    interleaved_candidate = False
    interleaved_reachable = False
    if terminal_unsuccessful:
        groups = runner_phase_groups(orm=report.orm)
        for group_index, group in enumerate(groups):
            if len(group) <= 1:
                continue
            prior_names = tuple(
                name for prior_group in groups[:group_index] for name in prior_group
            )
            active_suffix = report.phases[len(prior_names) :]
            active_names = tuple(phase.name for phase in active_suffix)
            if (
                phase_names[: len(prior_names)] != prior_names
                or not active_names
                or len(set(active_names)) != len(active_names)
                or not all(name in group for name in active_names)
            ):
                continue
            interleaved_candidate = True
            if _interleaved_suffix_is_reachable(
                report,
                group_index,
                active_suffix,
            ):
                interleaved_reachable = True
                break
    if interleaved_candidate and not interleaved_reachable:
        message = (
            "attempted executable report lacks a reachable seeded strategy boundary"
        )
        raise ValueError(message)
    if not canonical_prefix and not interleaved_reachable:
        message = "attempted executable report phases must be a runner phase prefix"
        raise ValueError(message)
    if terminal_unsuccessful and (not report.failed_phase or not report.error):
        message = "terminal unsuccessful report requires phase and error"
        raise ValueError(message)
    if report.status == "completed":
        if report.failed_phase is not None or report.error is not None:
            message = "completed report cannot carry a terminal failure"
            raise ValueError(message)
        if report.observed_topology != report.requested_topology:
            message = "completed report requires exact observed topology"
            raise ValueError(message)
        expected_phases = runner_phases(orm=report.orm)
        if tuple(phase.name for phase in report.phases) != expected_phases:
            message = "completed report has an incomplete phase graph"
            raise ValueError(message)
    phases = {phase.name: phase for phase in report.phases}
    setup = phases.get("setup")
    if (
        setup is not None
        and setup.status == "completed"
        and (
            setup.warmup != 0
            or setup.runs != 1
            or len(setup.samples) != 1
            or len(setup.observations) != 1
            or setup.warmup_observations
            or setup.summary is not None
            or not setup.samples[0].accepted
            or not setup.samples[0].verified
            or not setup.observations[0].verified
            or setup.samples[0].ordinal != 0
            or setup.observations[0].ordinal != 0
            or setup.samples[0].strategy != "setup"
            or setup.observations[0].strategy != "setup"
            or setup.samples[0].duration_ns != setup.observations[0].duration_ns
        )
    ):
        message = "setup must remain one unsummarized fresh-server observation"
        raise ValueError(message)
    stabilization = phases.get("stabilization")
    if (
        stabilization is not None
        and stabilization.status == "completed"
        and (
            stabilization.samples
            or stabilization.summary is not None
            or len(stabilization.observations) != 1
            or stabilization.observations[0].pane_count
            != report.requested_topology.panes
        )
    ):
        message = "stabilization requires one exact untimed topology observation"
        raise ValueError(message)
    control_applicable = (
        report.lane == EngineLane.CONTROL.value
        and report.mode == ExecutionMode.ASYNC.value
    )
    control_phase = phases.get("wait.control-stream")
    if control_phase is not None:
        if not control_applicable and control_phase.status != "not_applicable":
            message = "control-stream must be not_applicable outside async control"
            raise ValueError(message)
        if (
            control_applicable
            and report.status == "completed"
            and control_phase.status != "completed"
        ):
            message = "async control report requires control-stream evidence"
            raise ValueError(message)
    elif report.status == "completed":
        message = "completed report is missing control-stream disposition"
        raise ValueError(message)
    active = tuple(
        phase for phase in report.phases if phase.status in {"failed", "in_progress"}
    )
    if terminal_unsuccessful and len(active) > 1:
        message = "terminal unsuccessful report has multiple active phases"
        raise ValueError(message)
    failed_rows = tuple(phase for phase in active if phase.status == "failed")
    if failed_rows and report.failed_phase != failed_rows[0].name:
        message = "failed_phase must match the active failed phase"
        raise ValueError(message)
    repeatable_names = set(runner_repeatable_phases(orm=report.orm))
    if control_applicable:
        repeatable_names.add("wait.control-stream")
    for name in repeatable_names:
        phase = phases.get(name)
        if phase is None:
            continue
        if phase.status == "not_applicable":
            if name != "wait.control-stream" or control_applicable:
                message = f"repeatable phase {name} cannot be not_applicable"
                raise ValueError(message)
            continue
        if phase.warmup != report.warmup or phase.runs != report.runs:
            message = f"repeatable phase {name} count declaration differs from report"
            raise ValueError(message)
        if phase.status == "completed":
            if (
                len(phase.warmup_observations) != report.warmup
                or len(phase.samples) != report.runs
                or len(phase.observations) != report.runs
                or phase.summary is None
                or phase.summary.get("count") != report.runs
            ):
                message = f"repeatable phase {name} has incomplete raw evidence"
                raise ValueError(message)
        elif phase.status in {"failed", "in_progress"}:
            if (
                len(phase.warmup_observations) > report.warmup
                or len(phase.samples) > report.runs
                or len(phase.observations) > report.runs
                or phase.summary is not None
                or (phase.samples and len(phase.warmup_observations) != report.warmup)
            ):
                message = f"active repeatable phase {name} has invalid partial evidence"
                raise ValueError(message)
        else:
            message = f"repeatable phase {name} has an invalid status"
            raise ValueError(message)
        samples_by_ordinal = {sample.ordinal: sample for sample in phase.samples}
        for observation in phase.observations:
            sample = samples_by_ordinal.get(observation.ordinal)
            if (
                sample is None
                or sample.strategy != name
                or sample.duration_ns != observation.duration_ns
                or not sample.accepted
                or not sample.verified
            ):
                message = f"phase {name} observation does not match raw sample"
                raise ValueError(message)
    topology = report.requested_topology
    for kind, expected in (
        ("sessions", topology.sessions),
        ("windows", topology.windows),
        ("panes", topology.panes),
    ):
        enumeration = phases.get(f"enumeration.{kind}")
        if (
            enumeration is not None
            and enumeration.status == "completed"
            and any(
                observation.row_count != expected
                for observation in enumeration.observations
            )
        ):
            message = f"enumeration.{kind} row count differs from topology"
            raise ValueError(message)
    for strategy in ("serial", "batched"):
        capture = phases.get(f"capture.{strategy}")
        if (
            capture is not None
            and capture.status == "completed"
            and any(
                observation.pane_count != topology.panes
                or observation.line_count is None
                or observation.line_count <= 0
                or observation.byte_count is None
                or observation.byte_count <= 0
                for observation in capture.observations
            )
        ):
            message = f"capture.{strategy} count evidence is incomplete"
            raise ValueError(message)
    for phase in report.phases:
        if (
            phase.name.startswith("search.")
            and phase.status == "completed"
            and any(
                observation.matched_count != 1
                or observation.scanned_count is None
                or observation.scanned_count <= 0
                for observation in phase.observations
            )
        ):
            message = f"{phase.name} search count evidence is incomplete"
            raise ValueError(message)
    if report.status != "completed":
        return
    if control_applicable and control_phase is not None:
        if control_phase.status != "completed":
            message = "async control report requires control-stream evidence"
            raise ValueError(message)
    elif control_phase is not None and control_phase.status != "not_applicable":
        message = "control-stream must be not_applicable outside async control"
        raise ValueError(message)
    for name in runner_repeatable_phases(orm=report.orm):
        phase = phases[name]
        if phase.status != "completed":
            message = f"repeatable phase {name} has incomplete raw evidence"
            raise ValueError(message)
    if control_applicable and phases["wait.control-stream"].status != "completed":
        message = "async control report requires control-stream evidence"
        raise ValueError(message)


def _validate_executable_ramp(report: RunReport) -> None:
    """Require fresh per-shape identities and paths in a rendered ramp.

    >>> shape = Topology(1, 1, 1)
    >>> ramp = RunReport(
    ...     shape, status="completed", cleanup=CleanupReport(
    ...         True, processes_absent=True, socket_absent=True,
    ...         scratch_absent=True,
    ...     ), ramp_kind="custom", requested_shapes=(shape,),
    ...     ramp=(RampStep(shape, "completed", run_id="run-1",
    ...                    report_path="one.json", scratch_path="one",
    ...                    socket_path="one/sock"),),
    ...     environment=EnvironmentReport("3.10", None, 1, 11, ("ramp",), None),
    ... )
    >>> _validate_executable_ramp(ramp)
    """
    if report.status in {"completed", "refused", "cutoff"} and (
        report.cleanup.processes_absent is not True
        or report.cleanup.socket_absent is not True
        or report.cleanup.scratch_absent is not True
    ):
        message = "terminal ramp requires exact cleanup evidence"
        raise ValueError(message)
    if (
        not report.requested_shapes
        or report.requested_topology != report.requested_shapes[-1]
    ):
        message = "ramp requested topology must remain the declared final shape"
        raise ValueError(message)
    attempted = [step for step in report.ramp if step.status != "not_attempted"]
    for attribute in ("run_id", "report_path"):
        values = [getattr(step, attribute) for step in attempted]
        if any(not value for value in values) or len(set(values)) != len(values):
            message = f"ramp attempts require fresh unique {attribute} values"
            raise ValueError(message)
    resource_attempts = [step for step in attempted if step.status != "refused"]
    for attribute in ("scratch_path", "socket_path"):
        values = [getattr(step, attribute) for step in resource_attempts]
        if any(not value for value in values) or len(set(values)) != len(values):
            message = f"ramp attempts require fresh unique {attribute} values"
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
    capability_error = _pidfd_capability_error()
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
                "pidfd_capability": {
                    "available": capability_error is None,
                    "reason": capability_error,
                },
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
    capability = t.cast(dict[str, object], payload["pidfd_capability"])
    table.add_row("Stable signaling", str(capability["available"]))
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


def _pidfd_api_error() -> str | None:
    """Return why the interpreter cannot expose Linux stable signaling.

    >>> error = _pidfd_api_error()
    >>> error is None or "pidfd" in error
    True

    Returns
    -------
    str | None
        ``None`` only when both required Linux pidfd APIs are callable.
    """
    if platform.system() != "Linux":
        return "pidfd signaling requires Linux"
    if not callable(getattr(os, "pidfd_open", None)):
        return (
            "os.pidfd_open is unavailable, so exact process identity cannot "
            "be guaranteed. Free-threaded CPython builds are the usual cause; "
            "check with python -c 'import sysconfig; "
            'print(sysconfig.get_config_var("Py_GIL_DISABLED"))\'. '
            "Select an interpreter that exposes pidfd, for example "
            "UV_PYTHON=/path/to/cpython uv run ..."
        )
    if not callable(getattr(signal, "pidfd_send_signal", None)):
        return "signal.pidfd_send_signal is unavailable"
    if not callable(getattr(signal, "pthread_sigmask", None)):
        return "signal.pthread_sigmask is unavailable for the pidfd handoff"
    return None


def _pidfd_capability_error() -> str | None:
    """Probe whether stable signaling actually works for the current process.

    >>> error = _pidfd_capability_error()
    >>> error is None or "pidfd" in error
    True

    Returns
    -------
    str | None
        ``None`` only after opening a self pidfd and sending signal zero.
    """
    api_error = _pidfd_api_error()
    if api_error is not None:
        return api_error
    try:
        descriptor = os.pidfd_open(os.getpid(), 0)
    except Exception as error:  # noqa: BLE001
        return f"os.pidfd_open self-probe failed: {type(error).__name__}: {error}"
    failure: str | None = None
    try:
        signal.pidfd_send_signal(descriptor, 0, None, 0)
    except Exception as error:  # noqa: BLE001
        failure = (
            "signal.pidfd_send_signal signal-zero self-probe failed: "
            f"{type(error).__name__}: {error}"
        )
    finally:
        try:
            os.close(descriptor)
        except OSError as error:
            if failure is None:
                failure = (
                    "pidfd stable-signaling probe close failed: "
                    f"{type(error).__name__}: {error}"
                )
    return failure


@dataclasses.dataclass(frozen=True)
class _PidfdHandle:
    """One stable kernel handle bound to an exact recorded identity.

    Attributes
    ----------
    identity : ProcessIdentity
        Identity verified immediately before and after opening the handle.
    descriptor : int
        Owned pidfd closed by :class:`_PidfdRegistry`.

    Examples
    --------
    >>> _PidfdHandle(ProcessIdentity("worker", 2, 3), 4).descriptor
    4
    """

    identity: ProcessIdentity
    descriptor: int


class _PidfdRegistry:
    """Retain and signal stable handles without check-to-signal PID races.

    >>> registry = _PidfdRegistry()
    >>> current = _record_process("self", os.getpid())
    >>> registry.retain(current)
    True
    >>> registry.retained == (current,)
    True
    >>> registry.close()

    Parameters
    ----------
    _start_time_reader : collections.abc.Callable | None
        Private deterministic test seam for the two identity reads.
    """

    def __init__(
        self,
        *,
        _start_time_reader: cabc.Callable[[int], int | None] | None = None,
    ) -> None:
        """Create an empty registry after checking platform capability.

        >>> registry = _PidfdRegistry()
        >>> registry.retained
        ()
        >>> registry.close()
        """
        capability_error = _pidfd_api_error()
        if capability_error is not None:
            raise RuntimeError(capability_error)
        self._start_time_reader = _start_time_reader or _process_start_time
        self._handles: dict[tuple[int, int], _PidfdHandle] = {}
        self.errors: list[str] = []

    @property
    def retained(self) -> tuple[ProcessIdentity, ...]:
        """Return identities with live registry-owned handles.

        >>> registry = _PidfdRegistry()
        >>> registry.retained
        ()
        >>> registry.close()
        """
        return tuple(handle.identity for handle in self._handles.values())

    def retain(self, identity: ProcessIdentity) -> bool:
        """Bind one identity across pre-open and post-open start-time checks.

        >>> registry = _PidfdRegistry()
        >>> registry.retain(dataclasses.replace(
        ...     _record_process("self", os.getpid()), start_time=-1
        ... ))
        False
        >>> registry.close()

        Parameters
        ----------
        identity : ProcessIdentity
            Exact PID and start time learned from owned progress.

        Returns
        -------
        bool
            Whether a stable handle is retained for the exact identity.
        """
        key = (identity.pid, identity.start_time)
        if key in self._handles:
            return True
        if self._start_time_reader(identity.pid) != identity.start_time:
            return False
        try:
            descriptor = os.pidfd_open(identity.pid, 0)
        except OSError as error:
            self.errors.append(
                f"{identity.role} pid {identity.pid} pidfd_open: "
                f"{type(error).__name__}: {error}"
            )
            return False
        if self._start_time_reader(identity.pid) != identity.start_time:
            os.close(descriptor)
            return False
        self._handles[key] = _PidfdHandle(identity, descriptor)
        return True

    def retain_many(self, identities: t.Iterable[ProcessIdentity]) -> None:
        """Attempt to retain every newly learned identity.

        >>> registry = _PidfdRegistry()
        >>> registry.retain_many(())
        >>> registry.retained
        ()
        >>> registry.close()
        """
        for identity in identities:
            self.retain(identity)

    def signal(self, identity: ProcessIdentity, number: signal.Signals) -> bool:
        """Signal an exact retained handle without consulting its numeric PID.

        >>> registry = _PidfdRegistry()
        >>> registry.signal(ProcessIdentity("absent", 2, 3), signal.SIGTERM)
        False
        >>> registry.close()

        Parameters
        ----------
        identity : ProcessIdentity
            Previously retained exact identity.
        number : signal.Signals
            Signal delivered through the stable pidfd.

        Returns
        -------
        bool
            Whether the kernel accepted the pidfd signal.
        """
        handle = self._handles.get((identity.pid, identity.start_time))
        if handle is None:
            return False
        try:
            signal.pidfd_send_signal(
                handle.descriptor,
                number,
                None,
                0,
            )
        except ProcessLookupError:
            return False
        except OSError as error:
            self.errors.append(
                f"{identity.role} pid {identity.pid} pidfd signal {number}: "
                f"{type(error).__name__}: {error}"
            )
            return False
        return True

    def close(self) -> None:
        """Close every retained descriptor exactly once.

        >>> registry = _PidfdRegistry()
        >>> registry.close()
        >>> registry.close()
        """
        handles = tuple(self._handles.values())
        self._handles.clear()
        for handle in handles:
            os.close(handle.descriptor)


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
    try:
        registry = _PidfdRegistry()
    except RuntimeError as error:
        return CleanupReport(
            complete=False,
            errors=(str(error),),
            processes_absent=not process_identity_matches(identity),
        )
    try:
        registry.retain(identity)
        process.poll()
        if process.returncode is None:
            registry.signal(identity, signal.SIGTERM)
            try:
                process.wait(timeout=grace_s)
            except subprocess.TimeoutExpired:
                registry.signal(identity, signal.SIGKILL)
                try:
                    process.wait(timeout=grace_s)
                except subprocess.TimeoutExpired:
                    errors.append(f"{identity.role} pid {identity.pid} was not reaped")
        errors.extend(registry.errors)
    finally:
        registry.close()
    if process_identity_matches(identity):
        errors.append(
            f"{identity.role} pid {identity.pid} with start time "
            f"{identity.start_time} remains"
        )
    return CleanupReport(
        complete=not errors,
        errors=tuple(errors),
        processes_absent=not process_identity_matches(identity),
    )


def _socket_identity(socket_path: pathlib.Path) -> SocketIdentity:
    """Return the exact same-user Unix-socket identity from ``lstat``.

    Parameters
    ----------
    socket_path : pathlib.Path
        Socket path inside the run's private directory.

    Returns
    -------
    SocketIdentity
        Device, inode, owner, and mode from one non-following stat.

    Raises
    ------
    OSError
        If the path is absent, replaced by another file type, or not same-user.
    """
    status = socket_path.lstat()
    if not stat.S_ISSOCK(status.st_mode) or status.st_uid != os.getuid():
        message = f"configured socket is not an owned Unix socket: {socket_path}"
        raise OSError(message)
    return SocketIdentity(
        st_dev=status.st_dev,
        st_ino=status.st_ino,
        st_uid=status.st_uid,
        st_mode=status.st_mode,
        st_mtime_ns=status.st_mtime_ns,
    )


def _query_exact_socket_owner(
    socket_path: pathlib.Path,
    *,
    timeout_s: float,
) -> ProcessIdentity:
    """Boundedly query one exact tmux socket for its current server identity.

    Examples
    --------
    >>> with tempfile.TemporaryDirectory() as directory:
    ...     path = pathlib.Path(directory) / "tmux.sock"
    ...     _ = subprocess.run(
    ...         ("tmux", "-S", str(path), "new-session", "-d", "-s", "query"),
    ...         check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ...     )
    ...     identity = _query_exact_socket_owner(path, timeout_s=1.0)
    ...     _ = subprocess.run(
    ...         ("tmux", "-S", str(path), "kill-server"), check=True,
    ...         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ...     )
    ...     identity.role
    'server'

    Parameters
    ----------
    socket_path : pathlib.Path
        Exact socket path to query without inherited tmux coordinates.
    timeout_s : float
        Maximum query duration.

    Returns
    -------
    ProcessIdentity
        Current tmux PID with a verified procfs start time.

    Raises
    ------
    RuntimeError
        If the query times out, fails, or does not identify a live process.
    """
    environment = os.environ.copy()
    environment.pop("TMUX", None)
    environment.pop("TMUX_PANE", None)
    try:
        result = subprocess.run(
            (
                "tmux",
                "-S",
                str(socket_path),
                "display-message",
                "-p",
                "#{pid}",
            ),
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as error:
        message = "exact socket server identity query timed out"
        raise RuntimeError(message) from error
    except OSError as error:
        message = f"exact socket server identity query: {type(error).__name__}: {error}"
        raise RuntimeError(message) from error
    if result.returncode != 0:
        detail = result.stderr.strip()
        suffix = f": {detail}" if detail else ""
        message = (
            f"exact socket server identity query exited {result.returncode}{suffix}"
        )
        raise RuntimeError(message)
    try:
        identity = _record_process("server", int(result.stdout.strip()))
    except (RuntimeError, ValueError) as error:
        message = f"exact socket server identity query: {type(error).__name__}: {error}"
        raise RuntimeError(message) from error
    if not process_identity_matches(identity):
        message = "exact socket server identity changed after query"
        raise RuntimeError(message)
    return identity


def _capture_socket_ownership(
    socket_path: pathlib.Path,
    *,
    timeout_s: float,
) -> _SocketOwnership:
    """Capture one immutable process/socket capability around an owner query.

    The socket lives in a mode-0700 run directory. Two ``lstat`` calls bind the
    read-only tmux owner query to one inode before the capability is published.

    Examples
    --------
    >>> with tempfile.TemporaryDirectory() as directory:
    ...     path = pathlib.Path(directory) / "tmux.sock"
    ...     _ = subprocess.run(
    ...         ("tmux", "-S", str(path), "new-session", "-d", "-s", "capture"),
    ...         check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ...     )
    ...     ownership = _capture_socket_ownership(path, timeout_s=1.0)
    ...     _ = subprocess.run(
    ...         ("tmux", "-S", str(path), "kill-server"), check=True,
    ...         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ...     )
    ...     ownership.process.role, stat.S_ISSOCK(ownership.socket.st_mode)
    ('server', True)

    Parameters
    ----------
    socket_path : pathlib.Path
        Newly established exact tmux socket.
    timeout_s : float
        Maximum owner-query duration.

    Returns
    -------
    _SocketOwnership
        Process and socket identities that matched throughout capture.

    Raises
    ------
    RuntimeError
        If the path or process changes during capture.
    OSError
        If private-directory or socket ownership cannot be verified.
    """
    _verify_private_directory_mode(socket_path.parent)
    before = _socket_identity(socket_path)
    process = _query_exact_socket_owner(socket_path, timeout_s=timeout_s)
    after = _socket_identity(socket_path)
    if not before.matches(after) or not process_identity_matches(process):
        message = "exact socket ownership changed during capture"
        raise RuntimeError(message)
    return _SocketOwnership(process=process, socket=before)


def _kill_exact_tmux_socket(
    socket_path: pathlib.Path,
    *,
    timeout_s: float,
    process_handles: _PidfdRegistry,
    server_identity: ProcessIdentity | None = None,
    socket_ownership: _SocketOwnership | None = None,
) -> tuple[str, ...]:
    """Boundedly clean only the server/socket pair captured at establishment.

    >>> registry = _PidfdRegistry()
    >>> _kill_exact_tmux_socket(
    ...     pathlib.Path("missing.sock"), timeout_s=0.01,
    ...     process_handles=registry,
    ... )
    ()
    >>> registry.close()

    An observed pathname mismatch fails closed. The original process is killed
    only through its retained pidfd, while the replacement inode is preserved.
    A same-user pathname race cannot be made atomic with ``unlink``; mode-0700
    parent ownership and repeated identity checks bound the supported contract.

    Parameters
    ----------
    socket_path : pathlib.Path
        Exact isolated socket owned by one benchmark run.
    timeout_s : float
        Maximum wait for the helper and each stable-handle escalation.
    process_handles : _PidfdRegistry
        Existing registry that retained the server when its identity was learned.
    server_identity : ProcessIdentity | None
        Exact original server identity learned from process progress.
    socket_ownership : _SocketOwnership | None
        Capability captured while the owned tmux server established the socket.

    Returns
    -------
    tuple[str, ...]
        Empty only when the captured server and socket are absent afterward.

    Raises
    ------
    ValueError
        If the timeout is not positive.
    """
    if timeout_s <= 0:
        message = "exact socket cleanup timeout must be positive"
        raise ValueError(message)
    owner = server_identity
    if owner is None and socket_ownership is not None:
        owner = socket_ownership.process
    errors: list[str] = []
    if owner is None:
        return (
            ()
            if not socket_path.exists()
            else (f"exact socket ownership capability unavailable: {socket_path}",)
        )
    if socket_ownership is not None and socket_ownership.process != owner:
        errors.append("socket ownership process differs from recorded server")
        socket_ownership = None
    retained = owner in process_handles.retained

    def kill_original_without_path() -> None:
        if not process_identity_matches(owner):
            return
        if not retained:
            errors.append(
                f"server pid {owner.pid} stable handle unavailable; "
                "pathname cleanup refused"
            )
            return
        process_handles.signal(owner, signal.SIGTERM)
        survivors = _wait_identity_absence((owner,), timeout_s=timeout_s)
        if survivors:
            process_handles.signal(owner, signal.SIGKILL)
            survivors = _wait_identity_absence((owner,), timeout_s=timeout_s)
        if survivors:
            errors.append(
                f"server pid {owner.pid} with start time {owner.start_time} remains"
            )

    if process_identity_matches(owner) and not retained:
        errors.append(
            f"server pid {owner.pid} stable handle unavailable; "
            "pathname cleanup refused"
        )
        return tuple(errors)
    if socket_ownership is None:
        kill_original_without_path()
        if socket_path.exists():
            errors.append(
                f"exact socket ownership capability unavailable: {socket_path}"
            )
        return tuple(errors)
    if not socket_path.exists():
        kill_original_without_path()
        return tuple(errors)
    try:
        _verify_private_directory_mode(socket_path.parent)
        before = _socket_identity(socket_path)
    except OSError as error:
        errors.append(f"exact socket ownership: {type(error).__name__}: {error}")
        kill_original_without_path()
        return tuple(errors)
    if not before.matches(socket_ownership.socket):
        errors.append(f"configured socket ownership changed: {socket_path}")
        kill_original_without_path()
        return tuple(errors)
    if not process_identity_matches(owner):
        errors.extend(_remove_proven_stale_socket(socket_path, socket_ownership))
        return tuple(errors)
    try:
        current_owner = _query_exact_socket_owner(socket_path, timeout_s=timeout_s)
        after = _socket_identity(socket_path)
    except (OSError, RuntimeError) as error:
        errors.append(f"exact socket ownership query: {type(error).__name__}: {error}")
        kill_original_without_path()
        return tuple(errors)
    if not after.matches(socket_ownership.socket) or current_owner != owner:
        errors.append(f"configured socket owner changed: {socket_path}")
        kill_original_without_path()
        return tuple(errors)

    environment = os.environ.copy()
    environment.pop("TMUX", None)
    environment.pop("TMUX_PANE", None)
    helper: subprocess.Popen[bytes] | None = None
    helper_timed_out = False
    try:
        helper = subprocess.Popen(
            ("tmux", "-S", str(socket_path), "kill-server"),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as error:
        errors.append(f"exact socket kill-server: {type(error).__name__}: {error}")
    if helper is not None:
        try:
            helper_identity = _record_process("tmux-kill-server", helper.pid)
        except RuntimeError:
            try:
                helper.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                helper_timed_out = True
                errors.append("exact socket kill-server identity unavailable")
        else:
            helper_registry = _PidfdRegistry()
            try:
                helper_retained = helper_registry.retain(helper_identity)
                try:
                    helper.wait(timeout=timeout_s)
                except subprocess.TimeoutExpired:
                    helper_timed_out = True
                    if helper_retained:
                        helper_registry.signal(helper_identity, signal.SIGTERM)
                        try:
                            helper.wait(timeout=timeout_s)
                        except subprocess.TimeoutExpired:
                            helper_registry.signal(helper_identity, signal.SIGKILL)
                            try:
                                helper.wait(timeout=timeout_s)
                            except subprocess.TimeoutExpired:
                                errors.append("exact socket kill-server helper remains")
                    else:
                        errors.append(
                            "exact socket kill-server helper stable handle unavailable"
                        )
                errors.extend(helper_registry.errors)
            finally:
                helper_registry.close()
        if helper_timed_out:
            errors.append("exact socket kill-server timed out")
        elif helper.returncode not in (0, _TMUX_NO_SERVER_STATUS):
            # Any other non-zero status is the helper behaving unexpectedly
            # rather than tmux reporting an absent server, so it is worth
            # reporting even when the fallback signals below rescue the
            # teardown.
            errors.append(f"exact socket kill-server exited {helper.returncode}")

    survivors = _wait_identity_absence((owner,), timeout_s=timeout_s)
    for signal_number in (signal.SIGTERM, signal.SIGKILL):
        if not survivors:
            break
        process_handles.signal(owner, signal_number)
        survivors = _wait_identity_absence((owner,), timeout_s=timeout_s)
    if survivors:
        errors.append(
            f"server pid {owner.pid} with start time {owner.start_time} remains"
        )
        if helper is not None and helper.returncode == _TMUX_NO_SERVER_STATUS:
            # The server outlived a kill that reported no server: worth saying,
            # but only now that its survival is established.
            errors.append("exact socket kill-server found no server, yet one remains")
    elif socket_path.exists():
        errors.extend(_remove_proven_stale_socket(socket_path, socket_ownership))
    return tuple(errors)


def _remove_proven_stale_socket(
    socket_path: pathlib.Path,
    socket_ownership: _SocketOwnership | None,
) -> tuple[str, ...]:
    """Remove only the captured inode after proving its server is absent.

    >>> _remove_proven_stale_socket(pathlib.Path("missing.sock"), None)
    ()

    Parameters
    ----------
    socket_path : pathlib.Path
        Exact configured socket after a bounded server cleanup attempt.
    socket_ownership : _SocketOwnership | None
        Original process/socket capability.

    Returns
    -------
    tuple[str, ...]
        Empty only when the path is absent or the captured stale inode was removed.
    """
    if not socket_path.exists():
        return ()
    if socket_ownership is None:
        return (f"socket ownership capability unavailable: {socket_path}",)
    try:
        _verify_private_directory_mode(socket_path.parent)
        before = _socket_identity(socket_path)
    except OSError as error:
        return (f"stale socket identity: {type(error).__name__}: {error}",)
    if not before.matches(socket_ownership.socket):
        return (f"configured socket ownership changed: {socket_path}",)
    if process_identity_matches(socket_ownership.process):
        return (f"socket owner is not proven absent: {socket_path}",)
    try:
        _verify_private_directory_mode(socket_path.parent)
        after = _socket_identity(socket_path)
        if not after.matches(socket_ownership.socket) or process_identity_matches(
            socket_ownership.process
        ):
            return (f"configured socket ownership changed: {socket_path}",)
        socket_path.unlink()
    except OSError as error:
        return (f"stale socket removal: {type(error).__name__}: {error}",)
    return () if not socket_path.exists() else (f"socket remains: {socket_path}",)


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
    _identity_callback: (
        cabc.Callable[[tuple[ProcessIdentity, ...]], None] | None
    ) = None,
) -> subprocess.Popen[bytes]:
    """Start the paused Task 1 service and wait for its exact ready marker.

    Examples
    --------
    >>> try:
    ...     start_fuzzer(pathlib.Path("."), "", ready_timeout_s=1.0)
    ... except ValueError as error:
    ...     str(error).startswith("run_id must be a 1-128 byte terminal-safe")
    True

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
    _identity_callback : collections.abc.Callable | None
        Private worker hook invoked immediately after the child identity is
        captured and before readiness is awaited.

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
    if not _is_terminal_safe_component(run_id):
        message = (
            f"run_id must be a 1-{_SENTINEL_COMPONENT_MAX_BYTES} byte "
            "terminal-safe ASCII component using letters, digits, '.', '_', ':', "
            "or '-'"
        )
        raise ValueError(message)
    if ready_timeout_s <= 0:
        message = "ready timeout must be positive"
        raise ValueError(message)
    if (
        isinstance(duration_s, bool)
        or not isinstance(duration_s, (int, float))
        or not math.isfinite(duration_s)
        or duration_s <= 0
    ):
        message = "fuzzer duration must be finite and positive"
        raise ValueError(message)
    duration_s = float(duration_s)
    if (
        not math.isfinite(frame_rate_hz)
        or frame_rate_hz <= 0
        or frame_rate_hz > _WAIT_FRAME_RATE_MAX_HZ
    ):
        message = (
            f"fuzzer frame rate must be positive and at most "
            f"{_WAIT_FRAME_RATE_MAX_HZ} frames per second"
        )
        raise ValueError(message)
    output_dir = scratch / "fuzzer"
    script = pathlib.Path(__file__).with_name("fuzzer.py")
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
        if _identity_out is not None:
            _identity_out.append(identity)
        if _identity_callback is not None:
            _identity_callback((identity,))
        _wait_for_fuzzer_ready(
            process,
            ready,
            run_id,
            timeout_s=ready_timeout_s,
        )
    except BaseException as startup_error:
        if identity is None:
            start_time = _process_start_time(process.pid)
            if start_time is not None:
                identity = ProcessIdentity("fuzzer", process.pid, start_time)
        if identity is None:
            process.poll()
            if process.returncode is None:
                cleanup_error = (
                    f"fuzzer pid {process.pid} identity unavailable; "
                    "refused unsafe PID signaling"
                )
                cleanup_report = CleanupReport(
                    complete=False,
                    errors=(cleanup_error,),
                    processes_absent=False,
                )
            else:
                process.wait()
                cleanup_report = CleanupReport(
                    complete=True,
                    processes_absent=True,
                )
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
    fuzzer_duration_s: float = 300.0,
    watchdog_s: float = 120.0,
    _process_identity_callback: (
        cabc.Callable[[tuple[ProcessIdentity, ...]], None] | None
    ) = None,
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
    fuzzer_duration_s : float
        Active-service lifetime; supervised runs pass their derived budget.
    watchdog_s : float
        Supervisor progress interval used to cap pane readiness.
    _process_identity_callback : collections.abc.Callable | None
        Private worker hook invoked as exact process identities become known.

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
    watchdog_seconds = _validated_watchdog_seconds(watchdog_s)
    if not _is_terminal_safe_component(run_id):
        message = (
            f"run_id must be a 1-{_SENTINEL_COMPONENT_MAX_BYTES} byte "
            "terminal-safe ASCII component using letters, digits, '.', '_', ':', "
            "or '-'"
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
    process_handles: _PidfdRegistry | None = None
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
        process_handles = _PidfdRegistry()

        def publish_identities(delta: tuple[ProcessIdentity, ...]) -> None:
            process_handles.retain_many(delta)
            if _process_identity_callback is not None:
                _process_identity_callback(delta)

        fuzzer_identities: list[ProcessIdentity] = []
        fuzzer = start_fuzzer(
            resolved_scratch,
            run_id,
            duration_s=fuzzer_duration_s,
            _identity_out=fuzzer_identities,
            _identity_callback=publish_identities,
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
            watchdog_s=watchdog_seconds,
            processes=(fuzzer_identity,),
            ambient_tmux_environment=ambient_tmux_environment,
            process_identity_callback=publish_identities,
            process_handles=process_handles,
        )
    except BaseException as setup_error:
        cleanup_errors: list[str] = []
        if fuzzer is not None and fuzzer_identity is not None:
            cleanup_errors.extend(_stop_owned_process(fuzzer, fuzzer_identity).errors)
        if process_handles is not None:
            cleanup_errors.extend(process_handles.errors)
            process_handles.close()
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
    fuzzer_duration_s: float = 300.0,
    watchdog_s: float = 120.0,
    _process_identity_callback: (
        cabc.Callable[[tuple[ProcessIdentity, ...]], None] | None
    ) = None,
    _socket_ownership_callback: cabc.Callable[[_SocketOwnership], None] | None = None,
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
    fuzzer_duration_s : float
        Active-service lifetime; supervised runs pass their derived budget.
    watchdog_s : float
        Supervisor progress interval used to cap pane readiness.
    _process_identity_callback : collections.abc.Callable | None
        Private worker hook invoked as exact process identities become known.
    _socket_ownership_callback : collections.abc.Callable | None
        Private worker hook invoked when exact socket ownership is established.

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
        BoundedPlanner,
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
        fuzzer_duration_s=fuzzer_duration_s,
        watchdog_s=watchdog_s,
        _process_identity_callback=_process_identity_callback,
    )
    engine = t.cast("TmuxEngine", context.engine)
    keepalive = f"bench-{run_id}-keepalive"
    try:
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
        socket_ownership = _capture_socket_ownership(
            context.socket_path,
            timeout_s=_WAIT_TIMEOUT_MAX_S,
        )
        server_identity = socket_ownership.process
        context.socket_ownership = socket_ownership
        context.processes = (*context.processes, server_identity)
        if _socket_ownership_callback is not None:
            assert context.process_handles is not None
            context.process_handles.retain(server_identity)
            _socket_ownership_callback(socket_ownership)
        elif context.process_identity_callback is not None:
            context.process_identity_callback((server_identity,))
        if lane is EngineLane.CONTROL:
            run(ListSessions(), engine).raise_for_status()

        workspaces = build_workspaces(
            topology,
            context.scratch / "fuzzer" / "streams",
            run_id,
            delayed_ordinal=delayed_ordinal,
        )
        compiled = workspaces.compile()
        setup_planner = BoundedPlanner(
            BatchingPlanner(), frozenset(compiled.host_after)
        )
        context.setup_metrics = _phase_metrics(
            context,
            operations=len(compiled.plan),
            planner_steps=len(compiled.plan.explain(setup_planner)),
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
    fuzzer_duration_s: float = 300.0,
    watchdog_s: float = 120.0,
    _process_identity_callback: (
        cabc.Callable[[tuple[ProcessIdentity, ...]], None] | None
    ) = None,
    _socket_ownership_callback: cabc.Callable[[_SocketOwnership], None] | None = None,
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
    fuzzer_duration_s : float
        Active-service lifetime; supervised runs pass their derived budget.
    watchdog_s : float
        Supervisor progress interval used to cap pane readiness.
    _process_identity_callback : collections.abc.Callable | None
        Private worker hook invoked as exact process identities become known.
    _socket_ownership_callback : collections.abc.Callable | None
        Private worker hook invoked when exact socket ownership is established.

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
    from libtmux.experimental.engines.base import CommandRequest, CommandResult
    from libtmux.experimental.ops import (
        BatchingPlanner,
        BoundedPlanner,
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
        fuzzer_duration_s=fuzzer_duration_s,
        watchdog_s=watchdog_s,
        _process_identity_callback=_process_identity_callback,
    )
    engine = t.cast("AsyncTmuxEngine", context.engine)
    keepalive = f"bench-{run_id}-keepalive"

    def require_control_output(result: CommandResult) -> None:
        """Raise one setup error for a rejected pane-output subscription."""
        if result.returncode != 0:
            message = "control stream could not enable delayed-pane output"
            raise RuntimeError(message)

    try:
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
        socket_ownership = _capture_socket_ownership(
            context.socket_path,
            timeout_s=_WAIT_TIMEOUT_MAX_S,
        )
        server_identity = socket_ownership.process
        context.socket_ownership = socket_ownership
        context.processes = (*context.processes, server_identity)
        if _socket_ownership_callback is not None:
            assert context.process_handles is not None
            context.process_handles.retain(server_identity)
            _socket_ownership_callback(socket_ownership)
        elif context.process_identity_callback is not None:
            context.process_identity_callback((server_identity,))
        if lane is EngineLane.CONTROL:
            control = t.cast(AsyncControlModeEngine, engine)
            await control.start()
            (await arun(ListSessions(), engine)).raise_for_status()

        workspaces = build_workspaces(
            topology,
            context.scratch / "fuzzer" / "streams",
            run_id,
            delayed_ordinal=delayed_ordinal,
        )
        compiled = workspaces.compile()
        setup_planner = BoundedPlanner(
            BatchingPlanner(), frozenset(compiled.host_after)
        )
        context.setup_metrics = _phase_metrics(
            context,
            operations=len(compiled.plan),
            planner_steps=len(compiled.plan.explain(setup_planner)),
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
        (await arun(KillSession(target=NameRef(keepalive)), engine)).raise_for_status()
        context.setup_duration_ns = time.perf_counter_ns() - started_ns
        verified = verify_topology(context, await snapshot_topology_async(context))
        if lane is EngineLane.CONTROL:
            delayed_pane_id = t.cast(str, context.delayed_pane_id)
            delayed_pane = next(
                pane for pane in verified.panes if pane.pane_id == delayed_pane_id
            )
            clients = (await arun(ListClients(), engine)).raise_for_status().clients
            delayed_session_id = delayed_pane.session_id
            (
                await arun(
                    SwitchClient(
                        client=_only_control_client_name(clients),
                        to_session=delayed_session_id,
                    ),
                    engine,
                )
            ).raise_for_status()
            control.set_attach_targets([delayed_session_id])
            # The pane:state argument needs explicit quotes for tmux's
            # control-mode parser.
            enabled = await engine.run(
                CommandRequest.from_args(
                    "refresh-client",
                    "-A",
                    f'"{delayed_pane_id}:on"',
                )
            )
            require_control_output(enabled)
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
    if any(
        pane.width is None or pane.width < _MIN_PANE_WIDTH for pane in snapshot.panes
    ):
        fail(f"pane width is below {_MIN_PANE_WIDTH} columns")
    for pane in snapshot.panes:
        history_limit = pane.fields.get("history_limit")
        if (
            type(history_limit) is not str
            or not history_limit.isascii()
            or not history_limit.isdecimal()
        ):
            fail(
                "pane history limit is not an exact integer of at least "
                f"{_WAIT_CAPTURE_HISTORY_LINES}"
            )
        try:
            parsed_history_limit = int(history_limit)
        except ValueError:
            fail(
                "pane history limit is not an exact integer of at least "
                f"{_WAIT_CAPTURE_HISTORY_LINES}"
            )
        if (
            str(parsed_history_limit) != history_limit
            or parsed_history_limit < _WAIT_CAPTURE_HISTORY_LINES
        ):
            fail(
                "pane history limit is not an exact integer of at least "
                f"{_WAIT_CAPTURE_HISTORY_LINES}"
            )

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
    identity_callback = getattr(context, "process_identity_callback", None)
    if identity_callback is not None:
        identity_callback(pane_processes)
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
    marker = f"LIBTMUX_EPOCH epoch={epoch}"
    write_json_atomic(
        context.scratch / "fuzzer" / "gate.json",
        {"schema_version": 1, "run_id": context.run_id, "epoch": epoch},
    )
    context.activity_epoch = epoch
    context.activity_marker = marker
    context.heartbeat_epoch = observed_epoch or 0
    return epoch


def verify_activity_sync(
    context: RunContext,
    *,
    timeout_s: float | None = None,
    no_progress_timeout_s: float = 3.0,
    poll_interval_s: float = 0.02,
) -> int:
    """Wait until every pane and the heartbeat expose the released epoch.

    >>> try:
    ...     verify_activity_sync(types.SimpleNamespace(mode=ExecutionMode.ASYNC))
    ... except ValueError as error:
    ...     print(error)
    sync activity verification requires a synchronous context

    Parameters
    ----------
    context : RunContext
        Released synchronous live run.
    timeout_s : float or None
        Overall stabilization deadline, derived from pane scale when omitted.
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
    if context.mode is not ExecutionMode.SYNC:
        message = "sync activity verification requires a synchronous context"
        raise ValueError(message)
    if context.activity_epoch is None or context.activity_marker is None:
        message = "activity gate has not been released"
        raise RuntimeError(message)
    if timeout_s is None:
        timeout_s = _pane_epoch_overall_timeout_s(
            len(context.pane_ids), context.watchdog_s
        )
    timeout_s, no_progress_timeout_s, poll_interval_s = _validated_pane_epoch_timing(
        timeout_s,
        no_progress_timeout_s,
        poll_interval_s,
    )
    deadline = time.monotonic() + timeout_s
    _wait_pane_epoch_sync(
        context,
        context.activity_epoch,
        timeout_s=timeout_s,
        no_progress_timeout_s=no_progress_timeout_s,
        poll_interval_s=poll_interval_s,
    )
    progress_deadline = min(
        deadline,
        time.monotonic() + no_progress_timeout_s,
    )
    observed_epoch = context.heartbeat_epoch
    while True:
        if context.fuzzer.poll() is not None:
            message = "fuzzer exited during activity stabilization"
            raise RuntimeError(message)
        state, heartbeat_epoch = _heartbeat_epoch(context)
        heartbeat_advanced = False
        if heartbeat_epoch is not None:
            if heartbeat_epoch < observed_epoch:
                message = "fuzzer heartbeat epoch moved backwards"
                raise RuntimeError(message)
            if heartbeat_epoch > observed_epoch:
                observed_epoch = heartbeat_epoch
                heartbeat_advanced = True
        now = time.monotonic()
        if now >= deadline:
            message = "activity stabilization timed out waiting for heartbeat"
            raise TimeoutError(message)
        if now >= progress_deadline:
            message = "activity stabilization heartbeat made no progress"
            raise TimeoutError(message)
        if heartbeat_advanced:
            progress_deadline = now + no_progress_timeout_s
        if (
            state == "active"
            and heartbeat_epoch is not None
            and heartbeat_epoch >= context.activity_epoch
        ):
            heartbeat = _current_activity_heartbeat(
                context,
                max_age_s=no_progress_timeout_s,
            )
            if heartbeat.epoch < context.activity_epoch:
                message = "fuzzer heartbeat did not reach released activity epoch"
                raise RuntimeError(message)
            break
        time.sleep(min(poll_interval_s, deadline - now, progress_deadline - now))
    context.activity_pane_ids = context.pane_ids
    return context.activity_epoch


async def verify_activity_async(
    context: RunContext,
    *,
    timeout_s: float | None = None,
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
    timeout_s : float or None
        Overall stabilization deadline, derived from pane scale when omitted.
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
    if context.mode is not ExecutionMode.ASYNC:
        message = "async activity verification requires an asynchronous context"
        raise ValueError(message)
    if context.activity_epoch is None or context.activity_marker is None:
        message = "activity gate has not been released"
        raise RuntimeError(message)
    if timeout_s is None:
        timeout_s = _pane_epoch_overall_timeout_s(
            len(context.pane_ids), context.watchdog_s
        )
    timeout_s, no_progress_timeout_s, poll_interval_s = _validated_pane_epoch_timing(
        timeout_s,
        no_progress_timeout_s,
        poll_interval_s,
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    await _wait_pane_epoch_async(
        context,
        context.activity_epoch,
        timeout_s=timeout_s,
        no_progress_timeout_s=no_progress_timeout_s,
        poll_interval_s=poll_interval_s,
    )
    progress_deadline = min(deadline, loop.time() + no_progress_timeout_s)
    observed_epoch = context.heartbeat_epoch
    while True:
        if context.fuzzer.poll() is not None:
            message = "fuzzer exited during activity stabilization"
            raise RuntimeError(message)
        state, heartbeat_epoch = _heartbeat_epoch(context)
        heartbeat_advanced = False
        if heartbeat_epoch is not None:
            if heartbeat_epoch < observed_epoch:
                message = "fuzzer heartbeat epoch moved backwards"
                raise RuntimeError(message)
            if heartbeat_epoch > observed_epoch:
                observed_epoch = heartbeat_epoch
                heartbeat_advanced = True
        now = loop.time()
        if now >= deadline:
            message = "activity stabilization timed out waiting for heartbeat"
            raise TimeoutError(message)
        if now >= progress_deadline:
            message = "activity stabilization heartbeat made no progress"
            raise TimeoutError(message)
        if heartbeat_advanced:
            progress_deadline = now + no_progress_timeout_s
        if (
            state == "active"
            and heartbeat_epoch is not None
            and heartbeat_epoch >= context.activity_epoch
        ):
            heartbeat = _current_activity_heartbeat(
                context,
                max_age_s=no_progress_timeout_s,
            )
            if heartbeat.epoch < context.activity_epoch:
                message = "fuzzer heartbeat did not reach released activity epoch"
                raise RuntimeError(message)
            break
        await asyncio.sleep(
            min(poll_interval_s, deadline - now, progress_deadline - now)
        )
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
    if context.activity_pane_ids != context.pane_ids:
        message = "measured phases require complete initial activity stabilization"
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
        Unique 1-128 byte terminal-safe ASCII component.
    value : str
        Terminal-safe 1-128 byte value embedded in the canonical sentinel.

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
    token = _sentinel_token(context.run_id, request_id, value)
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
    from libtmux import exc
    from libtmux.experimental.engines.base import CommandRequest, encode_direct_argv
    from libtmux.experimental.engines.control_mode import (
        ControlModeEngine,
        ControlModeError,
    )
    from libtmux.experimental.engines.subprocess import SubprocessEngine
    from libtmux.experimental.ops import CapturePane, PaneId

    if context.mode is not ExecutionMode.SYNC:
        message = "sync capture wait requires a synchronous run context"
        raise ValueError(message)
    timeout_s = _validated_wait_timeout(timeout_s)
    poll_interval_s = _validated_poll_interval(poll_interval_s)
    engine = context.engine
    if not isinstance(engine, (SubprocessEngine, ControlModeEngine)):
        message = "sync capture wait requires a subprocess or control engine"
        raise TypeError(message)
    pane_id = context.delayed_pane_id
    if not isinstance(pane_id, str) or not pane_id:
        message = "capture wait requires a concrete delayed pane ID"
        raise ValueError(message)
    request = request_sentinel(context, request_id=request_id, value=value)
    deadline_ns = request.requested_monotonic_ns + int(timeout_s * 1_000_000_000)
    operation = CapturePane(
        target=PaneId(pane_id),
        start=-_WAIT_CAPTURE_HISTORY_LINES,
        join_wrapped=True,
    )
    rendered = operation.render()
    needle = f"{request.token}\n".encode()
    poll_count = 0
    detected_ns: int | None = None
    while time.monotonic_ns() < deadline_ns:
        if context.fuzzer.poll() is not None:
            message = "fuzzer exited during capture wait"
            raise RuntimeError(message)
        remaining_s = (deadline_ns - time.monotonic_ns()) / 1_000_000_000
        if remaining_s <= 0:
            break
        if isinstance(engine, SubprocessEngine):
            command = engine.connection.argv(*encode_direct_argv(rendered))
            handles = _PidfdRegistry()
            try:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="backslashreplace",
                    start_new_session=True,
                )
            except FileNotFoundError:
                handles.close()
                raise exc.TmuxCommandNotFound from None
            try:
                try:
                    recorded_identity = _record_process("capture-wait", process.pid)
                except RuntimeError:
                    identity = None
                else:
                    identity = recorded_identity
                    handles.retain(recorded_identity)
                try:
                    stdout, stderr = process.communicate(timeout=remaining_s)
                except subprocess.TimeoutExpired as error:
                    if identity is None or not handles.signal(identity, signal.SIGKILL):
                        message = (
                            "capture wait could not safely stop its timed-out "
                            "subprocess"
                        )
                        raise RuntimeError(message) from error
                    try:
                        stdout, stderr = process.communicate(timeout=0.1)
                    except subprocess.TimeoutExpired as cleanup_error:
                        message = (
                            "capture wait subprocess did not exit after escalation"
                        )
                        raise RuntimeError(message) from cleanup_error
                    del stdout, stderr
                    message = f"capture wait timed out for request {request.request_id}"
                    raise TimeoutError(message) from error
            finally:
                handles.close()
            stdout_lines = stdout.split("\n")
            while stdout_lines and stdout_lines[-1] == "":
                stdout_lines.pop()
            stderr_lines = tuple(line for line in stderr.split("\n") if line)
            result = operation.build_result(
                argv=rendered,
                returncode=(
                    process.returncode if process.returncode is not None else -1
                ),
                stdout=tuple(stdout_lines),
                stderr=stderr_lines,
            ).raise_for_status()
        else:
            original_timeout = engine.timeout
            engine.timeout = min(original_timeout, remaining_s)
            try:
                raw = engine.run(CommandRequest(args=rendered))
            except ControlModeError as error:
                if time.monotonic_ns() >= deadline_ns:
                    message = f"capture wait timed out for request {request.request_id}"
                    raise TimeoutError(message) from error
                raise
            finally:
                engine.timeout = original_timeout
            result = operation.build_result(
                argv=rendered,
                returncode=raw.returncode,
                stdout=raw.stdout,
                stderr=raw.stderr,
            ).raise_for_status()
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
    timeout_s = _validated_wait_timeout(timeout_s)
    poll_interval_s = _validated_poll_interval(poll_interval_s)
    engine = t.cast("AsyncTmuxEngine", context.engine)
    pane_id = context.delayed_pane_id
    if not isinstance(pane_id, str) or not pane_id:
        message = "capture wait requires a concrete delayed pane ID"
        raise ValueError(message)
    request = request_sentinel(context, request_id=request_id, value=value)
    deadline_ns = request.requested_monotonic_ns + int(timeout_s * 1_000_000_000)
    operation = CapturePane(
        target=PaneId(pane_id),
        start=-_WAIT_CAPTURE_HISTORY_LINES,
        join_wrapped=True,
    )
    needle = f"{request.token}\n".encode()
    poll_count = 0
    detected_ns: int | None = None
    while time.monotonic_ns() < deadline_ns:
        if context.fuzzer.poll() is not None:
            message = "fuzzer exited during capture wait"
            raise RuntimeError(message)
        remaining_s = (deadline_ns - time.monotonic_ns()) / 1_000_000_000
        if remaining_s <= 0:
            break
        capture_task = asyncio.create_task(
            arun(operation, engine),
            name=f"bench-capture-wait-{request.request_id}",
        )
        try:
            result = (
                await asyncio.wait_for(capture_task, timeout=remaining_s)
            ).raise_for_status()
        except asyncio.TimeoutError as error:
            message = f"capture wait timed out for request {request.request_id}"
            raise TimeoutError(message) from error
        finally:
            if not capture_task.done():
                capture_task.cancel()
            await asyncio.gather(capture_task, return_exceptions=True)
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
    timeout_s = _validated_wait_timeout(timeout_s)
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


def enumerate_orm(
    context: RunContext,
    *,
    kind: EnumerationKind,
) -> EnumerationResult:
    """Execute and validate one classic ORM hierarchy read.

    This is the reference cell, not a fifth lane. :class:`~libtmux.Server`
    reaches tmux through its own request graph regardless of which engine the
    run is measuring, so its timing is never folded into an engine speedup
    claim. It is comparable only because it is required to return exactly the
    rows the typed operations return, which this validates on every sample.

    Parameters
    ----------
    context : RunContext
        Verified active topology carrying the bound classic server.
    kind : {"sessions", "windows", "panes"}
        One hierarchy cell to enumerate.

    Returns
    -------
    EnumerationResult
        Exact row count, concrete IDs, checksum, and timing.

    Examples
    --------
    >>> try:
    ...     enumerate_orm(types.SimpleNamespace(server=None), kind="panes")
    ... except ValueError as error:
    ...     print(error)
    orm phase requires a bound classic server
    """
    server = getattr(context, "server", None)
    if server is None:
        message = "orm phase requires a bound classic server"
        raise ValueError(message)
    _enumeration_expected(context, kind)
    attribute = {"sessions": "sessions", "windows": "windows", "panes": "panes"}[kind]
    identifier = {
        "sessions": "session_id",
        "windows": "window_id",
        "panes": "pane_id",
    }[kind]
    started_ns = time.perf_counter_ns()
    rows = list(getattr(server, attribute))
    ids = tuple(str(getattr(row, identifier)) for row in rows)
    duration_ns = time.perf_counter_ns() - started_ns
    return _accepted_enumeration(context, kind, ids, duration_ns)


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


def _capture_plan(
    context: RunContext,
    *,
    pane_ids: tuple[str, ...] | None = None,
    history_lines: int = _MEASURED_CAPTURE_HISTORY_LINES,
) -> LazyPlan:
    """Build the transport-independent all-pane capture operation graph.

    >>> context = types.SimpleNamespace(pane_ids=("%1", "%2"))
    >>> [operation.target.value for operation in _capture_plan(context).operations]
    ['%1', '%2']
    >>> [operation.target.value for operation in _capture_plan(
    ...     context, pane_ids=("%2",)
    ... ).operations]
    ['%2']

    Parameters
    ----------
    context : RunContext
        Verified stable pane ID authority.
    pane_ids : tuple[str, ...] or None
        Ordered subset to capture, or every stable pane when omitted.
    history_lines : int
        Positive number of trailing rows requested from each pane.

    Returns
    -------
    LazyPlan
        One bounded ``CapturePane`` operation per concrete pane.
    """
    from libtmux.experimental.ops import CapturePane, LazyPlan, PaneId

    if type(history_lines) is not int or history_lines <= 0:
        message = "capture history line bound must be a positive integer"
        raise ValueError(message)
    plan = LazyPlan()
    for pane_id in context.pane_ids if pane_ids is None else pane_ids:
        plan.add(CapturePane(target=PaneId(pane_id), start=-history_lines))
    return plan


def _content_capture_plan(context: RunContext) -> tuple[LazyPlan, Planner]:
    """Build the delayed-first bounded plan for one content snapshot.

    >>> context = types.SimpleNamespace(
    ...     pane_ids=("%1", "%2", "%3"), delayed_pane_id="%2"
    ... )
    >>> plan, planner = _content_capture_plan(context)
    >>> [operation.target.value for operation in plan.operations]
    ['%2', '%1', '%3']
    >>> [step.indices for step in planner.plan(plan.operations)]
    [(0,), (1, 2)]

    Parameters
    ----------
    context : RunContext
        Verified stable pane IDs and unique delayed-pane identity.

    Returns
    -------
    tuple[LazyPlan, Planner]
        Capture graph and bounded batching policy with operation zero isolated.

    Raises
    ------
    ValueError
        If stable pane IDs are empty, malformed, duplicated, or do not contain
        exactly one delayed pane.
    """
    from libtmux.experimental.ops import (
        BatchingPlanner,
        BoundedPlanner,
        CapturePane,
        LazyPlan,
        PaneId,
    )

    pane_ids = tuple(context.pane_ids)
    if (
        not pane_ids
        or any(type(pane_id) is not str or not pane_id for pane_id in pane_ids)
        or len(set(pane_ids)) != len(pane_ids)
    ):
        message = "content snapshot requires nonempty unique stable pane IDs"
        raise ValueError(message)
    delayed_pane_id = context.delayed_pane_id
    if type(delayed_pane_id) is not str or pane_ids.count(delayed_pane_id) != 1:
        message = "content snapshot requires exactly one stable delayed pane ID"
        raise ValueError(message)
    target_order = (
        delayed_pane_id,
        *(pane_id for pane_id in pane_ids if pane_id != delayed_pane_id),
    )
    plan = LazyPlan()
    for index, pane_id in enumerate(target_order):
        delayed = index == 0
        plan.add(
            CapturePane(
                target=PaneId(pane_id),
                start=(
                    -_WAIT_CAPTURE_HISTORY_LINES
                    if delayed
                    else -_MEASURED_CAPTURE_HISTORY_LINES
                ),
                join_wrapped=delayed,
            )
        )
    boundaries = frozenset(
        (
            0,
            *range(
                _PANE_CAPTURE_CHUNK_SIZE, len(target_order), _PANE_CAPTURE_CHUNK_SIZE
            ),
        )
    )
    planner = BoundedPlanner(BatchingPlanner(), boundaries)
    return plan, planner


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

    >>> _activity_frame_epochs(("LIBTMUX_EPOCH epoch=3", "other"))
    (3,)

    Parameters
    ----------
    lines : tuple[str, ...]
        Captured pane lines in display order.

    Returns
    -------
    tuple[int, ...]
        Nonnegative epochs from exact pulse lines.
    """
    epochs: list[int] = []
    for line in lines:
        prefix = "LIBTMUX_EPOCH epoch="
        epoch_text = line[len(prefix) :] if line.startswith(prefix) else ""
        if (
            epoch_text.isascii()
            and epoch_text.isdecimal()
            and len(f"{line}\n".encode("ascii")) <= _EPOCH_PULSE_MAX_BYTES
        ):
            epochs.append(int(epoch_text))
    return tuple(epochs)


def _captured_lines_for_panes(
    pane_ids: tuple[str, ...],
    plan_result: object,
) -> tuple[tuple[str, ...], ...]:
    """Return attributed typed capture lines for an ordered pane subset.

    >>> from libtmux.experimental.ops import CapturePane, PaneId
    >>> operation = CapturePane(target=PaneId("%1"))
    >>> result = operation.build_result(returncode=0, stdout=("line",))
    >>> _captured_lines_for_panes(
    ...     ("%1",), types.SimpleNamespace(results=(result,))
    ... )
    (('line',),)

    Parameters
    ----------
    pane_ids : tuple[str, ...]
        Expected concrete targets in dispatch order.
    plan_result : object
        Plan result containing one typed capture result per target.

    Returns
    -------
    tuple[tuple[str, ...], ...]
        Captured lines in the same order as ``pane_ids``.

    Raises
    ------
    RuntimeError
        If result cardinality or target attribution differs.
    TypeError
        If a result is not a typed capture result.
    """
    from libtmux.experimental.ops import CapturePane, CapturePaneResult, PaneId

    results = tuple(t.cast(t.Any, plan_result).results)
    if len(results) != len(pane_ids):
        message = "pane readiness result count did not match stable pane IDs"
        raise RuntimeError(message)
    result_targets = tuple(
        result.operation.target.value
        if isinstance(result, CapturePaneResult)
        and isinstance(result.operation, CapturePane)
        and isinstance(result.operation.target, PaneId)
        else None
        for result in results
    )
    if result_targets != pane_ids:
        message = "pane readiness target order did not match stable pane IDs"
        raise RuntimeError(message)
    lines: list[tuple[str, ...]] = []
    for pane_id, result in zip(pane_ids, results, strict=True):
        if not isinstance(result, CapturePaneResult):
            message = f"pane readiness for {pane_id} did not return typed lines"
            raise TypeError(message)
        result.raise_for_status()
        lines.append(result.lines)
    return tuple(lines)


def _pane_ids_before_epoch(
    pane_ids: tuple[str, ...],
    captured_lines: tuple[tuple[str, ...], ...],
    epoch: int,
) -> tuple[str, ...]:
    """Return panes whose visible history has not consumed a frozen epoch.

    >>> _pane_ids_before_epoch(
    ...     ("%1", "%2"),
    ...     (("LIBTMUX_EPOCH epoch=7",), ("LIBTMUX_EPOCH epoch=6",)),
    ...     7,
    ... )
    ('%2',)

    Parameters
    ----------
    pane_ids : tuple[str, ...]
        Concrete pane targets in capture order.
    captured_lines : tuple[tuple[str, ...], ...]
        Typed lines attributed to those panes.
    epoch : int
        Frozen heartbeat epoch every pane must expose.

    Returns
    -------
    tuple[str, ...]
        Ordered subset still below ``epoch``.

    Raises
    ------
    RuntimeError
        If capture cardinality differs from the pane subset.
    """
    if len(captured_lines) != len(pane_ids):
        message = "pane readiness lines did not match stable pane IDs"
        raise RuntimeError(message)
    return tuple(
        pane_id
        for pane_id, lines in zip(pane_ids, captured_lines, strict=True)
        if max(_activity_frame_epochs(lines), default=-1) < epoch
    )


def _wait_pane_epoch_sync(
    context: RunContext,
    epoch: int,
    *,
    timeout_s: float | None = None,
    no_progress_timeout_s: float = 3.0,
    poll_interval_s: float = 0.005,
) -> None:
    """Wait outside timing until every pane exposes a frozen heartbeat epoch.

    >>> try:
    ...     _wait_pane_epoch_sync(types.SimpleNamespace(), 1, timeout_s=0)
    ... except ValueError as error:
    ...     print(error)
    pane epoch timeouts and cadence must be finite and positive

    Parameters
    ----------
    context : RunContext
        Active synchronous run owning the stable pane IDs and engine.
    epoch : int
        Frozen heartbeat epoch every pane must expose.
    timeout_s : float or None
        Overall pane-consumption deadline, derived from pane scale when omitted.
    no_progress_timeout_s : float
        Deadline reset whenever another pane reaches ``epoch``.
    poll_interval_s : float
        Delay between incomplete readiness captures.

    Raises
    ------
    ValueError
        If timeout or cadence values are not finite and positive.
    RuntimeError
        If the fuzzer exits or typed capture attribution fails.
    TimeoutError
        If pane consumption stops progressing.
    """
    from libtmux.experimental.ops import BatchingPlanner

    if timeout_s is None:
        timeout_s = _pane_epoch_overall_timeout_s(
            len(context.pane_ids), context.watchdog_s
        )
    timeout_s, no_progress_timeout_s, poll_interval_s = _validated_pane_epoch_timing(
        timeout_s,
        no_progress_timeout_s,
        poll_interval_s,
    )
    engine = t.cast("TmuxEngine", context.engine)
    pending = context.pane_ids
    deadline = time.monotonic() + timeout_s
    progress_deadline = time.monotonic() + no_progress_timeout_s
    while pending:
        now = time.monotonic()
        if now >= deadline:
            message = f"pane epoch wait timed out with {len(pending)} panes pending"
            raise TimeoutError(message)
        if now >= progress_deadline:
            message = (
                f"pane epoch wait made no progress with {len(pending)} panes pending"
            )
            raise TimeoutError(message)
        if context.fuzzer.poll() is not None:
            message = "fuzzer exited before panes consumed capture epoch"
            raise RuntimeError(message)
        next_pending: list[str] = []
        for offset in range(0, len(pending), _PANE_CAPTURE_CHUNK_SIZE):
            chunk = pending[offset : offset + _PANE_CAPTURE_CHUNK_SIZE]
            now = time.monotonic()
            pending_count = len(next_pending) + len(pending) - offset
            if now >= deadline:
                message = (
                    f"pane epoch wait timed out with {pending_count} panes pending"
                )
                raise TimeoutError(message)
            if now >= progress_deadline:
                message = (
                    "pane epoch wait made no progress with "
                    f"{pending_count} panes pending"
                )
                raise TimeoutError(message)
            if context.fuzzer.poll() is not None:
                message = "fuzzer exited before panes consumed capture epoch"
                raise RuntimeError(message)
            plan = _capture_plan(
                context,
                pane_ids=chunk,
                history_lines=_READINESS_CAPTURE_HISTORY_LINES,
            )
            result = plan.execute(engine, planner=BatchingPlanner())
            result.raise_for_status()
            stale = _pane_ids_before_epoch(
                chunk,
                _captured_lines_for_panes(chunk, result),
                epoch,
            )
            now = time.monotonic()
            made_progress = len(stale) < len(chunk)
            next_pending.extend(stale)
            pending_count = len(next_pending) + len(pending) - offset - len(chunk)
            if context.fuzzer.poll() is not None:
                message = "fuzzer exited before panes consumed capture epoch"
                raise RuntimeError(message)
            if now >= deadline:
                message = (
                    f"pane epoch wait timed out with {pending_count} panes pending"
                )
                raise TimeoutError(message)
            if now >= progress_deadline:
                message = (
                    "pane epoch wait made no progress with "
                    f"{pending_count} panes pending"
                )
                raise TimeoutError(message)
            if made_progress:
                progress_deadline = now + no_progress_timeout_s
        pending = tuple(next_pending)
        if not pending:
            return
        time.sleep(
            min(
                poll_interval_s,
                deadline - now,
                progress_deadline - now,
            )
        )


async def _wait_pane_epoch_async(
    context: RunContext,
    epoch: int,
    *,
    timeout_s: float | None = None,
    no_progress_timeout_s: float = 3.0,
    poll_interval_s: float = 0.005,
) -> None:
    """Asynchronously wait until every pane exposes a frozen heartbeat epoch.

    >>> async def invalid_pane_wait():
    ...     try:
    ...         await _wait_pane_epoch_async(
    ...             types.SimpleNamespace(), 1, timeout_s=0
    ...         )
    ...     except ValueError as error:
    ...         return str(error)
    >>> asyncio.run(invalid_pane_wait())
    'pane epoch timeouts and cadence must be finite and positive'

    Parameters
    ----------
    context : RunContext
        Active asynchronous run owning the stable pane IDs and engine.
    epoch : int
        Frozen heartbeat epoch every pane must expose.
    timeout_s : float or None
        Overall pane-consumption deadline, derived from pane scale when omitted.
    no_progress_timeout_s : float
        Deadline reset whenever another pane reaches ``epoch``.
    poll_interval_s : float
        Delay between incomplete readiness captures.

    Raises
    ------
    ValueError
        If timeout or cadence values are not finite and positive.
    RuntimeError
        If the fuzzer exits or typed capture attribution fails.
    TimeoutError
        If pane consumption stops progressing.
    """
    from libtmux.experimental.ops import BatchingPlanner

    if timeout_s is None:
        timeout_s = _pane_epoch_overall_timeout_s(
            len(context.pane_ids), context.watchdog_s
        )
    timeout_s, no_progress_timeout_s, poll_interval_s = _validated_pane_epoch_timing(
        timeout_s,
        no_progress_timeout_s,
        poll_interval_s,
    )
    engine = t.cast("AsyncTmuxEngine", context.engine)
    pending = context.pane_ids
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    progress_deadline = loop.time() + no_progress_timeout_s
    while pending:
        now = loop.time()
        if now >= deadline:
            message = f"pane epoch wait timed out with {len(pending)} panes pending"
            raise TimeoutError(message)
        if now >= progress_deadline:
            message = (
                f"pane epoch wait made no progress with {len(pending)} panes pending"
            )
            raise TimeoutError(message)
        if context.fuzzer.poll() is not None:
            message = "fuzzer exited before panes consumed capture epoch"
            raise RuntimeError(message)
        next_pending: list[str] = []
        for offset in range(0, len(pending), _PANE_CAPTURE_CHUNK_SIZE):
            chunk = pending[offset : offset + _PANE_CAPTURE_CHUNK_SIZE]
            now = loop.time()
            pending_count = len(next_pending) + len(pending) - offset
            if now >= deadline:
                message = (
                    f"pane epoch wait timed out with {pending_count} panes pending"
                )
                raise TimeoutError(message)
            if now >= progress_deadline:
                message = (
                    "pane epoch wait made no progress with "
                    f"{pending_count} panes pending"
                )
                raise TimeoutError(message)
            if context.fuzzer.poll() is not None:
                message = "fuzzer exited before panes consumed capture epoch"
                raise RuntimeError(message)
            plan = _capture_plan(
                context,
                pane_ids=chunk,
                history_lines=_READINESS_CAPTURE_HISTORY_LINES,
            )
            result = await plan.aexecute(engine, planner=BatchingPlanner())
            result.raise_for_status()
            stale = _pane_ids_before_epoch(
                chunk,
                _captured_lines_for_panes(chunk, result),
                epoch,
            )
            now = loop.time()
            made_progress = len(stale) < len(chunk)
            next_pending.extend(stale)
            pending_count = len(next_pending) + len(pending) - offset - len(chunk)
            if context.fuzzer.poll() is not None:
                message = "fuzzer exited before panes consumed capture epoch"
                raise RuntimeError(message)
            if now >= deadline:
                message = (
                    f"pane epoch wait timed out with {pending_count} panes pending"
                )
                raise TimeoutError(message)
            if now >= progress_deadline:
                message = (
                    "pane epoch wait made no progress with "
                    f"{pending_count} panes pending"
                )
                raise TimeoutError(message)
            if made_progress:
                progress_deadline = now + no_progress_timeout_s
        pending = tuple(next_pending)
        if not pending:
            return
        await asyncio.sleep(
            min(
                poll_interval_s,
                deadline - now,
                progress_deadline - now,
            )
        )


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
    ...     returncode=0, stdout=("LIBTMUX_EPOCH epoch=2",)
    ... )
    >>> context = types.SimpleNamespace(
    ...     pane_ids=("%1",), activity_marker="epoch", activity_epoch=2,
    ...     heartbeat_epoch=2, lane=EngineLane.CONTROL,
    ... )
    >>> _accepted_capture(
    ...     context, plan, types.SimpleNamespace(results=(raw,)), "serial", 4
    ... ).line_count
    1

    Parameters
    ----------
    context : RunContext
        Initially stabilized run with exact pane IDs and frozen heartbeat epoch.
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
    _wait_pane_epoch_sync(context, heartbeat.epoch)
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
    await _wait_pane_epoch_async(context, heartbeat.epoch)
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


def _accepted_content_captures(
    context: RunContext,
    plan: LazyPlan,
    plan_result: object,
    *,
    token: str,
    epoch: int,
) -> tuple[PaneCapture, ...]:
    """Validate and canonically order one dedicated content snapshot.

    >>> context = types.SimpleNamespace(pane_ids=("%1",), delayed_pane_id="%1")
    >>> plan, _planner = _content_capture_plan(context)
    >>> result = plan.operations[0].build_result(
    ...     returncode=0,
    ...     stdout=("token", "LIBTMUX_EPOCH epoch=7"),
    ... )
    >>> _accepted_content_captures(
    ...     context, plan, types.SimpleNamespace(results=(result,)),
    ...     token="token", epoch=7,
    ... )
    (PaneCapture(pane_id='%1', lines=('token', 'LIBTMUX_EPOCH epoch=7')),)

    Parameters
    ----------
    context : RunContext
        Stable canonical pane order and unique delayed-pane identity.
    plan : LazyPlan
        Executed delayed-first content plan.
    plan_result : object
        Result sequence returned by the plan execution.
    token : str
        Exact fresh sentinel required once in the delayed pane only.
    epoch : int
        Frozen pre-request heartbeat epoch that every pane's latest exact
        parsed pulse must meet or exceed.

    Returns
    -------
    tuple[PaneCapture, ...]
        Immutable typed captures reordered to canonical stable pane order.

    Raises
    ------
    ValueError
        If the token or epoch is invalid.
    TypeError
        If an operation result is not a typed capture result.
    RuntimeError
        If cardinality, order, attribution, status, pulse, or sentinel evidence
        differs from the dedicated plan contract.
    """
    from libtmux.experimental.ops import CapturePane, CapturePaneResult, PaneId

    if not token:
        message = "content snapshot token must be nonempty"
        raise ValueError(message)
    if type(epoch) is not int or epoch < 0:
        message = "content snapshot epoch must be a nonnegative integer"
        raise ValueError(message)
    pane_ids = tuple(context.pane_ids)
    delayed_pane_id = context.delayed_pane_id
    if (
        not pane_ids
        or any(type(pane_id) is not str or not pane_id for pane_id in pane_ids)
        or len(set(pane_ids)) != len(pane_ids)
    ):
        message = "content snapshot requires nonempty unique stable pane IDs"
        raise ValueError(message)
    if type(delayed_pane_id) is not str or pane_ids.count(delayed_pane_id) != 1:
        message = "content snapshot requires exactly one stable delayed pane ID"
        raise ValueError(message)
    expected_targets = (
        delayed_pane_id,
        *(pane_id for pane_id in pane_ids if pane_id != delayed_pane_id),
    )
    operations = tuple(plan.operations)
    results = tuple(t.cast(t.Any, plan_result).results)
    if (
        len(operations) != len(pane_ids)
        or len(results) != len(operations)
        or not operations
    ):
        message = "content snapshot result count did not match stable pane IDs"
        raise RuntimeError(message)
    operation_targets = tuple(
        operation.target.value
        if isinstance(operation, CapturePane) and isinstance(operation.target, PaneId)
        else None
        for operation in operations
    )
    if operation_targets != expected_targets or len(set(operation_targets)) != len(
        operation_targets
    ):
        message = "content snapshot operation order did not match stable pane IDs"
        raise RuntimeError(message)
    for index, operation in enumerate(operations):
        if not isinstance(operation, CapturePane):
            message = "content snapshot operation was not a typed pane capture"
            raise TypeError(message)
        expected_start = (
            -_WAIT_CAPTURE_HISTORY_LINES
            if index == 0
            else -_MEASURED_CAPTURE_HISTORY_LINES
        )
        if operation.start != expected_start or operation.join_wrapped is not (
            index == 0
        ):
            message = "content snapshot operation flags differ from retention plan"
            raise RuntimeError(message)
    captures_by_id: dict[str, PaneCapture] = {}
    sentinel_counts: dict[str, int] = {}
    for operation, pane_id, result in zip(
        operations,
        expected_targets,
        results,
        strict=True,
    ):
        if not isinstance(result, CapturePaneResult):
            message = f"content snapshot for {pane_id} did not return typed lines"
            raise TypeError(message)
        if result.operation != operation:
            message = "content snapshot result order or target attribution differed"
            raise RuntimeError(message)
        result.raise_for_status()
        if max(_activity_frame_epochs(result.lines), default=-1) < epoch:
            message = (
                f"content snapshot for {pane_id} lacks current or newer epoch pulse"
            )
            raise RuntimeError(message)
        sentinel_counts[pane_id] = result.lines.count(token)
        captures_by_id[pane_id] = PaneCapture(pane_id, tuple(result.lines))
    if sentinel_counts.get(delayed_pane_id) != 1 or any(
        count != 0
        for pane_id, count in sentinel_counts.items()
        if pane_id != delayed_pane_id
    ):
        message = "content snapshot sentinel is not unique to the delayed pane"
        raise RuntimeError(message)
    return tuple(captures_by_id[pane_id] for pane_id in pane_ids)


def search_contents(
    captures: tuple[PaneCapture, ...],
    *,
    token: str,
    expected_pane_id: str | None,
) -> SearchResult:
    """Search retained typed capture lines for one exact sentinel token.

    >>> captures = (
    ...     PaneCapture("%1", ("token",)),
    ...     PaneCapture("%2", ("other",)),
    ... )
    >>> search_contents(
    ...     captures, token="token", expected_pane_id="%1"
    ... ).matched_ids
    ('%1',)

    Parameters
    ----------
    captures : tuple[PaneCapture, ...]
        Immutable prematerialized typed pane lines; no tmux I/O occurs here.
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
    matches = tuple(capture for capture in captures if token in capture.lines)
    duration_ns = time.perf_counter_ns() - started_ns
    return _search_result(
        family="contents",
        kind="panes",
        scanned_count=len(captures),
        target=expected_pane_id,
        matches=matches,
        duration_ns=duration_ns,
        token=token,
    )


async def _prepare_content_search_strategy(
    context: RunContext,
    *,
    request_id: str,
) -> cabc.Callable[[], SearchResult]:
    """Bind content search to one fresh sentinel and adjacent pane snapshot.

    >>> async def invalid_content_preparation():
    ...     try:
    ...         await _prepare_content_search_strategy(
    ...             types.SimpleNamespace(mode=None), request_id="search-1"
    ...         )
    ...     except ValueError as error:
    ...         return str(error)
    >>> asyncio.run(invalid_content_preparation())
    'content search preparation requires a benchmark execution mode'

    Parameters
    ----------
    context : RunContext
        Verified live topology whose wait transport and panes are authoritative.
    request_id : str
        Fresh run-scoped sentinel request identity.

    Returns
    -------
    collections.abc.Callable[[], SearchResult]
        Zero-argument search over the verified frozen token and capture.

    Raises
    ------
    ValueError
        If the context has no supported execution mode.
    RuntimeError
        If the fresh sentinel is not retained by exactly its delayed pane.
    """
    from libtmux.experimental.ops import CapturePane, CapturePaneResult, PaneId

    if context.mode not in (ExecutionMode.SYNC, ExecutionMode.ASYNC):
        message = "content search preparation requires a benchmark execution mode"
        raise ValueError(message)
    heartbeat = _current_activity_heartbeat(context, max_age_s=2.0)
    wait_result: WaitResult
    if context.mode is ExecutionMode.SYNC:
        _wait_pane_epoch_sync(context, heartbeat.epoch)
        wait_result = wait_capture_poll_sync(context, request_id=request_id)
    else:
        await _wait_pane_epoch_async(context, heartbeat.epoch)
        if context.lane is EngineLane.CONTROL:
            wait_result = await wait_control_stream(context, request_id=request_id)
        else:
            wait_result = await wait_capture_poll_async(
                context,
                request_id=request_id,
            )
    if not isinstance(wait_result, WaitResult):
        message = "content search wait did not return typed evidence"
        raise TypeError(message)
    if wait_result.pane_id != context.delayed_pane_id:
        message = "content search wait did not target the delayed pane"
        raise RuntimeError(message)
    deadline_ns = wait_result.requested_monotonic_ns + int(
        wait_result.timeout_s * 1_000_000_000
    )
    plan, planner = _content_capture_plan(context)
    first_step_completed = False

    def accept_first_step(report: t.Any) -> None:
        """Validate and timestamp the isolated delayed-pane planner step."""
        nonlocal first_step_completed
        if first_step_completed:
            return
        if report.step.indices != (0,) or len(report.results) != 1:
            message = "content snapshot first planner step was not operation zero"
            raise RuntimeError(message)
        result = report.results[0]
        operation = plan.operations[0]
        if (
            not isinstance(operation, CapturePane)
            or not isinstance(operation.target, PaneId)
            or operation.target.value != context.delayed_pane_id
            or not isinstance(result, CapturePaneResult)
            or result.operation != operation
        ):
            message = "content snapshot first result was not the delayed pane"
            raise RuntimeError(message)
        result.raise_for_status()
        completed_ns = time.monotonic_ns()
        if completed_ns > deadline_ns:
            message = "content snapshot delayed pane completed after request deadline"
            raise TimeoutError(message)
        first_step_completed = True

    if context.mode is ExecutionMode.SYNC:
        plan_result = plan.execute(
            t.cast("TmuxEngine", context.engine),
            planner=planner,
            on_step=accept_first_step,
        )
    else:

        async def accept_first_step_async(report: t.Any) -> None:
            """Awaitable adapter for the shared first-step deadline validator."""
            accept_first_step(report)

        plan_result = await plan.aexecute(
            t.cast("AsyncTmuxEngine", context.engine),
            planner=planner,
            on_step=accept_first_step_async,
        )
    if not first_step_completed:
        message = "content snapshot did not complete its delayed-pane step"
        raise RuntimeError(message)
    captures = _accepted_content_captures(
        context,
        plan,
        plan_result,
        token=wait_result.token,
        epoch=heartbeat.epoch,
    )
    search = functools.partial(
        search_contents,
        captures,
        token=wait_result.token,
        expected_pane_id=context.delayed_pane_id,
    )
    search()
    return search


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


def _repeatable_schedule(
    strategy_names: cabc.Iterable[str],
    *,
    warmup: int,
    runs: int,
    seed: int,
) -> tuple[tuple[t.Literal["warmup", "timed"], str, int], ...]:
    """Build the exact seeded, rotated repeatable-phase schedule.

    >>> _repeatable_schedule(("a", "b"), warmup=1, runs=1, seed=1)
    (('warmup', 'b', 0), ('warmup', 'a', 0), ('timed', 'a', 0), ('timed', 'b', 0))

    Parameters
    ----------
    strategy_names : collections.abc.Iterable[str]
        Strategy names in production mapping order.
    warmup : int
        Untimed invocation count per strategy.
    runs : int
        Timed invocation count per strategy.
    seed : int
        Seed used to shuffle the one base order.

    Returns
    -------
    tuple[tuple[typing.Literal, str, int], ...]
        Stage, strategy, and stage-local ordinal for every invocation.
    """
    base_order = list(strategy_names)
    random.Random(seed).shuffle(base_order)
    schedule: list[tuple[t.Literal["warmup", "timed"], str, int]] = []
    for cycle in range(warmup + runs):
        stage: t.Literal["warmup", "timed"] = "warmup" if cycle < warmup else "timed"
        ordinal = cycle if stage == "warmup" else cycle - warmup
        rotation = cycle % len(base_order)
        cycle_order = (*base_order[rotation:], *base_order[:rotation])
        schedule.extend((stage, strategy, ordinal) for strategy in cycle_order)
    return tuple(schedule)


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
    progress_callback: cabc.Callable[
        [str, str, int, PhaseMeasurement, RawSample | None], object
    ]
    | None = None,
    boundary_callback: cabc.Callable[[str], object] | None = None,
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
    progress_callback : collections.abc.Callable | None
        Private orchestration hook called after every accepted warmup or timed
        invocation. Timed calls receive the newly retained raw sample.
    boundary_callback : collections.abc.Callable | None
        Private hook called with the exact strategy before every invocation.

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
    samples: list[RawSample] = []
    order: list[str] = []
    for stage, strategy, ordinal in _repeatable_schedule(
        strategies,
        warmup=warmup,
        runs=runs,
        seed=seed,
    ):
        order.append(strategy)
        try:
            if boundary_callback is not None:
                await _await_if_needed(boundary_callback(strategy))
            resources_before = sampler()
            produced = strategies[strategy]()
            measurement = _validated_phase_measurement(await _await_if_needed(produced))
            postcondition = await _await_if_needed(live_postcondition(measurement))
            _require_live_postcondition(postcondition)
            resources_after = sampler()
            raw_sample: RawSample | None = None
            if stage == "timed":
                raw_sample = RawSample(
                    duration_ns=measurement.duration_ns,
                    accepted=True,
                    verified=True,
                    strategy=strategy,
                    ordinal=ordinal,
                    resources_before=resources_before,
                    resources_after=resources_after,
                )
                samples.append(raw_sample)
            if progress_callback is not None:
                await _await_if_needed(
                    progress_callback(
                        stage,
                        strategy,
                        ordinal,
                        measurement,
                        raw_sample,
                    )
                )
        except RuntimeCutoffError:
            raise
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
    registry = getattr(context, "process_handles", None)
    if registry is None:
        registry = _PidfdRegistry()
    registry.retain_many(context.processes)
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

    errors.extend(
        _kill_exact_tmux_socket(
            context.socket_path,
            timeout_s=grace_s,
            process_handles=registry,
            server_identity=next(
                (
                    identity
                    for identity in context.processes
                    if identity.role == "server"
                ),
                None,
            ),
            socket_ownership=context.socket_ownership,
        )
    )

    survivors = await _wait_for_process_absence(
        context.processes,
        timeout_s=grace_s,
        poll_child=context.fuzzer.poll,
    )
    for signal_number in (signal.SIGTERM, signal.SIGKILL):
        if not survivors:
            break
        for identity in survivors:
            if identity.role == "server":
                continue
            registry.signal(identity, signal_number)
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
    processes_absent = all(
        not process_identity_matches(identity) for identity in context.processes
    )
    socket_absent = not context.socket_path.exists()
    if processes_absent and socket_absent:
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
    else:
        if not processes_absent:
            errors.append("owned processes remain; retained scratch evidence")
        if not socket_absent:
            errors.append("configured socket remains; retained scratch evidence")
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
    errors.extend(registry.errors)
    registry.close()
    processes_absent = all(
        not process_identity_matches(identity) for identity in context.processes
    )
    socket_absent = not context.socket_path.exists()
    scratch_absent = not context.scratch.exists() and (
        context.socket_root is None or not context.socket_root.exists()
    )
    return CleanupReport(
        complete=(not errors and processes_absent and socket_absent and scratch_absent),
        errors=tuple(errors),
        processes_absent=processes_absent,
        socket_absent=socket_absent,
        scratch_absent=scratch_absent,
    )


class RuntimeCutoffError(RuntimeError):
    """A non-forceable live resource guard stopped the current run.

    Attributes
    ----------
    decision : GuardDecision
        Exact runtime guard observation that caused the cutoff.

    Examples
    --------
    >>> decision = GuardDecision(
    ...     False, "runtime_cutoff", "watchdog", None, None, False,
    ...     HostSnapshot(),
    ... )
    >>> RuntimeCutoffError(decision).decision.rule
    'watchdog'
    """

    def __init__(self, decision: GuardDecision) -> None:
        """Retain one non-forceable runtime decision.

        >>> decision = GuardDecision(
        ...     False, "runtime_cutoff", "memory_floor", 1, 2, False,
        ...     HostSnapshot(),
        ... )
        >>> str(RuntimeCutoffError(decision))
        'runtime cutoff: memory_floor'
        """
        self.decision = decision
        super().__init__(f"runtime cutoff: {decision.rule or 'unknown'}")


class PhaseExecutionError(RuntimeError):
    """A repeatable phase failed before producing all requested samples.

    Attributes
    ----------
    phase : str
        Exact cell that failed.
    failure : RepeatablePhaseFailure
        Stage, ordinal, and original error metadata.

    Examples
    --------
    >>> failure = RepeatablePhaseFailure("timed", "cell", 1, "RuntimeError: no")
    >>> PhaseExecutionError("cell", failure).phase
    'cell'
    """

    def __init__(self, phase: str, failure: RepeatablePhaseFailure) -> None:
        """Retain one typed repeatable failure.

        >>> failure = RepeatablePhaseFailure("warmup", "cell", 0, "ValueError: x")
        >>> str(PhaseExecutionError("cell", failure))
        'cell warmup 0 failed: ValueError: x'
        """
        self.phase = phase
        self.failure = failure
        super().__init__(
            f"{phase} {failure.stage} {failure.ordinal} failed: {failure.error}"
        )


def _collect_environment(
    *,
    seed: int,
    command_line: t.Sequence[str],
    include_tmux: bool = True,
) -> EnvironmentReport:
    """Collect descriptive version and checkout facts without contacting a server.

    >>> environment = _collect_environment(seed=11, command_line=("run",))
    >>> environment.seed, environment.command_line
    (11, ('run',))

    Parameters
    ----------
    seed : int
        Deterministic phase-order seed.
    command_line : collections.abc.Sequence[str]
        Public command arguments represented by the artifact.
    include_tmux : bool
        Whether admission has occurred and invoking ``tmux -V`` is permitted.

    Returns
    -------
    EnvironmentReport
        Local descriptive evidence with unavailable values retained as ``None``.
    """
    tmux_version: str | None = None
    git_revision: str | None = None
    if include_tmux:
        try:
            completed = subprocess.run(
                ("tmux", "-V"),
                check=False,
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if completed.returncode == 0:
                tmux_version = completed.stdout.strip() or None
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        completed = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=pathlib.Path(__file__).parents[1],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if completed.returncode == 0:
            git_revision = completed.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        pass
    return EnvironmentReport(
        python_version=platform.python_version(),
        tmux_version=tmux_version,
        cpu_count=os.cpu_count(),
        seed=seed,
        command_line=tuple(command_line),
        git_revision=git_revision,
    )


def _observation_for_measurement(
    strategy: str,
    ordinal: int,
    measurement: PhaseMeasurement,
) -> PhaseObservation:
    """Project one accepted typed measurement into stable JSON evidence.

    >>> measurement = EnumerationResult(
    ...     7, ExecutionMetrics(1, 1, 1, 1, 0), "sessions", 2,
    ...     ("$0", "$1"), "digest", True,
    ... )
    >>> _observation_for_measurement("enumeration.sessions", 0, measurement).row_count
    2

    Parameters
    ----------
    strategy : str
        Stable full phase name.
    ordinal : int
        Zero-based timed ordinal.
    measurement : PhaseMeasurement
        Verified typed Task 4 or Task 5 result.

    Returns
    -------
    PhaseObservation
        Counts sufficient for artifact validation without serializing operations.
    """
    if isinstance(measurement, MutationResult):
        return PhaseObservation(
            ordinal,
            strategy,
            measurement.duration_ns,
            metrics=measurement.metrics,
            session_count=1,
            window_count=len(measurement.window_ids),
            pane_count=len(measurement.pane_ids),
            target=measurement.session_id,
            verified=measurement.verified,
        )
    if isinstance(measurement, EnumerationResult):
        return PhaseObservation(
            ordinal,
            strategy,
            measurement.duration_ns,
            metrics=measurement.metrics,
            row_count=measurement.row_count,
            verified=measurement.verified,
        )
    if isinstance(measurement, CaptureResult):
        return PhaseObservation(
            ordinal,
            strategy,
            measurement.duration_ns,
            metrics=measurement.metrics,
            byte_count=measurement.byte_count,
            line_count=measurement.line_count,
            pane_count=len(measurement.captures),
            verified=measurement.verified,
        )
    if isinstance(measurement, SearchResult):
        return PhaseObservation(
            ordinal,
            strategy,
            measurement.duration_ns,
            scanned_count=measurement.scanned_count,
            matched_count=len(measurement.matched_ids),
            target=measurement.target,
            verified=measurement.verified,
        )
    return PhaseObservation(
        ordinal,
        strategy,
        measurement.duration_ns,
        poll_count=measurement.poll_count,
        frame_count=measurement.frame_count,
        dropped_notification_delta=measurement.dropped_notification_delta,
        configured_delay_ns=measurement.configured_delay_ns,
        scheduling_lateness_ns=measurement.scheduling_lateness_ns,
        detection_overhead_ns=measurement.detection_overhead_ns,
        target=measurement.pane_id,
        verified=measurement.verified,
    )


def _replace_phase(report: RunReport, phase: PhaseReport) -> RunReport:
    """Replace a named phase in place or append it while preserving order.

    >>> topology = Topology(1, 1, 1)
    >>> report = RunReport(topology, phases=(PhaseReport("a", topology, None),))
    >>> tuple(row.name for row in _replace_phase(
    ...     report, PhaseReport("b", topology, None)
    ... ).phases)
    ('a', 'b')
    """
    phases = list(report.phases)
    for index, existing in enumerate(phases):
        if existing.name == phase.name:
            phases[index] = phase
            break
    else:
        phases.append(phase)
    return dataclasses.replace(report, phases=tuple(phases))


def append_progress_event(path: pathlib.Path, event: ProgressEvent) -> None:
    """Durably append one complete JSON line without rewriting prior events.

    >>> with tempfile.TemporaryDirectory() as directory:
    ...     path = pathlib.Path(directory) / "progress.jsonl"
    ...     append_progress_event(path, ProgressEvent("run-7", 0, "start", 1))
    ...     json.loads(path.read_text(encoding="utf-8"))["sequence"]
    0

    Parameters
    ----------
    path : pathlib.Path
        Append-only worker-to-supervisor progress stream.
    event : ProgressEvent
        Complete event with only the identities first learned at this checkpoint.

    Returns
    -------
    None
        After bytes and the containing directory are synchronized.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(_json_value(event), separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()
    flags = os.O_APPEND | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    created = False
    try:
        descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
    except FileExistsError:
        descriptor = os.open(path, flags)
    try:
        remaining = memoryview(encoded)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                message = "zero-byte append to progress stream"
                raise OSError(message)
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if created:
        parent_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)


def _initialize_progress_journal(path: pathlib.Path) -> None:
    """Durably create an empty supervisor-owned progress journal.

    >>> with tempfile.TemporaryDirectory() as directory:
    ...     path = pathlib.Path(directory) / "progress.jsonl"
    ...     _initialize_progress_journal(path)
    ...     path.read_bytes()
    b''

    Parameters
    ----------
    path : pathlib.Path
        Fresh journal path created before the worker handoff begins.

    Returns
    -------
    None
        After the empty file and its parent directory are synchronized.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    parent_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent_descriptor)
    finally:
        os.close(parent_descriptor)


def _progress_event_from_json(value: object) -> ProgressEvent:
    """Decode and validate one complete progress line.

    >>> _progress_event_from_json({
    ...     "schema_version": 2, "run_id": "run-7", "sequence": 0,
    ...     "checkpoint": "start", "monotonic_ns": 1, "processes": [],
    ... }).checkpoint
    'start'
    """
    row = _json_mapping(value, "progress event")
    event = ProgressEvent(
        run_id=t.cast(str, row.get("run_id")),
        sequence=t.cast(int, row.get("sequence")),
        checkpoint=t.cast(str, row.get("checkpoint")),
        monotonic_ns=t.cast(int, row.get("monotonic_ns")),
        processes=tuple(_identity_from_json(item) for item in row.get("processes", [])),
        socket_ownership=_socket_ownership_from_json(row.get("socket_ownership")),
        schema_version=t.cast(int, row.get("schema_version")),
    )
    if (
        event.schema_version != _PROGRESS_SCHEMA_VERSION
        or not _is_terminal_safe_component(event.run_id)
        or type(event.sequence) is not int
        or event.sequence < 0
        or not event.checkpoint
        or type(event.monotonic_ns) is not int
        or event.monotonic_ns < 0
    ):
        message = "invalid progress event"
        raise ValueError(message)
    server_delta = tuple(
        identity for identity in event.processes if identity.role == "server"
    )
    if (event.socket_ownership is None and server_delta) or (
        event.socket_ownership is not None
        and server_delta != (event.socket_ownership.process,)
    ):
        message = "progress event lacks atomic server socket ownership"
        raise ValueError(message)
    return event


def _stall_until_reaped(max_seconds: float | None = None) -> None:
    """Wait to be cancelled, but never longer than the caller can outlive.

    ``--_test-stall-after`` parks a worker mid-run so the cancellation tests
    can prove the supervisor reaps it. The wait used to be ``while True``, which
    is correct only while the test is alive to do the reaping: a test that
    failed, timed out, or was interrupted left the worker stalled forever. That
    is not a quiet leak, because :func:`_preflight` refuses to start while any
    benchmark process is running -- so one orphan blocks every subsequent
    benchmark on the machine until reboot. Observed in practice: a stalled
    worker from a load-flaked test run was still parked 1h44m later, with its
    pytest temporary directory long deleted, and it refused three unrelated
    matrix runs.

    Two exits, both cheap: the parent going away means nobody is left to
    cancel, and the deadline covers the case where the parent survives but
    forgets.

    Parameters
    ----------
    max_seconds : float | None
        Longest to wait. ``None`` uses :data:`_STALL_MAX_S`; passing a value
        keeps the bound testable without patching a module global.

    Examples
    --------
    >>> _stall_until_reaped(0.0)
    """
    original_parent = os.getppid()
    limit = _STALL_MAX_S if max_seconds is None else max_seconds
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        # Reparenting is the portable signal that the spawner died.
        if os.getppid() != original_parent:
            return
        time.sleep(0.05)


@dataclasses.dataclass
class _WorkerRecorder:
    """Own worker checkpoints and the append-only progress sequence.

    Attributes
    ----------
    report : RunReport
        Current immutable report snapshot.
    checkpoint_path : pathlib.Path
        Worker-owned atomic checkpoint artifact.
    progress_path : pathlib.Path
        Append-only supervisor progress stream.
    stall_after : str | None
        Private test-harness checkpoint that deliberately stops progress.
    sequence : int
        Last published sequence number.
    identities : list[ProcessIdentity]
        Cumulative exact identities retained for one terminal report copy.

    Examples
    --------
    >>> with tempfile.TemporaryDirectory() as directory:
    ...     root = pathlib.Path(directory)
    ...     recorder = _WorkerRecorder(
    ...         RunReport(Topology(1, 1, 1)), root / "report.json",
    ...         root / "progress.jsonl",
    ...     )
    ...     recorder.checkpoint("start")
    ...     recorder.sequence
    0
    """

    report: RunReport
    checkpoint_path: pathlib.Path
    progress_path: pathlib.Path
    stall_after: str | None = None
    sequence: int = -1
    identities: list[ProcessIdentity] = dataclasses.field(default_factory=list)

    def checkpoint(
        self,
        name: str,
        *,
        identity_delta: tuple[ProcessIdentity, ...] = (),
        socket_ownership: _SocketOwnership | None = None,
    ) -> None:
        """Publish an increasing event before its matching report checkpoint.

        >>> with tempfile.TemporaryDirectory() as directory:
        ...     root = pathlib.Path(directory)
        ...     recorder = _WorkerRecorder(
        ...         RunReport(Topology(1, 1, 1)), root / "report.json",
        ...         root / "progress.jsonl",
        ...     )
        ...     recorder.checkpoint("one")
        ...     load_run_report(root / "report.json").progress_sequence
        0
        """
        self.sequence += 1
        self.report = dataclasses.replace(
            self.report,
            progress_sequence=self.sequence,
        )
        append_progress_event(
            self.progress_path,
            ProgressEvent(
                run_id=t.cast(str, self.report.run_id),
                sequence=self.sequence,
                checkpoint=name,
                monotonic_ns=time.monotonic_ns(),
                processes=identity_delta,
                socket_ownership=socket_ownership,
            ),
        )
        write_json_atomic(self.checkpoint_path, self.report)
        if self.stall_after == name:
            _stall_until_reaped()

    def record_identity(self, identity: ProcessIdentity) -> None:
        """Publish one exact identity once, at the moment it becomes known.

        >>> recorder = _WorkerRecorder(
        ...     RunReport(Topology(1, 1, 1), run_id="run-7"),
        ...     pathlib.Path("unused"), pathlib.Path("unused-progress"),
        ... )
        >>> recorder.identities.append(ProcessIdentity("worker", 2, 3))
        >>> len(recorder.identities)
        1
        """
        self.record_identities((identity,), checkpoint=f"identity.{identity.role}")

    def record_identities(
        self,
        identities: t.Iterable[ProcessIdentity],
        *,
        checkpoint: str | None = None,
    ) -> None:
        """Publish one constant-count or batched identity delta exactly once.

        >>> recorder = _WorkerRecorder(
        ...     RunReport(Topology(1, 1, 1), run_id="run-7"),
        ...     pathlib.Path("unused"), pathlib.Path("unused-progress"),
        ... )
        >>> recorder.identities.extend((ProcessIdentity("worker", 2, 3),))
        >>> len(recorder.identities)
        1

        Parameters
        ----------
        identities : collections.abc.Iterable[ProcessIdentity]
            Newly learned exact identities, possibly one verified pane batch.
        checkpoint : str | None
            Stable delta checkpoint label. When omitted, a homogeneous delta
            uses its role and a mixed delta uses ``identities``.
        """
        known = {
            (identity.role, identity.pid, identity.start_time)
            for identity in self.identities
        }
        delta: list[ProcessIdentity] = []
        for identity in identities:
            key = (identity.role, identity.pid, identity.start_time)
            if key in known:
                continue
            known.add(key)
            delta.append(identity)
        if not delta:
            return
        self.identities.extend(delta)
        if checkpoint is None:
            roles = {identity.role for identity in delta}
            role = roles.pop() if len(roles) == 1 else "identities"
            checkpoint = f"identity.{role}"
        self.checkpoint(checkpoint, identity_delta=tuple(delta))

    def record_socket_ownership(self, ownership: _SocketOwnership) -> None:
        """Durably publish the immutable server/socket capability once.

        Examples
        --------
        >>> with tempfile.TemporaryDirectory() as directory:
        ...     root = pathlib.Path(directory)
        ...     owner = _record_process("server", os.getpid())
        ...     socket_id = SocketIdentity(
        ...         1, 2, os.getuid(), stat.S_IFSOCK | 0o600, 4
        ...     )
        ...     recorder = _WorkerRecorder(
        ...         RunReport(Topology(1, 1, 1), run_id="run-7"),
        ...         root / "report.json", root / "progress.jsonl",
        ...     )
        ...     recorder.record_socket_ownership(
        ...         _SocketOwnership(owner, socket_id)
        ...     )
        ...     load_run_report(root / "report.json").processes == (owner,)
        True

        Parameters
        ----------
        ownership : _SocketOwnership
            Capability captured around the exact socket owner query.

        Raises
        ------
        RuntimeError
            If a different capability was already recorded for this run.
        """
        _validate_socket_ownership(ownership)
        existing = self.report.socket_ownership
        if existing is not None and existing != ownership:
            message = "worker socket ownership changed after establishment"
            raise RuntimeError(message)
        if existing is not None:
            return
        owner = ownership.process
        known_servers = tuple(
            identity for identity in self.identities if identity.role == "server"
        )
        if known_servers and known_servers != (owner,):
            message = "worker server identity changed before socket establishment"
            raise RuntimeError(message)
        if owner not in self.identities:
            self.identities.append(owner)
        self.report = dataclasses.replace(
            self.report,
            processes=_merge_identities(self.report.processes, (owner,)),
            socket_ownership=ownership,
        )
        self.checkpoint(
            "identity.server.socket",
            identity_delta=(owner,),
            socket_ownership=ownership,
        )


async def _worker_live_postcondition(
    context: RunContext,
    _measurement: PhaseMeasurement,
    policy: ResourcePolicy,
) -> bool:
    """Require live activity, owned processes, topology, and resource headroom.

    >>> async def invalid():
    ...     context = types.SimpleNamespace(
    ...         fuzzer=types.SimpleNamespace(poll=lambda: 1), processes=(),
    ...         topology_verified=True,
    ...     )
    ...     measurement = SearchResult(
    ...         1, "snapshot", "sessions", 1, "$0", ("$0",), verified=True
    ...     )
    ...     try:
    ...         await _worker_live_postcondition(context, measurement, ResourcePolicy())
    ...     except RuntimeError as error:
    ...         return str(error)
    >>> asyncio.run(invalid())
    'fuzzer exited during measured phase'

    Parameters
    ----------
    context : RunContext
        Active worker-owned topology.
    _measurement : PhaseMeasurement
        Independently typed and verified phase result.
    policy : ResourcePolicy
        Runtime PID and memory reserve configuration.

    Returns
    -------
    bool
        Exactly ``True`` after every independent live check passes.
    """
    _current_activity_heartbeat(context, max_age_s=2.0)
    snapshot = probe_host(ProcessReader())
    decision = check_runtime_guard(
        snapshot,
        policy=policy,
        processes_alive=all(
            process_identity_matches(identity) for identity in context.processes
        ),
        topology_verified=context.topology_verified,
        watchdog_ok=True,
        cleanup_complete=True,
    )
    if not decision.allowed:
        raise RuntimeCutoffError(decision)
    return True


def _completed_phase(phase: PhaseReport) -> PhaseReport:
    """Summarize all accepted raw rows and mark one repeatable cell complete.

    >>> topology = Topology(1, 1, 1)
    >>> sample = RawSample(3, True, verified=True, strategy="x", ordinal=0)
    >>> _completed_phase(PhaseReport(
    ...     "x", topology, topology, (sample,), status="in_progress", runs=1
    ... )).summary["count"]
    1
    """
    durations = tuple(
        t.cast(int, sample.duration_ns) for sample in phase.samples if sample.accepted
    )
    return dataclasses.replace(
        phase,
        status="completed",
        summary=summarize_ns(durations),
    )


async def _run_worker_group(
    recorder: _WorkerRecorder,
    context: RunContext,
    strategies: cabc.Mapping[str, cabc.Callable[[], object]],
    *,
    warmup: int,
    runs: int,
    seed: int,
    policy: ResourcePolicy,
    fail_after: str | None,
    active_phase: list[str],
) -> None:
    """Run one repeatable family lazily and checkpoint each accepted call.

    >>> async def empty_group():
    ...     try:
    ...         await _run_worker_group(
    ...             t.cast(_WorkerRecorder, None), t.cast(RunContext, None), {},
    ...             warmup=0, runs=1, seed=1, policy=ResourcePolicy(),
    ...             fail_after=None, active_phase=["setup"],
    ...         )
    ...     except ValueError as error:
    ...         return str(error)
    >>> asyncio.run(empty_group())
    'worker phase group requires strategies'

    Parameters
    ----------
    recorder : _WorkerRecorder
        Atomic checkpoint and append-only progress owner.
    context : RunContext
        Active topology used by every strategy.
    strategies : collections.abc.Mapping[str, collections.abc.Callable]
        Full phase names mapped to typed sync or async callables.
    warmup : int
        Untimed calls per cell.
    runs : int
        Timed accepted calls per cell.
    seed : int
        Deterministic family-order seed.
    policy : ResourcePolicy
        Runtime guard thresholds.
    fail_after : str | None
        Private test-harness phase that raises after its final checkpoint.
    active_phase : list[str]
        Single-item mutable exact boundary owned by :func:`run_worker`.

    Returns
    -------
    None
        After all cells retain exactly ``runs`` accepted samples.
    """
    if not strategies:
        message = "worker phase group requires strategies"
        raise ValueError(message)
    topology = context.topology

    strategy_names = tuple(strategies)
    prior_phases = recorder.report.phases
    phase_states: dict[str, PhaseReport] = {}

    def publish_active(strategy: str) -> None:
        completed = tuple(
            phase for phase in phase_states.values() if phase.status == "completed"
        )
        active = phase_states[strategy]
        active_suffix = () if active.status == "completed" else (active,)
        recorder.report = dataclasses.replace(
            recorder.report,
            phases=(*prior_phases, *completed, *active_suffix),
        )

    async def on_boundary(strategy: str) -> None:
        active_phase[0] = strategy
        if strategy in phase_states:
            publish_active(strategy)
        else:
            phase_states[strategy] = PhaseReport(
                name=strategy,
                requested_topology=topology,
                observed_topology=topology,
                status="in_progress",
                warmup=warmup,
                runs=runs,
            )
            publish_active(strategy)
        recorder.checkpoint(f"{strategy}.started")

    async def on_progress(
        stage: str,
        strategy: str,
        ordinal: int,
        measurement: PhaseMeasurement,
        sample: RawSample | None,
    ) -> None:
        phase = phase_states[strategy]
        observation = _observation_for_measurement(strategy, ordinal, measurement)
        if stage == "warmup":
            phase = dataclasses.replace(
                phase,
                warmup_observations=(*phase.warmup_observations, observation),
            )
        elif sample is not None:
            phase = dataclasses.replace(
                phase,
                samples=(*phase.samples, sample),
                observations=(*phase.observations, observation),
            )
            if ordinal == runs - 1:
                phase = _completed_phase(phase)
        phase_states[strategy] = phase
        checkpoint = (
            strategy
            if sample is not None and ordinal == runs - 1
            else f"{strategy}.{stage}.{ordinal}"
        )
        will_fail = checkpoint == strategy and fail_after == strategy
        if not will_fail and all(
            phase_states.get(name) is not None
            and phase_states[name].status == "completed"
            for name in strategy_names
        ):
            recorder.report = dataclasses.replace(
                recorder.report,
                phases=(
                    *prior_phases,
                    *(phase_states[name] for name in strategy_names),
                ),
            )
        else:
            publish_active(strategy)
        recorder.checkpoint(checkpoint)
        if will_fail:
            message = f"injected phase failure after {strategy}"
            raise RuntimeError(message)

    def retain_terminal_group(strategy: str, *, failed: bool) -> None:
        active = phase_states[strategy]
        if failed:
            active = dataclasses.replace(active, status="failed", summary=None)
        completed = tuple(
            phase
            for name, phase in phase_states.items()
            if name != strategy and phase.status == "completed"
        )
        recorder.report = dataclasses.replace(
            recorder.report,
            phases=(*prior_phases, *completed, active),
        )

    try:
        result = await run_repeatable_phase(
            strategies,
            warmup=warmup,
            runs=runs,
            seed=seed,
            snapshot_resources=lambda: probe_host(ProcessReader()),
            live_postcondition=lambda measurement: _worker_live_postcondition(
                context, measurement, policy
            ),
            progress_callback=on_progress,
            boundary_callback=on_boundary,
        )
    except RuntimeCutoffError:
        retain_terminal_group(active_phase[0], failed=False)
        raise
    if result.failure is not None:
        retain_terminal_group(result.failure.strategy, failed=True)
        recorder.checkpoint(f"{result.failure.strategy}.failed")
        raise PhaseExecutionError(result.failure.strategy, result.failure)


def _position_target(ids: tuple[str, ...], position: str) -> str:
    """Return the stable first, middle, or last concrete ID.

    >>> [_position_target(("a", "b", "c"), position) for position in _SEARCH_POSITIONS]
    ['a', 'b', 'c']

    Parameters
    ----------
    ids : tuple[str, ...]
        Nonempty stable concrete ID sequence.
    position : str
        One of ``first``, ``middle``, or ``last``.

    Returns
    -------
    str
        Concrete ID at the requested stable position.
    """
    if not ids:
        message = "search target sequence must be nonempty"
        raise ValueError(message)
    indices = {"first": 0, "middle": len(ids) // 2, "last": len(ids) - 1}
    try:
        return ids[indices[position]]
    except KeyError as error:
        message = f"unknown search position: {position}"
        raise ValueError(message) from error


_ShieldedResult = t.TypeVar("_ShieldedResult")


async def _drain_task_under_repeated_cancellation(
    task: asyncio.Task[_ShieldedResult],
    *,
    initial_cancellation: asyncio.CancelledError | None = None,
) -> tuple[_ShieldedResult, asyncio.CancelledError | None]:
    """Drain an independently owned task before re-raising first cancellation.

    >>> async def example():
    ...     task = asyncio.create_task(asyncio.sleep(0, result=7))
    ...     result, cancellation = await _drain_task_under_repeated_cancellation(task)
    ...     return result, cancellation
    >>> asyncio.run(example())
    (7, None)

    Parameters
    ----------
    task : asyncio.Task
        Independently owned finalization task that must reach a terminal state.
    initial_cancellation : asyncio.CancelledError | None
        Cancellation already caught before finalization began.

    Returns
    -------
    tuple[typing.Any, asyncio.CancelledError | None]
        Finalization result and the first cancellation to re-raise directly.

    Raises
    ------
    BaseException
        Finalization failure after the task has been drained.
    """
    cancellation = initial_cancellation
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:  # noqa: PERF203
            if cancellation is None:
                cancellation = error
        except BaseException:  # noqa: BLE001
            break
    return task.result(), cancellation


async def run_worker(
    topology: Topology,
    *,
    lane: EngineLane,
    mode: ExecutionMode,
    runs: int,
    warmup: int,
    seed: int,
    run_id: str,
    scratch: pathlib.Path,
    socket_path: pathlib.Path,
    checkpoint_path: pathlib.Path,
    progress_path: pathlib.Path,
    guard_decision: GuardDecision,
    original_guard_decision: GuardDecision,
    policy: ResourcePolicy,
    fuzzer_duration_s: float,
    watchdog_s: float,
    stall_after: str | None = None,
    fail_after: str | None = None,
    extra_identity: ProcessIdentity | None = None,
    orm: bool = False,
) -> RunReport:
    """Execute one complete worker phase graph with cleanup in ``finally``.

    The private injection arguments are a subprocess-only test harness. Public
    callers cannot select them through ``run`` or ``ramp`` help.

    >>> async def invalid_worker():
    ...     try:
    ...         await run_worker(
    ...             Topology(1, 1, 1), lane=EngineLane.CONTROL,
    ...             mode=ExecutionMode.ASYNC, runs=0, warmup=0, seed=11,
    ...             run_id="run-7", scratch=pathlib.Path("unused"),
    ...             socket_path=pathlib.Path("unused/sock"),
    ...             checkpoint_path=pathlib.Path("unused.json"),
    ...             progress_path=pathlib.Path("unused.jsonl"),
    ...             guard_decision=GuardDecision(
    ...                 True, "ok", None, None, None, False, HostSnapshot()
    ...             ),
    ...             original_guard_decision=GuardDecision(
    ...                 True, "ok", None, None, None, False, HostSnapshot()
    ...             ), policy=ResourcePolicy(), fuzzer_duration_s=300.0,
    ...             watchdog_s=120.0,
    ...         )
    ...     except ValueError as error:
    ...         return str(error)
    >>> asyncio.run(invalid_worker())
    'worker runs must be positive and warmup nonnegative'

    Parameters
    ----------
    topology : Topology
        Exact requested hierarchy.
    lane : EngineLane
        Subprocess or control transport.
    mode : ExecutionMode
        Synchronous or asynchronous dispatch.
    runs : int
        Timed samples for every repeatable cell.
    warmup : int
        Untimed samples for every repeatable cell.
    seed : int
        Deterministic interleaving seed.
    run_id : str
        Terminal-safe owner identity.
    scratch : pathlib.Path
        New exclusive private run directory.
    socket_path : pathlib.Path
        Exact scratch-contained tmux socket.
    checkpoint_path : pathlib.Path
        Worker-owned atomic report checkpoint.
    progress_path : pathlib.Path
        Append-only supervisor progress stream.
    guard_decision : GuardDecision
        Effective predictive admission decision.
    original_guard_decision : GuardDecision
        Unmodified predictive admission evidence.
    policy : ResourcePolicy
        Runtime guard thresholds.
    fuzzer_duration_s : float
        Exact finite active-service lifetime derived by the supervisor.
    watchdog_s : float
        Exact finite supervisor progress interval bounding pane readiness.
    stall_after : str | None
        Private test checkpoint that stops emitting progress.
    fail_after : str | None
        Private test phase that raises after completion.
    extra_identity : ProcessIdentity | None
        Private test identity published to prove PID-reuse safety.

    Returns
    -------
    RunReport
        Terminal worker candidate for supervisor validation and ownership.
    """
    if type(runs) is not int or runs <= 0 or type(warmup) is not int or warmup < 0:
        message = "worker runs must be positive and warmup nonnegative"
        raise ValueError(message)
    if not guard_decision.allowed:
        message = "worker cannot start after predictive refusal"
        raise ValueError(message)
    watchdog_seconds = _validated_watchdog_seconds(watchdog_s)
    if (
        isinstance(fuzzer_duration_s, bool)
        or not isinstance(fuzzer_duration_s, (int, float))
        or not math.isfinite(fuzzer_duration_s)
        or fuzzer_duration_s <= 0
    ):
        message = "worker fuzzer duration must be finite and positive"
        raise ValueError(message)
    environment = _collect_environment(
        seed=seed,
        command_line=(
            "run",
            "--shape",
            str(topology),
            "--lane",
            lane.value,
            "--mode",
            mode.value,
            "--runs",
            str(runs),
            "--warmup",
            str(warmup),
        ),
    )
    initial = RunReport(
        requested_topology=topology,
        status="in_progress",
        cleanup=CleanupReport(False),
        guard_decision=guard_decision,
        original_guard_decision=original_guard_decision,
        run_id=run_id,
        lane=lane.value,
        mode=mode.value,
        warmup=warmup,
        runs=runs,
        scratch_path=str(scratch),
        socket_path=str(socket_path),
        progress_path=str(progress_path),
        environment=environment,
        orm=orm,
    )
    recorder = _WorkerRecorder(
        initial,
        checkpoint_path,
        progress_path,
        stall_after=stall_after,
    )
    recorder.record_identities(
        (_record_process("worker", os.getpid()),),
        checkpoint="worker.started",
    )
    if extra_identity is not None:
        recorder.record_identity(extra_identity)
    context: RunContext | None = None
    terminal_status: t.Literal["completed", "failed", "cutoff"] = "completed"
    failed_phase: str | None = None
    terminal_error: str | None = None
    cleanup = CleanupReport(False)
    active_phase = ["setup"]
    cancellation: asyncio.CancelledError | None = None

    def fail_if_requested(phase: str) -> None:
        if fail_after == phase:
            message = f"injected phase failure after {phase}"
            raise RuntimeError(message)

    try:
        resources_before = probe_host(ProcessReader())
        panes_per_session = topology.windows_per_session * topology.panes_per_window
        delayed_ordinal = min(topology.panes // 2, panes_per_session - 1)
        if mode is ExecutionMode.SYNC:
            context = setup_sync(
                topology,
                lane,
                scratch,
                socket_path=socket_path,
                run_id=run_id,
                delayed_ordinal=delayed_ordinal,
                fuzzer_duration_s=float(fuzzer_duration_s),
                watchdog_s=watchdog_seconds,
                _process_identity_callback=recorder.record_identities,
                _socket_ownership_callback=recorder.record_socket_ownership,
            )
        else:
            context = await setup_async(
                topology,
                lane,
                scratch,
                socket_path=socket_path,
                run_id=run_id,
                delayed_ordinal=delayed_ordinal,
                fuzzer_duration_s=float(fuzzer_duration_s),
                watchdog_s=watchdog_seconds,
                _process_identity_callback=recorder.record_identities,
                _socket_ownership_callback=recorder.record_socket_ownership,
            )
        resources_after = probe_host(ProcessReader())
        setup_duration = max(1, context.setup_duration_ns)
        setup_sample = RawSample(
            setup_duration,
            True,
            verified=True,
            strategy="setup",
            ordinal=0,
            resources_before=resources_before,
            resources_after=resources_after,
        )
        setup_observation = PhaseObservation(
            ordinal=0,
            strategy="setup",
            duration_ns=setup_duration,
            metrics=context.setup_metrics,
            session_count=topology.sessions,
            window_count=topology.windows,
            pane_count=topology.panes,
        )
        recorder.report = dataclasses.replace(
            recorder.report,
            observed_topology=topology,
        )
        recorder.report = _replace_phase(
            recorder.report,
            PhaseReport(
                "setup",
                topology,
                topology,
                samples=(setup_sample,),
                summary=None,
                status="completed",
                warmup=0,
                runs=1,
                observations=(setup_observation,),
            ),
        )
        recorder.checkpoint("setup")
        fail_if_requested("setup")

        active_phase[0] = "stabilization"
        stabilization_started = time.perf_counter_ns()
        release_activity_gate(context)
        if mode is ExecutionMode.SYNC:
            verify_activity_sync(context)
        else:
            await verify_activity_async(context)
        stabilization_duration = max(1, time.perf_counter_ns() - stabilization_started)
        recorder.report = _replace_phase(
            recorder.report,
            PhaseReport(
                "stabilization",
                topology,
                topology,
                status="completed",
                observations=(
                    PhaseObservation(
                        0,
                        "stabilization",
                        stabilization_duration,
                        session_count=topology.sessions,
                        window_count=topology.windows,
                        pane_count=len(context.activity_pane_ids),
                    ),
                ),
            ),
        )
        recorder.checkpoint("stabilization")
        fail_if_requested("stabilization")

        mutation_counter = 0

        def mutation_sync_call() -> MutationResult:
            nonlocal mutation_counter
            mutation_counter += 1
            return mutate_sync(context, generation=mutation_counter)

        async def mutation_async_call() -> MutationResult:
            nonlocal mutation_counter
            mutation_counter += 1
            return await mutate_async(context, generation=mutation_counter)

        await _run_worker_group(
            recorder,
            context,
            {
                "mutation.bulk": (
                    mutation_sync_call
                    if mode is ExecutionMode.SYNC
                    else mutation_async_call
                )
            },
            warmup=warmup,
            runs=runs,
            seed=seed,
            policy=policy,
            fail_after=fail_after,
            active_phase=active_phase,
        )

        wait_counter = 0

        def next_request_id(strategy: str) -> str:
            nonlocal wait_counter
            wait_counter += 1
            compact = strategy.removeprefix("wait.").replace("-", "_")
            return f"{compact}-{wait_counter:04d}"

        def wait_sync_call() -> WaitResult:
            return wait_capture_poll_sync(
                context,
                request_id=next_request_id("wait.capture-poll"),
            )

        async def wait_async_call() -> WaitResult:
            return await wait_capture_poll_async(
                context,
                request_id=next_request_id("wait.capture-poll"),
            )

        async def wait_control_call() -> WaitResult:
            return await wait_control_stream(
                context,
                request_id=next_request_id("wait.control-stream"),
            )

        wait_strategies: dict[str, cabc.Callable[[], object]] = {
            "wait.capture-poll": (
                wait_sync_call if mode is ExecutionMode.SYNC else wait_async_call
            )
        }
        control_applicable = lane is EngineLane.CONTROL and mode is ExecutionMode.ASYNC
        if control_applicable:
            wait_strategies["wait.control-stream"] = wait_control_call
        await _run_worker_group(
            recorder,
            context,
            wait_strategies,
            warmup=warmup,
            runs=runs,
            seed=seed + 1,
            policy=policy,
            fail_after=fail_after,
            active_phase=active_phase,
        )
        if not control_applicable:
            active_phase[0] = "wait.control-stream"
            recorder.report = _replace_phase(
                recorder.report,
                PhaseReport(
                    "wait.control-stream",
                    topology,
                    topology,
                    status="not_applicable",
                    warmup=warmup,
                    runs=runs,
                ),
            )
            recorder.checkpoint("wait.control-stream")
            fail_if_requested("wait.control-stream")

        enumeration_strategies: dict[str, cabc.Callable[[], object]] = {}
        for kind in _ENUMERATION_KINDS:
            phase_name = f"enumeration.{kind}"
            enumeration_kind = t.cast("EnumerationKind", kind)
            if mode is ExecutionMode.SYNC:
                enumeration_strategies[phase_name] = functools.partial(
                    enumerate_sync,
                    context,
                    kind=enumeration_kind,
                )
            else:
                enumeration_strategies[phase_name] = functools.partial(
                    enumerate_async,
                    context,
                    kind=enumeration_kind,
                )
        if orm:
            for kind in _ENUMERATION_KINDS:
                enumeration_strategies[f"enumeration.orm.{kind}"] = functools.partial(
                    enumerate_orm,
                    context,
                    kind=t.cast("EnumerationKind", kind),
                )
        await _run_worker_group(
            recorder,
            context,
            enumeration_strategies,
            warmup=warmup,
            runs=runs,
            seed=seed + 2,
            policy=policy,
            fail_after=fail_after,
            active_phase=active_phase,
        )

        capture_strategies: dict[str, cabc.Callable[[], object]] = {}
        for strategy in ("serial", "batched"):
            phase_name = f"capture.{strategy}"
            if mode is ExecutionMode.SYNC:
                capture_strategies[phase_name] = functools.partial(
                    capture_all_sync,
                    context,
                    strategy=strategy,
                )
            else:
                capture_strategies[phase_name] = functools.partial(
                    capture_all_async,
                    context,
                    strategy=strategy,
                )
        await _run_worker_group(
            recorder,
            context,
            capture_strategies,
            warmup=warmup,
            runs=runs,
            seed=seed + 3,
            policy=policy,
            fail_after=fail_after,
            active_phase=active_phase,
        )

        from libtmux._internal.query_list import QueryList

        active_phase[0] = "search.classic.sessions.first"
        snapshot = (
            snapshot_topology_sync(context)
            if mode is ExecutionMode.SYNC
            else await snapshot_topology_async(context)
        )
        snapshot_rows = {
            "sessions": QueryList(snapshot.sessions),
            "windows": QueryList(snapshot.windows),
            "panes": QueryList(snapshot.panes),
        }
        ids_by_kind = {
            "sessions": context.session_ids,
            "windows": context.window_ids,
            "panes": context.pane_ids,
        }
        search_strategies: dict[str, cabc.Callable[[], object]] = {}
        for family in _SEARCH_FAMILIES:
            for kind in _ENUMERATION_KINDS:
                for position in _SEARCH_POSITIONS:
                    phase_name = f"search.{family}.{kind}.{position}"
                    target = _position_target(ids_by_kind[kind], position)
                    search_kind = t.cast("EnumerationKind", kind)
                    if family == "classic":
                        search_strategies[phase_name] = functools.partial(
                            search_server_side,
                            context,
                            kind=search_kind,
                            target=target,
                        )
                    elif family == "snapshot":
                        search_strategies[phase_name] = functools.partial(
                            search_snapshot,
                            snapshot_rows[kind],
                            kind=search_kind,
                            target=target,
                        )
                    else:
                        search_strategies[phase_name] = functools.partial(
                            search_end_to_end,
                            context,
                            kind=search_kind,
                            target=target,
                        )
        active_phase[0] = "search.contents"
        search_strategies["search.contents"] = await _prepare_content_search_strategy(
            context,
            request_id=next_request_id("search.contents"),
        )
        if lane is EngineLane.CONTROL and mode is ExecutionMode.ASYNC:
            from libtmux.experimental.engines import AsyncControlModeEngine

            control_engine = t.cast(AsyncControlModeEngine, context.engine)
            await control_engine.disable_output_notifications()
        await _run_worker_group(
            recorder,
            context,
            search_strategies,
            warmup=warmup,
            runs=runs,
            seed=seed + 4,
            policy=policy,
            fail_after=fail_after,
            active_phase=active_phase,
        )

        active_phase[0] = "verification"
        final_snapshot = (
            snapshot_topology_sync(context)
            if mode is ExecutionMode.SYNC
            else await snapshot_topology_async(context)
        )
        verify_topology(context, final_snapshot)
        recorder.checkpoint("verification")
        fail_if_requested("verification")
    except asyncio.CancelledError as error:
        cancellation = error
        terminal_status = "cutoff"
        failed_phase = "cancellation"
        terminal_error = f"CancelledError: {error}"
    except RuntimeCutoffError as error:
        terminal_status = "cutoff"
        failed_phase = error.decision.rule or "runtime_guard"
        terminal_error = str(error)
        recorder.report = dataclasses.replace(
            recorder.report, guard_decision=error.decision
        )
    except PhaseExecutionError as error:
        terminal_status = "failed"
        failed_phase = error.phase
        terminal_error = str(error)
    except BaseException as error:  # noqa: BLE001
        terminal_status = "failed"
        failed_phase = failed_phase or active_phase[0]
        terminal_error = f"{type(error).__name__}: {error}"
    finally:

        async def finalize_worker() -> None:
            nonlocal cleanup, terminal_status, failed_phase, terminal_error
            if context is not None:
                try:
                    cleanup = await cleanup_run(context)
                except BaseException as error:  # noqa: BLE001
                    cleanup = CleanupReport(
                        False,
                        (f"cleanup raised {type(error).__name__}: {error}",),
                        processes_absent=False,
                        socket_absent=not socket_path.exists(),
                        scratch_absent=not scratch.exists(),
                    )
            else:
                owned = tuple(
                    identity
                    for identity in recorder.identities
                    if identity.role != "worker" and identity is not extra_identity
                )
                processes_absent = all(
                    not process_identity_matches(identity) for identity in owned
                )
                socket_absent = not socket_path.exists()
                scratch_absent = not scratch.exists()
                cleanup = CleanupReport(
                    complete=(processes_absent and socket_absent and scratch_absent),
                    errors=(),
                    processes_absent=processes_absent,
                    socket_absent=socket_absent,
                    scratch_absent=scratch_absent,
                )
            if not cleanup.complete:
                terminal_status = "failed"
                failed_phase = failed_phase or "cleanup"
                cleanup_detail = "; ".join(cleanup.errors) or "cleanup incomplete"
                terminal_error = (
                    f"{terminal_error}; {cleanup_detail}"
                    if terminal_error
                    else cleanup_detail
                )
            recorder.report = dataclasses.replace(
                recorder.report,
                status=terminal_status,
                cleanup=cleanup,
                maximum_completed=(
                    terminal_status == "completed"
                    and topology == Topology(100, 100, 4)
                    and recorder.report.observed_topology == topology
                ),
                failed_phase=failed_phase,
                error=terminal_error,
            )
            recorder.checkpoint("cleanup")

        finalization = asyncio.create_task(
            finalize_worker(),
            name="orchestration-worker-finalization",
        )
        _result, deferred_cancellation = await _drain_task_under_repeated_cancellation(
            finalization,
            initial_cancellation=cancellation,
        )
        if deferred_cancellation is not None:
            raise deferred_cancellation
    return recorder.report


def _read_progress_chunk(
    path: pathlib.Path,
    offset: int,
    remainder: str,
    *,
    terminal: bool = False,
) -> tuple[tuple[ProgressEvent, ...], int, str]:
    """Read only newly appended complete JSONL records.

    >>> with tempfile.TemporaryDirectory() as directory:
    ...     path = pathlib.Path(directory) / "events.jsonl"
    ...     append_progress_event(path, ProgressEvent("run-7", 0, "start", 1))
    ...     events, offset, remainder = _read_progress_chunk(path, 0, "")
    ...     (events[0].sequence, offset > 0, remainder)
    (0, True, '')

    Parameters
    ----------
    path : pathlib.Path
        Append-only progress stream.
    offset : int
        Previously consumed byte offset.
    remainder : str
        Incomplete decoded line retained from the prior read.
    terminal : bool
        Whether the producer has exited and any incomplete tail is corruption.

    Returns
    -------
    tuple[tuple[ProgressEvent, ...], int, str]
        Complete events, new byte offset, and any incomplete final line.
    """
    try:
        with path.open("r", encoding="utf-8") as stream:
            stream.seek(offset)
            chunk = stream.read()
            new_offset = stream.tell()
    except FileNotFoundError as error:
        if terminal:
            message = "progress journal is missing at terminal drain"
            raise ValueError(message) from error
        return (), offset, remainder
    combined = remainder + chunk
    pieces = combined.split("\n")
    trailing = pieces.pop()
    if terminal and trailing:
        message = "progress journal has a torn terminal record"
        raise ValueError(message)
    try:
        events = tuple(
            _progress_event_from_json(json.loads(line)) for line in pieces if line
        )
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        message = "progress journal contains an invalid event"
        raise ValueError(message) from error
    return events, new_offset, trailing


def _wait_identity_absence(
    identities: t.Iterable[ProcessIdentity],
    *,
    timeout_s: float,
) -> tuple[ProcessIdentity, ...]:
    """Wait boundedly for exact identities without using process-name scans.

    >>> _wait_identity_absence((), timeout_s=0.01)
    ()
    """
    deadline = time.monotonic() + timeout_s
    identities_tuple = tuple(identities)
    while True:
        survivors = tuple(
            identity
            for identity in identities_tuple
            if process_identity_matches(identity)
        )
        if not survivors or time.monotonic() >= deadline:
            return survivors
        time.sleep(0.02)


def _remove_supervised_scratch(path: pathlib.Path) -> tuple[str, ...]:
    """Remove one exact private directory without following replacement links.

    >>> with tempfile.TemporaryDirectory() as directory:
    ...     path = pathlib.Path(directory) / "run"
    ...     _ = _acquire_private_directory(path)
    ...     _remove_supervised_scratch(path)
    ()
    """
    if not path.exists() and not path.is_symlink():
        return ()
    try:
        status = path.lstat()
        if stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
            return (f"scratch is not an owned directory: {path}",)
        if status.st_uid != os.getuid() or stat.S_IMODE(status.st_mode) != 0o700:
            return (f"scratch ownership or mode changed: {path}",)
        shutil.rmtree(path)
    except OSError as error:
        return (f"scratch removal: {type(error).__name__}: {error}",)
    return () if not path.exists() else (f"scratch remains: {path}",)


def _recover_supervised_run(
    worker: subprocess.Popen[bytes] | None,
    worker_identity: ProcessIdentity | None,
    progress: _ProgressTracker,
    *,
    scratch: pathlib.Path,
    socket_path: pathlib.Path,
    grace_s: float,
) -> CleanupReport:
    """Boundedly stop exact worker-owned processes and verify filesystem absence.

    >>> finished = subprocess.Popen((sys.executable, "-c", "pass"))
    >>> finished.wait(timeout=1)
    0
    >>> with tempfile.TemporaryDirectory() as directory:
    ...     root = pathlib.Path(directory)
    ...     journal = root / "progress.jsonl"
    ...     identity = ProcessIdentity("worker", finished.pid, -1)
    ...     append_progress_event(
    ...         journal, ProgressEvent("run-7", 0, "worker.started", 1)
    ...     )
    ...     registry = _PidfdRegistry()
    ...     progress = _ProgressTracker(journal, "run-7", registry)
    ...     report = _recover_supervised_run(
    ...         finished, identity, progress, scratch=root / "absent",
    ...         socket_path=root / "absent" / "sock", grace_s=0.01,
    ...     )
    ...     registry.close()
    ...     report.complete
    True

    Parameters
    ----------
    worker : subprocess.Popen[bytes] | None
        Direct child launched in its own session, or ``None`` when spawn failed.
    worker_identity : ProcessIdentity | None
        Exact group-leader identity captured immediately after spawn, if available.
    progress : _ProgressTracker
        Live journal state and stable handles for newly learned identities.
    scratch : pathlib.Path
        Exact private worker directory.
    socket_path : pathlib.Path
        Exact isolated tmux socket.
    grace_s : float
        Bounded graceful and escalated wait interval.

    Returns
    -------
    CleanupReport
        Exact identity, socket, and scratch absence evidence.
    """
    if grace_s <= 0:
        message = "supervisor cleanup grace must be positive"
        raise ValueError(message)
    errors: list[str] = []
    if worker_identity is not None:
        progress.handles.retain(worker_identity)

    def drain(*, terminal: bool = False) -> bool:
        try:
            return progress.drain(terminal=terminal)
        except (RuntimeError, ValueError) as error:
            detail = f"progress journal: {type(error).__name__}: {error}"
            if detail not in errors:
                errors.append(detail)
            return False

    def wait_worker() -> bool:
        if worker is None:
            return True
        deadline = time.monotonic() + grace_s
        while worker.poll() is None and time.monotonic() < deadline:
            drain()
            time.sleep(0.02)
        drain()
        return worker.poll() is not None

    drain()
    if worker is not None and worker.poll() is None:
        if worker_identity is None:
            errors.append("worker identity unavailable; exact signaling is impossible")
        else:
            progress.handles.signal(worker_identity, signal.SIGTERM)
    if not wait_worker() and worker_identity is not None:
        progress.handles.signal(worker_identity, signal.SIGKILL)
        if not wait_worker():
            errors.append("worker process did not exit")
    worker_absent = worker is None or worker.poll() is not None
    drain(terminal=worker_absent)
    unique: dict[tuple[int, int], ProcessIdentity] = {}
    initial_identities = (
        progress.identities
        if worker_identity is None
        else (worker_identity, *progress.identities)
    )
    for identity in initial_identities:
        unique[(identity.pid, identity.start_time)] = identity
    owned = tuple(unique.values())
    progress.handles.retain_many(owned)
    errors.extend(
        _kill_exact_tmux_socket(
            socket_path,
            timeout_s=grace_s,
            process_handles=progress.handles,
            server_identity=next(
                (identity for identity in owned if identity.role == "server"),
                None,
            ),
            socket_ownership=progress.socket_ownership,
        )
    )
    survivors = _wait_identity_absence(owned, timeout_s=grace_s)
    for signal_number in (signal.SIGTERM, signal.SIGKILL):
        if not survivors:
            break
        for identity in survivors:
            if identity.role == "server":
                continue
            progress.handles.signal(identity, signal_number)
        survivors = _wait_identity_absence(owned, timeout_s=grace_s)
    errors.extend(
        f"{identity.role} pid {identity.pid} with start time "
        f"{identity.start_time} remains"
        for identity in survivors
        if process_identity_matches(identity)
    )
    processes_absent = worker_absent and not any(
        process_identity_matches(identity) for identity in owned
    )
    socket_absent = not socket_path.exists()
    errors.extend(progress.handles.errors)
    if progress.journal_error is not None and not any(
        progress.journal_error in error for error in errors
    ):
        errors.append(f"progress journal: {progress.journal_error}")
    if not errors and processes_absent and socket_absent:
        errors.extend(_remove_supervised_scratch(scratch))
    scratch_absent = not scratch.exists()
    if not socket_absent:
        errors.append(f"socket remains: {socket_path}")
    return CleanupReport(
        complete=(not errors and processes_absent and socket_absent and scratch_absent),
        errors=tuple(errors),
        processes_absent=processes_absent,
        socket_absent=socket_absent,
        scratch_absent=scratch_absent,
    )


def _merge_identities(
    *groups: t.Iterable[ProcessIdentity],
) -> tuple[ProcessIdentity, ...]:
    """Deduplicate identities without collapsing different start times.

    >>> one = ProcessIdentity("worker", 2, 3)
    >>> _merge_identities((one,), (one,))
    (ProcessIdentity(role='worker', pid=2, start_time=3),)
    """
    merged: dict[tuple[str, int, int], ProcessIdentity] = {}
    for group in groups:
        for identity in group:
            merged[(identity.role, identity.pid, identity.start_time)] = identity
    return tuple(merged.values())


def _validate_progress_run_id(event: ProgressEvent, run_id: str) -> None:
    """Reject progress from any other supervised run.

    >>> _validate_progress_run_id(ProgressEvent("run", 0, "started", 1), "run")
    >>> _validate_progress_run_id(ProgressEvent("other", 0, "started", 1), "run")
    Traceback (most recent call last):
        ...
    RuntimeError: progress event run identity mismatch
    """
    if event.run_id != run_id:
        message = "progress event run identity mismatch"
        raise RuntimeError(message)


def _accept_progress_events(
    events: t.Iterable[ProgressEvent],
    *,
    run_id: str,
    highest_sequence: int,
    identities: tuple[ProcessIdentity, ...],
) -> tuple[int, tuple[ProcessIdentity, ...], bool]:
    """Accept only events that advance one supervised run's sequence.

    >>> event = ProgressEvent("run-7", 1, "setup", 10)
    >>> _accept_progress_events(
    ...     (event,), run_id="run-7", highest_sequence=1, identities=()
    ... )
    (1, (), False)

    Parameters
    ----------
    events : collections.abc.Iterable[ProgressEvent]
        Newly appended complete progress rows.
    run_id : str
        Exact supervised run identity.
    highest_sequence : int
        Highest sequence previously accepted.
    identities : tuple[ProcessIdentity, ...]
        Cumulative identities from previously accepted rows.

    Returns
    -------
    tuple[int, tuple[ProcessIdentity, ...], bool]
        New high-water sequence, identities, and whether progress increased.

    Raises
    ------
    RuntimeError
        If any event belongs to another run.
    """
    advanced = False
    for event in events:
        _validate_progress_run_id(event, run_id)
        if event.sequence <= highest_sequence:
            continue
        if event.sequence != highest_sequence + 1:
            message = (
                "progress journal sequence gap: expected "
                f"{highest_sequence + 1}, observed {event.sequence}"
            )
            raise RuntimeError(message)
        highest_sequence = event.sequence
        identities = _merge_identities(identities, event.processes)
        advanced = True
    return highest_sequence, identities, advanced


@dataclasses.dataclass
class _ProgressTracker:
    """Incrementally merge one journal while retaining newly learned pidfds.

    Attributes
    ----------
    path : pathlib.Path
        Append-only progress journal.
    run_id : str
        Exact producer identity accepted from every event.
    handles : _PidfdRegistry
        Registry that binds each accepted identity delta.
    identities : tuple[ProcessIdentity, ...]
        Cumulative identities retained once for the terminal report.
    socket_ownership : _SocketOwnership | None
        Immutable server/socket capability accepted from progress.
    highest_sequence : int
        Last strictly increasing accepted sequence.
    offset : int
        Consumed journal byte offset.
    remainder : str
        Incomplete active tail retained between reads.
    journal_error : str | None
        First corruption detected while draining.

    Examples
    --------
    >>> with tempfile.TemporaryDirectory() as directory:
    ...     root = pathlib.Path(directory)
    ...     registry = _PidfdRegistry()
    ...     tracker = _ProgressTracker(root / "missing", "run-7", registry)
    ...     tracker.drain()
    ...     registry.close()
    False
    """

    path: pathlib.Path
    run_id: str
    handles: _PidfdRegistry
    identities: tuple[ProcessIdentity, ...] = ()
    socket_ownership: _SocketOwnership | None = None
    highest_sequence: int = -1
    offset: int = 0
    remainder: str = ""
    journal_error: str | None = None

    def drain(self, *, terminal: bool = False) -> bool:
        """Accept new complete records and bind every accepted identity delta.

        >>> with tempfile.TemporaryDirectory() as directory:
        ...     root = pathlib.Path(directory)
        ...     path = root / "progress.jsonl"
        ...     append_progress_event(path, ProgressEvent("run-7", 0, "start", 1))
        ...     registry = _PidfdRegistry()
        ...     tracker = _ProgressTracker(path, "run-7", registry)
        ...     tracker.drain(terminal=True)
        ...     registry.close()
        True

        Parameters
        ----------
        terminal : bool
            Whether a missing journal or nonempty final tail is corruption.

        Returns
        -------
        bool
            Whether the highest accepted sequence increased.

        Raises
        ------
        RuntimeError
            If event ownership or sequence continuity is invalid.
        ValueError
            If terminal JSONL evidence is missing, torn, or malformed.
        """

        def merge_socket_ownership(
            events: tuple[ProgressEvent, ...],
            *,
            previous_highest: int,
            highest: int,
            identities: tuple[ProcessIdentity, ...],
        ) -> _SocketOwnership | None:
            ownership = self.socket_ownership
            for event in events:
                if not previous_highest < event.sequence <= highest:
                    continue
                observed = event.socket_ownership
                if observed is None:
                    continue
                if observed.process not in identities:
                    message = "socket ownership process is absent from progress"
                    raise RuntimeError(message)
                if ownership is not None and ownership != observed:
                    message = "socket ownership changed in progress"
                    raise RuntimeError(message)
                ownership = observed
            return ownership

        try:
            previous_highest = self.highest_sequence
            events, offset, remainder = _read_progress_chunk(
                self.path,
                self.offset,
                self.remainder,
                terminal=terminal,
            )
            highest, identities, advanced = _accept_progress_events(
                events,
                run_id=self.run_id,
                highest_sequence=self.highest_sequence,
                identities=self.identities,
            )
            socket_ownership = merge_socket_ownership(
                events,
                previous_highest=previous_highest,
                highest=highest,
                identities=identities,
            )
        except (RuntimeError, ValueError) as error:
            if self.journal_error is None:
                self.journal_error = f"{type(error).__name__}: {error}"
            raise
        self.offset = offset
        self.remainder = remainder
        self.highest_sequence = highest
        self.identities = identities
        self.socket_ownership = socket_ownership
        self.handles.retain_many(
            identity for event in events for identity in event.processes
        )
        return advanced


_FinalizerResult = t.TypeVar("_FinalizerResult")


def _drain_finalizer_thread(
    callback: cabc.Callable[[], _FinalizerResult],
    *,
    initial_interrupt: KeyboardInterrupt | None = None,
    interrupt_state: list[KeyboardInterrupt | None] | None = None,
    restore_handlers: cabc.Mapping[signal.Signals, t.Any] | None = None,
) -> tuple[_FinalizerResult, KeyboardInterrupt | None]:
    """Drain independent synchronous finalization through repeated interrupts.

    >>> result, interruption = _drain_finalizer_thread(lambda: 7)
    >>> result, interruption is None
    (7, True)

    Parameters
    ----------
    callback : collections.abc.Callable
        Recovery, report, or ramp finalization that must run to completion.
    initial_interrupt : KeyboardInterrupt | None
        First interruption already translated into terminal report state.
    interrupt_state : list[KeyboardInterrupt | None] | None
        Optional single-item state shared with an interruption-aware callback.
    restore_handlers : collections.abc.Mapping | None
        Exact caller handlers restored inside this protected ownership scope.
        Unspecified signals restore the handlers observed on entry.

    Returns
    -------
    tuple[typing.Any, KeyboardInterrupt | None]
        Finalization result and the first observed interruption.

    Raises
    ------
    BaseException
        Callback failure after its independently owned thread terminates.
    """
    if interrupt_state is None:
        interrupt_state = [initial_interrupt]
    elif len(interrupt_state) != 1:
        message = "finalizer interrupt state must contain exactly one item"
        raise ValueError(message)
    elif interrupt_state[0] is None:
        interrupt_state[0] = initial_interrupt
    results: list[_FinalizerResult] = []
    failures: list[BaseException] = []
    completed = threading.Event()
    launch_released = threading.Event()

    def run() -> None:
        try:
            launch_released.wait()
            results.append(callback())
        except BaseException as error:  # noqa: BLE001
            failures.append(error)
        finally:
            completed.set()

    thread = threading.Thread(
        target=run,
        name="orchestration-finalization",
    )

    def record_interrupt(error: KeyboardInterrupt) -> None:
        if interrupt_state[0] is None:
            interrupt_state[0] = error

    interruption_failures: list[BaseException] = []
    launch_failure: BaseException | None = None
    blocked = frozenset({signal.SIGINT, signal.SIGTERM})
    previous_handlers = {
        signal_number: signal.getsignal(signal_number) for signal_number in blocked
    }
    target_handlers = dict(previous_handlers)
    if restore_handlers is not None:
        unknown = set(restore_handlers) - set(blocked)
        if unknown:
            message = "finalizer restore handlers contain an unsupported signal"
            raise ValueError(message)
        target_handlers.update(restore_handlers)

    def record_signal(
        signal_number: int,
        frame: types.FrameType | None,
    ) -> None:
        previous = previous_handlers[signal.Signals(signal_number)]
        if previous == signal.SIG_IGN:
            return
        if callable(previous):
            try:
                previous(signal_number, frame)
            except KeyboardInterrupt as error:
                record_interrupt(error)
            except BaseException as error:  # noqa: BLE001
                interruption_failures.append(error)
            return
        message = f"received {signal.Signals(signal_number).name} during finalization"
        record_interrupt(KeyboardInterrupt(message))

    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
    installed_handlers: list[signal.Signals] = []
    try:
        for signal_number in blocked:
            signal.signal(signal_number, record_signal)
            installed_handlers.append(signal_number)
        try:
            thread.start()
        except KeyboardInterrupt as error:
            record_interrupt(error)
        except BaseException as error:  # noqa: BLE001
            launch_failure = error
    finally:
        while True:
            try:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
                break
            except KeyboardInterrupt as error:
                record_interrupt(error)
            except BaseException as error:  # noqa: BLE001
                if launch_failure is None:
                    launch_failure = error
                break

    launched = False
    while True:
        try:
            identity = thread.ident
            alive = thread.is_alive()
            launched = identity is not None or alive
            break
        except KeyboardInterrupt as error:
            record_interrupt(error)
        except RuntimeError:
            launched = thread.ident is not None
            break
    if launched:
        while True:
            try:
                launch_released.set()
                break
            except KeyboardInterrupt as error:
                record_interrupt(error)
        while True:
            try:
                if completed.is_set():
                    break
                completed.wait(timeout=0.02)
            except KeyboardInterrupt as error:
                record_interrupt(error)
        while True:
            try:
                alive = thread.is_alive()
            except KeyboardInterrupt as error:
                record_interrupt(error)
                continue
            except RuntimeError:
                alive = False
            if not alive:
                break
            try:
                thread.join(timeout=0.02)
            except KeyboardInterrupt as error:
                record_interrupt(error)
            except RuntimeError:
                pass

    final_result: _FinalizerResult | None = None
    callback_failure: BaseException | None = None
    while launched:
        try:
            if failures:
                callback_failure = failures[0]
            else:
                final_result = results[0]
            break
        except KeyboardInterrupt as error:
            record_interrupt(error)

    restore_failure: BaseException | None = None
    while True:
        try:
            signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
            break
        except KeyboardInterrupt as error:
            record_interrupt(error)
        except BaseException as error:  # noqa: BLE001
            restore_failure = error
            break
    for signal_number in reversed(installed_handlers):
        while True:
            try:
                signal.signal(signal_number, target_handlers[signal_number])
                break
            except KeyboardInterrupt as error:
                record_interrupt(error)
            except BaseException as error:  # noqa: BLE001
                if restore_failure is None:
                    restore_failure = error
                break
    while True:
        try:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            break
        except KeyboardInterrupt as error:
            record_interrupt(error)
        except BaseException as error:  # noqa: BLE001
            if restore_failure is None:
                restore_failure = error
            break

    interruption = interrupt_state[0]
    if not launched:
        if interruption is not None:
            raise interruption
        if launch_failure is not None:
            raise launch_failure
        message = "finalization thread did not launch"
        raise RuntimeError(message)
    if launch_failure is not None:
        if interruption is not None:
            raise interruption from launch_failure
        if callback_failure is not None:
            raise launch_failure from callback_failure
        raise launch_failure
    if callback_failure is not None:
        if interruption is not None:
            raise interruption from callback_failure
        raise callback_failure
    if interruption_failures:
        raise interruption_failures[0]
    if restore_failure is not None:
        if interruption is not None:
            raise interruption from restore_failure
        raise restore_failure
    return t.cast(_FinalizerResult, final_result), interruption


def _finalize_supervised_worker(
    worker: subprocess.Popen[bytes] | None,
    worker_identity: ProcessIdentity | None,
    progress: _ProgressTracker,
    *,
    topology: Topology,
    lane: EngineLane,
    mode: ExecutionMode,
    runs: int,
    warmup: int,
    seed: int,
    run_id: str,
    scratch: pathlib.Path,
    socket_path: pathlib.Path,
    output: pathlib.Path,
    markdown_output: pathlib.Path,
    checkpoint_path: pathlib.Path,
    admission_path: pathlib.Path,
    guard_decision: GuardDecision,
    original_guard_decision: GuardDecision,
    cleanup_grace_s: float,
    supervisor_status: t.Literal["failed", "cutoff"] | None,
    failed_phase: str | None,
    terminal_error: str | None,
) -> RunReport:
    """Recover, terminally drain, validate, and render one supervised worker.

    >>> _finalize_supervised_worker.__name__
    '_finalize_supervised_worker'

    Returns
    -------
    RunReport
        Durable supervisor-owned terminal artifact.
    """
    try:
        if supervisor_status is not None:
            cleanup = _recover_supervised_run(
                worker,
                worker_identity,
                progress,
                scratch=scratch,
                socket_path=socket_path,
                grace_s=cleanup_grace_s,
            )
        elif worker is not None:
            worker.wait()
            try:
                progress.drain(terminal=True)
            except (RuntimeError, ValueError) as error:
                supervisor_status = "failed"
                failed_phase = "supervisor"
                terminal_error = f"{type(error).__name__}: {error}"
            if supervisor_status is not None:
                cleanup = _recover_supervised_run(
                    worker,
                    worker_identity,
                    progress,
                    scratch=scratch,
                    socket_path=socket_path,
                    grace_s=cleanup_grace_s,
                )
            else:
                processes_absent = not any(
                    process_identity_matches(item) for item in progress.identities
                )
                socket_absent = not socket_path.exists()
                scratch_absent = not scratch.exists()
                cleanup = CleanupReport(
                    complete=(
                        processes_absent
                        and socket_absent
                        and scratch_absent
                        and not progress.handles.errors
                    ),
                    errors=tuple(progress.handles.errors),
                    processes_absent=processes_absent,
                    socket_absent=socket_absent,
                    scratch_absent=scratch_absent,
                )
            if not cleanup.complete:
                cleanup = _recover_supervised_run(
                    worker,
                    worker_identity,
                    progress,
                    scratch=scratch,
                    socket_path=socket_path,
                    grace_s=cleanup_grace_s,
                )
        else:
            supervisor_status = "failed"
            failed_phase = failed_phase or "supervisor"
            terminal_error = terminal_error or "worker was not spawned"
            cleanup = _recover_supervised_run(
                worker,
                worker_identity,
                progress,
                scratch=scratch,
                socket_path=socket_path,
                grace_s=cleanup_grace_s,
            )

        try:
            candidate = load_run_report(checkpoint_path)
        except (OSError, ValueError):
            candidate = RunReport(
                topology,
                status="in_progress",
                cleanup=CleanupReport(False),
                guard_decision=guard_decision,
                original_guard_decision=original_guard_decision,
                run_id=run_id,
                lane=lane.value,
                mode=mode.value,
                warmup=warmup,
                runs=runs,
                scratch_path=str(scratch),
                socket_path=str(socket_path),
                progress_path=str(progress.path),
                environment=_collect_environment(
                    seed=seed, command_line=("run", "--shape", str(topology))
                ),
            )
        if supervisor_status is None:
            assert worker is not None
            if worker.returncode == 0 and candidate.status == "completed":
                final_status: t.Literal["completed", "failed", "cutoff"] = "completed"
            elif candidate.status == "cutoff":
                final_status = "cutoff"
            else:
                final_status = "failed"
            if final_status != "completed":
                failed_phase = candidate.failed_phase or "worker"
                terminal_error = candidate.error or f"worker exited {worker.returncode}"
        else:
            final_status = supervisor_status
        if not cleanup.complete:
            final_status = "failed"
            failed_phase = "cleanup"
            detail = "; ".join(cleanup.errors) or "cleanup verification failed"
            terminal_error = f"{terminal_error}; {detail}" if terminal_error else detail
        final_report = dataclasses.replace(
            candidate,
            status=final_status,
            cleanup=cleanup,
            maximum_completed=(
                final_status == "completed"
                and topology == Topology(100, 100, 4)
                and candidate.observed_topology == topology
            ),
            failed_phase=(None if final_status == "completed" else failed_phase),
            error=(None if final_status == "completed" else terminal_error),
            processes=progress.identities,
            socket_ownership=progress.socket_ownership,
            progress_path=str(progress.path),
            progress_sequence=progress.highest_sequence,
            guard_decision=(
                candidate.guard_decision
                if candidate.guard_decision is not None
                else guard_decision
            ),
            original_guard_decision=original_guard_decision,
        )
        write_json_atomic(output, final_report)
        validate_report(final_report)
        render_markdown_summary(output, markdown_output)
        admission_path.unlink(missing_ok=True)
        return final_report
    finally:
        progress.handles.close()


def _publish_interrupted_supervisor_report(
    report: RunReport,
    output: pathlib.Path,
    markdown_output: pathlib.Path,
) -> RunReport:
    """Replace a post-work completion with durable cancellation evidence.

    >>> _publish_interrupted_supervisor_report.__name__
    '_publish_interrupted_supervisor_report'

    Returns
    -------
    RunReport
        Validated cutoff report with the already verified cleanup evidence.
    """
    interrupted = dataclasses.replace(
        report,
        status="cutoff",
        maximum_completed=False,
        failed_phase="cancellation",
        error="KeyboardInterrupt: supervisor interrupted during finalization",
    )
    write_json_atomic(output, interrupted)
    validate_report(interrupted)
    render_markdown_summary(output, markdown_output)
    return interrupted


def supervise_worker(
    topology: Topology,
    *,
    lane: EngineLane,
    mode: ExecutionMode,
    runs: int,
    warmup: int,
    seed: int,
    run_id: str,
    scratch: pathlib.Path,
    socket_path: pathlib.Path,
    output: pathlib.Path,
    markdown_output: pathlib.Path,
    guard_decision: GuardDecision,
    original_guard_decision: GuardDecision,
    policy: ResourcePolicy,
    watchdog_s: float,
    cleanup_grace_s: float,
    orm: bool = False,
    _test_stall_after: str | None = None,
    _test_fail_after: str | None = None,
    _test_extra_identity: ProcessIdentity | None = None,
) -> RunReport:
    """Launch and supervise the hidden worker with a sequence-based watchdog.

    The ``_test_*`` arguments are private CLI injection points used only by the
    benchmark's subprocess recovery tests. Artifact ownership linearizes when
    the sole finalizer has durably written and validated JSON and Markdown,
    applied any already observed cutoff, and commits that result back to the
    caller. A later signal is re-raised without rewriting committed evidence.

    >>> try:
    ...     supervise_worker(
    ...         Topology(1, 1, 1), lane=EngineLane.CONTROL,
    ...         mode=ExecutionMode.ASYNC, runs=1, warmup=0, seed=11,
    ...         run_id="run-7", scratch=pathlib.Path("scratch"),
    ...         socket_path=pathlib.Path("scratch/sock"),
    ...         output=pathlib.Path("report.json"),
    ...         markdown_output=pathlib.Path("report.md"),
    ...         guard_decision=GuardDecision(
    ...             True, "ok", None, None, None, False, HostSnapshot()
    ...         ),
    ...         original_guard_decision=GuardDecision(
    ...             True, "ok", None, None, None, False, HostSnapshot()
    ...         ), policy=ResourcePolicy(), watchdog_s=0,
    ...         cleanup_grace_s=1,
    ...     )
    ... except ValueError as error:
    ...     print(error)
    watchdog interval must be finite and positive

    Returns
    -------
    RunReport
        Supervisor-owned terminal report.
    """
    watchdog_seconds = _validated_watchdog_seconds(watchdog_s)
    if cleanup_grace_s <= 0:
        message = "supervisor cleanup grace must be positive"
        raise ValueError(message)
    fuzzer_duration_s = _fuzzer_duration_budget_s(
        lane=lane,
        mode=mode,
        runs=runs,
        warmup=warmup,
        watchdog_s=watchdog_seconds,
        cleanup_grace_s=cleanup_grace_s,
        orm=orm,
    )
    progress_path = output.with_name(f"{output.stem}.{run_id}.progress.jsonl")
    checkpoint_path = output.with_name(f".{output.name}.{run_id}.worker.json")
    admission_path = output.with_name(f".{output.name}.{run_id}.admission.json")
    command = [
        sys.executable,
        str(pathlib.Path(__file__)),
        "_worker",
        "--shape",
        str(topology),
        "--lane",
        lane.value,
        "--mode",
        mode.value,
        "--runs",
        str(runs),
        "--warmup",
        str(warmup),
        "--seed",
        str(seed),
        "--run-id",
        run_id,
        "--scratch",
        str(scratch),
        "--socket-path",
        str(socket_path),
        "--checkpoint",
        str(checkpoint_path),
        "--progress",
        str(progress_path),
        "--admission",
        str(admission_path),
        "--pid-reserve",
        str(policy.pid_reserve) if policy.pid_reserve is not None else "dynamic",
        "--memory-floor-bytes",
        (
            str(policy.memory_floor_bytes)
            if policy.memory_floor_bytes is not None
            else "dynamic"
        ),
        "--service-duration-seconds",
        str(fuzzer_duration_s),
        "--watchdog-seconds",
        str(watchdog_seconds),
    ]
    if orm:
        command.append("--with-orm")
    if _test_stall_after is not None:
        command.extend(("--_test-stall-after", _test_stall_after))
    if _test_fail_after is not None:
        command.extend(("--_test-fail-after", _test_fail_after))
    if _test_extra_identity is not None:
        serialized_identity = ":".join(
            (
                _test_extra_identity.role,
                str(_test_extra_identity.pid),
                str(_test_extra_identity.start_time),
            )
        )
        command.extend(
            (
                "--_test-extra-identity",
                serialized_identity,
            )
        )
    environment = os.environ.copy()
    environment.pop("TMUX", None)
    environment.pop("TMUX_PANE", None)
    capability_error = _pidfd_capability_error()
    if capability_error is not None:
        raise RuntimeError(capability_error)
    if threading.current_thread() is not threading.main_thread():
        message = "supervisor worker handoff requires the main thread"
        raise RuntimeError(message)
    worker: subprocess.Popen[bytes] | None = None
    worker_identity: ProcessIdentity | None = None
    handles = _PidfdRegistry()
    progress = _ProgressTracker(
        progress_path,
        run_id,
        handles,
    )
    deadline = time.monotonic() + watchdog_seconds
    supervisor_status: t.Literal["failed", "cutoff"] | None = None
    failed_phase: str | None = None
    terminal_error: str | None = None
    interruption: KeyboardInterrupt | None = None
    previous_sigterm_handler = signal.getsignal(signal.SIGTERM)

    def request_termination(
        signal_number: int,
        _frame: types.FrameType | None,
    ) -> t.NoReturn:
        message = f"received {signal.Signals(signal_number).name}"
        raise KeyboardInterrupt(message)

    signal.signal(signal.SIGTERM, request_termination)
    try:
        _initialize_progress_journal(progress_path)
        write_json_atomic(
            admission_path,
            {
                "guard_decision": guard_decision,
                "original_guard_decision": original_guard_decision,
            },
        )
        blocked = frozenset({signal.SIGINT, signal.SIGTERM})
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
        handoff_failure: BaseException | None = None
        try:
            worker = subprocess.Popen(
                command,
                cwd=pathlib.Path(__file__).parents[1],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            worker_identity = _record_process("worker", worker.pid)
            if not handles.retain(worker_identity):
                message = "cannot retain stable worker pidfd during handoff"
                raise RuntimeError(message)  # noqa: TRY301
            progress.identities = (worker_identity,)
        except BaseException as error:  # noqa: BLE001
            handoff_failure = error
            if worker is not None:
                try:
                    if worker_identity is None:
                        worker_identity = _record_process("worker", worker.pid)
                    if handles.retain(worker_identity):
                        progress.identities = _merge_identities(
                            progress.identities,
                            (worker_identity,),
                        )
                except BaseException as recovery_error:  # noqa: BLE001
                    handles.errors.append(
                        "worker pidfd handoff recovery: "
                        f"{type(recovery_error).__name__}: {recovery_error}"
                    )
        finally:
            try:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            except BaseException as error:  # noqa: BLE001
                if handoff_failure is None:
                    handoff_failure = error
        if handoff_failure is not None:
            raise handoff_failure  # noqa: TRY301
        assert worker is not None
        while worker.poll() is None:
            advanced = progress.drain()
            if advanced:
                deadline = time.monotonic() + watchdog_seconds
            if time.monotonic() >= deadline:
                supervisor_status = "cutoff"
                failed_phase = "watchdog"
                terminal_error = (
                    f"progress watchdog expired after {watchdog_seconds} seconds"
                )
                break
            time.sleep(0.02)
    except KeyboardInterrupt as error:
        interruption = error
        supervisor_status = "cutoff"
        failed_phase = "cancellation"
        terminal_error = "KeyboardInterrupt: supervisor interrupted"
    except BaseException as error:  # noqa: BLE001
        supervisor_status = "failed"
        failed_phase = "supervisor"
        terminal_error = f"{type(error).__name__}: {error}"

    interrupt_state = [interruption]
    artifact_committed = [False]

    def finalize_once() -> RunReport:
        final_report = _finalize_supervised_worker(
            worker,
            worker_identity,
            progress,
            topology=topology,
            lane=lane,
            mode=mode,
            runs=runs,
            warmup=warmup,
            seed=seed,
            run_id=run_id,
            scratch=scratch,
            socket_path=socket_path,
            output=output,
            markdown_output=markdown_output,
            checkpoint_path=checkpoint_path,
            admission_path=admission_path,
            guard_decision=guard_decision,
            original_guard_decision=original_guard_decision,
            cleanup_grace_s=cleanup_grace_s,
            supervisor_status=supervisor_status,
            failed_phase=failed_phase,
            terminal_error=terminal_error,
        )
        if interrupt_state[0] is not None and (
            final_report.cleanup.complete
            and not any(phase.status == "failed" for phase in final_report.phases)
            and (
                final_report.status != "cutoff"
                or final_report.failed_phase != "cancellation"
            )
        ):
            final_report = _publish_interrupted_supervisor_report(
                final_report,
                output,
                markdown_output,
            )
        artifact_committed[0] = True
        return final_report

    final_report, deferred_interruption = _drain_finalizer_thread(
        finalize_once,
        initial_interrupt=interruption,
        interrupt_state=interrupt_state,
        restore_handlers={signal.SIGTERM: previous_sigterm_handler},
    )
    if not artifact_committed[0]:
        message = "supervisor finalizer returned without committing artifacts"
        raise RuntimeError(message)
    if deferred_interruption is not None:
        raise deferred_interruption
    return final_report


def _write_text_atomic(path: pathlib.Path, text: str) -> None:
    r"""Atomically and durably replace one UTF-8 text artifact.

    >>> with tempfile.TemporaryDirectory() as directory:
    ...     path = pathlib.Path(directory) / "summary.md"
    ...     _write_text_atomic(path, "summary\n")
    ...     path.read_text(encoding="utf-8")
    'summary\n'
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: pathlib.Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = pathlib.Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        temporary = None
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _format_ns(value: float) -> str:
    """Render integer nanoseconds as compact descriptive milliseconds.

    >>> _format_ns(1_500_000)
    '1.500 ms'
    """
    return f"{float(value) / 1_000_000:.3f} ms"


def _format_cleanup_fact(value: bool | None) -> str:
    """Render one cleanup fact without conflating unknown with false.

    >>> _format_cleanup_fact(True)
    'true'
    >>> _format_cleanup_fact(None)
    'unknown'

    Parameters
    ----------
    value : bool | None
        Verified absence fact or unavailable evidence.

    Returns
    -------
    str
        Lowercase truth value or ``unknown``.
    """
    return "unknown" if value is None else str(value).lower()


def _redact_owned_paths(value: str | None, report: RunReport) -> str:
    """Remove known or explicit absolute local paths from summary prose.

    >>> report = RunReport(Topology(1, 1, 1), scratch_path="/tmp/private")
    >>> _redact_owned_paths("failed at /tmp/private", report)
    'failed at [owned path]'

    Parameters
    ----------
    value : str | None
        Terminal or ramp-step reason intended for Markdown.
    report : RunReport
        Root report carrying known owned resource identities.

    Returns
    -------
    str
        Reason with owned and remaining absolute path tokens redacted.
    """
    if value is None:
        return ""
    owned_paths = {
        path
        for path in (report.scratch_path, report.socket_path, report.progress_path)
        if path
    }
    owned_paths.update(
        path
        for step in report.ramp
        for path in (step.scratch_path, step.socket_path)
        if path
    )
    redacted = value
    for owned_path in sorted(owned_paths, key=len, reverse=True):
        redacted = redacted.replace(owned_path, "[owned path]")
    redacted = re.sub(
        r"(?P<quote>['\"])/[^'\"\r\n]+(?P=quote)",
        lambda match: f"{match.group('quote')}[owned path]{match.group('quote')}",
        redacted,
    )
    redacted = re.sub(r"`/[^`\r\n]+`", "`[owned path]`", redacted)
    return re.sub(r"(?<![\w.])/(?:[^\r\n|`]+)", "[owned path]", redacted)


def _markdown_cell(value: str | None, report: RunReport) -> str:
    r"""Return redacted single-line text safe inside a Markdown table cell.

    >>> report = RunReport(Topology(1, 1, 1), scratch_path="/tmp/private path")
    >>> _markdown_cell("bad | row\n`/tmp/private path`", report)
    'bad \\| row<br>&#96;[owned path]&#96;'

    Parameters
    ----------
    value : str | None
        Reason, error, or relative artifact reference intended for Markdown.
    report : RunReport
        Root report carrying modeled owned paths.

    Returns
    -------
    str
        Redacted text with row delimiters and newlines neutralized.
    """
    redacted = html.escape(_redact_owned_paths(value, report), quote=False)
    return (
        redacted.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "<br>")
        .replace("|", r"\|")
        .replace("`", "&#96;")
    )


def render_markdown_summary(
    report_path: pathlib.Path,
    output_path: pathlib.Path | None = None,
) -> str:
    """Render only a validated JSON artifact as local descriptive evidence.

    >>> with tempfile.TemporaryDirectory() as directory:
    ...     root = pathlib.Path(directory)
    ...     path = root / "report.json"
    ...     report = RunReport(
    ...         Topology(1, 1, 1), status="refused",
    ...         cleanup=CleanupReport(
    ...             True, processes_absent=True, socket_absent=True,
    ...             scratch_absent=True,
    ...         ), run_id="run-7", lane="control", mode="async", warmup=0,
    ...         runs=1, failed_phase="preflight", error="predictive refusal",
    ...         guard_decision=GuardDecision(
    ...             False, "predictive_refusal", "pid_reserve", 2, 1, True,
    ...             HostSnapshot(),
    ...         ),
    ...     )
    ...     write_json_atomic(path, report)
    ...     "Local descriptive evidence" in render_markdown_summary(path)
    True

    Parameters
    ----------
    report_path : pathlib.Path
        Complete machine-readable JSON artifact.
    output_path : pathlib.Path | None
        Optional Markdown destination.

    Returns
    -------
    str
        Markdown summary explicitly limited to local descriptive evidence.

    Raises
    ------
    ValueError
        If JSON or its recomputed report contract is invalid.
    """
    report = validate_report_artifact(report_path)
    if report.status == "in_progress":
        message = "cannot render an in-progress report"
        raise ValueError(message)
    if output_path is not None:
        try:
            aggregate_path = report_path.resolve()
            artifact_paths = {aggregate_path}
            artifact_paths.update(
                (aggregate_path.parent / step.report_path).resolve()
                for step in report.ramp
                if step.report_path is not None
            )
            resolved_output = output_path.resolve()
        except (OSError, RuntimeError) as error:
            message = f"Markdown output is missing or inaccessible: {output_path}"
            raise ValueError(message) from error
        if resolved_output in artifact_paths:
            message = (
                "Markdown output cannot replace the same file in the JSON artifact tree"
            )
            raise ValueError(message)
    lines = [
        "# Active orchestration benchmark",
        "",
        (
            "> Local descriptive evidence only; these timings are not causal or "
            "machine-independent claims."
        ),
        "",
        f"Status: `{report.status}`",
        "",
        f"Requested topology: `{report.requested_topology}`",
        "",
    ]
    if report.observed_topology is not None:
        lines.extend((f"Observed topology: `{report.observed_topology}`", ""))
    if report.lane is not None and report.mode is not None:
        lines.extend((f"Lane: `{report.lane}/{report.mode}`", ""))
    if report.runs is not None:
        lines.extend((f"Runs: `{report.runs}`", ""))
    if report.warmup is not None:
        lines.extend((f"Warmup: `{report.warmup}`", ""))
    if report.environment is not None:
        python_version = _markdown_cell(report.environment.python_version, report)
        tmux_version = _markdown_cell(report.environment.tmux_version or "n/a", report)
        revision = _markdown_cell(report.environment.git_revision or "n/a", report)
        lines.extend(
            (
                f"Seed: `{report.environment.seed}`",
                "",
                f"Python: `{python_version}`",
                "",
                f"tmux: `{tmux_version}`",
                "",
                f"Revision: `{revision}`",
                "",
            )
        )
    if report.error is not None:
        lines.extend((f"Terminal reason: {_markdown_cell(report.error, report)}", ""))
    if report.ramp:
        lines.extend(
            (
                "## Ramp attempts",
                "",
                "| Shape | Status | Reason | Child report |",
                "| --- | --- | --- | --- |",
            )
        )
        lines.extend(
            f"| `{step.shape}` | `{step.status}` | "
            f"{_markdown_cell(step.reason, report)} | "
            f"{_markdown_cell(step.report_path, report)} |"
            for step in report.ramp
        )
        lines.append("")
    if report.phases:
        lines.extend(
            (
                "## Phase timings",
                "",
                (
                    "| Phase | Status | Count | Min | Mean | Median | p90 | p95 | "
                    "p99 | Max |"
                ),
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            )
        )
        setup_observations: tuple[str, ...] = ()
        for phase in report.phases:
            accepted = tuple(
                t.cast(int, sample.duration_ns)
                for sample in phase.samples
                if sample.accepted
            )
            if phase.name == "setup":
                setup_observations = tuple(
                    _format_ns(t.cast(int, sample.duration_ns))
                    for sample in phase.samples
                    if sample.accepted
                )
                lines.append(
                    f"| `{phase.name}` | `{phase.status}` | "
                    f"{len(accepted)} | n/a | n/a | n/a | "
                    "n/a | n/a | n/a | n/a |"
                )
            elif accepted:
                summary = summarize_ns(accepted)
                lines.append(
                    f"| `{phase.name}` | `{phase.status}` | "
                    f"{summary['count']} | "
                    f"{_format_ns(summary['min_ns'])} | "
                    f"{_format_ns(summary['mean_ns'])} | "
                    f"{_format_ns(summary['median_ns'])} | "
                    f"{_format_ns(summary['p90_ns'])} | "
                    f"{_format_ns(summary['p95_ns'])} | "
                    f"{_format_ns(summary['p99_ns'])} | "
                    f"{_format_ns(summary['max_ns'])} |"
                )
            else:
                lines.append(
                    f"| `{phase.name}` | `{phase.status}` | 0 | n/a | n/a | "
                    "n/a | n/a | n/a | n/a | n/a |"
                )
        lines.append("")
        if setup_observations:
            values = ", ".join(f"`{value}`" for value in setup_observations)
            lines.extend((f"Setup individual observations: {values}", ""))
    lines.extend(
        (
            "## Cleanup",
            "",
            f"Verified complete: `{str(report.cleanup.complete).lower()}`",
            "",
            (
                "Processes absent: "
                f"`{_format_cleanup_fact(report.cleanup.processes_absent)}`"
            ),
            "",
            f"Socket absent: `{_format_cleanup_fact(report.cleanup.socket_absent)}`",
            "",
            f"Scratch absent: `{_format_cleanup_fact(report.cleanup.scratch_absent)}`",
            "",
        )
    )
    if report.cleanup.errors:
        lines.extend(("Cleanup errors:", ""))
        lines.extend(
            f"- {_markdown_cell(error, report)}" for error in report.cleanup.errors
        )
        lines.append("")
    rendered = "\n".join(lines)
    if output_path is not None:
        _write_text_atomic(output_path, rendered)
    return rendered


def run_scenario(
    topology: Topology,
    *,
    lane: EngineLane = EngineLane.CONTROL,
    mode: ExecutionMode = ExecutionMode.ASYNC,
    runs: int = 100,
    warmup: int = 3,
    seed: int = 11,
    output: pathlib.Path = pathlib.Path("orchestration-report.json"),
    markdown_output: pathlib.Path | None = None,
    scratch_root: pathlib.Path | None = None,
    force_extreme: bool = False,
    policy: ResourcePolicy | None = None,
    host_snapshot: HostSnapshot | None = None,
    watchdog_s: float = 120.0,
    cleanup_grace_s: float = 2.0,
    orm: bool = False,
    _test_stall_after: str | None = None,
    _test_fail_after: str | None = None,
    _test_extra_identity: ProcessIdentity | None = None,
) -> RunReport:
    """Preflight and supervise one fresh active benchmark scenario.

    Private ``_test_*`` arguments are exposed only as suppressed hidden-worker
    harness flags and are never part of the documented benchmark interface.

    >>> refusal_path = pathlib.Path(tempfile.gettempdir()) / "unused-refusal.json"
    >>> refused = run_scenario(
    ...     Topology(1, 1, 1), runs=1, warmup=0,
    ...     output=refusal_path,
    ...     host_snapshot=HostSnapshot(pids_current=10, pids_max=11),
    ...     policy=ResourcePolicy(pid_reserve=1),
    ... )
    >>> refused.status
    'refused'
    >>> refusal_path.unlink(missing_ok=True)
    >>> refusal_path.with_suffix(".md").unlink(missing_ok=True)

    Parameters
    ----------
    topology : Topology
        Exact requested hierarchy.
    lane : EngineLane
        Subprocess or control transport; control is the default.
    mode : ExecutionMode
        Sync or async execution; async is the default.
    runs : int
        Timed samples per repeatable cell.
    warmup : int
        Untimed samples per repeatable cell.
    seed : int
        Deterministic cell interleaving seed.
    output : pathlib.Path
        Supervisor-owned JSON destination.
    markdown_output : pathlib.Path | None
        Summary destination, defaulting beside ``output``.
    scratch_root : pathlib.Path | None
        Parent for fresh private run directories.
    force_extreme : bool
        Override predictive refusal only.
    policy : ResourcePolicy | None
        Predictive and runtime reserve thresholds.
    host_snapshot : HostSnapshot | None
        Injectable preflight observation; live probing is the default.
    watchdog_s : float
        Maximum interval without an increasing progress sequence.
    cleanup_grace_s : float
        Bounded graceful and escalation waits.

    Returns
    -------
    RunReport
        Validated supervisor-owned terminal report.
    """
    if type(runs) is not int or runs <= 0 or type(warmup) is not int or warmup < 0:
        message = "runs must be positive and warmup nonnegative"
        raise ValueError(message)
    policy = policy or ResourcePolicy(
        persistent_clients=(1 if lane is EngineLane.CONTROL else 0)
    )
    snapshot = host_snapshot or probe_host(ProcessReader())
    original = predict_resources(topology, snapshot, policy)
    decision = _forced_decision(original, force_extreme)
    capability_error = _pidfd_capability_error()
    if decision.allowed and capability_error is not None:
        decision = GuardDecision(
            False,
            "predictive_refusal",
            "pidfd_capability",
            None,
            None,
            False,
            snapshot,
        )
    run_id = f"r{uuid.uuid4().hex[:10]}"
    markdown_output = markdown_output or output.with_suffix(".md")
    if not decision.allowed:
        report = RunReport(
            topology,
            status="refused",
            cleanup=CleanupReport(
                True,
                processes_absent=True,
                socket_absent=True,
                scratch_absent=True,
            ),
            guard_decision=decision,
            original_guard_decision=original,
            run_id=run_id,
            lane=lane.value,
            mode=mode.value,
            warmup=warmup,
            runs=runs,
            failed_phase="preflight",
            error=(
                capability_error
                if capability_error is not None and decision.rule == "pidfd_capability"
                else f"predictive refusal: {original.rule or 'unknown'}"
            ),
            environment=EnvironmentReport(
                python_version=platform.python_version(),
                tmux_version=None,
                cpu_count=os.cpu_count(),
                seed=seed,
                command_line=("run", "--shape", str(topology)),
                git_revision=None,
            ),
        )
        write_json_atomic(output, report)
        validate_report(report)
        render_markdown_summary(output, markdown_output)
        return report
    scratch_parent = scratch_root or pathlib.Path(tempfile.gettempdir())
    scratch = scratch_parent.resolve() / f"run-{run_id}"
    socket_path = scratch / "tmux.sock"
    return supervise_worker(
        topology,
        lane=lane,
        mode=mode,
        runs=runs,
        warmup=warmup,
        seed=seed,
        run_id=run_id,
        scratch=scratch,
        socket_path=socket_path,
        output=output,
        markdown_output=markdown_output,
        guard_decision=decision,
        original_guard_decision=original,
        policy=policy,
        watchdog_s=watchdog_s,
        cleanup_grace_s=cleanup_grace_s,
        orm=orm,
        _test_stall_after=_test_stall_after,
        _test_fail_after=_test_fail_after,
        _test_extra_identity=_test_extra_identity,
    )


def _finalize_ramp_aggregation(
    report: RunReport,
    steps: t.Sequence[RampStep],
    *,
    last_observed: Topology | None,
    terminal_status: t.Literal["refused", "failed", "cutoff"] | None,
    terminal_reason: str | None,
    output: pathlib.Path,
    markdown_output: pathlib.Path,
    active_index: int | None = None,
    active_child_output: pathlib.Path | None = None,
    interrupt_state: list[KeyboardInterrupt | None] | None = None,
) -> RunReport:
    """Validate child cleanup and durably publish one terminal ramp aggregate.

    >>> _finalize_ramp_aggregation.__name__
    '_finalize_ramp_aggregation'

    Returns
    -------
    RunReport
        Validated aggregate retaining every declared step.
    """
    state: list[KeyboardInterrupt | None] = (
        interrupt_state if interrupt_state is not None else [None]
    )
    resolved_steps = list(steps)
    resolved_observed = last_observed

    def record_interrupt(error: KeyboardInterrupt) -> None:
        if state[0] is None:
            state[0] = error

    def interruption_reason(error: KeyboardInterrupt) -> str:
        detail = str(error)
        suffix = f": {detail}" if detail else ""
        return f"KeyboardInterrupt: ramp bookkeeping interrupted{suffix}"

    if (
        active_index is not None
        and active_child_output is not None
        and active_child_output.exists()
    ):
        try:
            child = load_run_report(active_child_output)
        except ValueError:
            child = None
        if child is not None and child.status in {
            "completed",
            "refused",
            "failed",
            "cutoff",
        }:
            resolved_steps[active_index] = RampStep(
                resolved_steps[active_index].shape,
                child.status,
                child.error,
                run_id=child.run_id,
                report_path=active_child_output.relative_to(output.parent).as_posix(),
                scratch_path=child.scratch_path,
                socket_path=child.socket_path,
            )
            if child.status == "completed":
                resolved_observed = child.observed_topology

    def build_terminal() -> RunReport:
        final_status: t.Literal["completed", "refused", "failed", "cutoff"]
        existing_terminal = next(
            (
                step
                for step in resolved_steps
                if step.status in {"refused", "failed", "cutoff"}
            ),
            None,
        )
        if existing_terminal is not None:
            final_status = t.cast(
                t.Literal["refused", "failed", "cutoff"],
                existing_terminal.status,
            )
            final_reason = existing_terminal.reason or final_status
        elif terminal_status is not None:
            final_status = terminal_status
            final_reason = terminal_reason or terminal_status
        elif state[0] is not None:
            final_status = "cutoff"
            final_reason = interruption_reason(state[0])
        else:
            final_status = "completed"
            final_reason = None
        if final_status != "completed":
            for index, step in enumerate(resolved_steps):
                if step.status == "not_attempted":
                    resolved_steps[index] = dataclasses.replace(
                        step,
                        reason=final_reason,
                    )
        child_cleanups = tuple(
            (
                step.shape,
                load_run_report(
                    output.parent / pathlib.Path(t.cast(str, step.report_path))
                ).cleanup,
            )
            for step in resolved_steps
            if step.status != "not_attempted"
        )
        cleanup = _aggregate_ramp_cleanup(child_cleanups)
        return dataclasses.replace(
            report,
            status=final_status,
            observed_topology=resolved_observed,
            cleanup=cleanup,
            ramp=tuple(resolved_steps),
            error=final_reason,
        )

    def publish(terminal: RunReport) -> None:
        write_json_atomic(output, terminal)
        validate_report(terminal)
        render_markdown_summary(output, markdown_output)

    observed_interrupt = state[0]
    terminal = build_terminal()
    try:
        publish(terminal)
    except KeyboardInterrupt as error:
        record_interrupt(error)
        terminal = build_terminal()
        publish(terminal)
    else:
        if state[0] is not observed_interrupt:
            terminal = build_terminal()
            publish(terminal)
    return terminal


def run_ramp(
    shapes: t.Sequence[Topology],
    *,
    lane: EngineLane = EngineLane.CONTROL,
    mode: ExecutionMode = ExecutionMode.ASYNC,
    runs: int = 100,
    warmup: int = 3,
    seed: int = 11,
    output: pathlib.Path = pathlib.Path("orchestration-ramp.json"),
    markdown_output: pathlib.Path | None = None,
    scratch_root: pathlib.Path | None = None,
    force_extreme: bool = False,
    policy: ResourcePolicy | None = None,
    host_snapshot: HostSnapshot | None = None,
    watchdog_s: float = 120.0,
    cleanup_grace_s: float = 2.0,
    canonical: bool = False,
    _test_stall_after: str | None = None,
    _test_fail_after: str | None = None,
    _test_extra_identity: ProcessIdentity | None = None,
) -> RunReport:
    """Run fresh disposable scenarios until completion or the first terminal stop.

    >>> try:
    ...     run_ramp((), runs=1, warmup=0)
    ... except ValueError as error:
    ...     print(error)
    ramp requires at least one unique shape

    Returns
    -------
    RunReport
        Validated aggregate with later shapes marked ``not_attempted``.
    """
    declared = tuple(shapes)
    if not declared or len(set(declared)) != len(declared):
        message = "ramp requires at least one unique shape"
        raise ValueError(message)
    if canonical and declared != canonical_ramp():
        message = "canonical ramp must use the exact declared sequence"
        raise ValueError(message)
    markdown_output = markdown_output or output.with_suffix(".md")
    attempts = tuple(RampStep(shape, "not_attempted") for shape in declared)
    report = RunReport(
        requested_topology=declared[-1],
        status="in_progress",
        cleanup=CleanupReport(False),
        ramp=attempts,
        requested_shapes=declared,
        ramp_kind="canonical" if canonical else "custom",
        lane=lane.value,
        mode=mode.value,
        warmup=warmup,
        runs=runs,
        environment=_collect_environment(
            seed=seed,
            command_line=("ramp", "--shapes", ",".join(map(str, declared))),
            include_tmux=False,
        ),
    )
    child_root = output.with_name(f"{output.stem}.runs")
    steps = list(attempts)
    last_observed: Topology | None = None
    terminal_status: t.Literal["refused", "failed", "cutoff"] | None = None
    terminal_reason: str | None = None
    interruption: KeyboardInterrupt | None = None
    active_index: int | None = None
    active_child_output: pathlib.Path | None = None
    final_report: RunReport | None = None

    def step_from_child(
        index: int,
        child: RunReport,
        child_output: pathlib.Path,
    ) -> RampStep:
        return RampStep(
            declared[index],
            t.cast(
                t.Literal["completed", "refused", "failed", "cutoff"],
                child.status,
            ),
            child.error,
            run_id=child.run_id,
            report_path=child_output.relative_to(output.parent).as_posix(),
            scratch_path=child.scratch_path,
            socket_path=child.socket_path,
        )

    def write_checkpoint(candidate: RunReport) -> None:
        _result, deferred = _drain_finalizer_thread(
            lambda: write_json_atomic(output, candidate)
        )
        if deferred is not None:
            raise deferred

    def mark_pending(reason: str) -> None:
        for pending_index, step in enumerate(steps):
            if step.status == "not_attempted":
                steps[pending_index] = dataclasses.replace(step, reason=reason)

    try:
        write_checkpoint(report)
        for index, shape in enumerate(declared):
            active_index = index
            child_output = child_root / f"{index:02d}-{shape}.json"
            active_child_output = child_output
            child_markdown = child_output.with_suffix(".md")
            child = run_scenario(
                shape,
                lane=lane,
                mode=mode,
                runs=runs,
                warmup=warmup,
                seed=seed + index,
                output=child_output,
                markdown_output=child_markdown,
                scratch_root=scratch_root,
                force_extreme=force_extreme,
                policy=policy,
                host_snapshot=host_snapshot,
                watchdog_s=watchdog_s,
                cleanup_grace_s=cleanup_grace_s,
                _test_stall_after=_test_stall_after,
                _test_fail_after=_test_fail_after,
                _test_extra_identity=_test_extra_identity,
            )
            steps[index] = step_from_child(index, child, child_output)
            if child.status == "completed":
                last_observed = child.observed_topology
            else:
                terminal_status = t.cast(
                    t.Literal["refused", "failed", "cutoff"], child.status
                )
                terminal_reason = child.error or child.status
                mark_pending(terminal_reason)
                break
            report = dataclasses.replace(
                report,
                observed_topology=last_observed,
                ramp=tuple(steps),
            )
            write_checkpoint(report)
            active_index = None
            active_child_output = None
    except KeyboardInterrupt as error:
        if interruption is None:
            interruption = error
    finally:
        interrupt_state = [interruption]
        finalize: t.Callable[[], RunReport] = functools.partial(
            _finalize_ramp_aggregation,
            report,
            steps,
            last_observed=last_observed,
            terminal_status=terminal_status,
            terminal_reason=terminal_reason,
            output=output,
            markdown_output=markdown_output,
            active_index=active_index,
            active_child_output=active_child_output,
            interrupt_state=interrupt_state,
        )
        final_report, deferred_interruption = _drain_finalizer_thread(
            finalize,
            initial_interrupt=interruption,
            interrupt_state=interrupt_state,
        )
        if interruption is None:
            interruption = deferred_interruption
    assert final_report is not None
    if interruption is not None:
        raise interruption
    return final_report


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


def _load_host_snapshot(path: pathlib.Path | None) -> HostSnapshot | None:
    """Load a private test-harness preflight snapshot.

    >>> _load_host_snapshot(None) is None
    True

    Parameters
    ----------
    path : pathlib.Path | None
        Hidden CLI JSON fixture, or ``None`` for live probing.

    Returns
    -------
    HostSnapshot | None
        Decoded fixture or ``None``.
    """
    if path is None:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        message = f"test host snapshot is not complete JSON: {path}"
        raise ValueError(message) from error
    snapshot = _host_snapshot_from_json(value)
    if snapshot is None:
        message = "test host snapshot cannot be null"
        raise ValueError(message)
    return snapshot


def _parse_optional_limit(value: str) -> int | None:
    """Parse a positive integer or the hidden worker's ``dynamic`` marker.

    >>> _parse_optional_limit("dynamic") is None
    True
    >>> _parse_optional_limit("1024")
    1024
    """
    if value == "dynamic":
        return None
    try:
        parsed = int(value)
    except ValueError as error:
        message = "resource limit must be a positive integer or dynamic"
        raise ValueError(message) from error
    if parsed <= 0:
        message = "resource limit must be a positive integer or dynamic"
        raise ValueError(message)
    return parsed


def _parse_extra_identity(value: str | None) -> ProcessIdentity | None:
    """Decode the private PID-reuse test identity.

    >>> _parse_extra_identity("pane:42:100")
    ProcessIdentity(role='pane', pid=42, start_time=100)
    >>> _parse_extra_identity(None) is None
    True
    """
    if value is None:
        return None
    pieces = value.split(":")
    if len(pieces) != 3 or not pieces[0]:
        message = "test identity must use role:pid:start_time"
        raise ValueError(message)
    try:
        identity = ProcessIdentity(pieces[0], int(pieces[1]), int(pieces[2]))
    except ValueError as error:
        message = "test identity must use role:pid:start_time"
        raise ValueError(message) from error
    if identity.pid <= 0 or identity.start_time <= 0:
        message = "test identity requires positive pid and start_time"
        raise ValueError(message)
    return identity


async def _run_worker_with_signals(**kwargs: t.Any) -> RunReport:
    """Translate worker SIGINT/SIGTERM into cancellation and awaited cleanup.

    >>> async def invalid():
    ...     try:
    ...         await _run_worker_with_signals()
    ...     except TypeError as error:
    ...         return "topology" in str(error)
    >>> asyncio.run(invalid())
    True
    """
    loop = asyncio.get_running_loop()
    task = asyncio.create_task(run_worker(**kwargs), name="orchestration-worker")
    installed: list[signal.Signals] = []
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(
                signal_number,
                task.cancel,
                f"received {signal_number.name}",
            )
        except (NotImplementedError, RuntimeError):
            continue
        installed.append(signal_number)
    if installed and callable(getattr(signal, "pthread_sigmask", None)):
        signal.pthread_sigmask(signal.SIG_UNBLOCK, installed)
    try:
        return await task
    finally:
        for signal_number in installed:
            loop.remove_signal_handler(signal_number)


def _run_hidden_worker(arguments: argparse.Namespace) -> int:
    """Decode hidden CLI state and execute exactly one worker process.

    >>> _run_hidden_worker.__name__
    '_run_hidden_worker'
    """
    admission = _json_mapping(
        json.loads(arguments.admission.read_text(encoding="utf-8")), "admission"
    )
    guard = _guard_from_json(admission.get("guard_decision"))
    original = _guard_from_json(admission.get("original_guard_decision"))
    if guard is None or original is None:
        message = "worker admission requires both guard decisions"
        raise ValueError(message)
    policy = ResourcePolicy(
        persistent_clients=(1 if arguments.lane == "control" else 0),
        pid_reserve=_parse_optional_limit(arguments.pid_reserve),
        memory_floor_bytes=_parse_optional_limit(arguments.memory_floor_bytes),
    )
    report = asyncio.run(
        _run_worker_with_signals(
            topology=parse_topology(arguments.shape),
            lane=EngineLane(arguments.lane),
            mode=ExecutionMode(arguments.mode),
            runs=arguments.runs,
            warmup=arguments.warmup,
            seed=arguments.seed,
            run_id=arguments.run_id,
            scratch=arguments.scratch,
            socket_path=arguments.socket_path,
            checkpoint_path=arguments.checkpoint,
            progress_path=arguments.progress,
            guard_decision=guard,
            original_guard_decision=original,
            policy=policy,
            fuzzer_duration_s=arguments.service_duration_seconds,
            watchdog_s=arguments.watchdog_seconds,
            orm=arguments.orm,
            stall_after=arguments.test_stall_after,
            fail_after=arguments.test_fail_after,
            extra_identity=_parse_extra_identity(arguments.test_extra_identity),
        )
    )
    return 0 if report.status == "completed" else 2


def _add_execution_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the shared public run/ramp execution flags.

    >>> parser = argparse.ArgumentParser()
    >>> _add_execution_arguments(parser)
    >>> parser.parse_args(["--runs", "2"]).runs
    2
    """
    parser.add_argument(
        "--lane",
        choices=tuple(lane.value for lane in EngineLane),
        default="control",
        help="transport lane; combine with --mode for one of four execution lanes",
    )
    parser.add_argument(
        "--mode",
        choices=tuple(mode.value for mode in ExecutionMode),
        default="async",
        help="dispatch mode paired with --lane",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=100,
        help="timed invocations retained per repeatable phase",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=3,
        help="untimed invocations before each repeatable phase",
    )
    parser.add_argument("--seed", type=int, default=11, help="schedule seed")
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        help="machine-readable JSON artifact destination",
    )
    parser.add_argument(
        "--markdown-output",
        type=pathlib.Path,
        help="local Markdown summary destination",
    )
    parser.add_argument(
        "--scratch-root",
        type=pathlib.Path,
        help="parent for private per-run state",
    )
    parser.add_argument(
        "--force-extreme",
        action="store_true",
        help=(
            "relax predictive refusal only; never runtime cutoff, correctness, "
            "or cleanup"
        ),
    )
    parser.add_argument("--pid-reserve", type=int, help="minimum free PID reserve")
    parser.add_argument(
        "--memory-floor-bytes",
        type=int,
        help="minimum free memory reserve",
    )
    parser.add_argument(
        "--watchdog-seconds",
        type=float,
        default=120.0,
        help="maximum interval without progress",
    )
    parser.add_argument(
        "--cleanup-grace-seconds",
        type=float,
        default=2.0,
        help="grace interval before exact process escalation",
    )
    parser.add_argument(
        "--with-orm",
        dest="orm",
        action="store_true",
        help=(
            "also measure the classic ORM enumeration reference; its own "
            "request graph differs, so it is never an engine speedup claim"
        ),
    )
    parser.add_argument(
        "--_test-host-snapshot",
        dest="test_host_snapshot",
        type=pathlib.Path,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--_test-stall-after",
        dest="test_stall_after",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--_test-fail-after",
        dest="test_fail_after",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--_test-extra-identity",
        dest="test_extra_identity",
        help=argparse.SUPPRESS,
    )


def _hidden_worker_parser() -> argparse.ArgumentParser:
    """Build the private supervisor-to-worker protocol parser.

    Keeping this parser outside the public subcommand collection prevents the
    implementation protocol and its test harness from appearing in help.

    >>> parser = _hidden_worker_parser()
    >>> parser.prog
    'scripts/orchestration/benchmark.py _worker'

    Returns
    -------
    argparse.ArgumentParser
        Parser for arguments emitted only by :func:`supervise_worker`.
    """
    parser = argparse.ArgumentParser(prog="scripts/orchestration/benchmark.py _worker")
    parser.add_argument("--shape", required=True)
    parser.add_argument("--lane", required=True, choices=("subprocess", "control"))
    parser.add_argument("--mode", required=True, choices=("sync", "async"))
    parser.add_argument("--runs", required=True, type=int)
    parser.add_argument("--warmup", required=True, type=int)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--scratch", required=True, type=pathlib.Path)
    parser.add_argument("--socket-path", required=True, type=pathlib.Path)
    parser.add_argument("--checkpoint", required=True, type=pathlib.Path)
    parser.add_argument("--progress", required=True, type=pathlib.Path)
    parser.add_argument("--admission", required=True, type=pathlib.Path)
    parser.add_argument("--pid-reserve", required=True)
    parser.add_argument("--memory-floor-bytes", required=True)
    parser.add_argument("--service-duration-seconds", required=True, type=float)
    parser.add_argument("--watchdog-seconds", required=True, type=float)
    parser.add_argument("--with-orm", dest="orm", action="store_true")
    parser.add_argument(
        "--_test-stall-after", dest="test_stall_after", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--_test-fail-after", dest="test_fail_after", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--_test-extra-identity",
        dest="test_extra_identity",
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: t.Sequence[str] | None = None) -> int:
    """Plan, run, validate, or render active orchestration evidence.

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
        Zero only after the selected public work completes successfully.

    Raises
    ------
    SystemExit
        If command-line arguments are invalid.
    ValueError
        If the selected plan topology is malformed or nonpositive.
    OSError
        If the selected plan output cannot be written.
    """
    raw_arguments = tuple(sys.argv[1:] if argv is None else argv)
    if raw_arguments[:1] == ("_worker",):
        worker_arguments = _hidden_worker_parser().parse_args(raw_arguments[1:])
        return _run_hidden_worker(worker_arguments)
    parser = argparse.ArgumentParser(
        prog="scripts/orchestration/benchmark.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Topology syntax: SxWxP means sessions x windows per session x "
            "panes per window.\n"
            "Ramp --shapes accepts comma-separated SxWxP values. --runs retains "
            "timed samples; --warmup performs untimed calls.\n"
            "Execution lanes: subprocess/sync, subprocess/async, control/sync, "
            "and control/async.\n"
            "Run and ramp write JSON evidence and optional Markdown summaries; "
            "validate and render consume that evidence.\n"
            "--force-extreme relaxes predictive refusal only, never runtime "
            "cutoff, correctness, or cleanup."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    plan_parser = commands.add_parser("plan", help="inspect topology and host limits")
    plan_parser.add_argument(
        "--shape",
        required=True,
        help="topology in SxWxP notation",
    )
    plan_parser.add_argument(
        "--output",
        type=pathlib.Path,
        help="optional JSON plan destination",
    )
    plan_parser.add_argument(
        "--force-extreme",
        action="store_true",
        help="show predictive-refusal override without changing runtime safety",
    )
    run_parser = commands.add_parser("run", help="run one active topology")
    run_parser.add_argument(
        "--shape",
        required=True,
        help="topology in SxWxP notation",
    )
    _add_execution_arguments(run_parser)
    ramp_parser = commands.add_parser("ramp", help="run fresh topologies in order")
    ramp_parser.add_argument(
        "--shapes",
        help="comma-separated SxWxP shapes; default is the canonical ramp",
    )
    _add_execution_arguments(ramp_parser)
    validate_parser = commands.add_parser(
        "validate",
        help="validate a complete JSON artifact tree",
        description=(
            "Read-only validation of a complete artifact tree without contacting tmux."
        ),
        epilog="Ramp child references are checked without modifying any artifact.",
    )
    validate_parser.add_argument(
        "--input",
        required=True,
        type=pathlib.Path,
        help="complete JSON report artifact",
    )
    render_parser = commands.add_parser(
        "render",
        help="render a complete JSON artifact tree as Markdown",
        description="Validate a complete artifact tree before rendering Markdown.",
        epilog=(
            "With --output, Markdown is replaced atomically only after validation; "
            "without it, Markdown is written to stdout."
        ),
    )
    render_parser.add_argument(
        "--input",
        required=True,
        type=pathlib.Path,
        help="complete JSON report artifact",
    )
    render_parser.add_argument(
        "--output",
        type=pathlib.Path,
        help="atomic Markdown destination; omit for stdout",
    )
    arguments = parser.parse_args(raw_arguments)
    if arguments.command == "plan":
        return run_plan(arguments.shape, arguments.output, arguments.force_extreme)
    if arguments.command == "validate":
        try:
            report = validate_report_artifact(arguments.input)
        except (OSError, TypeError, ValueError) as error:
            print(f"invalid benchmark artifact: {error}", file=sys.stderr)
            return 2
        if report.status == "in_progress":
            print(
                "invalid benchmark artifact: report is still in-progress",
                file=sys.stderr,
            )
            return 2
        print(f"Status: {report.status}")
        print(f"Requested topology: {report.requested_topology}")
        print(f"Observed topology: {report.observed_topology or 'n/a'}")
        return 0
    if arguments.command == "render":
        try:
            rendered = render_markdown_summary(arguments.input, arguments.output)
        except (OSError, TypeError, ValueError) as error:
            print(f"invalid benchmark artifact: {error}", file=sys.stderr)
            return 2
        if arguments.output is None:
            print(rendered)
        return 0
    policy = ResourcePolicy(
        persistent_clients=(1 if arguments.lane == "control" else 0),
        pid_reserve=arguments.pid_reserve,
        memory_floor_bytes=arguments.memory_floor_bytes,
    )
    host_snapshot = _load_host_snapshot(arguments.test_host_snapshot)
    extra_identity = _parse_extra_identity(arguments.test_extra_identity)
    if arguments.command == "run":
        output = arguments.output or pathlib.Path("orchestration-report.json")
        try:
            report = run_scenario(
                parse_topology(arguments.shape),
                lane=EngineLane(arguments.lane),
                mode=ExecutionMode(arguments.mode),
                runs=arguments.runs,
                warmup=arguments.warmup,
                seed=arguments.seed,
                output=output,
                markdown_output=arguments.markdown_output,
                scratch_root=arguments.scratch_root,
                force_extreme=arguments.force_extreme,
                policy=policy,
                host_snapshot=host_snapshot,
                watchdog_s=arguments.watchdog_seconds,
                cleanup_grace_s=arguments.cleanup_grace_seconds,
                orm=arguments.orm,
                _test_stall_after=arguments.test_stall_after,
                _test_fail_after=arguments.test_fail_after,
                _test_extra_identity=extra_identity,
            )
        except KeyboardInterrupt:
            return 130
        return 0 if report.status == "completed" else 2
    if arguments.command == "ramp":
        shapes = (
            canonical_ramp()
            if arguments.shapes is None
            else tuple(parse_topology(shape) for shape in arguments.shapes.split(","))
        )
        output = arguments.output or pathlib.Path("orchestration-ramp.json")
        try:
            report = run_ramp(
                shapes,
                lane=EngineLane(arguments.lane),
                mode=ExecutionMode(arguments.mode),
                runs=arguments.runs,
                warmup=arguments.warmup,
                seed=arguments.seed,
                output=output,
                markdown_output=arguments.markdown_output,
                scratch_root=arguments.scratch_root,
                force_extreme=arguments.force_extreme,
                policy=policy,
                host_snapshot=host_snapshot,
                watchdog_s=arguments.watchdog_seconds,
                cleanup_grace_s=arguments.cleanup_grace_seconds,
                canonical=arguments.shapes is None,
                _test_stall_after=arguments.test_stall_after,
                _test_fail_after=arguments.test_fail_after,
                _test_extra_identity=extra_identity,
            )
        except KeyboardInterrupt:
            return 130
        return 0 if report.status == "completed" else 2
    message = "argparse selected an unsupported command"
    raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
