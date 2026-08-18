"""Behavioral checks for the orchestration benchmark's pure model."""

from __future__ import annotations

import asyncio
import dataclasses
import errno
import hashlib
import importlib.util
import json
import os
import pathlib
import signal
import stat
import subprocess
import sys
import threading
import time
import types
import typing as t

import pytest

from libtmux._internal.query_list import QueryList
from libtmux.experimental.models import PaneSnapshot, SessionSnapshot, WindowSnapshot

_PHASE_LANES = (
    ("subprocess", "sync"),
    ("subprocess", "async"),
    ("control", "sync"),
    ("control", "async"),
)

_RUNNER_REPEATABLE_PHASES = (
    "mutation.bulk",
    "wait.capture-poll",
    "enumeration.sessions",
    "enumeration.windows",
    "enumeration.panes",
    "capture.serial",
    "capture.batched",
    "search.classic.sessions.first",
    "search.classic.sessions.middle",
    "search.classic.sessions.last",
    "search.classic.windows.first",
    "search.classic.windows.middle",
    "search.classic.windows.last",
    "search.classic.panes.first",
    "search.classic.panes.middle",
    "search.classic.panes.last",
    "search.snapshot.sessions.first",
    "search.snapshot.sessions.middle",
    "search.snapshot.sessions.last",
    "search.snapshot.windows.first",
    "search.snapshot.windows.middle",
    "search.snapshot.windows.last",
    "search.snapshot.panes.first",
    "search.snapshot.panes.middle",
    "search.snapshot.panes.last",
    "search.end-to-end.sessions.first",
    "search.end-to-end.sessions.middle",
    "search.end-to-end.sessions.last",
    "search.end-to-end.windows.first",
    "search.end-to-end.windows.middle",
    "search.end-to-end.windows.last",
    "search.end-to-end.panes.first",
    "search.end-to-end.panes.middle",
    "search.end-to-end.panes.last",
    "search.contents",
)

_RUNNER_PHASES = (
    "setup",
    "stabilization",
    "mutation.bulk",
    "wait.capture-poll",
    "wait.control-stream",
    *_RUNNER_REPEATABLE_PHASES[2:],
)


def _benchmark_script() -> pathlib.Path:
    """Return the real standalone benchmark entry point."""
    return pathlib.Path(__file__).parents[1] / "scripts" / "bench_orchestration.py"


def _run_cli(*arguments: str, cwd: pathlib.Path) -> subprocess.CompletedProcess[str]:
    """Run the real benchmark process with no inherited tmux coordinates."""
    environment = os.environ.copy()
    environment.pop("TMUX", None)
    environment.pop("TMUX_PANE", None)
    return subprocess.run(
        (sys.executable, str(_benchmark_script()), *arguments),
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )


def _start_cli(*arguments: str, cwd: pathlib.Path) -> subprocess.Popen[str]:
    """Start the real benchmark so a test can interrupt its supervisor."""
    environment = os.environ.copy()
    environment.pop("TMUX", None)
    environment.pop("TMUX_PANE", None)
    return subprocess.Popen(
        (sys.executable, str(_benchmark_script()), *arguments),
        cwd=cwd,
        env=environment,
        text=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _process_start_time(pid: int) -> int:
    """Read one exact Linux process start-time identity."""
    raw = pathlib.Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    close = raw.rindex(")")
    return int(raw[close + 2 :].split()[19])


def _identity_still_matches(identity: dict[str, t.Any]) -> bool:
    """Return whether procfs still names the exact serialized process."""
    try:
        raw = pathlib.Path(f"/proc/{identity['pid']}/stat").read_text(encoding="utf-8")
        close = raw.rindex(")")
        return int(raw[close + 2 :].split()[19]) == t.cast(int, identity["start_time"])
    except (FileNotFoundError, OSError, ValueError, IndexError):
        return False


def _assert_terminal_cleanup(payload: dict[str, t.Any]) -> None:
    """Assert the supervisor's exact terminal cleanup evidence."""
    assert payload["cleanup"] == {
        "complete": True,
        "errors": [],
        "processes_absent": True,
        "scratch_absent": True,
        "socket_absent": True,
    }
    assert not pathlib.Path(payload["scratch_path"]).exists()
    assert not pathlib.Path(payload["socket_path"]).exists()
    assert all(not _identity_still_matches(row) for row in payload["processes"])


@pytest.fixture()
def benchmark_module() -> types.ModuleType:
    """Load the standalone benchmark script without contacting tmux."""
    script = pathlib.Path(__file__).parents[1] / "scripts" / "bench_orchestration.py"
    spec = importlib.util.spec_from_file_location("bench_orchestration", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_topology_derives_exact_totals(
    benchmark_module: types.ModuleType,
) -> None:
    """Changing any topology multiplier would misstate the active workload."""
    topology = benchmark_module.parse_topology("100x100x4")

    assert topology.sessions == 100
    assert topology.windows == 10_000
    assert topology.panes == 40_000


@pytest.mark.parametrize("shape", ("0x1x1", "1x0x1", "1x1x0", "-1x1x1"))
def test_parse_topology_rejects_nonpositive_dimensions(
    benchmark_module: types.ModuleType, shape: str
) -> None:
    """Accepting a nonpositive dimension would create a false workload plan."""
    with pytest.raises(ValueError, match="positive"):
        benchmark_module.parse_topology(shape)


@pytest.mark.parametrize("shape", ("100", "100x20", "100x20x1x2", "100X20X1", "one"))
def test_parse_topology_rejects_malformed_shape(
    benchmark_module: types.ModuleType, shape: str
) -> None:
    """Malformed topology syntax must not silently select another scenario."""
    with pytest.raises(ValueError, match="SxWxP"):
        benchmark_module.parse_topology(shape)


def test_summarize_ns_uses_nearest_rank_percentiles(
    benchmark_module: types.ModuleType,
) -> None:
    """Changing percentile ranks would distort tail latency evidence."""
    samples = tuple(range(1, 101))

    assert benchmark_module.summarize_ns(samples) == {
        "count": 100,
        "min_ns": 1,
        "mean_ns": 50.5,
        "median_ns": 50.5,
        "p90_ns": 90,
        "p95_ns": 95,
        "p99_ns": 99,
        "max_ns": 100,
    }


def test_summarize_ns_rejects_empty_samples(benchmark_module: types.ModuleType) -> None:
    """An empty timing cell has no defensible descriptive summary."""
    with pytest.raises(ValueError, match="empty"):
        benchmark_module.summarize_ns(())


def test_canonical_ramp_is_ordered_by_live_pane_pressure(
    benchmark_module: types.ModuleType,
) -> None:
    """A reordered ramp would make resource cutoff evidence incomparable."""
    assert tuple(str(shape) for shape in benchmark_module.canonical_ramp()) == (
        "80x20x1",
        "100x20x1",
        "80x20x2",
        "80x50x1",
        "80x20x4",
        "80x100x1",
        "100x50x2",
        "100x100x2",
        "100x100x4",
    )


class LiteralReader:
    """Inject complete procfs and cgroup text without reading the live host."""

    def __init__(self, files: dict[str, str]) -> None:
        self.files = files

    def read_text(self, path: str) -> str:
        """Return the literal content for one absolute procfs path."""
        return self.files[path]

    def getrlimit(self, kind: int) -> tuple[int, int]:
        """Return a finite nofile limit without consulting the process."""
        assert kind >= 0
        return (65_536, 65_536)


def complete_procfs_files() -> dict[str, str]:
    """Return a hand-derived unified-cgroup host fixture."""
    cgroup_path = "/user.slice/user-1000.slice/user@1000.service/app.slice/bench.scope"
    cgroup_root = "/sys/fs/cgroup" + cgroup_path
    return {
        "/proc/meminfo": (
            "MemTotal:       33554432 kB\n"
            "MemFree:         1048576 kB\n"
            "MemAvailable:   25165824 kB\n"
            "Buffers:          123456 kB\n"
            "Cached:          2345678 kB\n"
        ),
        "/proc/self/cgroup": f"0::{cgroup_path}\n",
        "/proc/self/mountinfo": (
            "29 23 0:26 / /sys/fs/cgroup rw,nosuid,nodev,noexec,relatime "
            "- cgroup2 cgroup rw\n"
        ),
        f"{cgroup_root}/pids.current": "472\n",
        f"{cgroup_root}/pids.max": "45343\n",
        f"{cgroup_root}/memory.current": "8589934592\n",
        f"{cgroup_root}/memory.max": "34359738368\n",
        f"{cgroup_root}/memory.pressure": (
            "some avg10=0.00 avg60=0.00 avg300=0.00 total=7\n"
            "full avg10=0.00 avg60=0.00 avg300=0.00 total=7\n"
        ),
    }


def test_probe_host_resolves_unified_cgroup_and_literal_limits(
    benchmark_module: types.ModuleType,
) -> None:
    """A wrong cgroup join would hide the real container resource envelope."""
    snapshot = benchmark_module.probe_host(LiteralReader(complete_procfs_files()))

    assert snapshot.available_memory_bytes == 25_165_824 * 1024
    assert snapshot.physical_memory_bytes == 33_554_432 * 1024
    assert snapshot.pids_current == 472
    assert snapshot.pids_max == 45_343
    assert snapshot.memory_current_bytes == 8_589_934_592
    assert snapshot.memory_max_bytes == 34_359_738_368
    assert snapshot.nofile_soft_limit == 65_536
    assert snapshot.memory_pressure_some_avg10 == 0.0
    assert snapshot.source_errors == {}


def test_probe_host_preserves_missing_telemetry_as_unknown(
    benchmark_module: types.ModuleType,
) -> None:
    """Treating an unreadable cgroup value as zero would make false admissions."""
    files = complete_procfs_files()
    del files[
        "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/bench.scope/pids.current"
    ]

    snapshot = benchmark_module.probe_host(LiteralReader(files))

    assert snapshot.pids_current is None
    assert "pids.current" in snapshot.source_errors


def test_predict_resources_refuses_when_projected_pids_break_reserve(
    benchmark_module: types.ModuleType,
) -> None:
    """Ignoring the PID reserve would let the 40,000-pane plan exhaust cgroups."""
    snapshot = benchmark_module.probe_host(LiteralReader(complete_procfs_files()))

    decision = benchmark_module.predict_resources(
        benchmark_module.parse_topology("100x100x4"), snapshot
    )

    assert decision.allowed is False
    assert decision.kind == "predictive_refusal"
    assert decision.rule == "pid_reserve"
    assert decision.observed == 40_475
    assert decision.limit == 38_541
    assert decision.forceable is True


def test_predict_resources_admits_small_shape_with_same_host_limits(
    benchmark_module: types.ModuleType,
) -> None:
    """A guard that over-refuses would prevent the canonical ramp from starting."""
    snapshot = benchmark_module.probe_host(LiteralReader(complete_procfs_files()))

    decision = benchmark_module.predict_resources(
        benchmark_module.parse_topology("80x20x1"), snapshot
    )

    assert decision.allowed is True
    assert decision.kind == "ok"
    assert decision.rule is None


def completed_report(benchmark_module: types.ModuleType) -> t.Any:
    """Build a literal completed artifact with one failed raw sample excluded."""
    topology = benchmark_module.parse_topology("100x100x4")
    phase = benchmark_module.PhaseReport(
        name="enumeration.sessions",
        requested_topology=topology,
        observed_topology=topology,
        samples=(
            benchmark_module.RawSample(duration_ns=10, accepted=True, verified=True),
            benchmark_module.RawSample(duration_ns=30, accepted=True, verified=True),
            benchmark_module.RawSample(
                duration_ns=999, accepted=False, error="lost row count"
            ),
        ),
        summary={
            "count": 2,
            "min_ns": 10,
            "mean_ns": 20,
            "median_ns": 20.0,
            "p90_ns": 30,
            "p95_ns": 30,
            "p99_ns": 30,
            "max_ns": 30,
        },
    )
    return benchmark_module.RunReport(
        status="completed",
        requested_topology=topology,
        observed_topology=topology,
        phases=(phase,),
        cleanup=benchmark_module.CleanupReport(
            complete=True,
            processes_absent=True,
            socket_absent=True,
            scratch_absent=True,
        ),
        maximum_completed=True,
    )


def test_write_json_atomic_replaces_complete_report(
    benchmark_module: types.ModuleType, tmp_path: pathlib.Path
) -> None:
    """A torn report replacement would destroy evidence after a phase checkpoint."""
    report_path = tmp_path / "report.json"
    report_path.write_text('{"old":true}\n', encoding="utf-8")
    report = completed_report(benchmark_module)

    benchmark_module.write_json_atomic(report_path, report)

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["status"] == "completed"
    assert payload["requested_topology"] == {
        "sessions": 100,
        "windows_per_session": 100,
        "panes_per_window": 4,
    }


def test_write_json_atomic_syncs_file_then_parent(
    benchmark_module: types.ModuleType, tmp_path: pathlib.Path
) -> None:
    """Skipping either durability barrier could lose a completed checkpoint."""
    target = tmp_path / "report.json"
    calls: list[str] = []

    def record_fsync(fd: int) -> None:
        """Record the real descriptor type while preserving fsync behavior."""
        calls.append(
            "directory" if pathlib.Path(f"/proc/self/fd/{fd}").is_dir() else "file"
        )
        benchmark_module.os.fsync(fd)

    def record_replace(
        source: str | pathlib.Path, destination: str | pathlib.Path
    ) -> None:
        """Record atomic replacement while preserving the filesystem effect."""
        calls.append("replace")
        pathlib.Path(source).replace(destination)

    benchmark_module.write_json_atomic(
        target, {"ok": True}, fsync=record_fsync, replace=record_replace
    )

    assert calls == ["file", "replace", "directory"]
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}


def test_report_collections_are_deeply_immutable(
    benchmark_module: types.ModuleType,
) -> None:
    """Mutable source errors or summaries could silently rewrite retained evidence."""
    snapshot = benchmark_module.HostSnapshot(source_errors={"proc": "missing"})
    phase = benchmark_module.PhaseReport(
        "phase",
        benchmark_module.Topology(1, 1, 1),
        benchmark_module.Topology(1, 1, 1),
        summary={"count": 1},
    )

    with pytest.raises(TypeError):
        snapshot.source_errors["proc"] = "changed"
    assert phase.summary is not None
    with pytest.raises(TypeError):
        phase.summary["count"] = 2
    assert benchmark_module._json_value(snapshot)["source_errors"] == {
        "proc": "missing"
    }


def test_probe_host_keeps_rlimit_when_cgroup_resolution_fails(
    benchmark_module: types.ModuleType,
) -> None:
    """A broken cgroup mount must not erase an independent descriptor limit."""
    files = complete_procfs_files()
    files["/proc/self/mountinfo"] = "bad mountinfo\n"
    snapshot = benchmark_module.probe_host(LiteralReader(files))

    assert snapshot.nofile_soft_limit == 65_536
    assert "cgroup2" in snapshot.source_errors


def test_probe_host_marks_malformed_pressure_and_partial_reads(
    benchmark_module: types.ModuleType,
) -> None:
    """A partial cgroup fixture must retain every unavailable source explicitly."""
    files = complete_procfs_files()
    files[
        "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/bench.scope/memory.pressure"
    ] = "some total=1\n"
    del files[
        "/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/bench.scope/memory.max"
    ]
    snapshot = benchmark_module.probe_host(LiteralReader(files))

    assert snapshot.memory_max_bytes is None
    assert {"memory.max", "memory.pressure"} <= set(snapshot.source_errors)


@pytest.mark.parametrize(
    "sample",
    (
        {"duration_ns": 1, "accepted": True, "error": "failure", "verified": True},
        {"duration_ns": 1, "accepted": True, "verified": False},
    ),
)
def test_validate_report_rejects_unverified_accepted_samples(
    benchmark_module: types.ModuleType, sample: dict[str, t.Any]
) -> None:
    """An accepted timing without verified success is not benchmark evidence."""
    report = completed_report(benchmark_module)
    phase = dataclasses.replace(
        report.phases[0], samples=(benchmark_module.RawSample(**sample),)
    )
    with pytest.raises(ValueError, match="verified"):
        benchmark_module.validate_report(dataclasses.replace(report, phases=(phase,)))


def test_validate_report_rejects_missing_or_mismatched_observed_topology(
    benchmark_module: types.ModuleType,
) -> None:
    """A completed phase requires an exact observed topology check."""
    report = completed_report(benchmark_module)
    for observed in (None, benchmark_module.Topology(1, 1, 1)):
        phase = dataclasses.replace(report.phases[0], observed_topology=observed)
        with pytest.raises(ValueError, match="observed topology"):
            benchmark_module.validate_report(
                dataclasses.replace(report, phases=(phase,))
            )


def test_validate_report_recomputes_only_accepted_samples(
    benchmark_module: types.ModuleType,
) -> None:
    """Including a failed duration would poison the reported benchmark statistic."""
    benchmark_module.validate_report(completed_report(benchmark_module))


def test_validate_report_rejects_summary_with_failed_sample(
    benchmark_module: types.ModuleType,
) -> None:
    """A summary that includes a failed timing must not be publishable evidence."""
    report = completed_report(benchmark_module)
    bad_phase = dataclasses.replace(
        report.phases[0],
        summary={
            "count": 3,
            "min_ns": 10,
            "mean_ns": 346.3333333333333,
            "median_ns": 30,
            "p90_ns": 999,
            "p95_ns": 999,
            "p99_ns": 999,
            "max_ns": 999,
        },
    )

    with pytest.raises(ValueError, match="summary"):
        benchmark_module.validate_report(
            dataclasses.replace(report, phases=(bad_phase,))
        )


@pytest.mark.parametrize("status", ("refused", "cutoff"))
def test_validate_report_requires_cleanup_for_terminal_status(
    benchmark_module: types.ModuleType, status: str
) -> None:
    """Successful refusal or cutoff cleanup cannot leave owned state behind."""
    report = dataclasses.replace(
        completed_report(benchmark_module),
        status=status,
        cleanup=benchmark_module.CleanupReport(
            complete=False, errors=("socket remains",)
        ),
        maximum_completed=False,
    )

    with pytest.raises(ValueError, match="cleanup"):
        benchmark_module.validate_report(report)


def test_validate_report_requires_unattempted_shapes_after_cutoff(
    benchmark_module: types.ModuleType,
) -> None:
    """Continuing after a cutoff would misrepresent the ramp's host evidence."""
    report = dataclasses.replace(
        completed_report(benchmark_module),
        status="cutoff",
        maximum_completed=False,
        ramp_kind="custom",
        ramp=(
            benchmark_module.RampStep(
                benchmark_module.parse_topology("80x20x1"), "completed"
            ),
            benchmark_module.RampStep(
                benchmark_module.parse_topology("100x20x1"), "cutoff"
            ),
            benchmark_module.RampStep(
                benchmark_module.parse_topology("80x20x2"), "completed"
            ),
        ),
        requested_shapes=tuple(
            benchmark_module.parse_topology(shape)
            for shape in ("80x20x1", "100x20x1", "80x20x2")
        ),
    )

    with pytest.raises(ValueError, match="not_attempted"):
        benchmark_module.validate_report(report)


@pytest.mark.parametrize(
    ("requested", "observed"),
    (("100x100x2", "100x100x2"), ("100x100x4", "100x100x2")),
)
def test_validate_report_rejects_false_maximum_completion(
    benchmark_module: types.ModuleType, requested: str, observed: str
) -> None:
    """A smaller or incomplete shape cannot be presented as the maximum completed."""
    report = dataclasses.replace(
        completed_report(benchmark_module),
        requested_topology=benchmark_module.parse_topology(requested),
        observed_topology=benchmark_module.parse_topology(observed),
    )

    with pytest.raises(ValueError, match="maximum_completed"):
        benchmark_module.validate_report(report)


def test_runtime_guard_never_allows_force_override(
    benchmark_module: types.ModuleType,
) -> None:
    """Forcing a runtime cutoff would bypass actual liveness and cleanup safety."""
    snapshot = benchmark_module.HostSnapshot(pids_current=45_000, pids_max=45_343)

    decision = benchmark_module.check_runtime_guard(snapshot, force_extreme=True)

    assert decision.allowed is False
    assert decision.kind == "runtime_cutoff"
    assert decision.forceable is False


def test_plan_writes_original_predictive_decision_without_talking_to_tmux(
    tmp_path: pathlib.Path,
) -> None:
    """The planning path must remain an offline inspection even when forced."""
    script = pathlib.Path(__file__).parents[1] / "scripts" / "bench_orchestration.py"
    output = tmp_path / "plan.json"

    completed = subprocess.run(
        (
            sys.executable,
            str(script),
            "plan",
            "--shape",
            "1x1x1",
            "--output",
            str(output),
            "--force-extreme",
        ),
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Sessions" in completed.stdout
    assert not list(tmp_path.glob("*.sock"))
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["command"] == "plan"
    assert (
        payload["original_guard_decision"] == payload["guard_decision"]
        or payload["original_guard_decision"]["kind"] == "predictive_refusal"
    )
    assert payload["pidfd_capability"] == {
        "available": True,
        "reason": None,
    }


def test_validate_report_rejects_contradictory_ramp_terminal_sequence(
    benchmark_module: types.ModuleType,
) -> None:
    """A ramp cannot report completion after recording a cutoff."""
    shapes = tuple(benchmark_module.Topology(1, 1, panes) for panes in (1, 2, 3))
    report = dataclasses.replace(
        completed_report(benchmark_module),
        status="cutoff",
        maximum_completed=False,
        ramp_kind="custom",
        requested_shapes=shapes,
        ramp=(
            benchmark_module.RampStep(shapes[0], "completed"),
            benchmark_module.RampStep(shapes[1], "cutoff", "pid_reserve"),
            benchmark_module.RampStep(shapes[2], "completed"),
        ),
    )
    with pytest.raises(ValueError, match="not_attempted"):
        benchmark_module.validate_report(report)


def test_validate_report_rejects_canonical_kind_with_custom_shapes(
    benchmark_module: types.ModuleType,
) -> None:
    """Canonical evidence must retain every specified canonical ramp shape."""
    shape = benchmark_module.Topology(1, 1, 1)
    report = dataclasses.replace(
        completed_report(benchmark_module),
        ramp_kind="canonical",
        requested_shapes=(shape,),
        ramp=(benchmark_module.RampStep(shape, "completed"),),
    )
    with pytest.raises(ValueError, match="canonical"):
        benchmark_module.validate_report(report)


def test_validate_report_rejects_invalid_runtime_ramp_kind(
    benchmark_module: types.ModuleType,
) -> None:
    """Deserialized report data must not bypass the Literal ramp vocabulary."""
    report = dataclasses.replace(
        completed_report(benchmark_module), ramp_kind="invalid"
    )
    with pytest.raises(ValueError, match="ramp_kind"):
        benchmark_module.validate_report(report)


def test_validate_report_rejects_invalid_runtime_report_status(
    benchmark_module: types.ModuleType,
) -> None:
    """Deserialized lifecycle state must remain inside the report vocabulary."""
    report = dataclasses.replace(completed_report(benchmark_module), status="invalid")

    with pytest.raises(ValueError, match="status"):
        benchmark_module.validate_report(report)


@pytest.mark.parametrize("field", ("guard_decision", "original_guard_decision"))
def test_validate_report_rejects_invalid_runtime_guard_kind(
    benchmark_module: types.ModuleType, field: str
) -> None:
    """Deserialized guard evidence must remain inside its Literal vocabulary."""
    invalid_guard = benchmark_module.GuardDecision(
        True,
        "invalid",
        None,
        None,
        None,
        False,
        benchmark_module.HostSnapshot(),
    )
    report = dataclasses.replace(
        completed_report(benchmark_module), **{field: invalid_guard}
    )

    with pytest.raises(ValueError, match="guard decision kind"):
        benchmark_module.validate_report(report)


@pytest.mark.parametrize("status", ("refused", "failed", "cutoff"))
def test_validate_report_accepts_exact_terminal_ramp_sequence(
    benchmark_module: types.ModuleType, status: str
) -> None:
    """Each terminal ramp state has one matching stop and one shared reason."""
    shapes = tuple(benchmark_module.Topology(1, 1, panes) for panes in (1, 2, 3))
    reason = f"{status}_reason"
    report = dataclasses.replace(
        completed_report(benchmark_module),
        status=status,
        maximum_completed=False,
        ramp_kind="custom",
        requested_shapes=shapes,
        ramp=(
            benchmark_module.RampStep(shapes[0], "completed"),
            benchmark_module.RampStep(shapes[1], status, reason),
            benchmark_module.RampStep(shapes[2], "not_attempted", reason),
        ),
    )

    benchmark_module.validate_report(report)


def test_validate_report_rejects_invalid_runtime_attempt_status(
    benchmark_module: types.ModuleType,
) -> None:
    """Deserialized attempt state must remain inside the ramp vocabulary."""
    shape = benchmark_module.Topology(1, 1, 1)
    report = dataclasses.replace(
        completed_report(benchmark_module),
        maximum_completed=False,
        ramp_kind="custom",
        requested_shapes=(shape,),
        ramp=(benchmark_module.RampStep(shape, "invalid"),),
    )

    with pytest.raises(ValueError, match="attempt status"):
        benchmark_module.validate_report(report)


def test_validate_report_rejects_none_ramp_kind_with_shapes(
    benchmark_module: types.ModuleType,
) -> None:
    """Single-run evidence cannot smuggle in an undeclared ramp sequence."""
    shape = benchmark_module.Topology(1, 1, 1)
    report = dataclasses.replace(
        completed_report(benchmark_module),
        maximum_completed=False,
        requested_shapes=(shape,),
        ramp=(benchmark_module.RampStep(shape, "completed"),),
    )

    with pytest.raises(ValueError, match="none ramp kind"):
        benchmark_module.validate_report(report)


@pytest.mark.parametrize("duplicate", (False, True))
def test_validate_report_rejects_invalid_custom_shape_declaration(
    benchmark_module: types.ModuleType, duplicate: bool
) -> None:
    """A custom ramp must declare at least one shape and cannot repeat one."""
    shape = benchmark_module.Topology(1, 1, 1)
    requested_shapes = (shape, shape) if duplicate else ()
    ramp = tuple(
        benchmark_module.RampStep(requested, "completed")
        for requested in requested_shapes
    )
    report = dataclasses.replace(
        completed_report(benchmark_module),
        maximum_completed=False,
        ramp_kind="custom",
        requested_shapes=requested_shapes,
        ramp=ramp,
    )

    with pytest.raises(ValueError, match="custom ramp kind"):
        benchmark_module.validate_report(report)


def test_validate_report_rejects_in_progress_ramp_with_cutoff_attempt(
    benchmark_module: types.ModuleType,
) -> None:
    """A runtime cutoff requires finalizing the report at the same checkpoint."""
    shapes = (
        benchmark_module.Topology(1, 1, 1),
        benchmark_module.Topology(1, 1, 2),
        benchmark_module.Topology(1, 1, 3),
    )
    report = benchmark_module.RunReport(
        requested_topology=shapes[-1],
        status="in_progress",
        ramp_kind="custom",
        requested_shapes=shapes,
        ramp=(
            benchmark_module.RampStep(shapes[0], "completed"),
            benchmark_module.RampStep(shapes[1], "cutoff", "pid_reserve"),
            benchmark_module.RampStep(shapes[2], "not_attempted", "pid_reserve"),
        ),
    )

    with pytest.raises(ValueError, match=r"in-progress.*terminal"):
        benchmark_module.validate_report(report)


def test_validate_report_rejects_in_progress_ramp_with_different_terminals(
    benchmark_module: types.ModuleType,
) -> None:
    """An unfinished report cannot retain competing terminal outcomes."""
    shapes = (
        benchmark_module.Topology(1, 1, 1),
        benchmark_module.Topology(1, 1, 2),
        benchmark_module.Topology(1, 1, 3),
    )
    report = benchmark_module.RunReport(
        requested_topology=shapes[-1],
        status="in_progress",
        ramp_kind="custom",
        requested_shapes=shapes,
        ramp=(
            benchmark_module.RampStep(shapes[0], "refused", "pid_reserve"),
            benchmark_module.RampStep(shapes[1], "failed", "tmux_exit"),
            benchmark_module.RampStep(shapes[2], "not_attempted"),
        ),
    )

    with pytest.raises(ValueError, match=r"in-progress.*terminal"):
        benchmark_module.validate_report(report)


def test_validate_report_rejects_in_progress_ramp_completed_after_pending(
    benchmark_module: types.ModuleType,
) -> None:
    """Completed ramp work must remain a prefix of an unfinished checkpoint."""
    shapes = (
        benchmark_module.Topology(1, 1, 1),
        benchmark_module.Topology(1, 1, 2),
        benchmark_module.Topology(1, 1, 3),
    )
    report = benchmark_module.RunReport(
        requested_topology=shapes[-1],
        status="in_progress",
        ramp_kind="custom",
        requested_shapes=shapes,
        ramp=(
            benchmark_module.RampStep(shapes[0], "completed"),
            benchmark_module.RampStep(shapes[1], "not_attempted"),
            benchmark_module.RampStep(shapes[2], "completed"),
        ),
    )

    with pytest.raises(ValueError, match="completed prefix"):
        benchmark_module.validate_report(report)


def test_validate_report_rejects_in_progress_ramp_pending_reason(
    benchmark_module: types.ModuleType,
) -> None:
    """Pending attempts use ``None`` until a terminal reason exists."""
    shapes = benchmark_module.canonical_ramp()
    report = benchmark_module.RunReport(
        requested_topology=shapes[-1],
        status="in_progress",
        ramp_kind="canonical",
        requested_shapes=shapes,
        ramp=tuple(
            benchmark_module.RampStep(
                shape,
                "not_attempted",
                "waiting" if index == 0 else None,
            )
            for index, shape in enumerate(shapes)
        ),
    )

    with pytest.raises(ValueError, match=r"pending.*reason"):
        benchmark_module.validate_report(report)


def test_validate_report_accepts_initial_in_progress_ramp(
    benchmark_module: types.ModuleType,
) -> None:
    """A canonical ramp may checkpoint before attempting its first shape."""
    shapes = benchmark_module.canonical_ramp()
    report = benchmark_module.RunReport(
        requested_topology=shapes[-1],
        status="in_progress",
        ramp_kind="canonical",
        requested_shapes=shapes,
        ramp=tuple(
            benchmark_module.RampStep(shape, "not_attempted") for shape in shapes
        ),
    )

    benchmark_module.validate_report(report)


def test_validate_report_accepts_in_progress_completed_prefix(
    benchmark_module: types.ModuleType,
) -> None:
    """An unfinished custom ramp may retain completed work before pending shapes."""
    shapes = (
        benchmark_module.Topology(1, 1, 1),
        benchmark_module.Topology(1, 1, 2),
        benchmark_module.Topology(1, 1, 3),
    )
    report = benchmark_module.RunReport(
        requested_topology=shapes[-1],
        status="in_progress",
        ramp_kind="custom",
        requested_shapes=shapes,
        ramp=(
            benchmark_module.RampStep(shapes[0], "completed"),
            benchmark_module.RampStep(shapes[1], "completed"),
            benchmark_module.RampStep(shapes[2], "not_attempted"),
        ),
    )

    benchmark_module.validate_report(report)


def test_lifecycle_marker_reader_rejects_boolean_schema_version(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
) -> None:
    """A boolean schema value must not release a run as integer version one."""
    marker = tmp_path / "marker.json"
    marker.write_text('{"schema_version":true,"run_id":"run-7"}\n', encoding="utf-8")

    assert benchmark_module._read_run_marker(marker, "run-7") is None


def test_live_topology_setup_preserves_preexisting_scratch(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
) -> None:
    """A rejected run must never delete a directory it did not create."""
    scratch = tmp_path / "already-owned"
    scratch.mkdir()
    marker = scratch / "owner.txt"
    marker.write_text("keep\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        benchmark_module.setup_sync(
            benchmark_module.Topology(1, 1, 1),
            benchmark_module.EngineLane.SUBPROCESS,
            scratch,
            run_id="preexisting",
        )

    assert marker.read_text(encoding="utf-8") == "keep\n"


def test_owned_process_cleanup_kills_sigterm_ignoring_child(
    benchmark_module: types.ModuleType,
) -> None:
    """A child that ignores graceful stop must be identity-killed and reaped."""
    process = subprocess.Popen(
        (
            sys.executable,
            "-c",
            (
                "import signal,sys,time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "print('ready', flush=True); time.sleep(30)"
            ),
        ),
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline() == "ready\n"
        identity = benchmark_module._record_process("test-child", process.pid)

        report = benchmark_module._stop_owned_process(
            process,
            identity,
            grace_s=0.05,
        )

        assert report.complete
        assert report.errors == ()
        assert process.poll() == -signal.SIGKILL
        assert not benchmark_module.process_identity_matches(identity)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=2.0)


def test_pidfd_registry_signals_only_the_retained_real_child(
    benchmark_module: types.ModuleType,
) -> None:
    """A retained pidfd must terminate its exact child without a PID lookup."""
    capability_error = benchmark_module._pidfd_capability_error()
    if capability_error is not None:
        pytest.skip(capability_error)
    target = subprocess.Popen(
        (sys.executable, "-c", "import time; time.sleep(60)"),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    unrelated = subprocess.Popen(
        (sys.executable, "-c", "import time; time.sleep(60)"),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    registry = benchmark_module._PidfdRegistry()
    try:
        identity = benchmark_module._record_process("target", target.pid)
        assert registry.retain(identity)
        assert registry.signal(identity, signal.SIGTERM)
        assert target.wait(timeout=2.0) == -signal.SIGTERM
        assert unrelated.poll() is None
    finally:
        registry.close()
        if target.poll() is None:
            target.kill()
        target.wait(timeout=2.0)
        if unrelated.poll() is None:
            unrelated.terminate()
        unrelated.wait(timeout=2.0)


def test_pidfd_capability_probe_opens_signals_and_closes_self(
    benchmark_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Capability success requires a real signal-zero operation on a self pidfd."""
    calls: list[tuple[t.Any, ...]] = []
    descriptor = os.open("/proc/self/stat", os.O_RDONLY)

    def open_pidfd(pid: int, flags: int) -> int:
        calls.append(("open", pid, flags))
        return descriptor

    def send_signal(
        received: int,
        number: int,
        siginfo: object,
        flags: int,
    ) -> None:
        calls.append(("signal", received, number, siginfo, flags))

    monkeypatch.setattr(benchmark_module.os, "pidfd_open", open_pidfd, raising=False)
    monkeypatch.setattr(
        benchmark_module.signal,
        "pidfd_send_signal",
        send_signal,
        raising=False,
    )

    assert benchmark_module._pidfd_capability_error() is None
    assert calls == [
        ("open", os.getpid(), 0),
        ("signal", descriptor, 0, None, 0),
    ]
    with pytest.raises(OSError, match="Bad file descriptor"):
        os.fstat(descriptor)


@pytest.mark.parametrize(
    ("operation", "error_number"),
    (
        ("open", errno.ENOSYS),
        ("open", errno.EACCES),
        ("signal", errno.EPERM),
        ("signal", errno.EINVAL),
    ),
)
def test_run_scenario_refuses_failed_pidfd_self_probe_before_side_effects(
    benchmark_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    operation: str,
    error_number: int,
) -> None:
    """An unusable stable-signal syscall must refuse before any run resource."""
    descriptor: int | None = None

    def fail_open(pid: int, flags: int) -> int:
        nonlocal descriptor
        if operation == "open":
            raise OSError(error_number, os.strerror(error_number))
        descriptor = os.open("/proc/self/stat", os.O_RDONLY)
        return descriptor

    def fail_signal(
        descriptor: int,
        number: int,
        siginfo: object,
        flags: int,
    ) -> None:
        if operation == "signal":
            raise OSError(error_number, os.strerror(error_number))
        pytest.fail("open failure reached pidfd_send_signal")

    monkeypatch.setattr(benchmark_module.os, "pidfd_open", fail_open, raising=False)
    monkeypatch.setattr(
        benchmark_module.signal,
        "pidfd_send_signal",
        fail_signal,
        raising=False,
    )
    marker = tmp_path / "tmux-executed"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_tmux = fake_bin / "tmux"
    fake_tmux.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib\n"
        f"pathlib.Path({str(marker)!r}).touch()\n",
        encoding="utf-8",
    )
    fake_tmux.chmod(fake_tmux.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")

    def reject_spawn(*_args: t.Any, **_kwargs: t.Any) -> t.NoReturn:
        pytest.fail("failed pidfd preflight spawned a worker")

    monkeypatch.setattr(benchmark_module.subprocess, "Popen", reject_spawn)
    output = tmp_path / f"pidfd-{operation}.json"
    scratch_root = tmp_path / "scratch"

    report = benchmark_module.run_scenario(
        benchmark_module.Topology(1, 1, 1),
        runs=1,
        warmup=0,
        output=output,
        scratch_root=scratch_root,
        host_snapshot=benchmark_module.HostSnapshot(
            available_memory_bytes=16 * 1024**3,
            pids_current=1,
            pids_max=100_000,
            nofile_soft_limit=65_536,
        ),
        policy=benchmark_module.ResourcePolicy(
            pid_reserve=1,
            memory_floor_bytes=1,
        ),
    )

    assert report.status == "refused"
    assert report.failed_phase == "preflight"
    assert "pidfd" in t.cast(str, report.error)
    assert os.strerror(error_number) in t.cast(str, report.error)
    assert not scratch_root.exists()
    assert report.scratch_path is None
    assert report.socket_path is None
    assert report.processes == ()
    assert not marker.exists()
    if descriptor is not None:
        with pytest.raises(OSError, match="Bad file descriptor"):
            os.fstat(descriptor)


def test_pidfd_capability_real_self_probe(
    benchmark_module: types.ModuleType,
) -> None:
    """The supported test host must prove a stable signal-zero pidfd operation."""
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        pytest.skip("interpreter does not expose Linux pidfd APIs")
    assert benchmark_module._pidfd_capability_error() is None


def test_pidfd_registry_rejects_reuse_between_open_checks(
    benchmark_module: types.ModuleType,
) -> None:
    """A PID reused between precheck/open/postcheck must never be signaled."""
    child = subprocess.Popen(
        (sys.executable, "-c", "import time; time.sleep(60)"),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    identity = benchmark_module._record_process("target", child.pid)
    observed = iter((identity.start_time, identity.start_time + 1))
    registry = benchmark_module._PidfdRegistry(
        _start_time_reader=lambda _pid: next(observed),
    )
    try:
        assert not registry.retain(identity)
        assert not registry.signal(identity, signal.SIGKILL)
        assert child.poll() is None
        assert registry.retained == ()
    finally:
        registry.close()
        child.terminate()
        child.wait(timeout=2.0)


def test_pidfd_registry_rejects_an_already_mismatched_identity(
    benchmark_module: types.ModuleType,
) -> None:
    """An unrelated process at a recorded PID must remain untouched."""
    child = subprocess.Popen(
        (sys.executable, "-c", "import time; time.sleep(60)"),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    current = benchmark_module._record_process("unrelated", child.pid)
    stale = dataclasses.replace(current, start_time=current.start_time + 1)
    registry = benchmark_module._PidfdRegistry()
    try:
        assert not registry.retain(stale)
        assert not registry.signal(stale, signal.SIGKILL)
        assert child.poll() is None
    finally:
        registry.close()
        child.terminate()
        child.wait(timeout=2.0)


def test_exact_socket_fallback_kills_only_the_configured_tmux_server(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
) -> None:
    """Fallback cleanup must address one socket and preserve another daemon."""
    target = tmp_path / "target.sock"
    unrelated = tmp_path / "unrelated.sock"
    for socket_path in (target, unrelated):
        created = subprocess.run(
            (
                "tmux",
                "-S",
                str(socket_path),
                "new-session",
                "-d",
                "-s",
                "keepalive",
            ),
            check=False,
            capture_output=True,
            text=True,
        )
        assert created.returncode == 0, created.stderr
    try:
        errors = benchmark_module._kill_exact_tmux_socket(target, timeout_s=1.0)

        assert errors == ()
        assert not target.exists()
        still_alive = subprocess.run(
            ("tmux", "-S", str(unrelated), "list-sessions"),
            check=False,
            capture_output=True,
            text=True,
        )
        assert still_alive.returncode == 0, still_alive.stderr
    finally:
        subprocess.run(
            ("tmux", "-S", str(unrelated), "kill-server"),
            check=False,
            capture_output=True,
            text=True,
        )


def test_run_scenario_refuses_when_pidfds_are_unavailable(
    benchmark_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """Unsupported hosts must fail closed before the hidden worker is spawned."""
    monkeypatch.setattr(
        benchmark_module,
        "_pidfd_capability_error",
        lambda: "pidfd signaling unavailable",
    )

    def reject_spawn(*_args: t.Any, **_kwargs: t.Any) -> t.NoReturn:
        pytest.fail("unsupported pidfd host spawned a worker")

    monkeypatch.setattr(benchmark_module.subprocess, "Popen", reject_spawn)
    output = tmp_path / "unsupported.json"
    report = benchmark_module.run_scenario(
        benchmark_module.Topology(1, 1, 1),
        runs=1,
        warmup=0,
        output=output,
        host_snapshot=benchmark_module.HostSnapshot(
            available_memory_bytes=16 * 1024**3,
            pids_current=1,
            pids_max=100_000,
            nofile_soft_limit=65_536,
        ),
        policy=benchmark_module.ResourcePolicy(
            pid_reserve=1,
            memory_floor_bytes=1,
        ),
    )

    assert report.status == "refused"
    assert report.failed_phase == "preflight"
    assert report.error == "pidfd signaling unavailable"
    assert report.cleanup.complete
    assert output.exists()


def test_start_fuzzer_reaps_child_after_readiness_timeout(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
) -> None:
    """A pre-return timeout must leave no fuzzer child for the caller to own."""
    run_id = f"readiness-timeout-{os.getpid()}"

    with pytest.raises(RuntimeError, match="did not become ready"):
        benchmark_module.start_fuzzer(
            tmp_path,
            run_id,
            ready_timeout_s=1e-9,
        )

    processes = subprocess.run(
        ("ps", "-eo", "args="),
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert run_id not in processes


def test_start_fuzzer_publishes_identity_before_readiness_wait(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A startup stall cannot hide the already spawned fuzzer from recovery."""
    published: list[t.Any] = []

    def stop_at_readiness(*_args: t.Any, **_kwargs: t.Any) -> t.NoReturn:
        assert [identity.role for identity in published] == ["fuzzer"]
        message = "injected readiness stop"
        raise RuntimeError(message)

    monkeypatch.setattr(
        benchmark_module,
        "_wait_for_fuzzer_ready",
        stop_at_readiness,
    )

    with pytest.raises(RuntimeError, match="injected readiness stop"):
        benchmark_module.start_fuzzer(
            tmp_path,
            "early-fuzzer",
            _identity_callback=lambda delta: published.extend(delta),
        )

    assert len(published) == 1
    assert not benchmark_module.process_identity_matches(published[0])


def test_prepare_context_keeps_start_fuzzer_identity_for_partial_cleanup(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Later setup must reuse the identity captured while starting the child."""
    real_record_process = benchmark_module._record_process
    real_start_fuzzer = benchmark_module.start_fuzzer
    fuzzer_identities: list[t.Any] = []
    spawned: list[subprocess.Popen[bytes]] = []
    context = None

    def record_fuzzer_once(role: str, pid: int) -> t.Any:
        if role == "fuzzer":
            if fuzzer_identities:
                message = "fuzzer identity was captured twice"
                raise RuntimeError(message)
            identity = real_record_process(role, pid)
            fuzzer_identities.append(identity)
            return identity
        return real_record_process(role, pid)

    def capture_fuzzer(*args: t.Any, **kwargs: t.Any) -> subprocess.Popen[bytes]:
        process = t.cast(
            subprocess.Popen[bytes],
            real_start_fuzzer(*args, **kwargs),
        )
        spawned.append(process)
        return process

    monkeypatch.setattr(benchmark_module, "_record_process", record_fuzzer_once)
    monkeypatch.setattr(benchmark_module, "start_fuzzer", capture_fuzzer)
    try:
        context = benchmark_module._prepare_context(
            benchmark_module.Topology(1, 1, 1),
            benchmark_module.EngineLane.SUBPROCESS,
            benchmark_module.ExecutionMode.SYNC,
            tmp_path / "identity-owner",
            socket_path=None,
            run_id="identity-owner",
            delayed_ordinal=0,
        )

        assert len(fuzzer_identities) == 1
        assert context.processes == (fuzzer_identities[0],)
    finally:
        if context is not None:
            report = asyncio.run(benchmark_module.cleanup_run(context))
            assert report.complete, report.errors
        elif spawned:
            report = benchmark_module._stop_owned_process(
                spawned[0],
                fuzzer_identities[0],
            )
            assert report.complete, report.errors


def test_setup_publishes_early_constant_deltas_and_one_pane_batch(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
) -> None:
    """Server recovery identity must precede build and panes must publish once."""
    topology = benchmark_module.Topology(1, 2, 2)
    scratch = tmp_path / "identity-deltas"
    socket_path = scratch / "tmux.sock"
    deltas: list[tuple[t.Any, ...]] = []
    context = cleanup = None

    def publish(delta: tuple[t.Any, ...]) -> None:
        deltas.append(delta)
        if tuple(identity.role for identity in delta) == ("server",):
            listed = subprocess.run(
                (
                    "tmux",
                    "-S",
                    str(socket_path),
                    "list-sessions",
                    "-F",
                    "#{session_name}",
                ),
                check=True,
                capture_output=True,
                text=True,
            )
            assert listed.stdout.splitlines() == ["bench-identity-deltas-keepalive"]

    try:
        context = benchmark_module.setup_sync(
            topology,
            benchmark_module.EngineLane.SUBPROCESS,
            scratch,
            socket_path=socket_path,
            run_id="identity-deltas",
            delayed_ordinal=1,
            _process_identity_callback=publish,
        )
    finally:
        if context is not None:
            cleanup = asyncio.run(benchmark_module.cleanup_run(context))

    assert cleanup is not None and cleanup.complete, getattr(cleanup, "errors", ())
    assert [tuple(identity.role for identity in delta) for delta in deltas] == [
        ("fuzzer",),
        ("server",),
        ("pane", "pane", "pane", "pane"),
    ]


@pytest.mark.parametrize("mode_name", ("sync", "async"))
def test_setup_surfaces_original_and_cleanup_failures(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    mode_name: str,
) -> None:
    """A partial setup must retain its cause and unsuccessful cleanup evidence."""
    captured_contexts: list[t.Any] = []
    real_cleanup = benchmark_module.cleanup_run

    def fail_verification(_context: t.Any, _snapshot: t.Any) -> t.NoReturn:
        message = "injected setup failure"
        raise RuntimeError(message)

    async def cleanup_with_injected_failure(context: t.Any) -> t.Any:
        captured_contexts.append(context)
        report = await real_cleanup(context)
        assert report.complete, report.errors
        return benchmark_module.CleanupReport(
            complete=False,
            errors=("injected cleanup failure",),
        )

    monkeypatch.setattr(benchmark_module, "verify_topology", fail_verification)
    monkeypatch.setattr(
        benchmark_module,
        "cleanup_run",
        cleanup_with_injected_failure,
    )
    scratch = tmp_path / mode_name

    with pytest.raises(benchmark_module.SetupCleanupError) as raised:
        if mode_name == "sync":
            benchmark_module.setup_sync(
                benchmark_module.Topology(1, 1, 1),
                benchmark_module.EngineLane.SUBPROCESS,
                scratch,
                run_id=f"cleanup-evidence-{mode_name}",
            )
        else:
            asyncio.run(
                benchmark_module.setup_async(
                    benchmark_module.Topology(1, 1, 1),
                    benchmark_module.EngineLane.SUBPROCESS,
                    scratch,
                    run_id=f"cleanup-evidence-{mode_name}",
                )
            )

    error = raised.value
    assert isinstance(error.setup_error, RuntimeError)
    assert str(error.setup_error) == "injected setup failure"
    assert error.__cause__ is error.setup_error
    assert error.cleanup_report.errors == ("injected cleanup failure",)
    assert len(captured_contexts) == 1
    assert not scratch.exists()
    assert all(
        not benchmark_module.process_identity_matches(identity)
        for identity in captured_contexts[0].processes
    )


def test_setup_acquires_private_scratch_under_permissive_umask(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
) -> None:
    """Run scratch must be mode 0700 even when the ambient umask permits 0777."""
    scratch = tmp_path / "private-scratch"
    context = None
    previous_umask = os.umask(0)
    try:
        context = benchmark_module.setup_sync(
            benchmark_module.Topology(1, 1, 1),
            benchmark_module.EngineLane.SUBPROCESS,
            scratch,
            run_id="private-scratch",
        )
    finally:
        os.umask(previous_umask)
    try:
        assert stat.S_IMODE(scratch.stat().st_mode) == 0o700
    finally:
        if context is not None:
            cleanup = asyncio.run(benchmark_module.cleanup_run(context))
            assert cleanup.complete, cleanup.errors


@pytest.mark.parametrize(
    ("target_kind", "failure_kind"),
    (
        ("scratch", "chmod"),
        ("scratch", "stat"),
        ("socket-root", "chmod"),
        ("socket-root", "stat"),
    ),
)
def test_private_directory_acquisition_rolls_back_post_mkdir_failure(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    target_kind: str,
    failure_kind: str,
) -> None:
    """A post-mkdir acquisition failure must remove the exact new directory."""
    token = f"{target_kind[:3]}{failure_kind[:4]}0"
    scratch = tmp_path / f"{target_kind}-{failure_kind}"
    socket_root = pathlib.Path(benchmark_module.tempfile.gettempdir()) / (
        f"libtmux-bench-{os.getpid():x}-{token}"
    )
    target = scratch if target_kind == "scratch" else socket_root
    real_chmod = pathlib.Path.chmod
    real_stat = pathlib.Path.stat
    injected = False

    def fail_target_chmod(path: pathlib.Path, *args: t.Any, **kwargs: t.Any) -> None:
        nonlocal injected
        if path == target:
            injected = True
            message = f"injected {target_kind} chmod failure"
            raise OSError(message)
        real_chmod(path, *args, **kwargs)

    def fail_target_stat(
        path: pathlib.Path,
        *args: t.Any,
        **kwargs: t.Any,
    ) -> os.stat_result:
        nonlocal injected
        if path == target and os.path.lexists(path) and not injected:
            injected = True
            message = f"injected {target_kind} stat failure"
            raise OSError(message)
        return real_stat(path, *args, **kwargs)

    def unexpected_fuzzer(*_args: object, **_kwargs: object) -> t.NoReturn:
        message = "fuzzer started after failed directory acquisition"
        raise AssertionError(message)

    monkeypatch.setattr(
        benchmark_module.uuid,
        "uuid4",
        lambda: types.SimpleNamespace(hex=token),
    )
    monkeypatch.setattr(benchmark_module, "start_fuzzer", unexpected_fuzzer)
    if failure_kind == "chmod":
        monkeypatch.setattr(pathlib.Path, "chmod", fail_target_chmod)
    else:
        monkeypatch.setattr(pathlib.Path, "stat", fail_target_stat)

    try:
        with pytest.raises(
            OSError,
            match=f"injected {target_kind} {failure_kind} failure",
        ):
            benchmark_module._prepare_context(
                benchmark_module.Topology(1, 1, 1),
                benchmark_module.EngineLane.SUBPROCESS,
                benchmark_module.ExecutionMode.SYNC,
                scratch,
                socket_path=None,
                run_id=f"acquire-{target_kind}-{failure_kind}",
                delayed_ordinal=0,
            )

        assert injected
        assert not scratch.exists()
        assert not socket_root.exists()
    finally:
        if socket_root.exists():
            socket_root.rmdir()
        if scratch.exists():
            scratch.rmdir()


def test_private_directory_acquisition_surfaces_exact_rollback_failure(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A nonempty rollback must preserve its path and both failure objects."""
    directory = tmp_path / "rollback-failure"
    marker = directory / "do-not-delete"
    acquisition_error = OSError("injected chmod failure")
    real_chmod = pathlib.Path.chmod

    def fail_after_writing_marker(
        path: pathlib.Path,
        *args: t.Any,
        **kwargs: t.Any,
    ) -> None:
        if path == directory:
            marker.write_text("preserved\n", encoding="utf-8")
            raise acquisition_error
        real_chmod(path, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "chmod", fail_after_writing_marker)
    try:
        with pytest.raises(RuntimeError) as raised:
            benchmark_module._acquire_private_directory(directory)

        error = raised.value
        assert isinstance(error, benchmark_module.PrivateDirectoryAcquisitionError)
        assert error.directory == directory
        assert error.acquisition_error is acquisition_error
        assert isinstance(error.rollback_error, OSError)
        assert error.__cause__ is acquisition_error
        assert marker.read_text(encoding="utf-8") == "preserved\n"
    finally:
        if marker.exists():
            marker.unlink()
        if directory.exists():
            directory.rmdir()


def test_socket_path_limit_counts_encoded_bytes(
    benchmark_module: types.ModuleType,
) -> None:
    """The pathname ceiling must reserve the sockaddr_un terminator byte."""
    at_limit = pathlib.Path("/" + "é" * 53)
    over_limit = pathlib.Path("/" + "é" * 53 + "s")
    assert len(os.fsencode(at_limit)) == 107
    assert len(os.fsencode(over_limit)) == 108

    assert benchmark_module._validate_socket_path(at_limit) == at_limit
    with pytest.raises(ValueError, match="107 encoded bytes"):
        benchmark_module._validate_socket_path(over_limit)


def test_explicit_long_socket_is_rejected_before_owned_side_effects(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An invalid explicit socket must not start a fuzzer or acquire scratch."""
    scratch = tmp_path / "must-not-exist"
    socket_path = scratch / ("s" * 200)

    def unexpected_fuzzer(*_args: object, **_kwargs: object) -> t.NoReturn:
        message = "fuzzer started before socket validation"
        raise AssertionError(message)

    monkeypatch.setattr(benchmark_module, "start_fuzzer", unexpected_fuzzer)

    with pytest.raises(ValueError, match="107 encoded bytes"):
        benchmark_module.setup_sync(
            benchmark_module.Topology(1, 1, 1),
            benchmark_module.EngineLane.SUBPROCESS,
            scratch,
            socket_path=socket_path,
            run_id="long-socket",
        )

    assert not scratch.exists()


def test_default_socket_uses_short_owned_root_for_long_scratch(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
) -> None:
    """An owned socket remains ABI-safe when the caller's scratch path is long."""
    scratch = tmp_path / ("long-scratch-" + "s" * 100)
    context = benchmark_module.setup_sync(
        benchmark_module.Topology(1, 1, 1),
        benchmark_module.EngineLane.SUBPROCESS,
        scratch,
        run_id="short-owned-socket",
    )
    socket_root = context.socket_root
    try:
        assert len(os.fsencode(context.socket_path)) <= 107
        assert socket_root is not None
        assert context.socket_path.parent == socket_root
        assert not context.socket_path.is_relative_to(scratch)
    finally:
        cleanup = asyncio.run(benchmark_module.cleanup_run(context))
        assert cleanup.complete, cleanup.errors
    assert not socket_root.exists()


def test_verify_topology_rejects_swapped_window_parents(
    benchmark_module: types.ModuleType,
) -> None:
    """Correct per-session counts must not hide windows attached to wrong parents."""
    session_names = ("bench-parent-s000", "bench-parent-s001")
    window_names = (
        "bench-parent-s000-w000",
        "bench-parent-s001-w000",
    )
    context = types.SimpleNamespace(
        topology=benchmark_module.Topology(2, 1, 1),
        expected_session_names=session_names,
        expected_window_names=window_names,
        expected_window_parents=(
            (window_names[0], session_names[0]),
            (window_names[1], session_names[1]),
        ),
        streams=(pathlib.Path("editor.log"), pathlib.Path("delayed-match.log")),
    )
    snapshot = benchmark_module.TopologySnapshot(
        sessions=(
            SessionSnapshot(session_id="$0", name=session_names[0]),
            SessionSnapshot(session_id="$1", name=session_names[1]),
        ),
        windows=(
            WindowSnapshot(window_id="@0", name=window_names[0], session_id="$1"),
            WindowSnapshot(window_id="@1", name=window_names[1], session_id="$0"),
        ),
        panes=(
            PaneSnapshot(pane_id="%0", window_id="@0", session_id="$1", pid=9_999_991),
            PaneSnapshot(pane_id="%1", window_id="@1", session_id="$0", pid=9_999_992),
        ),
    )

    with pytest.raises(
        benchmark_module.TopologyVerificationError,
        match="window parent differs from the declaration",
    ):
        benchmark_module.verify_topology(context, snapshot)


def test_verify_topology_rejects_pane_session_parent_mismatch(
    benchmark_module: types.ModuleType,
) -> None:
    """A pane must name the same session as the window that owns its ID."""
    session_names = ("bench-parent-s000", "bench-parent-s001")
    window_names = (
        "bench-parent-s000-w000",
        "bench-parent-s001-w000",
    )
    context = types.SimpleNamespace(
        topology=benchmark_module.Topology(2, 1, 1),
        expected_session_names=session_names,
        expected_window_names=window_names,
        expected_window_parents=(
            (window_names[0], session_names[0]),
            (window_names[1], session_names[1]),
        ),
        streams=(pathlib.Path("editor.log"), pathlib.Path("delayed-match.log")),
    )
    snapshot = benchmark_module.TopologySnapshot(
        sessions=(
            SessionSnapshot(session_id="$0", name=session_names[0]),
            SessionSnapshot(session_id="$1", name=session_names[1]),
        ),
        windows=(
            WindowSnapshot(window_id="@0", name=window_names[0], session_id="$0"),
            WindowSnapshot(window_id="@1", name=window_names[1], session_id="$1"),
        ),
        panes=(
            PaneSnapshot(pane_id="%0", window_id="@0", session_id="$1", pid=9_999_991),
            PaneSnapshot(pane_id="%1", window_id="@1", session_id="$0", pid=9_999_992),
        ),
    )

    with pytest.raises(
        benchmark_module.TopologyVerificationError,
        match="pane session differs from its window parent",
    ):
        benchmark_module.verify_topology(context, snapshot)


@pytest.mark.parametrize(
    ("lane_name", "mode_name"),
    (
        ("subprocess", "sync"),
        ("subprocess", "async"),
        ("control", "sync"),
        ("control", "async"),
    ),
)
def test_live_topology_lifecycle_cleans_each_engine_lane(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    lane_name: str,
    mode_name: str,
) -> None:
    """A lane must build, activate, and remove only its isolated live topology."""
    monkeypatch.setenv("TMUX", "ambient-server")
    monkeypatch.setenv("TMUX_PANE", "%ambient")
    topology = benchmark_module.Topology(2, 2, 2)
    lane = benchmark_module.EngineLane(lane_name)
    scratch = tmp_path / f"{lane_name}-{mode_name}"
    socket_path = scratch / "tmux.sock"
    run_id = f"live-{lane_name}-{mode_name}"
    context = None
    snapshot = None
    cleanup = None
    captured_activity: dict[str, str] = {}

    async def exercise_async() -> None:
        """Keep async engines on one event loop through their final close."""
        nonlocal context, snapshot, cleanup
        context = await benchmark_module.setup_async(
            topology,
            lane,
            scratch,
            socket_path=socket_path,
            run_id=run_id,
            delayed_ordinal=5,
        )
        try:
            assert "TMUX" not in os.environ
            assert "TMUX_PANE" not in os.environ
            snapshot = await benchmark_module.snapshot_topology_async(context)
            benchmark_module.verify_topology(context, snapshot)
            epoch = benchmark_module.release_activity_gate(context)
            assert await benchmark_module.verify_activity_async(context) == epoch
            for pane_id in context.pane_ids:
                result = context.server.cmd(
                    "capture-pane", "-t", pane_id, "-p", "-S", "-5000"
                )
                assert result.returncode == 0, result.stderr
                captured_activity[pane_id] = "\n".join(result.stdout)
        finally:
            cleanup = await benchmark_module.cleanup_run(context)

    if mode_name == "async":
        asyncio.run(exercise_async())
    else:
        context = benchmark_module.setup_sync(
            topology,
            lane,
            scratch,
            socket_path=socket_path,
            run_id=run_id,
            delayed_ordinal=5,
        )
        try:
            assert "TMUX" not in os.environ
            assert "TMUX_PANE" not in os.environ
            snapshot = benchmark_module.snapshot_topology_sync(context)
            benchmark_module.verify_topology(context, snapshot)
            epoch = benchmark_module.release_activity_gate(context)
            assert benchmark_module.verify_activity_sync(context) == epoch
            for pane_id in context.pane_ids:
                result = context.server.cmd(
                    "capture-pane", "-t", pane_id, "-p", "-S", "-5000"
                )
                assert result.returncode == 0, result.stderr
                captured_activity[pane_id] = "\n".join(result.stdout)
        finally:
            cleanup = asyncio.run(benchmark_module.cleanup_run(context))

    assert context is not None
    assert snapshot is not None
    assert cleanup is not None
    assert context.server.config_file == os.devnull
    assert context.socket_path == socket_path
    assert context.setup_duration_ns > 0
    assert len(snapshot.sessions) == 2
    assert len(snapshot.windows) == 4
    assert len(snapshot.panes) == 8
    assert len(context.session_ids) == len(set(context.session_ids)) == 2
    assert len(context.window_ids) == len(set(context.window_ids)) == 4
    assert len(context.pane_ids) == len(set(context.pane_ids)) == 8
    assert len({pane.pid for pane in snapshot.panes}) == 8
    assert all(pane.pid is not None and pane.pid > 0 for pane in snapshot.panes)
    assert all(pane.fields["pane_dead"] == "0" for pane in snapshot.panes)
    delayed = [
        pane
        for pane in snapshot.panes
        if "delayed-match.log" in pane.fields["pane_start_command"]
    ]
    assert [pane.pane_id for pane in delayed] == [context.delayed_pane_id]
    assert context.activity_pane_ids == context.pane_ids
    assert context.activity_marker == (
        f"LIBTMUX_EPOCH run={run_id} epoch={context.activity_epoch}"
    )
    assert set(captured_activity) == set(context.pane_ids)
    assert all(
        context.activity_marker in captured_activity[pane_id]
        for pane_id in context.pane_ids
    )
    assert context.heartbeat_epoch >= context.activity_epoch

    recorded_processes = context.processes
    assert (
        len([process for process in recorded_processes if process.role == "pane"]) == 8
    )
    assert cleanup.complete
    assert cleanup.errors == ()
    assert context.fuzzer.poll() is not None
    assert all(
        not benchmark_module.process_identity_matches(process)
        for process in recorded_processes
    )
    assert not socket_path.exists()
    assert not scratch.exists()
    assert os.environ["TMUX"] == "ambient-server"
    assert os.environ["TMUX_PANE"] == "%ambient"


def _checksum_ids(ids: tuple[str, ...]) -> str:
    """Derive the test oracle without calling the benchmark helper."""
    return hashlib.sha256("\0".join(ids).encode()).hexdigest()


def _capture_frame_epochs(lines: tuple[str, ...]) -> tuple[int, ...]:
    """Parse literal fuzzer frame epochs without benchmark implementation help."""
    epochs: list[int] = []
    for line in lines:
        prefix, separator, remainder = line.partition(" epoch=")
        epoch_text, closing, _tail = remainder.partition("]")
        if prefix.startswith("[") and separator and closing and epoch_text.isdigit():
            epochs.append(int(epoch_text))
    return tuple(epochs)


@pytest.mark.parametrize("mode_name", ("sync", "async"))
def test_activity_advance_rejects_stalled_heartbeat_in_both_modes(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    mode_name: str,
) -> None:
    """A fixed live marker must not satisfy post-restoration freshness."""
    heartbeat = tmp_path / "fuzzer" / "heartbeat.json"
    heartbeat.parent.mkdir()
    benchmark_module.write_json_atomic(
        heartbeat,
        {
            "schema_version": 1,
            "run_id": "stalled-run",
            "state": "active",
            "epoch": 41,
            "monotonic_ns": time.monotonic_ns(),
        },
    )
    context = types.SimpleNamespace(
        scratch=tmp_path,
        run_id="stalled-run",
        fuzzer=types.SimpleNamespace(poll=lambda: None),
        heartbeat_epoch=40,
        heartbeat_monotonic_ns=-1,
    )
    baseline = benchmark_module._current_activity_heartbeat(context, max_age_s=1.0)

    if mode_name == "async":
        with pytest.raises(TimeoutError, match="did not advance"):
            asyncio.run(
                benchmark_module._wait_activity_advance_async(
                    context, baseline, timeout_s=0.02
                )
            )
    else:
        with pytest.raises(TimeoutError, match="did not advance"):
            benchmark_module._wait_activity_advance_sync(
                context, baseline, timeout_s=0.02
            )


def test_current_activity_heartbeat_rejects_stale_publication(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
) -> None:
    """An old active marker must not prove that the fuzzer is still moving."""
    heartbeat = tmp_path / "fuzzer" / "heartbeat.json"
    heartbeat.parent.mkdir()
    benchmark_module.write_json_atomic(
        heartbeat,
        {
            "schema_version": 1,
            "run_id": "stale-run",
            "state": "active",
            "epoch": 99,
            "monotonic_ns": time.monotonic_ns() - 1_000_000_000,
        },
    )
    context = types.SimpleNamespace(
        scratch=tmp_path,
        run_id="stale-run",
        fuzzer=types.SimpleNamespace(poll=lambda: None),
        heartbeat_epoch=1,
        heartbeat_monotonic_ns=-1,
    )

    with pytest.raises(RuntimeError, match="stale"):
        benchmark_module._current_activity_heartbeat(context, max_age_s=0.01)


@pytest.mark.parametrize(("lane_name", "mode_name"), _PHASE_LANES)
def test_live_mutation_phase_restores_stable_targets_and_keeps_activity_advancing(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    lane_name: str,
    mode_name: str,
) -> None:
    """A mutation sample must verify live state and restore it outside timing."""
    topology = benchmark_module.Topology(2, 3, 2)
    lane = benchmark_module.EngineLane(lane_name)
    scratch = tmp_path / f"mutation-{lane_name}-{mode_name}"
    context = result = restored = cleanup = None

    async def exercise_async() -> None:
        """Keep an async engine on one loop through mutation and cleanup."""
        nonlocal context, result, restored, cleanup
        context = await benchmark_module.setup_async(
            topology,
            lane,
            scratch,
            run_id=f"mutation-{lane_name}-{mode_name}",
            delayed_ordinal=7,
        )
        try:
            benchmark_module.release_activity_gate(context)
            await benchmark_module.verify_activity_async(context)
            result = await benchmark_module.mutate_async(context, generation=7)
            restored = await benchmark_module.snapshot_topology_async(context)
        finally:
            cleanup = await benchmark_module.cleanup_run(context)

    if mode_name == "async":
        asyncio.run(exercise_async())
    else:
        context = benchmark_module.setup_sync(
            topology,
            lane,
            scratch,
            run_id=f"mutation-{lane_name}-{mode_name}",
            delayed_ordinal=7,
        )
        try:
            benchmark_module.release_activity_gate(context)
            benchmark_module.verify_activity_sync(context)
            result = benchmark_module.mutate_sync(context, generation=7)
            restored = benchmark_module.snapshot_topology_sync(context)
        finally:
            cleanup = asyncio.run(benchmark_module.cleanup_run(context))

    assert context is not None
    assert result is not None
    assert restored is not None
    assert cleanup is not None
    assert result.duration_ns > 0
    assert result.generation == "7"
    assert result.session_id in context.session_ids
    assert len(result.window_ids) == 3
    assert len(result.pane_ids) == 6
    assert result.metrics.operations == 10
    assert result.metrics.planner_steps == 1
    assert result.metrics.engine_batches == 1
    assert result.metrics.tmux_requests == 10
    assert result.metrics.process_starts == (
        10 if lane is benchmark_module.EngineLane.SUBPROCESS else 0
    )
    assert result.verified
    assert result.restored
    assert result.activity_baseline.epoch < result.activity_after.epoch
    assert (
        result.activity_baseline.published_monotonic_ns
        < result.activity_after.published_monotonic_ns
    )
    assert (
        result.restoration_verified_monotonic_ns
        <= result.activity_baseline.observed_monotonic_ns
        < result.activity_after.observed_monotonic_ns
    )
    assert tuple(session.name for session in restored.sessions) == (
        context.expected_session_names
    )
    assert {window.name for window in restored.windows} == set(
        context.expected_window_names
    )
    restored_panes = {
        pane.pane_id: pane.fields.get("pane_title") for pane in restored.panes
    }
    assert all(
        not (restored_panes[pane_id] or "").startswith(f"bench-{context.run_id}-g7-")
        for pane_id in result.pane_ids
    )
    assert cleanup.complete, cleanup.errors


@pytest.mark.parametrize("lane_name", ("subprocess", "control"))
def test_async_mutation_shields_restoration_through_repeated_cancellation(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    lane_name: str,
) -> None:
    """Cancellation must wait for real restoration and retain its first cause.

    The benchmark has no public restoration boundary, so this test wraps only
    ``LazyPlan.aexecute`` to pause its second real plan dispatch. The actual
    async engine, mutation plan, restoration plan, snapshots, and cleanup stay
    live.
    """
    from libtmux.experimental.ops import LazyPlan, SessionId, ShowOptions, arun

    topology = benchmark_module.Topology(2, 3, 2)
    lane = benchmark_module.EngineLane(lane_name)
    scratch = tmp_path / f"cancel-restoration-{lane_name}"
    original_aexecute = LazyPlan.aexecute
    plan_calls = 0
    restoration_started: asyncio.Event
    release_restoration: asyncio.Event

    async def gated_aexecute(
        plan: t.Any,
        engine: t.Any,
        *,
        version: str | None = None,
        planner: t.Any = None,
        on_step: t.Any = None,
    ) -> t.Any:
        nonlocal plan_calls
        plan_calls += 1
        if plan_calls == 2:
            restoration_started.set()
            await release_restoration.wait()
            await original_aexecute(
                plan,
                engine,
                version=version,
                planner=planner,
                on_step=on_step,
            )
            message = "restoration evidence failure"
            raise RuntimeError(message)
        return await original_aexecute(
            plan,
            engine,
            version=version,
            planner=planner,
            on_step=on_step,
        )

    async def exercise() -> None:
        nonlocal plan_calls, restoration_started, release_restoration
        restoration_started = asyncio.Event()
        release_restoration = asyncio.Event()
        context = await benchmark_module.setup_async(
            topology,
            lane,
            scratch,
            run_id=f"cancel-restoration-{lane_name}",
            delayed_ordinal=7,
        )
        cleanup = None
        try:
            benchmark_module.release_activity_gate(context)
            await benchmark_module.verify_activity_async(context)
            plan_calls = 0
            monkeypatch.setattr(LazyPlan, "aexecute", gated_aexecute)
            mutation = asyncio.create_task(
                benchmark_module.mutate_async(context, generation=19),
                name="mutation-under-cancellation",
            )
            await asyncio.wait_for(restoration_started.wait(), timeout=5.0)
            mutation.cancel("original cancellation")
            await asyncio.sleep(0)
            mutation.cancel("repeated cancellation")
            release_restoration.set()
            with pytest.raises(asyncio.CancelledError) as cancelled:
                await mutation
            expected_args = (
                () if sys.version_info[:2] == (3, 10) else ("original cancellation",)
            )
            assert cancelled.value.args == expected_args
            if sys.version_info[:2] == (3, 10):
                assert cancelled.value.__cause__ is None
            else:
                assert isinstance(cancelled.value.__cause__, RuntimeError)
                assert str(cancelled.value.__cause__) == "restoration evidence failure"

            restored = await benchmark_module.snapshot_topology_async(context)
            option_result = (
                await arun(
                    ShowOptions(target=SessionId(context.session_ids[0])),
                    context.engine,
                )
            ).raise_for_status()
            assert "@libtmux_bench_generation" not in option_result.options
            assert {window.name for window in restored.windows} == set(
                context.expected_window_names
            )
            restored_window_ids = {
                window.window_id
                for window in restored.windows
                if window.session_id == context.session_ids[0]
            }
            assert all(
                pane.fields.get("pane_title") in {None, ""}
                for pane in restored.panes
                if pane.window_id in restored_window_ids
            )
            assert not any(
                task.get_name() == "libtmux-mutation-restoration" and not task.done()
                for task in asyncio.all_tasks()
            )
        finally:
            release_restoration.set()
            cleanup = await benchmark_module.cleanup_run(context)
        assert cleanup.complete, cleanup.errors

    asyncio.run(exercise())


@pytest.mark.parametrize(("lane_name", "mode_name"), _PHASE_LANES)
def test_live_enumeration_phase_accepts_exact_rows_and_stable_id_checksums(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    lane_name: str,
    mode_name: str,
) -> None:
    """An accepted enumeration must match the verified concrete ID tuples."""
    topology = benchmark_module.Topology(2, 3, 2)
    lane = benchmark_module.EngineLane(lane_name)
    scratch = tmp_path / f"enumeration-{lane_name}-{mode_name}"
    context = cleanup = None
    observed: dict[str, t.Any] = {}

    async def exercise_async() -> None:
        """Keep async enumeration and cleanup on one event loop."""
        nonlocal context, cleanup
        context = await benchmark_module.setup_async(
            topology,
            lane,
            scratch,
            run_id=f"enumeration-{lane_name}-{mode_name}",
            delayed_ordinal=7,
        )
        try:
            benchmark_module.release_activity_gate(context)
            await benchmark_module.verify_activity_async(context)
            for kind in ("sessions", "windows", "panes"):
                observed[kind] = await benchmark_module.enumerate_async(
                    context, kind=kind
                )
        finally:
            cleanup = await benchmark_module.cleanup_run(context)

    if mode_name == "async":
        asyncio.run(exercise_async())
    else:
        context = benchmark_module.setup_sync(
            topology,
            lane,
            scratch,
            run_id=f"enumeration-{lane_name}-{mode_name}",
            delayed_ordinal=7,
        )
        try:
            benchmark_module.release_activity_gate(context)
            benchmark_module.verify_activity_sync(context)
            for kind in ("sessions", "windows", "panes"):
                observed[kind] = benchmark_module.enumerate_sync(context, kind=kind)
        finally:
            cleanup = asyncio.run(benchmark_module.cleanup_run(context))

    assert context is not None
    expected = {
        "sessions": context.session_ids,
        "windows": context.window_ids,
        "panes": context.pane_ids,
    }
    assert {kind: result.row_count for kind, result in observed.items()} == {
        "sessions": 2,
        "windows": 6,
        "panes": 12,
    }
    for kind, ids in expected.items():
        result = observed[kind]
        assert result.ids == ids
        assert result.id_checksum == _checksum_ids(ids)
        assert result.duration_ns > 0
        assert result.metrics.operations == 1
        assert result.metrics.tmux_requests == 1
        assert result.verified
    assert cleanup is not None
    assert cleanup.complete, cleanup.errors


@pytest.mark.parametrize(("lane_name", "mode_name"), _PHASE_LANES)
def test_live_capture_phase_uses_identical_graphs_with_distinct_planners(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    lane_name: str,
    mode_name: str,
) -> None:
    """Serial and batched capture must return every current active pane."""
    topology = benchmark_module.Topology(2, 3, 2)
    lane = benchmark_module.EngineLane(lane_name)
    scratch = tmp_path / f"capture-{lane_name}-{mode_name}"
    context = serial = batched = cleanup = None

    async def exercise_async() -> None:
        """Keep both async planner executions on the engine's owning loop."""
        nonlocal context, serial, batched, cleanup
        context = await benchmark_module.setup_async(
            topology,
            lane,
            scratch,
            run_id=f"capture-{lane_name}-{mode_name}",
            delayed_ordinal=7,
        )
        try:
            benchmark_module.release_activity_gate(context)
            await benchmark_module.verify_activity_async(context)
            heartbeat = json.loads(
                (scratch / "fuzzer" / "heartbeat.json").read_text(encoding="utf-8")
            )
            serial = await benchmark_module.capture_all_async(
                context, strategy="serial"
            )
            assert serial.epoch >= heartbeat["epoch"]
            heartbeat = json.loads(
                (scratch / "fuzzer" / "heartbeat.json").read_text(encoding="utf-8")
            )
            batched = await benchmark_module.capture_all_async(
                context, strategy="batched"
            )
            assert batched.epoch >= heartbeat["epoch"]
        finally:
            cleanup = await benchmark_module.cleanup_run(context)

    if mode_name == "async":
        asyncio.run(exercise_async())
    else:
        context = benchmark_module.setup_sync(
            topology,
            lane,
            scratch,
            run_id=f"capture-{lane_name}-{mode_name}",
            delayed_ordinal=7,
        )
        try:
            benchmark_module.release_activity_gate(context)
            benchmark_module.verify_activity_sync(context)
            heartbeat = json.loads(
                (scratch / "fuzzer" / "heartbeat.json").read_text(encoding="utf-8")
            )
            serial = benchmark_module.capture_all_sync(context, strategy="serial")
            assert serial.epoch >= heartbeat["epoch"]
            heartbeat = json.loads(
                (scratch / "fuzzer" / "heartbeat.json").read_text(encoding="utf-8")
            )
            batched = benchmark_module.capture_all_sync(context, strategy="batched")
            assert batched.epoch >= heartbeat["epoch"]
        finally:
            cleanup = asyncio.run(benchmark_module.cleanup_run(context))

    assert context is not None
    assert serial is not None
    assert batched is not None
    for result in (serial, batched):
        assert tuple(capture.pane_id for capture in result.captures) == (
            context.pane_ids
        )
        assert result.duration_ns > 0
        assert result.line_count >= 12
        assert result.byte_count > 0
        assert result.epoch >= context.activity_epoch
        assert all(
            max(_capture_frame_epochs(capture.lines), default=-1) >= result.epoch
            for capture in result.captures
        )
        assert result.metrics.operations == 12
        assert result.metrics.tmux_requests == 12
        assert result.metrics.process_starts == (
            12 if lane is benchmark_module.EngineLane.SUBPROCESS else 0
        )
        assert result.verified
    assert serial.metrics.planner_steps == 12
    assert serial.metrics.engine_batches == 12
    assert batched.metrics.planner_steps == 1
    assert batched.metrics.engine_batches == 1
    assert serial.operations == batched.operations
    assert cleanup is not None
    assert cleanup.complete, cleanup.errors


@pytest.mark.parametrize(
    "result_targets",
    (("%2", "%1"), ("%1", "%1"), ("%1", "%9")),
    ids=("reordered", "duplicate", "wrong"),
)
def test_capture_rejects_unattributed_typed_results(
    benchmark_module: types.ModuleType,
    result_targets: tuple[str, str],
) -> None:
    """Typed lines from reordered, duplicate, or wrong targets are invalid."""
    from libtmux.experimental.ops import CapturePane, PaneId

    context = types.SimpleNamespace(
        pane_ids=("%1", "%2"),
        activity_marker="LIBTMUX_EPOCH run=capture-run epoch=1",
        activity_epoch=1,
        heartbeat_epoch=8,
        lane=benchmark_module.EngineLane.CONTROL,
    )
    plan = benchmark_module._capture_plan(context)
    results = tuple(
        CapturePane(target=PaneId(pane_id)).build_result(
            returncode=0,
            stdout=(
                context.activity_marker,
                "[editor epoch=8] current",
            ),
        )
        for pane_id in result_targets
    )

    with pytest.raises(RuntimeError, match="target"):
        benchmark_module._accepted_capture(
            context,
            plan,
            types.SimpleNamespace(results=results),
            "batched",
            5,
        )


def _wait_result_invariants(
    benchmark_module: types.ModuleType,
    context: t.Any,
    result: t.Any,
    *,
    request_id: str,
    value: str,
    strategy: str,
) -> None:
    """Assert independently recomputable wait timing and identity evidence."""
    assert isinstance(result, benchmark_module.WaitResult)
    assert result.strategy == strategy
    assert result.request_id == request_id
    assert result.token == (
        f"LIBTMUX_SENTINEL run={context.run_id} request={request_id} value={value}"
    )
    assert result.pane_id == context.delayed_pane_id
    assert result.configured_delay_ns == 50_000_000
    assert result.scheduled_monotonic_ns == (
        result.requested_monotonic_ns + result.configured_delay_ns
    )
    assert result.emitted_monotonic_ns >= result.scheduled_monotonic_ns
    assert result.scheduling_lateness_ns == (
        result.emitted_monotonic_ns - result.scheduled_monotonic_ns
    )
    assert result.scheduling_lateness_ns >= 0
    assert result.detected_monotonic_ns >= result.emitted_monotonic_ns
    assert result.detection_overhead_ns == (
        result.detected_monotonic_ns - result.emitted_monotonic_ns
    )
    assert result.detection_overhead_ns >= 0
    assert result.duration_ns == result.detection_overhead_ns
    assert result.timeout_s == 2.0
    assert result.timed_out is False
    assert result.dropped_notification_delta == 0
    assert result.verified
    if strategy == "capture-poll":
        assert result.poll_count > 0
        assert result.frame_count == 0
    else:
        assert result.poll_count == 0
        assert result.frame_count > 0


def _ordinary_delayed_frame_follows_wait(context: t.Any, result: t.Any) -> bool:
    """Wait until the delayed pane shows ordinary scrolling after a sentinel."""
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        captured = context.server.cmd(
            "capture-pane",
            "-t",
            result.pane_id,
            "-p",
            "-J",
            "-S",
            "-5000",
        )
        if captured.returncode != 0:
            return False
        lines = captured.stdout
        try:
            sentinel_index = lines.index(result.token)
        except ValueError:
            time.sleep(0.005)
            continue
        if any(
            line.startswith("[delayed-match epoch=")
            for line in lines[sentinel_index + 1 :]
        ):
            return True
        time.sleep(0.005)
    return False


def _assert_wait_tokens_only_reach_delayed_pane(
    context: t.Any,
    results: list[t.Any],
) -> None:
    """Require every exact request token only in the selected delayed pane."""
    for pane_id in context.pane_ids:
        captured = context.server.cmd(
            "capture-pane",
            "-t",
            pane_id,
            "-p",
            "-J",
            "-S",
            "-5000",
        )
        assert captured.returncode == 0, captured.stderr
        matched = tuple(
            result.request_id for result in results if result.token in captured.stdout
        )
        if pane_id == context.delayed_pane_id:
            assert matched == tuple(result.request_id for result in results)
        else:
            assert matched == ()


def _isolated_wait_context(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    *,
    mode: t.Any,
    lane: t.Any,
    engine: t.Any,
    run_id: str = "wait-run",
) -> t.Any:
    """Build the marker boundary needed by deterministic waiter regressions."""
    fuzzer_root = tmp_path / "fuzzer"
    (fuzzer_root / "requests").mkdir(parents=True)
    (fuzzer_root / "sentinels").mkdir()
    return types.SimpleNamespace(
        mode=mode,
        lane=lane,
        engine=engine,
        delayed_pane_id="%7",
        run_id=run_id,
        scratch=tmp_path,
        sentinel_delay_ns=0,
        fuzzer=types.SimpleNamespace(poll=lambda: None),
    )


def _blocking_tmux_binary(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Create a real blocking process so timeout cleanup stays observable."""
    executable = tmp_path / "blocking-tmux"
    pid_path = tmp_path / "blocking-tmux.pid"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "import pathlib\n"
        "import time\n"
        "pathlib.Path(os.environ['BLOCKING_TMUX_PID']).write_text(\n"
        "    str(os.getpid()), encoding='ascii'\n"
        ")\n"
        "time.sleep(0.5)\n",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable, pid_path


@pytest.mark.parametrize(
    ("field", "unsafe"),
    (
        ("run_id", "unsafe run"),
        ("run_id", "unsafe\tcontrol"),
        ("run_id", "unsafe\nline"),
        ("run_id", "unsafe\x1bescape"),
        ("run_id", "unsafe\x08backspace"),
        ("run_id", "nonascii-π"),
        ("run_id", "r" * 129),
        ("request_id", "unsafe request"),
        ("request_id", "unsafe\tcontrol"),
        ("request_id", "unsafe\nline"),
        ("request_id", "unsafe\x1bescape"),
        ("request_id", "unsafe\x08backspace"),
        ("request_id", "nonascii-π"),
        ("request_id", "q" * 129),
        ("value", "unsafe value"),
        ("value", "unsafe\tcontrol"),
        ("value", "unsafe\nline"),
        ("value", "unsafe\x1bescape"),
        ("value", "unsafe\x08backspace"),
        ("value", "nonascii-π"),
        ("value", "v" * 129),
    ),
)
def test_request_sentinel_rejects_unsafe_components_before_publication(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    field: str,
    unsafe: str,
) -> None:
    """Terminal controls and oversized identities never reach marker storage."""
    context = _isolated_wait_context(
        benchmark_module,
        tmp_path,
        mode=benchmark_module.ExecutionMode.SYNC,
        lane=benchmark_module.EngineLane.SUBPROCESS,
        engine=object(),
    )
    arguments = {
        "request_id": "request.safe:1",
        "value": "VALUE.safe:1",
    }
    if field == "run_id":
        context.run_id = unsafe
    else:
        arguments[field] = unsafe

    with pytest.raises(ValueError, match="terminal-safe"):
        benchmark_module.request_sentinel(context, **arguments)

    assert tuple((tmp_path / "fuzzer" / "requests").iterdir()) == ()


def test_request_sentinel_accepts_literal_maximum_terminal_safe_token(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
) -> None:
    """All documented boundary bytes remain valid and exactly reproducible."""
    context = _isolated_wait_context(
        benchmark_module,
        tmp_path,
        mode=benchmark_module.ExecutionMode.SYNC,
        lane=benchmark_module.EngineLane.SUBPROCESS,
        engine=object(),
        run_id="r" * 128,
    )

    request = benchmark_module.request_sentinel(
        context,
        request_id="q" * 128,
        value="v" * 128,
    )

    assert len(f"{request.token}\n".encode()) == 422
    assert benchmark_module._SENTINEL_RECORD_MAX_BYTES == 422
    marker = json.loads(
        next((tmp_path / "fuzzer" / "requests").iterdir()).read_text(encoding="utf-8")
    )
    assert marker["run_id"] == "r" * 128
    assert marker["request_id"] == "q" * 128
    assert marker["value"] == "v" * 128


@pytest.mark.parametrize("timeout_s", (3.000_001, float("inf"), float("nan")))
def test_capture_wait_rejects_unbounded_timeout_before_publication(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    timeout_s: float,
) -> None:
    """The history-sized wait ceiling applies before a request is visible."""
    context = _isolated_wait_context(
        benchmark_module,
        tmp_path,
        mode=benchmark_module.ExecutionMode.SYNC,
        lane=benchmark_module.EngineLane.SUBPROCESS,
        engine=object(),
    )

    with pytest.raises(ValueError, match=r"at most 3\.0 seconds"):
        benchmark_module.wait_capture_poll_sync(
            context,
            request_id="bounded-timeout",
            timeout_s=timeout_s,
        )

    assert tuple((tmp_path / "fuzzer" / "requests").iterdir()) == ()


def test_start_fuzzer_rejects_frame_rate_above_wait_history_bound(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The producer cannot outrun the documented capture history budget."""
    monkeypatch.setattr(
        benchmark_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("fuzzer started above frame bound"),
    )

    with pytest.raises(ValueError, match=r"at most 40\.0 frames per second"):
        benchmark_module.start_fuzzer(
            tmp_path,
            "bounded-rate",
            frame_rate_hz=40.000_001,
        )


def test_sync_subprocess_capture_timeout_kills_and_reaps_exact_child(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blocked real subprocess cannot outlive the capture wait deadline."""
    from libtmux.experimental.engines import SubprocessEngine

    executable, pid_path = _blocking_tmux_binary(tmp_path)
    monkeypatch.setenv("BLOCKING_TMUX_PID", str(pid_path))
    monkeypatch.setattr(
        benchmark_module.os,
        "killpg",
        lambda *_args: pytest.fail("capture timeout used an unstable process group"),
    )
    engine = SubprocessEngine(tmux_bin=executable)
    context = _isolated_wait_context(
        benchmark_module,
        tmp_path,
        mode=benchmark_module.ExecutionMode.SYNC,
        lane=benchmark_module.EngineLane.SUBPROCESS,
        engine=engine,
    )
    threads_before = frozenset(thread.ident for thread in threading.enumerate())
    started = time.monotonic()

    with pytest.raises(
        TimeoutError,
        match="capture wait timed out for request sync-blocked",
    ):
        benchmark_module.wait_capture_poll_sync(
            context,
            request_id="sync-blocked",
            timeout_s=0.05,
            poll_interval_s=0.01,
        )

    elapsed = time.monotonic() - started
    pid = int(pid_path.read_text(encoding="ascii"))
    assert elapsed < 0.25
    assert benchmark_module._process_start_time(pid) is None
    assert frozenset(thread.ident for thread in threading.enumerate()) == threads_before


def test_sync_control_capture_uses_and_restores_remaining_transport_timeout(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
) -> None:
    """The supported control engine owns a blocked request until timeout."""
    from libtmux.experimental.engines.control_mode import (
        ControlModeEngine,
        ControlModeError,
    )

    class BlockingControlEngine(ControlModeEngine):
        def __init__(self) -> None:
            super().__init__(timeout=0.5)
            self.observed_timeout: float | None = None

        def tmux_version(self) -> None:
            return None

        def run(self, request: t.Any) -> t.NoReturn:
            del request
            self.observed_timeout = self.timeout
            threading.Event().wait(self.timeout)
            message = f"blocked for {self.timeout}s"
            raise ControlModeError(message)

    engine = BlockingControlEngine()
    context = _isolated_wait_context(
        benchmark_module,
        tmp_path,
        mode=benchmark_module.ExecutionMode.SYNC,
        lane=benchmark_module.EngineLane.CONTROL,
        engine=engine,
    )
    threads_before = frozenset(thread.ident for thread in threading.enumerate())
    started = time.monotonic()

    with pytest.raises(
        TimeoutError,
        match="capture wait timed out for request control-blocked",
    ):
        benchmark_module.wait_capture_poll_sync(
            context,
            request_id="control-blocked",
            timeout_s=0.05,
            poll_interval_s=0.01,
        )

    elapsed = time.monotonic() - started
    assert elapsed < 0.25
    assert engine.observed_timeout is not None
    assert 0 < engine.observed_timeout <= 0.05
    assert engine.timeout == 0.5
    assert frozenset(thread.ident for thread in threading.enumerate()) == threads_before


def test_async_subprocess_capture_timeout_drains_task_and_reaps_child(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelling a blocked native async capture leaves no task or child."""
    from libtmux.experimental.engines import AsyncSubprocessEngine

    executable, pid_path = _blocking_tmux_binary(tmp_path)
    monkeypatch.setenv("BLOCKING_TMUX_PID", str(pid_path))
    engine = AsyncSubprocessEngine(tmux_bin=executable)
    context = _isolated_wait_context(
        benchmark_module,
        tmp_path,
        mode=benchmark_module.ExecutionMode.ASYNC,
        lane=benchmark_module.EngineLane.SUBPROCESS,
        engine=engine,
    )

    async def exercise() -> tuple[float, tuple[str, ...]]:
        started = time.monotonic()
        with pytest.raises(
            TimeoutError,
            match="capture wait timed out for request async-blocked",
        ):
            await asyncio.wait_for(
                benchmark_module.wait_capture_poll_async(
                    context,
                    request_id="async-blocked",
                    timeout_s=0.05,
                    poll_interval_s=0.01,
                ),
                timeout=0.3,
            )
        await asyncio.sleep(0)
        names = tuple(
            task.get_name()
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
            and (
                task.get_name().startswith("bench-capture-wait-")
                or task.get_name().startswith("libtmux-async-subprocess-")
            )
        )
        return time.monotonic() - started, names

    elapsed, task_names = asyncio.run(exercise(), debug=True)
    pid = int(pid_path.read_text(encoding="ascii"))
    assert elapsed < 0.25
    assert task_names == ()
    assert benchmark_module._process_start_time(pid) is None


def test_control_wait_timeout_drains_pending_subscription(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
) -> None:
    """A pending real subscriber unregisters without loop diagnostics."""
    from libtmux.experimental.engines.async_control_mode import (
        AsyncControlModeEngine,
    )

    engine = AsyncControlModeEngine()
    context = _isolated_wait_context(
        benchmark_module,
        tmp_path,
        mode=benchmark_module.ExecutionMode.ASYNC,
        lane=benchmark_module.EngineLane.CONTROL,
        engine=engine,
    )

    async def exercise() -> tuple[list[dict[str, t.Any]], tuple[str, ...]]:
        diagnostics: list[dict[str, t.Any]] = []
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda _loop, details: diagnostics.append(details))
        with pytest.raises(
            TimeoutError,
            match="control stream wait timed out for request pending-timeout",
        ):
            await benchmark_module.wait_control_stream(
                context,
                request_id="pending-timeout",
                timeout_s=0.03,
            )
        await asyncio.sleep(0)
        assert engine._subscribers == set()
        names = tuple(
            task.get_name()
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
            and task.get_name().startswith("bench-control-wait-")
        )
        return diagnostics, names

    diagnostics, task_names = asyncio.run(exercise(), debug=True)
    assert diagnostics == []
    assert task_names == ()


def test_control_wait_external_cancellation_preserves_payload_and_unregisters(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
) -> None:
    """Caller cancellation drains pending iteration and remains unchanged."""
    from libtmux.experimental.engines.async_control_mode import (
        AsyncControlModeEngine,
    )

    engine = AsyncControlModeEngine()
    context = _isolated_wait_context(
        benchmark_module,
        tmp_path,
        mode=benchmark_module.ExecutionMode.ASYNC,
        lane=benchmark_module.EngineLane.CONTROL,
        engine=engine,
    )

    async def exercise() -> tuple[list[dict[str, t.Any]], tuple[str, ...]]:
        diagnostics: list[dict[str, t.Any]] = []
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda _loop, details: diagnostics.append(details))
        waiter = asyncio.create_task(
            benchmark_module.wait_control_stream(
                context,
                request_id="pending-cancel",
                timeout_s=1.0,
            ),
            name="test-pending-control-wait",
        )
        deadline = loop.time() + 0.5
        while not engine._subscribers and loop.time() < deadline:
            await asyncio.sleep(0)
        assert engine._subscribers
        waiter.cancel("caller-stop")
        with pytest.raises(asyncio.CancelledError) as captured:
            await waiter
        await asyncio.sleep(0)
        expected_args = () if sys.version_info[:2] == (3, 10) else ("caller-stop",)
        assert captured.value.args == expected_args
        assert engine._subscribers == set()
        names = tuple(
            task.get_name()
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
            and task.get_name().startswith("bench-control-wait-")
        )
        return diagnostics, names

    diagnostics, task_names = asyncio.run(exercise(), debug=True)
    assert diagnostics == []
    assert task_names == ()


def test_control_wait_matches_split_target_bytes_and_closes_subscription(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real engine object isolates deterministic chunk and close semantics."""
    from libtmux.experimental.engines.async_control_mode import (
        AsyncControlModeEngine,
        ControlNotification,
    )

    fuzzer_root = tmp_path / "fuzzer"
    (fuzzer_root / "requests").mkdir(parents=True)
    (fuzzer_root / "sentinels").mkdir()
    engine = AsyncControlModeEngine()
    events: list[str] = []
    context = types.SimpleNamespace(
        mode=benchmark_module.ExecutionMode.ASYNC,
        lane=benchmark_module.EngineLane.CONTROL,
        engine=engine,
        delayed_pane_id="%7",
        run_id="split-run",
        scratch=tmp_path,
        sentinel_delay_ns=0,
        fuzzer=types.SimpleNamespace(poll=lambda: None),
    )

    async def notifications() -> t.AsyncIterator[ControlNotification]:
        request_path = fuzzer_root / "requests" / "split-request.json"
        events.append("subscribed")
        assert not request_path.exists()
        try:
            while not request_path.exists():
                await asyncio.sleep(0)
            events.append("requested")
            marker = json.loads(request_path.read_text(encoding="utf-8"))
            token = "LIBTMUX_SENTINEL run=split-run request=split-request value=RIGHT"
            requested_ns = marker["requested_monotonic_ns"]
            emitted_ns = time.monotonic_ns()
            benchmark_module.write_json_atomic(
                fuzzer_root / "sentinels" / "split-request.json",
                {
                    "schema_version": 1,
                    "run_id": "split-run",
                    "request_id": "split-request",
                    "requested_monotonic_ns": requested_ns,
                    "configured_delay_ns": 0,
                    "scheduled_monotonic_ns": requested_ns,
                    "emitted_monotonic_ns": emitted_ns,
                    "scheduling_lateness_ns": emitted_ns - requested_ns,
                    "sentinel": token,
                    "sentinel_sha256": hashlib.sha256(
                        f"{token}\n".encode()
                    ).hexdigest(),
                },
            )
            yield ControlNotification(
                "output", (), "", pane_id="%8", payload=token.encode()
            )
            yield ControlNotification(
                "output",
                (),
                "",
                pane_id="%7",
                payload=b"LIBTMUX_SENTINEL run=split-run request=stale value=WRONG",
            )
            split = len(token) // 2
            yield ControlNotification(
                "extended-output",
                (),
                "",
                pane_id="%7",
                payload=token.encode()[:split],
            )
            yield ControlNotification(
                "output",
                (),
                "",
                pane_id="%7",
                payload=token.encode()[split:],
            )
        finally:
            events.append("closed")

    monkeypatch.setattr(engine, "subscribe", notifications)

    result = asyncio.run(
        benchmark_module.wait_control_stream(
            context,
            request_id="split-request",
            value="RIGHT",
            timeout_s=1.0,
        )
    )

    assert result.request_id == "split-request"
    assert result.frame_count == 3
    assert result.dropped_notification_delta == 0
    assert events == ["subscribed", "requested", "closed"]


def test_control_wait_rejects_drop_delta_and_still_closes_subscription(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deterministic overflow double proves drops invalidate and close a wait."""
    from libtmux.experimental.engines.async_control_mode import (
        AsyncControlModeEngine,
        ControlNotification,
    )

    fuzzer_root = tmp_path / "fuzzer"
    (fuzzer_root / "requests").mkdir(parents=True)
    (fuzzer_root / "sentinels").mkdir()
    engine = AsyncControlModeEngine()
    closed = False
    context = types.SimpleNamespace(
        mode=benchmark_module.ExecutionMode.ASYNC,
        lane=benchmark_module.EngineLane.CONTROL,
        engine=engine,
        delayed_pane_id="%7",
        run_id="drop-run",
        scratch=tmp_path,
        sentinel_delay_ns=0,
        fuzzer=types.SimpleNamespace(poll=lambda: None),
    )

    async def notifications() -> t.AsyncIterator[ControlNotification]:
        nonlocal closed
        request_path = fuzzer_root / "requests" / "drop-request.json"
        try:
            while not request_path.exists():
                await asyncio.sleep(0)
            marker = json.loads(request_path.read_text(encoding="utf-8"))
            token = "LIBTMUX_SENTINEL run=drop-run request=drop-request value=RIGHT"
            requested_ns = marker["requested_monotonic_ns"]
            emitted_ns = time.monotonic_ns()
            benchmark_module.write_json_atomic(
                fuzzer_root / "sentinels" / "drop-request.json",
                {
                    "schema_version": 1,
                    "run_id": "drop-run",
                    "request_id": "drop-request",
                    "requested_monotonic_ns": requested_ns,
                    "configured_delay_ns": 0,
                    "scheduled_monotonic_ns": requested_ns,
                    "emitted_monotonic_ns": emitted_ns,
                    "scheduling_lateness_ns": emitted_ns - requested_ns,
                    "sentinel": token,
                    "sentinel_sha256": hashlib.sha256(
                        f"{token}\n".encode()
                    ).hexdigest(),
                },
            )
            engine._dropped_notifications += 1
            yield ControlNotification(
                "output", (), "", pane_id="%7", payload=token.encode()
            )
        finally:
            closed = True

    monkeypatch.setattr(engine, "subscribe", notifications)

    with pytest.raises(RuntimeError, match="dropped 1 notification"):
        asyncio.run(
            benchmark_module.wait_control_stream(
                context,
                request_id="drop-request",
                value="RIGHT",
                timeout_s=1.0,
            )
        )

    assert closed


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    (
        ("run_id", "stale-run"),
        ("request_id", "stale-request"),
        ("requested_monotonic_ns", 8),
        ("sentinel", "LIBTMUX_SENTINEL run=run-7 request=old value=WRONG"),
        ("sentinel_sha256", "0" * 64),
    ),
)
def test_wait_evidence_rejects_wrong_or_stale_request_identity(
    benchmark_module: types.ModuleType,
    field: str,
    wrong_value: object,
) -> None:
    """Evidence from another request or token cannot validate a detection."""
    token = "LIBTMUX_SENTINEL run=run-7 request=request-1 value=RIGHT"
    request = benchmark_module.SentinelRequest(
        request_id="request-1",
        token=token,
        requested_monotonic_ns=7,
        configured_delay_ns=5,
    )
    marker = {
        "schema_version": 1,
        "run_id": "run-7",
        "request_id": "request-1",
        "requested_monotonic_ns": 7,
        "configured_delay_ns": 5,
        "scheduled_monotonic_ns": 12,
        "emitted_monotonic_ns": 14,
        "scheduling_lateness_ns": 2,
        "sentinel": token,
        "sentinel_sha256": hashlib.sha256(f"{token}\n".encode()).hexdigest(),
    }
    marker[field] = wrong_value

    with pytest.raises(RuntimeError, match="does not match request"):
        benchmark_module._validated_sentinel_evidence(
            types.SimpleNamespace(run_id="run-7"), request, marker
        )


def test_maximum_wait_token_round_trips_through_one_real_wrapped_pane(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
) -> None:
    """The longest supported token survives tmux wrapping byte-for-byte."""
    context = benchmark_module.setup_sync(
        benchmark_module.Topology(1, 2, 2),
        benchmark_module.EngineLane.SUBPROCESS,
        tmp_path / "maximum-wait-token",
        run_id="r" * 128,
        delayed_ordinal=2,
    )
    cleanup = None
    try:
        benchmark_module.release_activity_gate(context)
        result = benchmark_module.wait_capture_poll_sync(
            context,
            request_id="q" * 128,
            value="v" * 128,
            timeout_s=2.0,
            poll_interval_s=0.005,
        )
        captured = context.server.cmd(
            "capture-pane",
            "-t",
            context.delayed_pane_id,
            "-p",
            "-J",
            "-S",
            str(-benchmark_module._WAIT_CAPTURE_HISTORY_LINES),
        )
        assert captured.returncode == 0, captured.stderr
        assert result.token in captured.stdout
        assert len(f"{result.token}\n".encode()) == 422
    finally:
        cleanup = asyncio.run(benchmark_module.cleanup_run(context))
    assert cleanup.complete, cleanup.errors


def test_repeated_wait_capture_poll_sync_uses_one_active_topology(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
) -> None:
    """Five sync polls must match fresh requests without restarting resources."""
    context = benchmark_module.setup_sync(
        benchmark_module.Topology(1, 2, 2),
        benchmark_module.EngineLane.SUBPROCESS,
        tmp_path / "repeated-wait-sync",
        run_id="wait-sync",
        delayed_ordinal=2,
    )
    cleanup = None
    observed: list[t.Any] = []
    identities_before = context.processes
    request_ids = iter(f"sync-{ordinal}" for ordinal in range(5))

    def measured() -> t.Any:
        request_id = next(request_ids)
        value = f"TOKEN-{request_id}"
        result = benchmark_module.wait_capture_poll_sync(
            context,
            request_id=request_id,
            value=value,
            timeout_s=2.0,
            poll_interval_s=0.005,
        )
        _wait_result_invariants(
            benchmark_module,
            context,
            result,
            request_id=request_id,
            value=value,
            strategy="capture-poll",
        )
        observed.append(result)
        return result

    try:
        benchmark_module.release_activity_gate(context)
        benchmark_module.verify_activity_sync(context)
        repeated = asyncio.run(
            benchmark_module.run_repeatable_phase(
                {"capture-poll": measured},
                warmup=2,
                runs=3,
                seed=11,
                live_postcondition=lambda result: _ordinary_delayed_frame_follows_wait(
                    context, result
                ),
                snapshot_resources=lambda: benchmark_module.HostSnapshot(),
            )
        )
        _assert_wait_tokens_only_reach_delayed_pane(context, observed)
        assert repeated.failure is None
        assert len(repeated.samples) == 3
        assert len(observed) == 5
        assert len({result.request_id for result in observed}) == 5
        assert len({result.token for result in observed}) == 5
        assert context.fuzzer.pid == identities_before[0].pid
        assert context.processes == identities_before
        assert len(tuple((context.scratch / "fuzzer" / "requests").glob("*.json"))) == 5
    finally:
        cleanup = asyncio.run(benchmark_module.cleanup_run(context))
    assert cleanup.complete, cleanup.errors


@pytest.mark.parametrize(
    ("lane_name", "strategy"),
    (("subprocess", "capture-poll"), ("control", "control-stream")),
)
def test_repeated_wait_async_strategies_use_one_active_topology(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    lane_name: str,
    strategy: str,
) -> None:
    """Async polling and streaming each keep one active topology for five waits."""
    context = cleanup = repeated = None
    observed: list[t.Any] = []

    async def exercise() -> None:
        """Keep the async engine, waits, and cleanup on one event loop."""
        nonlocal context, cleanup, repeated
        context = await benchmark_module.setup_async(
            benchmark_module.Topology(1, 2, 2),
            benchmark_module.EngineLane(lane_name),
            tmp_path / f"repeated-wait-{lane_name}",
            run_id=f"wait-{lane_name}",
            delayed_ordinal=2,
        )
        identities_before = context.processes
        request_ids = iter(f"{strategy}-{ordinal}" for ordinal in range(5))

        async def measured() -> t.Any:
            request_id = next(request_ids)
            value = f"TOKEN-{request_id}"
            if strategy == "capture-poll":
                result = await benchmark_module.wait_capture_poll_async(
                    context,
                    request_id=request_id,
                    value=value,
                    timeout_s=2.0,
                    poll_interval_s=0.005,
                )
            else:
                result = await benchmark_module.wait_control_stream(
                    context,
                    request_id=request_id,
                    value=value,
                    timeout_s=2.0,
                )
            _wait_result_invariants(
                benchmark_module,
                context,
                result,
                request_id=request_id,
                value=value,
                strategy=strategy,
            )
            observed.append(result)
            return result

        try:
            benchmark_module.release_activity_gate(context)
            await benchmark_module.verify_activity_async(context)
            repeated = await benchmark_module.run_repeatable_phase(
                {strategy: measured},
                warmup=2,
                runs=3,
                seed=11,
                live_postcondition=lambda result: _ordinary_delayed_frame_follows_wait(
                    context, result
                ),
                snapshot_resources=lambda: benchmark_module.HostSnapshot(),
            )
            _assert_wait_tokens_only_reach_delayed_pane(context, observed)
            assert context.fuzzer.pid == identities_before[0].pid
            assert context.processes == identities_before
            assert (
                len(tuple((context.scratch / "fuzzer" / "requests").glob("*.json")))
                == 5
            )
        finally:
            cleanup = await benchmark_module.cleanup_run(context)

    asyncio.run(exercise())

    assert repeated is not None
    assert repeated.failure is None
    assert len(repeated.samples) == 3
    assert len(observed) == 5
    assert len({result.request_id for result in observed}) == 5
    assert len({result.token for result in observed}) == 5
    assert cleanup is not None
    assert cleanup.complete, cleanup.errors


def _request_content_sentinel(
    benchmark_module: types.ModuleType,
    context: t.Any,
    request_id: str,
) -> str:
    """Request one Task 1 sentinel and wait outside content-search timing."""
    requested_ns = time.monotonic_ns()
    benchmark_module.write_json_atomic(
        context.scratch / "fuzzer" / "requests" / f"{request_id}.json",
        {
            "schema_version": 1,
            "run_id": context.run_id,
            "request_id": request_id,
            "requested_monotonic_ns": requested_ns,
            "value": "CONTENT-ONLY",
        },
    )
    evidence_path = context.scratch / "fuzzer" / "sentinels" / f"{request_id}.json"
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(0.01)
            continue
        assert evidence["run_id"] == context.run_id
        assert evidence["request_id"] == request_id
        assert evidence["requested_monotonic_ns"] == requested_ns
        return t.cast(str, evidence["sentinel"])
    message = "Task 1 sentinel evidence did not arrive"
    raise AssertionError(message)


@pytest.mark.parametrize(("lane_name", "mode_name"), _PHASE_LANES)
@pytest.mark.parametrize(
    ("target_position", "delayed_ordinal"),
    (("first", 0), ("middle", 6), ("last", 11)),
)
def test_live_search_phase_keeps_server_snapshot_end_to_end_and_content_distinct(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    lane_name: str,
    mode_name: str,
    target_position: str,
    delayed_ordinal: int,
) -> None:
    """Every applicable family must find explicit targets in every live lane."""
    topology = benchmark_module.Topology(2, 3, 2)
    lane = benchmark_module.EngineLane(lane_name)
    run_id = f"s-{lane_name[0]}-{mode_name[0]}-{target_position[0]}"
    scratch = tmp_path / f"search-{lane_name}-{mode_name}-{target_position}"
    context: t.Any = None
    cleanup: t.Any = None
    observed: dict[tuple[str, str, str], tuple[int, tuple[str, ...]]] = {}

    def exercise_metadata(snapshot: t.Any) -> None:
        """Run classic, pre-materialized, and end-to-end metadata families."""
        ids_by_kind = {
            "sessions": context.session_ids,
            "windows": context.window_ids,
            "panes": context.pane_ids,
        }
        rows_by_kind = {
            "sessions": QueryList(snapshot.sessions),
            "windows": QueryList(snapshot.windows),
            "panes": QueryList(snapshot.panes),
        }
        indexes = {"first": 0, "middle": None, "last": -1}
        for kind, ids in ids_by_kind.items():
            for position, configured_index in indexes.items():
                index = len(ids) // 2 if configured_index is None else configured_index
                target = ids[index]
                classic = benchmark_module.search_server_side(
                    context, kind=kind, target=target
                )
                snapshot_only = benchmark_module.search_snapshot(
                    rows_by_kind[kind], kind=kind, target=target
                )
                end_to_end = benchmark_module.search_end_to_end(
                    context, kind=kind, target=target
                )
                assert classic.family == "classic"
                assert snapshot_only.family == "snapshot"
                assert end_to_end.family == "end-to-end"
                for family, result in (
                    ("classic", classic),
                    ("snapshot", snapshot_only),
                    ("end-to-end", end_to_end),
                ):
                    assert result.target == target
                    assert result.matched_ids == (target,)
                    assert result.verified
                    observed[family, kind, position] = (
                        result.scanned_count,
                        result.matched_ids,
                    )

    def assert_explicit_expectations() -> None:
        """Compare named family/target cells with hand-derived cardinalities."""
        expected_counts = {"sessions": 2, "windows": 6, "panes": 12}
        for family in ("classic", "snapshot", "end-to-end"):
            for kind, expected_count in expected_counts.items():
                ids = {
                    "sessions": context.session_ids,
                    "windows": context.window_ids,
                    "panes": context.pane_ids,
                }[kind]
                for position, target in (
                    ("first", ids[0]),
                    ("middle", ids[len(ids) // 2]),
                    ("last", ids[-1]),
                ):
                    assert observed[family, kind, position] == (
                        expected_count,
                        (target,),
                    )
        assert observed["contents", "panes", target_position] == (
            12,
            (context.pane_ids[delayed_ordinal],),
        )

    async def exercise_async() -> None:
        """Keep typed async capture and final topology proof on one loop."""
        nonlocal context, cleanup
        context = await benchmark_module.setup_async(
            topology,
            lane,
            scratch,
            run_id=run_id,
            delayed_ordinal=delayed_ordinal,
        )
        try:
            benchmark_module.release_activity_gate(context)
            await benchmark_module.verify_activity_async(context)
            snapshot = await benchmark_module.snapshot_topology_async(context)
            exercise_metadata(snapshot)
            sentinel = _request_content_sentinel(
                benchmark_module, context, f"content-{target_position}"
            )
            deadline = time.monotonic() + 3.0
            captures = None
            while time.monotonic() < deadline:
                candidate = await benchmark_module.capture_all_async(
                    context, strategy="batched"
                )
                if any(sentinel in capture.lines for capture in candidate.captures):
                    captures = candidate
                    break
                await asyncio.sleep(0.01)
            assert captures is not None
            content = benchmark_module.search_contents(
                captures,
                token=sentinel,
                expected_pane_id=context.pane_ids[delayed_ordinal],
            )
            observed["contents", "panes", target_position] = (
                content.scanned_count,
                content.matched_ids,
            )
            final_snapshot = await benchmark_module.snapshot_topology_async(context)
            assert tuple(row.session_id for row in final_snapshot.sessions) == (
                context.session_ids
            )
            assert tuple(row.window_id for row in final_snapshot.windows) == (
                context.window_ids
            )
            assert (
                tuple(row.pane_id for row in final_snapshot.panes) == context.pane_ids
            )
            assert (
                benchmark_module._current_activity_heartbeat(
                    context, max_age_s=2.0
                ).epoch
                >= captures.epoch
            )
            assert_explicit_expectations()
        finally:
            cleanup = await benchmark_module.cleanup_run(context)

    if mode_name == "async":
        asyncio.run(exercise_async())
    else:
        context = benchmark_module.setup_sync(
            topology,
            lane,
            scratch,
            run_id=run_id,
            delayed_ordinal=delayed_ordinal,
        )
        try:
            benchmark_module.release_activity_gate(context)
            benchmark_module.verify_activity_sync(context)
            snapshot = benchmark_module.snapshot_topology_sync(context)
            exercise_metadata(snapshot)
            sentinel = _request_content_sentinel(
                benchmark_module, context, f"content-{target_position}"
            )
            deadline = time.monotonic() + 3.0
            captures = None
            while time.monotonic() < deadline:
                candidate = benchmark_module.capture_all_sync(
                    context, strategy="batched"
                )
                if any(sentinel in capture.lines for capture in candidate.captures):
                    captures = candidate
                    break
                time.sleep(0.01)
            assert captures is not None
            content = benchmark_module.search_contents(
                captures,
                token=sentinel,
                expected_pane_id=context.pane_ids[delayed_ordinal],
            )
            observed["contents", "panes", target_position] = (
                content.scanned_count,
                content.matched_ids,
            )
            final_snapshot = benchmark_module.snapshot_topology_sync(context)
            assert tuple(row.session_id for row in final_snapshot.sessions) == (
                context.session_ids
            )
            assert tuple(row.window_id for row in final_snapshot.windows) == (
                context.window_ids
            )
            assert (
                tuple(row.pane_id for row in final_snapshot.panes) == context.pane_ids
            )
            assert (
                benchmark_module._current_activity_heartbeat(
                    context, max_age_s=2.0
                ).epoch
                >= captures.epoch
            )
            assert_explicit_expectations()
        finally:
            cleanup = asyncio.run(benchmark_module.cleanup_run(context))
    assert cleanup is not None
    assert cleanup.complete, cleanup.errors


def test_run_repeatable_phase_interleaves_and_accepts_only_verified_samples(
    benchmark_module: types.ModuleType,
) -> None:
    """Only typed results with a true live postcondition become raw samples."""
    calls: list[str] = []
    resource_ordinal = 0

    def snapshot_resources() -> t.Any:
        nonlocal resource_ordinal
        resource_ordinal += 1
        return benchmark_module.HostSnapshot(pids_current=resource_ordinal)

    def measured(name: str) -> t.Callable[[], t.Any]:
        def run() -> t.Any:
            calls.append(name)
            return benchmark_module.SearchResult(
                duration_ns=17,
                family="snapshot",
                kind="sessions",
                scanned_count=2,
                target="$1",
                matched_ids=("$1",),
                verified=True,
            )

        return run

    result = asyncio.run(
        benchmark_module.run_repeatable_phase(
            {"alpha": measured("alpha"), "beta": measured("beta")},
            warmup=1,
            runs=2,
            seed=11,
            snapshot_resources=snapshot_resources,
            live_postcondition=lambda measurement: measurement.matched_ids == ("$1",),
        )
    )

    assert result.failure is None
    assert len(result.samples) == 4
    assert len(result.order) == 6
    assert calls[:2] in (["alpha", "beta"], ["beta", "alpha"])
    assert calls[2:4] == list(reversed(calls[:2]))
    assert calls[4:6] == calls[:2]
    assert all(sample.duration_ns == 17 for sample in result.samples)
    assert all(sample.accepted and sample.verified for sample in result.samples)
    assert all(sample.resources_before is not None for sample in result.samples)
    assert all(sample.resources_after is not None for sample in result.samples)


def test_run_repeatable_phase_requires_live_postcondition_at_call_time(
    benchmark_module: types.ModuleType,
) -> None:
    """Omitting independent live validation must not create a coroutine."""
    with pytest.raises(TypeError, match="live_postcondition"):
        benchmark_module.run_repeatable_phase(
            {"only": lambda: None},
            warmup=0,
            runs=1,
            seed=1,
        )


@pytest.mark.parametrize("postcondition_kind", ("false", "exception"))
def test_run_repeatable_phase_rejects_postcondition_before_after_snapshot(
    benchmark_module: types.ModuleType,
    postcondition_kind: str,
) -> None:
    """A false or failing live check must retain no sample or after snapshot."""
    snapshot_calls = 0

    def snapshot_resources() -> t.Any:
        nonlocal snapshot_calls
        snapshot_calls += 1
        return benchmark_module.HostSnapshot(pids_current=snapshot_calls)

    def measured() -> t.Any:
        return benchmark_module.SearchResult(
            duration_ns=19,
            family="snapshot",
            kind="sessions",
            scanned_count=2,
            target="$1",
            matched_ids=("$1",),
            verified=True,
        )

    def live_postcondition(_measurement: t.Any) -> bool:
        if postcondition_kind == "exception":
            message = "independent live check failed"
            raise RuntimeError(message)
        return False

    result = asyncio.run(
        benchmark_module.run_repeatable_phase(
            {"only": measured},
            warmup=0,
            runs=1,
            seed=1,
            snapshot_resources=snapshot_resources,
            live_postcondition=live_postcondition,
        )
    )

    assert result.samples == ()
    assert result.failure is not None
    assert result.failure.strategy == "only"
    assert snapshot_calls == 1


def test_run_repeatable_phase_stops_without_appending_failed_duration(
    benchmark_module: types.ModuleType,
) -> None:
    """A phase exception must retain failure metadata but no duration row."""
    attempts = 0

    def fail_second() -> t.Any:
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            message = "live postcondition lost"
            raise RuntimeError(message)
        return benchmark_module.SearchResult(
            duration_ns=23,
            family="snapshot",
            kind="sessions",
            scanned_count=2,
            target="$1",
            matched_ids=("$1",),
            verified=True,
        )

    result = asyncio.run(
        benchmark_module.run_repeatable_phase(
            {"only": fail_second},
            warmup=0,
            runs=3,
            seed=3,
            snapshot_resources=lambda: benchmark_module.HostSnapshot(),
            live_postcondition=lambda _measurement: True,
        )
    )

    assert len(result.samples) == 1
    assert result.samples[0].duration_ns == 23
    assert result.failure is not None
    assert result.failure.strategy == "only"
    assert result.failure.ordinal == 1
    assert result.failure.error == "RuntimeError: live postcondition lost"


def test_cli_run_executes_every_phase_and_writes_validated_artifacts(
    tmp_path: pathlib.Path,
) -> None:
    """Skipping a phase or requested sample would publish incomplete evidence."""
    report_path = tmp_path / "run.json"
    markdown_path = tmp_path / "run.md"
    scratch_root = tmp_path / "scratch"

    completed = _run_cli(
        "run",
        "--shape",
        "2x2x2",
        "--runs",
        "2",
        "--warmup",
        "1",
        "--output",
        str(report_path),
        "--markdown-output",
        str(markdown_path),
        "--scratch-root",
        str(scratch_root),
        "--watchdog-seconds",
        "30",
        cwd=tmp_path,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "completed"
    assert payload["requested_topology"] == {
        "sessions": 2,
        "windows_per_session": 2,
        "panes_per_window": 2,
    }
    assert payload["observed_topology"] == payload["requested_topology"]
    assert payload["lane"] == "control"
    assert payload["mode"] == "async"
    phases = {phase["name"]: phase for phase in payload["phases"]}
    assert tuple(phases) == (
        "setup",
        "stabilization",
        *_RUNNER_REPEATABLE_PHASES[:2],
        "wait.control-stream",
        *_RUNNER_REPEATABLE_PHASES[2:],
    )
    assert phases["setup"]["summary"] is None
    assert len(phases["setup"]["samples"]) == 1
    assert phases["stabilization"]["samples"] == []
    for phase_name in (*_RUNNER_REPEATABLE_PHASES, "wait.control-stream"):
        phase = phases[phase_name]
        assert phase["status"] == "completed"
        assert phase["warmup"] == 1
        assert phase["runs"] == 2
        assert [row["ordinal"] for row in phase["warmup_observations"]] == [0]
        assert len(phase["samples"]) == 2
        assert phase["summary"]["count"] == 2
        assert len(phase["observations"]) == 2
        assert all(row["accepted"] and row["verified"] for row in phase["samples"])
    assert payload["cleanup"] == {
        "complete": True,
        "errors": [],
        "processes_absent": True,
        "scratch_absent": True,
        "socket_absent": True,
    }
    assert not pathlib.Path(payload["scratch_path"]).exists()
    assert not pathlib.Path(payload["socket_path"]).exists()
    assert all(not _identity_still_matches(row) for row in payload["processes"])
    progress = pathlib.Path(payload["progress_path"])
    events = [json.loads(line) for line in progress.read_text().splitlines()]
    assert [event["sequence"] for event in events] == list(range(len(events)))
    assert "Local descriptive evidence" in markdown_path.read_text(encoding="utf-8")


def test_cli_ramp_uses_fresh_owned_resources_for_every_shape(
    tmp_path: pathlib.Path,
) -> None:
    """Reusing a server between shapes would invalidate fresh-setup evidence."""
    report_path = tmp_path / "ramp.json"
    markdown_path = tmp_path / "ramp.md"

    completed = _run_cli(
        "ramp",
        "--shapes",
        "1x1x1,2x2x1",
        "--runs",
        "1",
        "--warmup",
        "0",
        "--output",
        str(report_path),
        "--markdown-output",
        str(markdown_path),
        "--scratch-root",
        str(tmp_path / "scratch"),
        "--watchdog-seconds",
        "30",
        cwd=tmp_path,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "completed"
    assert [step["status"] for step in payload["ramp"]] == [
        "completed",
        "completed",
    ]
    assert [step["shape"] for step in payload["ramp"]] == [
        {"sessions": 1, "windows_per_session": 1, "panes_per_window": 1},
        {"sessions": 2, "windows_per_session": 2, "panes_per_window": 1},
    ]
    run_ids = [step["run_id"] for step in payload["ramp"]]
    scratch_paths = [step["scratch_path"] for step in payload["ramp"]]
    socket_paths = [step["socket_path"] for step in payload["ramp"]]
    assert len(set(run_ids)) == 2
    assert len(set(scratch_paths)) == 2
    assert len(set(socket_paths)) == 2
    assert all(not pathlib.Path(path).exists() for path in scratch_paths)
    assert all(not pathlib.Path(path).exists() for path in socket_paths)
    child_reports = [
        json.loads(pathlib.Path(step["report_path"]).read_text(encoding="utf-8"))
        for step in payload["ramp"]
    ]
    assert [child["run_id"] for child in child_reports] == run_ids
    assert [child["status"] for child in child_reports] == [
        "completed",
        "completed",
    ]
    server_identities = [
        next(row for row in child["processes"] if row["role"] == "server")
        for child in child_reports
    ]
    assert len({(row["pid"], row["start_time"]) for row in server_identities}) == 2
    assert all(not _identity_still_matches(row) for row in server_identities)
    assert "1x1x1" in markdown_path.read_text(encoding="utf-8")
    assert "2x2x1" in markdown_path.read_text(encoding="utf-8")


def test_cli_predictive_refusal_writes_terminal_report_without_worker(
    tmp_path: pathlib.Path,
) -> None:
    """A refused preflight must not create any live benchmark-owned resource."""
    report_path = tmp_path / "refused.json"
    markdown_path = tmp_path / "refused.md"
    host_path = tmp_path / "host.json"
    host_path.write_text(
        json.dumps(
            {
                "available_memory_bytes": 16 * 1024**3,
                "physical_memory_bytes": 32 * 1024**3,
                "memory_current_bytes": 1024,
                "memory_max_bytes": 32 * 1024**3,
                "pids_current": 10,
                "pids_max": 12,
                "nofile_soft_limit": 65536,
                "nofile_hard_limit": 65536,
                "memory_pressure_some_avg10": 0.0,
                "source_errors": {},
            }
        ),
        encoding="utf-8",
    )

    completed = _run_cli(
        "run",
        "--shape",
        "2x2x2",
        "--runs",
        "1",
        "--warmup",
        "0",
        "--output",
        str(report_path),
        "--markdown-output",
        str(markdown_path),
        "--scratch-root",
        str(tmp_path / "scratch"),
        "--pid-reserve",
        "1",
        "--_test-host-snapshot",
        str(host_path),
        cwd=tmp_path,
    )

    assert completed.returncode != 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "refused"
    assert payload["failed_phase"] == "preflight"
    assert payload["guard_decision"]["kind"] == "predictive_refusal"
    assert payload["processes"] == []
    assert payload["progress_path"] is None
    assert payload["scratch_path"] is None
    assert payload["socket_path"] is None
    assert payload["cleanup"]["complete"] is True
    assert not (tmp_path / "scratch").exists()
    assert not list(tmp_path.glob("*.progress.jsonl"))
    assert "refused" in markdown_path.read_text(encoding="utf-8")


def test_cli_watchdog_recovers_stalled_worker_and_exact_resources(
    tmp_path: pathlib.Path,
) -> None:
    """A stopped progress stream must trigger bounded supervisor recovery."""
    report_path = tmp_path / "watchdog.json"

    completed = _run_cli(
        "run",
        "--shape",
        "1x1x1",
        "--runs",
        "1",
        "--warmup",
        "0",
        "--output",
        str(report_path),
        "--scratch-root",
        str(tmp_path / "scratch"),
        "--watchdog-seconds",
        "1.0",
        "--cleanup-grace-seconds",
        "0.3",
        "--_test-stall-after",
        "setup",
        cwd=tmp_path,
    )

    assert completed.returncode != 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "cutoff"
    assert payload["failed_phase"] == "watchdog"
    assert "progress watchdog expired" in payload["error"]
    assert payload["progress_sequence"] >= 0
    assert {row["role"] for row in payload["processes"]} >= {
        "worker",
        "fuzzer",
        "server",
        "pane",
    }
    _assert_terminal_cleanup(payload)


def test_watchdog_progress_requires_an_increasing_sequence(
    benchmark_module: types.ModuleType,
) -> None:
    """Duplicate or older progress lines must not refresh the watchdog."""
    identity = benchmark_module.ProcessIdentity("fuzzer", 2, 3)
    stalled = (
        benchmark_module.ProgressEvent("run-7", 3, "same", 10, (identity,)),
        benchmark_module.ProgressEvent("run-7", 2, "older", 11),
        benchmark_module.ProgressEvent("run-7", 3, "same-again", 12),
    )

    highest, identities, advanced = benchmark_module._accept_progress_events(
        stalled,
        run_id="run-7",
        highest_sequence=3,
        identities=(),
    )

    assert highest == 3
    assert identities == ()
    assert advanced is False
    advanced_event = benchmark_module.ProgressEvent("run-7", 4, "next", 13, (identity,))
    highest, identities, advanced = benchmark_module._accept_progress_events(
        (advanced_event,),
        run_id="run-7",
        highest_sequence=highest,
        identities=identities,
    )
    assert highest == 4
    assert identities == (identity,)
    assert advanced is True


def test_worker_progress_precedes_matching_report_checkpoint(
    benchmark_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """An identity event must be durable before its checkpoint can expose it."""
    calls: list[str] = []
    monkeypatch.setattr(
        benchmark_module,
        "append_progress_event",
        lambda _path, _event: calls.append("progress"),
    )
    monkeypatch.setattr(
        benchmark_module,
        "write_json_atomic",
        lambda _path, _report: calls.append("checkpoint"),
    )
    recorder = benchmark_module._WorkerRecorder(
        benchmark_module.RunReport(benchmark_module.Topology(1, 1, 1), run_id="run-7"),
        tmp_path / "checkpoint.json",
        tmp_path / "progress.jsonl",
    )

    recorder.checkpoint("worker.started")

    assert calls == ["progress", "checkpoint"]


def test_progress_append_retries_short_writes_and_syncs_new_parent(
    benchmark_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """A short kernel append must not leave a torn identity record."""
    path = tmp_path / "journal" / "progress.jsonl"
    real_write = os.write
    real_fsync = os.fsync
    write_sizes: list[int] = []
    sync_kinds: list[str] = []

    def short_write(descriptor: int, payload: bytes | bytearray | memoryview) -> int:
        chunk = bytes(payload[:7])
        write_sizes.append(len(chunk))
        return real_write(descriptor, chunk)

    def tracked_fsync(descriptor: int) -> None:
        mode = os.fstat(descriptor).st_mode
        sync_kinds.append("directory" if stat.S_ISDIR(mode) else "file")
        real_fsync(descriptor)

    monkeypatch.setattr(benchmark_module.os, "write", short_write)
    monkeypatch.setattr(benchmark_module.os, "fsync", tracked_fsync)
    event = benchmark_module.ProgressEvent(
        "run-7",
        0,
        "identity.fuzzer",
        1,
        (benchmark_module.ProcessIdentity("fuzzer", 42, 100),),
    )

    benchmark_module.append_progress_event(path, event)

    first = json.loads(path.read_text(encoding="utf-8"))
    assert first["checkpoint"] == "identity.fuzzer"
    assert len(write_sizes) > 1
    assert sync_kinds == ["file", "directory"]

    benchmark_module.append_progress_event(
        path,
        benchmark_module.ProgressEvent("run-7", 1, "setup", 2),
    )
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
    assert sync_kinds == ["file", "directory", "file"]


@pytest.mark.parametrize(
    "tail",
    (
        '{"schema_version":1',
        '{"schema_version":1}\n',
    ),
)
def test_terminal_progress_drain_rejects_torn_or_corrupt_tail(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    tail: str,
) -> None:
    """Terminal recovery cannot silently discard malformed identity evidence."""
    path = tmp_path / "progress.jsonl"
    path.write_text(tail, encoding="utf-8")

    with pytest.raises(ValueError, match="progress journal"):
        benchmark_module._read_progress_chunk(path, 0, "", terminal=True)


def test_progress_sequence_gap_is_journal_corruption(
    benchmark_module: types.ModuleType,
) -> None:
    """Losing one identity delta must not look like valid later progress."""
    events = (
        benchmark_module.ProgressEvent("run-7", 0, "worker.started", 1),
        benchmark_module.ProgressEvent("run-7", 2, "setup", 2),
    )

    with pytest.raises(RuntimeError, match="sequence gap"):
        benchmark_module._accept_progress_events(
            events,
            run_id="run-7",
            highest_sequence=-1,
            identities=(),
        )


def test_recovery_drains_and_stops_identity_published_during_grace(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
) -> None:
    """Recovery must merge a late identity instead of freezing its first read."""
    scratch = tmp_path / "late-identity"
    scratch.mkdir(mode=0o700)
    progress = scratch / "progress.jsonl"
    worker = subprocess.Popen(
        (
            sys.executable,
            "-c",
            (
                "import signal,time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "print('ready', flush=True); time.sleep(60)"
            ),
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    assert worker.stdout is not None
    assert worker.stdout.readline() == "ready\n"
    worker_identity = benchmark_module._record_process("worker", worker.pid)
    benchmark_module.append_progress_event(
        progress,
        benchmark_module.ProgressEvent(
            "run-7", 0, "worker.started", 1, (worker_identity,)
        ),
    )
    registry = benchmark_module._PidfdRegistry()
    registry.retain(worker_identity)
    tracker = benchmark_module._ProgressTracker(
        progress,
        "run-7",
        registry,
        identities=(worker_identity,),
    )
    assert tracker.drain()
    late_identities: list[t.Any] = []

    def publish_late_identity() -> None:
        time.sleep(0.05)
        late = subprocess.Popen(
            (
                sys.executable,
                "-c",
                (
                    "import signal,time; "
                    "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
                ),
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        identity = benchmark_module._record_process("fuzzer", late.pid)
        late_identities.append(identity)
        benchmark_module.append_progress_event(
            progress,
            benchmark_module.ProgressEvent(
                "run-7", 1, "identity.fuzzer", 2, (identity,)
            ),
        )
        late.wait(timeout=5.0)

    publisher = threading.Thread(target=publish_late_identity)
    publisher.start()
    try:
        cleanup = benchmark_module._recover_supervised_run(
            worker,
            worker_identity,
            tracker,
            scratch=scratch,
            socket_path=scratch / "tmux.sock",
            grace_s=0.15,
        )
    finally:
        publisher.join(timeout=5.0)
        registry.close()
        if worker.poll() is None:
            worker.kill()
        worker.wait(timeout=2.0)

    assert not publisher.is_alive()
    assert len(late_identities) == 1
    assert late_identities[0] in tracker.identities
    assert cleanup.complete, cleanup.errors
    assert not scratch.exists()


@pytest.mark.parametrize("journal_state", ("missing", "torn"))
def test_recovery_retains_evidence_when_terminal_journal_is_incomplete(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    journal_state: str,
) -> None:
    """Missing or torn terminal ownership evidence must make cleanup incomplete."""
    scratch = tmp_path / journal_state
    scratch.mkdir(mode=0o700)
    progress = scratch / "progress.jsonl"
    if journal_state == "torn":
        progress.write_text('{"schema_version":1', encoding="utf-8")
    worker = subprocess.Popen((sys.executable, "-c", "import time; time.sleep(1)"))
    worker_identity = benchmark_module._record_process("worker", worker.pid)
    worker.terminate()
    worker.wait(timeout=2.0)
    registry = benchmark_module._PidfdRegistry()
    tracker = benchmark_module._ProgressTracker(
        progress,
        "run-7",
        registry,
        identities=(worker_identity,),
    )
    try:
        cleanup = benchmark_module._recover_supervised_run(
            worker,
            worker_identity,
            tracker,
            scratch=scratch,
            socket_path=scratch / "tmux.sock",
            grace_s=0.05,
        )
    finally:
        registry.close()

    assert not cleanup.complete
    assert any("progress journal" in error for error in cleanup.errors)
    assert scratch.exists()


def test_progress_identity_deltas_scale_linearly(
    benchmark_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """Checkpoint count must not multiply a large identity set on disk."""
    events: list[t.Any] = []
    reports: list[dict[str, t.Any]] = []
    monkeypatch.setattr(
        benchmark_module,
        "append_progress_event",
        lambda _path, event: events.append(event),
    )
    monkeypatch.setattr(
        benchmark_module,
        "write_json_atomic",
        lambda _path, report: reports.append(
            t.cast(dict[str, t.Any], benchmark_module._json_value(report))
        ),
    )
    recorder = benchmark_module._WorkerRecorder(
        benchmark_module.RunReport(benchmark_module.Topology(1, 1, 1), run_id="run-7"),
        tmp_path / "checkpoint.json",
        tmp_path / "progress.jsonl",
    )
    identities = tuple(
        benchmark_module.ProcessIdentity("pane", 100_000 + ordinal, ordinal + 1)
        for ordinal in range(40_000)
    )

    recorder.record_identities(identities, checkpoint="identity.panes")
    for ordinal in range(100):
        recorder.checkpoint(f"timed.{ordinal}")

    assert len(events) == 101
    assert sum(len(event.processes) for event in events) == 40_000
    assert len(events[0].processes) == 40_000
    assert all(event.processes == () for event in events[1:])
    assert all(report["processes"] == [] for report in reports)


@pytest.mark.parametrize(
    "cleanup",
    (
        {"complete": True, "errors": ("socket remains",), "flags": (True, True, True)},
        {"complete": True, "errors": (), "flags": (False, True, True)},
        {"complete": True, "errors": (), "flags": (True, False, True)},
        {"complete": True, "errors": (), "flags": (True, True, False)},
    ),
)
def test_validator_rejects_false_cleanup_success(
    benchmark_module: types.ModuleType,
    cleanup: dict[str, t.Any],
) -> None:
    """A success bit cannot override errors or any surviving resource class."""
    processes_absent, socket_absent, scratch_absent = cleanup["flags"]
    report = benchmark_module.RunReport(
        benchmark_module.Topology(1, 1, 1),
        status="failed",
        cleanup=benchmark_module.CleanupReport(
            cleanup["complete"],
            cleanup["errors"],
            processes_absent=processes_absent,
            socket_absent=socket_absent,
            scratch_absent=scratch_absent,
        ),
    )

    with pytest.raises(ValueError, match="cleanup"):
        benchmark_module.validate_report(report)


def test_validator_accepts_explicit_terminal_cleanup_failure_evidence(
    benchmark_module: types.ModuleType,
) -> None:
    """A failed cleanup must remain publishable without claiming completion."""
    topology = benchmark_module.Topology(1, 1, 1)
    report = benchmark_module.RunReport(
        topology,
        status="failed",
        cleanup=benchmark_module.CleanupReport(
            False,
            ("socket remains",),
            processes_absent=True,
            socket_absent=False,
            scratch_absent=False,
        ),
        run_id="run-7",
        lane="control",
        mode="async",
        warmup=0,
        runs=1,
        failed_phase="cleanup",
        error="socket remains",
        scratch_path="scratch",
        socket_path="scratch/tmux.sock",
        progress_path="progress.jsonl",
        environment=benchmark_module.EnvironmentReport(
            "3.10", None, 1, 11, ("run",), None
        ),
    )

    benchmark_module.validate_report(report)


def test_validator_rejects_nonprefix_terminal_phase_graph(
    benchmark_module: types.ModuleType,
) -> None:
    """A failed run cannot invent a later phase after omitting stabilization."""
    topology = benchmark_module.Topology(1, 1, 1)
    setup_sample = benchmark_module.RawSample(
        1,
        True,
        verified=True,
        strategy="setup",
        ordinal=0,
    )
    report = benchmark_module.RunReport(
        topology,
        observed_topology=topology,
        status="failed",
        phases=(
            benchmark_module.PhaseReport(
                "setup",
                topology,
                topology,
                samples=(setup_sample,),
                status="completed",
                runs=1,
                observations=(benchmark_module.PhaseObservation(0, "setup", 1),),
            ),
            benchmark_module.PhaseReport(
                "mutation.bulk",
                topology,
                topology,
                status="failed",
                runs=1,
            ),
        ),
        cleanup=benchmark_module.CleanupReport(
            True,
            processes_absent=True,
            socket_absent=True,
            scratch_absent=True,
        ),
        run_id="run-7",
        lane="subprocess",
        mode="sync",
        warmup=0,
        runs=1,
        failed_phase="mutation.bulk",
        error="injected failure",
        scratch_path="scratch",
        socket_path="scratch/socket",
        progress_path="progress.jsonl",
        environment=benchmark_module.EnvironmentReport(
            "3.10", None, 1, 11, ("run",), None
        ),
    )

    with pytest.raises(ValueError, match="phase prefix"):
        benchmark_module.validate_report(report)


def test_validator_rejects_completed_phase_after_failed_prefix(
    benchmark_module: types.ModuleType,
) -> None:
    """No later completed row may follow the first failed phase boundary."""
    topology = benchmark_module.Topology(1, 1, 1)
    report = benchmark_module.RunReport(
        topology,
        status="failed",
        phases=(
            benchmark_module.PhaseReport("setup", topology, topology, status="failed"),
            benchmark_module.PhaseReport(
                "stabilization", topology, topology, status="completed"
            ),
        ),
        cleanup=benchmark_module.CleanupReport(
            True,
            processes_absent=True,
            socket_absent=True,
            scratch_absent=True,
        ),
    )

    with pytest.raises(ValueError, match="phase status prefix"):
        benchmark_module.validate_report(report)


def test_validator_requires_accepted_verified_setup_observation(
    benchmark_module: types.ModuleType,
) -> None:
    """A completed setup row cannot claim success with rejected raw evidence."""
    topology = benchmark_module.Topology(1, 1, 1)
    report = benchmark_module.RunReport(
        topology,
        observed_topology=topology,
        status="completed",
        phases=(
            benchmark_module.PhaseReport(
                "setup",
                topology,
                topology,
                samples=(
                    benchmark_module.RawSample(
                        1,
                        False,
                        error="not verified",
                        strategy="setup",
                        ordinal=0,
                    ),
                ),
                status="completed",
                runs=1,
                observations=(
                    benchmark_module.PhaseObservation(
                        0,
                        "setup",
                        1,
                        verified=False,
                    ),
                ),
            ),
        ),
        cleanup=benchmark_module.CleanupReport(
            True,
            processes_absent=True,
            socket_absent=True,
            scratch_absent=True,
        ),
    )

    with pytest.raises(ValueError, match=r"setup.*accepted.*verified"):
        benchmark_module.validate_report(report)


def test_validator_rejects_duplicate_timed_ordinals(
    benchmark_module: types.ModuleType,
) -> None:
    """Duplicate timed rows cannot satisfy a declared two-run cell."""
    topology = benchmark_module.Topology(1, 1, 1)
    samples = tuple(
        benchmark_module.RawSample(
            duration,
            True,
            verified=True,
            strategy="mutation.bulk",
            ordinal=0,
        )
        for duration in (10, 20)
    )
    observations = tuple(
        benchmark_module.PhaseObservation(
            0,
            "mutation.bulk",
            duration,
        )
        for duration in (10, 20)
    )
    report = benchmark_module.RunReport(
        topology,
        status="in_progress",
        phases=(
            benchmark_module.PhaseReport(
                "mutation.bulk",
                topology,
                topology,
                samples=samples,
                summary={
                    "count": 2,
                    "min_ns": 10,
                    "mean_ns": 15,
                    "median_ns": 15.0,
                    "p90_ns": 20,
                    "p95_ns": 20,
                    "p99_ns": 20,
                    "max_ns": 20,
                },
                status="completed",
                warmup=0,
                runs=2,
                observations=observations,
            ),
        ),
    )

    with pytest.raises(ValueError, match="timed ordinals"):
        benchmark_module.validate_report(report)


def test_validator_requires_exact_warmup_observation_ordinals(
    benchmark_module: types.ModuleType,
) -> None:
    """A completed cell must retain every unique declared warmup ordinal."""
    topology = benchmark_module.Topology(1, 1, 1)
    phase = benchmark_module.PhaseReport(
        "mutation.bulk",
        topology,
        topology,
        samples=(
            benchmark_module.RawSample(
                10,
                True,
                verified=True,
                strategy="mutation.bulk",
                ordinal=0,
            ),
        ),
        summary={
            "count": 1,
            "min_ns": 10,
            "mean_ns": 10,
            "median_ns": 10,
            "p90_ns": 10,
            "p95_ns": 10,
            "p99_ns": 10,
            "max_ns": 10,
        },
        status="completed",
        warmup=2,
        runs=1,
        warmup_observations=(
            benchmark_module.PhaseObservation(0, "mutation.bulk", 5),
            benchmark_module.PhaseObservation(0, "mutation.bulk", 6),
        ),
        observations=(benchmark_module.PhaseObservation(0, "mutation.bulk", 10),),
    )
    report = benchmark_module.RunReport(
        topology,
        status="in_progress",
        phases=(phase,),
    )

    with pytest.raises(ValueError, match="warmup ordinals"):
        benchmark_module.validate_report(report)


def _failed_report_with_completed_mutation_prefix(
    benchmark_module: types.ModuleType,
    *,
    phase_warmup: int = 2,
    phase_runs: int = 2,
    warmup_ordinals: tuple[int, ...] = (0, 1),
    timed_ordinals: tuple[int, ...] = (0, 1),
) -> t.Any:
    """Build a valid active failure after one configurable completed cell."""
    topology = benchmark_module.Topology(1, 1, 1)
    setup = benchmark_module.PhaseReport(
        "setup",
        topology,
        topology,
        samples=(
            benchmark_module.RawSample(
                1,
                True,
                verified=True,
                strategy="setup",
                ordinal=0,
            ),
        ),
        status="completed",
        runs=1,
        observations=(benchmark_module.PhaseObservation(0, "setup", 1),),
    )
    stabilization = benchmark_module.PhaseReport(
        "stabilization",
        topology,
        topology,
        status="completed",
        observations=(
            benchmark_module.PhaseObservation(
                0,
                "stabilization",
                1,
                pane_count=topology.panes,
            ),
        ),
    )
    samples = tuple(
        benchmark_module.RawSample(
            10 + ordinal,
            True,
            verified=True,
            strategy="mutation.bulk",
            ordinal=ordinal,
        )
        for ordinal in timed_ordinals
    )
    durations = tuple(t.cast(int, sample.duration_ns) for sample in samples)
    mutation = benchmark_module.PhaseReport(
        "mutation.bulk",
        topology,
        topology,
        samples=samples,
        summary=(benchmark_module.summarize_ns(durations) if durations else None),
        status="completed",
        warmup=phase_warmup,
        runs=phase_runs,
        warmup_observations=tuple(
            benchmark_module.PhaseObservation(
                ordinal,
                "mutation.bulk",
                2 + ordinal,
            )
            for ordinal in warmup_ordinals
        ),
        observations=tuple(
            benchmark_module.PhaseObservation(
                t.cast(int, sample.ordinal),
                "mutation.bulk",
                t.cast(int, sample.duration_ns),
            )
            for sample in samples
        ),
    )
    active_failure = benchmark_module.PhaseReport(
        "wait.capture-poll",
        topology,
        topology,
        status="failed",
        warmup=2,
        runs=2,
        warmup_observations=(
            benchmark_module.PhaseObservation(0, "wait.capture-poll", 3),
        ),
    )
    return benchmark_module.RunReport(
        topology,
        observed_topology=topology,
        status="failed",
        phases=(setup, stabilization, mutation, active_failure),
        cleanup=benchmark_module.CleanupReport(
            True,
            processes_absent=True,
            socket_absent=True,
            scratch_absent=True,
        ),
        run_id="run-7",
        lane="subprocess",
        mode="sync",
        warmup=2,
        runs=2,
        failed_phase="wait.capture-poll",
        error="injected active wait failure",
        scratch_path="scratch",
        socket_path="scratch/socket",
        progress_path="progress.jsonl",
        environment=benchmark_module.EnvironmentReport(
            "3.10", None, 1, 11, ("run",), None
        ),
    )


@pytest.mark.parametrize(
    "report_changes",
    (
        {"phase_warmup": 1, "warmup_ordinals": (0,)},
        {"phase_runs": 1, "timed_ordinals": (0,)},
        {"phase_warmup": 2, "warmup_ordinals": (0, 0)},
        {"phase_runs": 2, "timed_ordinals": (0, 0)},
    ),
)
def test_validator_rejects_incomplete_completed_cell_before_active_failure(
    benchmark_module: types.ModuleType,
    report_changes: dict[str, t.Any],
) -> None:
    """A later valid failure cannot excuse malformed completed-prefix evidence."""
    report = _failed_report_with_completed_mutation_prefix(
        benchmark_module,
        **report_changes,
    )

    with pytest.raises(ValueError, match=r"mutation\.bulk"):
        benchmark_module.validate_report(report)


def test_validator_accepts_partial_active_failure_after_complete_prefix(
    benchmark_module: types.ModuleType,
) -> None:
    """The one active failed cell may retain a valid incomplete warmup prefix."""
    benchmark_module.validate_report(
        _failed_report_with_completed_mutation_prefix(benchmark_module)
    )


def test_validator_rejects_failed_phase_that_disagrees_with_active_row(
    benchmark_module: types.ModuleType,
) -> None:
    """Terminal metadata must name the exact active failed phase."""
    report = dataclasses.replace(
        _failed_report_with_completed_mutation_prefix(benchmark_module),
        failed_phase="capture.serial",
    )

    with pytest.raises(ValueError, match="failed_phase"):
        benchmark_module.validate_report(report)


def test_validator_rejects_future_row_after_lazy_active_failure(
    benchmark_module: types.ModuleType,
) -> None:
    """A canonical future row is invalid even when it carries no evidence."""
    report = _failed_report_with_completed_mutation_prefix(benchmark_module)
    future = benchmark_module.PhaseReport(
        "wait.control-stream",
        report.requested_topology,
        report.requested_topology,
        status="not_applicable",
        warmup=report.warmup,
        runs=report.runs,
    )
    report = dataclasses.replace(report, phases=(*report.phases, future))

    with pytest.raises(ValueError, match="phase status prefix"):
        benchmark_module.validate_report(report)


def test_cli_phase_failure_uses_supervisor_cleanup_contract(
    tmp_path: pathlib.Path,
) -> None:
    """A measured phase exception must retain failure and cleanup evidence."""
    report_path = tmp_path / "failure.json"

    completed = _run_cli(
        "run",
        "--shape",
        "1x1x1",
        "--runs",
        "1",
        "--warmup",
        "0",
        "--output",
        str(report_path),
        "--scratch-root",
        str(tmp_path / "scratch"),
        "--watchdog-seconds",
        "30",
        "--_test-fail-after",
        "mutation.bulk",
        cwd=tmp_path,
    )

    assert completed.returncode != 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["failed_phase"] == "mutation.bulk"
    assert "injected phase failure" in payload["error"]
    phases = {phase["name"]: phase for phase in payload["phases"]}
    assert phases["mutation.bulk"]["status"] == "failed"
    _assert_terminal_cleanup(payload)


@pytest.mark.parametrize(
    "failed_phase",
    (
        "enumeration.windows",
        "capture.batched",
        "search.snapshot.windows.middle",
    ),
)
def test_cli_mid_strategy_failure_has_one_active_prefix_and_no_future_rows(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
    failed_phase: str,
) -> None:
    """A strategy failure cannot manufacture evidence for a later cell."""
    report_path = tmp_path / f"{failed_phase}.json"
    markdown_path = report_path.with_suffix(".md")

    completed = _run_cli(
        "run",
        "--shape",
        "1x1x1",
        "--lane",
        "subprocess",
        "--mode",
        "sync",
        "--runs",
        "1",
        "--warmup",
        "0",
        "--output",
        str(report_path),
        "--markdown-output",
        str(markdown_path),
        "--scratch-root",
        str(tmp_path / "scratch"),
        "--watchdog-seconds",
        "30",
        "--_test-fail-after",
        failed_phase,
        cwd=tmp_path,
    )

    assert completed.returncode != 0
    report = benchmark_module.load_run_report(report_path)
    phase_index = _RUNNER_PHASES.index(failed_phase)
    assert report.status == "failed"
    assert report.failed_phase == failed_phase
    assert (
        tuple(phase.name for phase in report.phases)
        == _RUNNER_PHASES[: phase_index + 1]
    )
    assert all(
        phase.status in {"completed", "not_applicable"} for phase in report.phases[:-1]
    )
    assert report.phases[-1].status == "failed"
    benchmark_module.validate_report(report)
    assert failed_phase in benchmark_module.render_markdown_summary(report_path)
    assert markdown_path.exists()
    assert report.cleanup.complete
    assert report.cleanup.errors == ()
    assert report.scratch_path is not None
    assert report.socket_path is not None
    assert not pathlib.Path(report.scratch_path).exists()
    assert not pathlib.Path(report.socket_path).exists()


def test_worker_reports_the_exact_active_stabilization_boundary(
    benchmark_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """An unexpected lifecycle error must not be mislabeled as setup."""
    context = types.SimpleNamespace(
        setup_duration_ns=1,
        setup_metrics=None,
        activity_pane_ids=(),
    )

    async def fake_setup(*_args: t.Any, **_kwargs: t.Any) -> t.Any:
        return context

    async def fake_cleanup(_context: t.Any) -> t.Any:
        return benchmark_module.CleanupReport(
            True,
            processes_absent=True,
            socket_absent=True,
            scratch_absent=True,
        )

    def fail_stabilization(_context: t.Any) -> t.NoReturn:
        message = "injected stabilization boundary failure"
        raise RuntimeError(message)

    monkeypatch.setattr(benchmark_module, "setup_async", fake_setup)
    monkeypatch.setattr(benchmark_module, "cleanup_run", fake_cleanup)
    monkeypatch.setattr(benchmark_module, "release_activity_gate", fail_stabilization)
    decision = benchmark_module.GuardDecision(
        True,
        "ok",
        None,
        None,
        None,
        False,
        benchmark_module.HostSnapshot(),
    )

    report = asyncio.run(
        benchmark_module.run_worker(
            benchmark_module.Topology(1, 1, 1),
            lane=benchmark_module.EngineLane.SUBPROCESS,
            mode=benchmark_module.ExecutionMode.ASYNC,
            runs=1,
            warmup=0,
            seed=11,
            run_id="active-stabilization",
            scratch=tmp_path / "scratch",
            socket_path=tmp_path / "scratch" / "tmux.sock",
            checkpoint_path=tmp_path / "checkpoint.json",
            progress_path=tmp_path / "progress.jsonl",
            guard_decision=decision,
            original_guard_decision=decision,
            policy=benchmark_module.ResourcePolicy(),
        )
    )

    assert report.status == "failed"
    assert report.failed_phase == "stabilization"
    assert "injected stabilization boundary failure" in t.cast(str, report.error)


def test_cli_worker_reports_exact_not_applicable_control_boundary(
    tmp_path: pathlib.Path,
) -> None:
    """A non-applicable wait boundary cannot inherit the prior phase label."""
    report_path = tmp_path / "not-applicable-failure.json"

    completed = _run_cli(
        "run",
        "--shape",
        "1x1x1",
        "--lane",
        "subprocess",
        "--mode",
        "async",
        "--runs",
        "1",
        "--warmup",
        "0",
        "--output",
        str(report_path),
        "--scratch-root",
        str(tmp_path / "scratch"),
        "--watchdog-seconds",
        "30",
        "--_test-fail-after",
        "wait.control-stream",
        cwd=tmp_path,
    )

    assert completed.returncode != 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["failed_phase"] == "wait.control-stream"
    _assert_terminal_cleanup(payload)


def test_worker_drains_cleanup_through_repeated_cancellation(
    benchmark_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """Repeated cancellation must wait for durable cleanup and preserve payload."""

    async def exercise() -> None:
        activity_started = asyncio.Event()
        cleanup_started = asyncio.Event()
        release_cleanup = asyncio.Event()
        context = types.SimpleNamespace(
            setup_duration_ns=1,
            setup_metrics=None,
            activity_pane_ids=(),
        )

        async def fake_setup(*_args: t.Any, **_kwargs: t.Any) -> t.Any:
            return context

        async def block_activity(_context: t.Any) -> t.NoReturn:
            activity_started.set()
            await asyncio.Event().wait()
            message = "unreachable"
            raise AssertionError(message)

        async def delayed_cleanup(_context: t.Any) -> t.Any:
            cleanup_started.set()
            await release_cleanup.wait()
            return benchmark_module.CleanupReport(
                True,
                processes_absent=True,
                socket_absent=True,
                scratch_absent=True,
            )

        monkeypatch.setattr(benchmark_module, "setup_async", fake_setup)
        monkeypatch.setattr(benchmark_module, "release_activity_gate", lambda _ctx: 1)
        monkeypatch.setattr(benchmark_module, "verify_activity_async", block_activity)
        monkeypatch.setattr(benchmark_module, "cleanup_run", delayed_cleanup)
        decision = benchmark_module.GuardDecision(
            True,
            "ok",
            None,
            None,
            None,
            False,
            benchmark_module.HostSnapshot(),
        )
        checkpoint = tmp_path / "cancel-checkpoint.json"
        task = asyncio.create_task(
            benchmark_module.run_worker(
                benchmark_module.Topology(1, 1, 1),
                lane=benchmark_module.EngineLane.SUBPROCESS,
                mode=benchmark_module.ExecutionMode.ASYNC,
                runs=1,
                warmup=0,
                seed=11,
                run_id="worker-cancellation",
                scratch=tmp_path / "scratch",
                socket_path=tmp_path / "scratch" / "tmux.sock",
                checkpoint_path=checkpoint,
                progress_path=tmp_path / "cancel-progress.jsonl",
                guard_decision=decision,
                original_guard_decision=decision,
                policy=benchmark_module.ResourcePolicy(),
            ),
            name="worker-cancellation-test",
        )
        await activity_started.wait()
        task.cancel("original cancellation")
        await cleanup_started.wait()
        task.cancel("repeated cancellation")
        await asyncio.sleep(0)
        assert not task.done()
        release_cleanup.set()
        with pytest.raises(asyncio.CancelledError) as cancelled:
            await task
        assert isinstance(cancelled.value, asyncio.CancelledError)
        report = benchmark_module.load_run_report(checkpoint)
        assert report.status == "cutoff"
        assert report.failed_phase == "cancellation"
        assert "original cancellation" in t.cast(str, report.error)
        assert report.cleanup.complete
        assert not [
            pending
            for pending in asyncio.all_tasks()
            if pending is not asyncio.current_task() and not pending.done()
        ]

    asyncio.run(exercise())


def test_cli_runtime_cutoff_is_not_relaxed_by_force_extreme(
    tmp_path: pathlib.Path,
) -> None:
    """A predictive override must not turn a live memory cutoff into failure."""
    report_path = tmp_path / "runtime-cutoff.json"

    completed = _run_cli(
        "run",
        "--shape",
        "1x1x1",
        "--runs",
        "1",
        "--warmup",
        "0",
        "--output",
        str(report_path),
        "--scratch-root",
        str(tmp_path / "scratch"),
        "--memory-floor-bytes",
        str(10**18),
        "--force-extreme",
        "--watchdog-seconds",
        "30",
        cwd=tmp_path,
    )

    assert completed.returncode != 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "cutoff"
    assert payload["failed_phase"] == "memory_floor"
    assert payload["guard_decision"]["kind"] == "runtime_cutoff"
    assert payload["original_guard_decision"]["kind"] == "predictive_refusal"
    _assert_terminal_cleanup(payload)


def test_cli_cancellation_uses_supervisor_cleanup_contract(
    tmp_path: pathlib.Path,
) -> None:
    """SIGINT to the public supervisor must clean its isolated worker run."""
    report_path = tmp_path / "cancelled.json"
    process = _start_cli(
        "run",
        "--shape",
        "1x1x1",
        "--runs",
        "1",
        "--warmup",
        "0",
        "--output",
        str(report_path),
        "--scratch-root",
        str(tmp_path / "scratch"),
        "--watchdog-seconds",
        "30",
        "--cleanup-grace-seconds",
        "0.3",
        "--_test-stall-after",
        "setup",
        cwd=tmp_path,
    )
    stdout = stderr = ""
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            streams = tuple(tmp_path.glob("*.progress.jsonl"))
            if streams and '"checkpoint":"setup"' in streams[0].read_text(
                encoding="utf-8"
            ):
                break
            if process.poll() is not None:
                break
            time.sleep(0.02)
        else:
            pytest.fail("worker never reached the injected setup stall")
        assert process.poll() is None
        process.send_signal(signal.SIGINT)
        time.sleep(0.05)
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=20)
    finally:
        if process.poll() is None:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)

    assert process.returncode == 130, (stdout, stderr)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "cutoff"
    assert payload["failed_phase"] == "cancellation"
    assert "supervisor interrupted" in payload["error"]
    _assert_terminal_cleanup(payload)


@pytest.mark.parametrize(
    "start_failure", (KeyboardInterrupt("start"), RuntimeError("start"))
)
def test_finalizer_start_after_native_launch_executes_once_and_restores_mask(
    benchmark_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    start_failure: BaseException,
) -> None:
    """A post-launch start failure must never cause a second native launch."""
    real_thread = threading.Thread
    callback_started = threading.Event()
    release_callback = threading.Event()
    invocation_count = 0
    wrapper: t.Any = None
    prior_mask = frozenset({signal.SIGUSR1})
    mask_calls: list[tuple[int, frozenset[signal.Signals]]] = []

    def callback() -> str:
        nonlocal invocation_count
        invocation_count += 1
        callback_started.set()
        assert release_callback.wait(timeout=10.0)
        return "finished"

    def thread_factory(*, target: t.Callable[[], None], name: str) -> t.Any:
        nonlocal wrapper
        delegate = real_thread(target=target, name=name)
        start_calls = 0

        def start() -> None:
            nonlocal start_calls
            start_calls += 1
            if start_calls != 1:
                pytest.fail("finalizer attempted a second native launch")
            delegate.start()
            raise start_failure

        wrapper = types.SimpleNamespace(
            start=start,
            join=delegate.join,
            is_alive=delegate.is_alive,
            ident=None,
            start_calls=lambda: start_calls,
        )
        return wrapper

    def record_mask(
        how: int,
        signals: t.Iterable[signal.Signals],
    ) -> frozenset[signal.Signals]:
        mask_calls.append((how, frozenset(signals)))
        return prior_mask

    def release() -> None:
        assert callback_started.wait(timeout=10.0)
        release_callback.set()

    monkeypatch.setattr(benchmark_module.threading, "Thread", thread_factory)
    monkeypatch.setattr(benchmark_module.signal, "pthread_sigmask", record_mask)
    releaser = real_thread(target=release)
    releaser.start()
    try:
        if isinstance(start_failure, KeyboardInterrupt):
            result, interruption = benchmark_module._drain_finalizer_thread(callback)
            assert result == "finished"
            assert interruption is start_failure
        else:
            with pytest.raises(RuntimeError) as raised:
                benchmark_module._drain_finalizer_thread(callback)
            assert raised.value is start_failure
    finally:
        release_callback.set()
        releaser.join(timeout=5.0)

    assert invocation_count == 1
    assert wrapper is not None
    assert wrapper.start_calls() == 1
    assert not wrapper.is_alive()
    assert mask_calls == [
        (signal.SIG_BLOCK, frozenset({signal.SIGINT, signal.SIGTERM})),
        (signal.SIG_SETMASK, prior_mask),
    ]


def test_finalizer_drains_repeated_sigint_once_and_restores_real_mask(
    benchmark_module: types.ModuleType,
) -> None:
    """Repeated SIGINT cannot duplicate work or leave a finalizer thread alive."""
    callback_started = threading.Event()
    release_callback = threading.Event()
    invocation_count = 0
    original_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR1})
    expected_mask = frozenset((*original_mask, signal.SIGUSR1))

    def callback() -> int:
        nonlocal invocation_count
        invocation_count += 1
        callback_started.set()
        assert release_callback.wait(timeout=10.0)
        return 7

    def interrupt_twice() -> None:
        assert callback_started.wait(timeout=10.0)
        os.kill(os.getpid(), signal.SIGINT)
        time.sleep(0.05)
        os.kill(os.getpid(), signal.SIGINT)
        time.sleep(0.05)
        release_callback.set()

    interrupter = threading.Thread(target=interrupt_twice)
    interrupter.start()
    try:
        result, interruption = benchmark_module._drain_finalizer_thread(callback)
        observed_mask = signal.pthread_sigmask(signal.SIG_BLOCK, ())
    finally:
        release_callback.set()
        interrupter.join(timeout=5.0)
        signal.pthread_sigmask(signal.SIG_SETMASK, original_mask)

    assert result == 7
    assert interruption is not None
    assert invocation_count == 1
    assert not interrupter.is_alive()
    assert frozenset(observed_mask) == expected_mask
    assert not any(
        thread.name == "orchestration-finalization" and thread.is_alive()
        for thread in threading.enumerate()
    )


def test_supervisor_cancellation_during_final_report_write_is_durable(
    benchmark_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """An interrupt during the atomic terminal write must be reported afterward."""
    report_path = tmp_path / "final-write.json"
    markdown_path = tmp_path / "final-write.md"
    entered_write = threading.Event()
    release_write = threading.Event()
    real_write = benchmark_module.write_json_atomic

    def delayed_terminal_write(path: pathlib.Path, value: t.Any) -> None:
        if (
            path == report_path
            and isinstance(value, benchmark_module.RunReport)
            and value.status == "completed"
        ):
            entered_write.set()
            assert release_write.wait(timeout=20.0)
        real_write(path, value)

    monkeypatch.setattr(
        benchmark_module,
        "write_json_atomic",
        delayed_terminal_write,
    )

    def interrupt_final_write() -> None:
        assert entered_write.wait(timeout=30.0)
        os.kill(os.getpid(), signal.SIGINT)
        time.sleep(0.05)
        release_write.set()

    interrupter = threading.Thread(target=interrupt_final_write)
    interrupter.start()
    decision = benchmark_module.GuardDecision(
        True,
        "ok",
        None,
        None,
        None,
        False,
        benchmark_module.HostSnapshot(),
    )
    try:
        with pytest.raises(KeyboardInterrupt) as cancellation:
            benchmark_module.supervise_worker(
                benchmark_module.Topology(1, 1, 1),
                lane=benchmark_module.EngineLane.SUBPROCESS,
                mode=benchmark_module.ExecutionMode.SYNC,
                runs=1,
                warmup=0,
                seed=11,
                run_id="cancel-final-write",
                scratch=tmp_path / "scratch",
                socket_path=tmp_path / "scratch" / "tmux.sock",
                output=report_path,
                markdown_output=markdown_path,
                guard_decision=decision,
                original_guard_decision=decision,
                policy=benchmark_module.ResourcePolicy(),
                watchdog_s=30.0,
                cleanup_grace_s=0.3,
            )
    finally:
        release_write.set()
        interrupter.join(timeout=5.0)

    assert not interrupter.is_alive()
    durable = benchmark_module.load_run_report(report_path)
    assert isinstance(cancellation.value, KeyboardInterrupt)
    assert durable.status == "cutoff"
    assert durable.failed_phase == "cancellation"
    assert durable.cleanup.complete
    assert all(
        not benchmark_module.process_identity_matches(row) for row in durable.processes
    )
    assert "cutoff" in markdown_path.read_text(encoding="utf-8")


def test_supervisor_interrupt_before_popen_return_is_durable_and_reraised(
    benchmark_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """A Popen interruption with no child must still publish then re-raise."""
    interruption = KeyboardInterrupt("popen interruption")
    mask_calls: list[tuple[int, frozenset[signal.Signals]]] = []
    prior_mask = frozenset({signal.SIGUSR1})
    real_popen = benchmark_module.subprocess.Popen
    interrupted = False

    def record_mask(
        how: int,
        signals: t.Iterable[signal.Signals],
    ) -> frozenset[signal.Signals]:
        mask_calls.append((how, frozenset(signals)))
        return prior_mask

    def interrupt_popen(*args: t.Any, **kwargs: t.Any) -> t.Any:
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise interruption
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(benchmark_module.signal, "pthread_sigmask", record_mask)
    monkeypatch.setattr(benchmark_module.subprocess, "Popen", interrupt_popen)
    output = tmp_path / "popen-interrupt.json"
    markdown = tmp_path / "popen-interrupt.md"
    decision = benchmark_module.GuardDecision(
        True,
        "ok",
        None,
        None,
        None,
        False,
        benchmark_module.HostSnapshot(),
    )

    with pytest.raises(KeyboardInterrupt) as raised:
        benchmark_module.supervise_worker(
            benchmark_module.Topology(1, 1, 1),
            lane=benchmark_module.EngineLane.SUBPROCESS,
            mode=benchmark_module.ExecutionMode.SYNC,
            runs=1,
            warmup=0,
            seed=11,
            run_id="popen-interrupt",
            scratch=tmp_path / "scratch",
            socket_path=tmp_path / "scratch" / "tmux.sock",
            output=output,
            markdown_output=markdown,
            guard_decision=decision,
            original_guard_decision=decision,
            policy=benchmark_module.ResourcePolicy(),
            watchdog_s=30.0,
            cleanup_grace_s=0.3,
        )

    assert raised.value is interruption
    assert mask_calls == [
        (signal.SIG_BLOCK, frozenset({signal.SIGINT, signal.SIGTERM})),
        (signal.SIG_SETMASK, prior_mask),
        (signal.SIG_BLOCK, frozenset({signal.SIGINT, signal.SIGTERM})),
        (signal.SIG_SETMASK, prior_mask),
    ]
    durable = benchmark_module.load_run_report(output)
    assert durable.status == "cutoff"
    assert durable.failed_phase == "cancellation"
    assert durable.cleanup.complete
    assert durable.processes == ()
    assert not (tmp_path / "scratch").exists()


def test_supervisor_interrupt_during_pidfd_handoff_recovers_exact_worker(
    benchmark_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """Post-spawn interruption must retain a pidfd, recover, and restore the mask."""
    interruption = KeyboardInterrupt("handoff interruption")
    real_popen = benchmark_module.subprocess.Popen
    real_record = benchmark_module._record_process
    spawned: list[subprocess.Popen[bytes]] = []
    record_calls = 0
    mask_calls: list[tuple[int, frozenset[signal.Signals]]] = []
    prior_mask = frozenset({signal.SIGUSR2})

    def record_popen(*args: t.Any, **kwargs: t.Any) -> subprocess.Popen[bytes]:
        process = t.cast("subprocess.Popen[bytes]", real_popen(*args, **kwargs))
        spawned.append(process)
        return process

    def interrupt_record(role: str, pid: int) -> t.Any:
        nonlocal record_calls
        identity = real_record(role, pid)
        record_calls += 1
        if role == "worker" and record_calls == 1:
            raise interruption
        return identity

    def record_mask(
        how: int,
        signals: t.Iterable[signal.Signals],
    ) -> frozenset[signal.Signals]:
        mask_calls.append((how, frozenset(signals)))
        return prior_mask

    monkeypatch.setattr(benchmark_module.subprocess, "Popen", record_popen)
    monkeypatch.setattr(benchmark_module, "_record_process", interrupt_record)
    monkeypatch.setattr(benchmark_module.signal, "pthread_sigmask", record_mask)
    output = tmp_path / "handoff-interrupt.json"
    markdown = tmp_path / "handoff-interrupt.md"
    decision = benchmark_module.GuardDecision(
        True,
        "ok",
        None,
        None,
        None,
        False,
        benchmark_module.HostSnapshot(),
    )
    worker_absent_before_test_cleanup = False
    durable: t.Any = None
    try:
        with pytest.raises(KeyboardInterrupt) as raised:
            benchmark_module.supervise_worker(
                benchmark_module.Topology(1, 1, 1),
                lane=benchmark_module.EngineLane.SUBPROCESS,
                mode=benchmark_module.ExecutionMode.SYNC,
                runs=1,
                warmup=0,
                seed=11,
                run_id="handoff-interrupt",
                scratch=tmp_path / "scratch",
                socket_path=tmp_path / "scratch" / "tmux.sock",
                output=output,
                markdown_output=markdown,
                guard_decision=decision,
                original_guard_decision=decision,
                policy=benchmark_module.ResourcePolicy(),
                watchdog_s=30.0,
                cleanup_grace_s=0.3,
            )
        worker_absent_before_test_cleanup = all(
            process.poll() is not None for process in spawned
        )
        durable = benchmark_module.load_run_report(output)
    finally:
        for process in spawned:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5.0)

    assert raised.value is interruption
    assert worker_absent_before_test_cleanup
    assert record_calls >= 2
    assert mask_calls == [
        (signal.SIG_BLOCK, frozenset({signal.SIGINT, signal.SIGTERM})),
        (signal.SIG_SETMASK, prior_mask),
        (signal.SIG_BLOCK, frozenset({signal.SIGINT, signal.SIGTERM})),
        (signal.SIG_SETMASK, prior_mask),
    ]
    assert durable is not None
    assert durable.status == "cutoff"
    assert durable.failed_phase == "cancellation"
    assert durable.cleanup.complete
    assert all(
        not benchmark_module.process_identity_matches(row) for row in durable.processes
    )
    assert not (tmp_path / "scratch").exists()


def test_supervisor_restores_exact_prior_signal_mask_after_real_handoff(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
) -> None:
    """A successful real worker handoff restores every preexisting mask bit."""
    capability_error = benchmark_module._pidfd_capability_error()
    if capability_error is not None:
        pytest.skip(capability_error)
    original_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR1})
    expected_mask = frozenset((*original_mask, signal.SIGUSR1))
    output = tmp_path / "mask-restored.json"
    try:
        report = benchmark_module.run_scenario(
            benchmark_module.Topology(1, 1, 1),
            lane=benchmark_module.EngineLane.SUBPROCESS,
            mode=benchmark_module.ExecutionMode.SYNC,
            runs=1,
            warmup=0,
            output=output,
            scratch_root=tmp_path / "scratch",
            watchdog_s=30.0,
            cleanup_grace_s=0.3,
        )
        observed_mask = signal.pthread_sigmask(signal.SIG_BLOCK, ())
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, original_mask)

    assert report.status == "completed"
    assert frozenset(observed_mask) == expected_mask
    assert report.cleanup.complete
    assert report.scratch_path is not None
    assert not pathlib.Path(report.scratch_path).exists()


def test_supervisor_reraises_original_monitor_interrupt_after_recovery_interrupt(
    benchmark_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """Repeated interruption during recovery cannot replace the monitor object."""
    interruption = KeyboardInterrupt("monitor interruption")
    real_drain = benchmark_module._ProgressTracker.drain
    real_recover = benchmark_module._recover_supervised_run
    raised_monitor = False
    recovery_started = threading.Event()
    release_recovery = threading.Event()

    def interrupt_monitor(tracker: t.Any, *, terminal: bool = False) -> bool:
        nonlocal raised_monitor
        advanced = real_drain(tracker, terminal=terminal)
        if not terminal and advanced and not raised_monitor:
            raised_monitor = True
            raise interruption
        return t.cast(bool, advanced)

    def delayed_recovery(*args: t.Any, **kwargs: t.Any) -> t.Any:
        recovery_started.set()
        assert release_recovery.wait(timeout=20.0)
        return real_recover(*args, **kwargs)

    monkeypatch.setattr(benchmark_module._ProgressTracker, "drain", interrupt_monitor)
    monkeypatch.setattr(benchmark_module, "_recover_supervised_run", delayed_recovery)

    def interrupt_recovery() -> None:
        assert recovery_started.wait(timeout=20.0)
        os.kill(os.getpid(), signal.SIGINT)
        time.sleep(0.05)
        release_recovery.set()

    interrupter = threading.Thread(target=interrupt_recovery)
    interrupter.start()
    output = tmp_path / "monitor-interrupt.json"
    markdown = tmp_path / "monitor-interrupt.md"
    decision = benchmark_module.GuardDecision(
        True,
        "ok",
        None,
        None,
        None,
        False,
        benchmark_module.HostSnapshot(),
    )
    try:
        with pytest.raises(KeyboardInterrupt) as raised:
            benchmark_module.supervise_worker(
                benchmark_module.Topology(1, 1, 1),
                lane=benchmark_module.EngineLane.SUBPROCESS,
                mode=benchmark_module.ExecutionMode.SYNC,
                runs=1,
                warmup=0,
                seed=11,
                run_id="monitor-interrupt",
                scratch=tmp_path / "scratch",
                socket_path=tmp_path / "scratch" / "tmux.sock",
                output=output,
                markdown_output=markdown,
                guard_decision=decision,
                original_guard_decision=decision,
                policy=benchmark_module.ResourcePolicy(),
                watchdog_s=30.0,
                cleanup_grace_s=0.3,
                _test_stall_after="worker.started",
            )
    finally:
        release_recovery.set()
        interrupter.join(timeout=5.0)

    assert not interrupter.is_alive()
    assert raised.value is interruption
    durable = benchmark_module.load_run_report(output)
    assert durable.status == "cutoff"
    assert durable.failed_phase == "cancellation"
    assert durable.cleanup.complete
    assert all(
        not benchmark_module.process_identity_matches(row) for row in durable.processes
    )
    assert not (tmp_path / "scratch").exists()


def test_cli_process_identity_mismatch_never_signals_unrelated_pid(
    tmp_path: pathlib.Path,
) -> None:
    """A reused PID with another start time must remain outside recovery."""
    unrelated = subprocess.Popen(
        (sys.executable, "-c", "import time; time.sleep(60)"),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        start_time = _process_start_time(unrelated.pid)
        report_path = tmp_path / "identity.json"
        completed = _run_cli(
            "run",
            "--shape",
            "1x1x1",
            "--runs",
            "1",
            "--warmup",
            "0",
            "--output",
            str(report_path),
            "--scratch-root",
            str(tmp_path / "scratch"),
            "--watchdog-seconds",
            "0.2",
            "--cleanup-grace-seconds",
            "0.3",
            "--_test-extra-identity",
            f"unrelated:{unrelated.pid}:{start_time + 1}",
            "--_test-stall-after",
            "identity.unrelated",
            cwd=tmp_path,
        )

        assert completed.returncode != 0
        assert unrelated.poll() is None
        assert _process_start_time(unrelated.pid) == start_time
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        assert payload["status"] == "cutoff"
        assert any(
            row
            == {
                "role": "unrelated",
                "pid": unrelated.pid,
                "start_time": start_time + 1,
            }
            for row in payload["processes"]
        )
        _assert_terminal_cleanup(payload)
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)


def test_cli_ramp_refusal_marks_later_shapes_not_attempted(
    tmp_path: pathlib.Path,
) -> None:
    """A refused shape must stop the ramp and preserve one reason downstream."""
    report_path = tmp_path / "ramp-refused.json"
    markdown_path = tmp_path / "ramp-refused.md"
    host_path = tmp_path / "host.json"
    host_path.write_text(
        json.dumps(
            {
                "available_memory_bytes": 16 * 1024**3,
                "physical_memory_bytes": 32 * 1024**3,
                "memory_current_bytes": 1024,
                "memory_max_bytes": 32 * 1024**3,
                "pids_current": 10,
                "pids_max": 12,
                "nofile_soft_limit": 65536,
                "nofile_hard_limit": 65536,
                "memory_pressure_some_avg10": 0.0,
                "source_errors": {},
            }
        ),
        encoding="utf-8",
    )

    completed = _run_cli(
        "ramp",
        "--shapes",
        "1x1x1,2x2x2",
        "--runs",
        "1",
        "--warmup",
        "0",
        "--output",
        str(report_path),
        "--markdown-output",
        str(markdown_path),
        "--scratch-root",
        str(tmp_path / "scratch"),
        "--pid-reserve",
        "1",
        "--_test-host-snapshot",
        str(host_path),
        cwd=tmp_path,
    )

    assert completed.returncode != 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "refused"
    assert [step["status"] for step in payload["ramp"]] == [
        "refused",
        "not_attempted",
    ]
    assert payload["ramp"][0]["reason"] == payload["ramp"][1]["reason"]
    assert payload["ramp"][0]["run_id"] is not None
    assert payload["ramp"][0]["report_path"] is not None
    assert payload["ramp"][0]["scratch_path"] is None
    assert payload["ramp"][0]["socket_path"] is None
    assert payload["ramp"][1]["run_id"] is None
    assert payload["cleanup"]["complete"] is True
    assert not (tmp_path / "scratch").exists()
    assert "not_attempted" in markdown_path.read_text(encoding="utf-8")


def _write_completed_ramp_child(
    benchmark_module: types.ModuleType,
    shape: t.Any,
    output: pathlib.Path,
    ordinal: int,
    write: t.Callable[[pathlib.Path, t.Any], None],
) -> t.Any:
    """Write one complete fake child artifact while keeping aggregation real."""
    child = benchmark_module.RunReport(
        shape,
        observed_topology=shape,
        status="completed",
        cleanup=benchmark_module.CleanupReport(
            True,
            processes_absent=True,
            socket_absent=True,
            scratch_absent=True,
        ),
        run_id=f"child-{ordinal}",
        lane="control",
        mode="async",
        warmup=0,
        runs=1,
        scratch_path=f"scratch-{ordinal}",
        socket_path=f"scratch-{ordinal}/tmux.sock",
        progress_path=f"progress-{ordinal}.jsonl",
        environment=benchmark_module.EnvironmentReport(
            "3.10", None, 1, 11, ("run",), None
        ),
    )
    write(output, child)
    return child


def test_ramp_interrupt_before_child_finalizes_unattempted_suffix(
    benchmark_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """Pre-child interruption must still publish and validate a cutoff aggregate."""
    interruption = KeyboardInterrupt("before child")
    output = tmp_path / "before-child.json"
    markdown = output.with_suffix(".md")

    def interrupt_child(*_args: t.Any, **_kwargs: t.Any) -> t.NoReturn:
        raise interruption

    monkeypatch.setattr(benchmark_module, "run_scenario", interrupt_child)

    with pytest.raises(KeyboardInterrupt) as raised:
        benchmark_module.run_ramp(
            (
                benchmark_module.Topology(1, 1, 1),
                benchmark_module.Topology(2, 1, 1),
            ),
            runs=1,
            warmup=0,
            output=output,
            markdown_output=markdown,
        )

    assert raised.value is interruption
    report = benchmark_module.load_run_report(output)
    assert report.status == "cutoff"
    assert tuple(step.status for step in report.ramp) == (
        "not_attempted",
        "not_attempted",
    )
    assert report.error is not None
    assert all(step.reason == report.error for step in report.ramp)
    benchmark_module.validate_report(report)
    assert report.cleanup.complete
    assert markdown.exists()


def test_ramp_interrupt_between_child_return_and_step_mutation_preserves_child(
    benchmark_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """A durable completed child survives interruption before step bookkeeping."""
    interruption = KeyboardInterrupt("after child")
    output = tmp_path / "after-child.json"
    markdown = output.with_suffix(".md")
    real_write = benchmark_module.write_json_atomic

    class InterruptingChild:
        def __init__(self, child: t.Any) -> None:
            self.child = child
            self.interrupted = False

        @property
        def status(self) -> str:
            if not self.interrupted:
                self.interrupted = True
                raise interruption
            return t.cast(str, self.child.status)

        def __getattr__(self, name: str) -> t.Any:
            return getattr(self.child, name)

    def complete_then_interrupt(shape: t.Any, **kwargs: t.Any) -> t.Any:
        child = _write_completed_ramp_child(
            benchmark_module,
            shape,
            kwargs["output"],
            1,
            real_write,
        )
        return InterruptingChild(child)

    monkeypatch.setattr(benchmark_module, "run_scenario", complete_then_interrupt)

    with pytest.raises(KeyboardInterrupt) as raised:
        benchmark_module.run_ramp(
            (
                benchmark_module.Topology(1, 1, 1),
                benchmark_module.Topology(2, 1, 1),
            ),
            runs=1,
            warmup=0,
            output=output,
            markdown_output=markdown,
        )

    assert raised.value is interruption
    report = benchmark_module.load_run_report(output)
    assert report.status == "cutoff"
    assert tuple(step.status for step in report.ramp) == (
        "completed",
        "not_attempted",
    )
    assert report.ramp[1].reason == report.error
    benchmark_module.validate_report(report)
    assert report.cleanup.complete
    assert markdown.exists()


def test_ramp_interrupt_during_child_checkpoint_write_preserves_completed_prefix(
    benchmark_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """Every successful-child aggregate write is cancellation-shielded."""
    interruption = KeyboardInterrupt("child checkpoint write")
    output = tmp_path / "child-checkpoint.json"
    markdown = output.with_suffix(".md")
    real_write = benchmark_module.write_json_atomic
    child_ordinal = 0
    interrupted = False

    def complete_child(shape: t.Any, **kwargs: t.Any) -> t.Any:
        nonlocal child_ordinal
        child_ordinal += 1
        return _write_completed_ramp_child(
            benchmark_module,
            shape,
            kwargs["output"],
            child_ordinal,
            real_write,
        )

    def interrupt_checkpoint(path: pathlib.Path, value: t.Any) -> None:
        nonlocal interrupted
        if (
            not interrupted
            and path == output
            and isinstance(value, benchmark_module.RunReport)
            and value.status == "in_progress"
            and any(step.status == "completed" for step in value.ramp)
        ):
            interrupted = True
            raise interruption
        real_write(path, value)

    monkeypatch.setattr(benchmark_module, "run_scenario", complete_child)
    monkeypatch.setattr(benchmark_module, "write_json_atomic", interrupt_checkpoint)

    with pytest.raises(KeyboardInterrupt) as raised:
        benchmark_module.run_ramp(
            (
                benchmark_module.Topology(1, 1, 1),
                benchmark_module.Topology(2, 1, 1),
            ),
            runs=1,
            warmup=0,
            output=output,
            markdown_output=markdown,
        )

    assert raised.value is interruption
    report = benchmark_module.load_run_report(output)
    assert report.status == "cutoff"
    assert tuple(step.status for step in report.ramp) == (
        "completed",
        "not_attempted",
    )
    assert report.ramp[1].reason == report.error
    benchmark_module.validate_report(report)
    assert report.cleanup.complete
    assert markdown.exists()


def test_ramp_interrupt_after_last_child_preserves_every_completed_attempt(
    benchmark_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """Final-render interruption cannot relabel a completed child as cutoff."""
    interruption = KeyboardInterrupt("before final render")
    output = tmp_path / "before-render.json"
    markdown = output.with_suffix(".md")
    real_write = benchmark_module.write_json_atomic
    real_render = benchmark_module.render_markdown_summary
    child_ordinal = 0
    interrupted = False

    def complete_child(shape: t.Any, **kwargs: t.Any) -> t.Any:
        nonlocal child_ordinal
        child_ordinal += 1
        return _write_completed_ramp_child(
            benchmark_module,
            shape,
            kwargs["output"],
            child_ordinal,
            real_write,
        )

    def interrupt_render(
        report_path: pathlib.Path,
        output_path: pathlib.Path | None = None,
    ) -> str:
        nonlocal interrupted
        if not interrupted and report_path == output:
            interrupted = True
            raise interruption
        return t.cast(str, real_render(report_path, output_path))

    monkeypatch.setattr(benchmark_module, "run_scenario", complete_child)
    monkeypatch.setattr(benchmark_module, "render_markdown_summary", interrupt_render)

    with pytest.raises(KeyboardInterrupt) as raised:
        benchmark_module.run_ramp(
            (
                benchmark_module.Topology(1, 1, 1),
                benchmark_module.Topology(2, 1, 1),
            ),
            runs=1,
            warmup=0,
            output=output,
            markdown_output=markdown,
        )

    assert raised.value is interruption
    report = benchmark_module.load_run_report(output)
    assert report.status == "cutoff"
    assert tuple(step.status for step in report.ramp) == ("completed", "completed")
    benchmark_module.validate_report(report)
    assert report.cleanup.complete
    assert markdown.exists()


def test_ramp_cancellation_during_aggregation_is_durable(
    benchmark_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """Aggregation interrupted after child cleanup must publish a terminal ramp."""
    output = tmp_path / "ramp-cancel.json"
    markdown = tmp_path / "ramp-cancel.md"
    entered_write = threading.Event()
    release_write = threading.Event()
    real_write = benchmark_module.write_json_atomic
    next_run = 0

    def fake_run_scenario(shape: t.Any, **kwargs: t.Any) -> t.Any:
        nonlocal next_run
        next_run += 1
        child = benchmark_module.RunReport(
            shape,
            observed_topology=shape,
            status="completed",
            cleanup=benchmark_module.CleanupReport(
                True,
                processes_absent=True,
                socket_absent=True,
                scratch_absent=True,
            ),
            run_id=f"child-{next_run}",
            lane="control",
            mode="async",
            warmup=0,
            runs=1,
            scratch_path=f"scratch-{next_run}",
            socket_path=f"scratch-{next_run}/tmux.sock",
            progress_path=f"progress-{next_run}.jsonl",
            environment=benchmark_module.EnvironmentReport(
                "3.10", None, 1, 11, ("run",), None
            ),
        )
        real_write(kwargs["output"], child)
        return child

    def delayed_aggregate_write(path: pathlib.Path, value: t.Any) -> None:
        if (
            path == output
            and isinstance(value, benchmark_module.RunReport)
            and value.status == "completed"
        ):
            entered_write.set()
            assert release_write.wait(timeout=10.0)
        real_write(path, value)

    monkeypatch.setattr(benchmark_module, "run_scenario", fake_run_scenario)
    monkeypatch.setattr(
        benchmark_module,
        "write_json_atomic",
        delayed_aggregate_write,
    )

    def interrupt_aggregation() -> None:
        assert entered_write.wait(timeout=10.0)
        os.kill(os.getpid(), signal.SIGINT)
        time.sleep(0.05)
        release_write.set()

    interrupter = threading.Thread(target=interrupt_aggregation)
    interrupter.start()
    try:
        with pytest.raises(KeyboardInterrupt) as cancellation:
            benchmark_module.run_ramp(
                (
                    benchmark_module.Topology(1, 1, 1),
                    benchmark_module.Topology(2, 1, 1),
                ),
                runs=1,
                warmup=0,
                output=output,
                markdown_output=markdown,
            )
    finally:
        release_write.set()
        interrupter.join(timeout=5.0)

    assert isinstance(cancellation.value, KeyboardInterrupt)
    report = benchmark_module.load_run_report(output)
    assert report.status == "cutoff"
    assert tuple(step.status for step in report.ramp) == ("completed", "completed")
    assert report.cleanup.complete
    assert "cutoff" in markdown.read_text(encoding="utf-8")


def test_ramp_reraises_same_child_cancellation_after_durable_aggregation(
    benchmark_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """A child cancellation object survives ramp aggregation unchanged."""
    interruption = KeyboardInterrupt("child cancellation")
    output = tmp_path / "ramp-child-cancel.json"
    markdown = tmp_path / "ramp-child-cancel.md"
    child_output: pathlib.Path | None = None

    def cancel_child(shape: t.Any, **kwargs: t.Any) -> t.NoReturn:
        nonlocal child_output
        child_output = kwargs["output"]
        child = benchmark_module.RunReport(
            shape,
            status="cutoff",
            cleanup=benchmark_module.CleanupReport(
                True,
                processes_absent=True,
                socket_absent=True,
                scratch_absent=True,
            ),
            run_id="child-cancelled",
            lane="control",
            mode="async",
            warmup=0,
            runs=1,
            failed_phase="cancellation",
            error="KeyboardInterrupt: child cancellation",
            scratch_path="child-scratch",
            socket_path="child-scratch/tmux.sock",
            progress_path="child-progress.jsonl",
            environment=benchmark_module.EnvironmentReport(
                "3.10", None, 1, 11, ("run",), None
            ),
        )
        benchmark_module.write_json_atomic(child_output, child)
        raise interruption

    monkeypatch.setattr(benchmark_module, "run_scenario", cancel_child)

    with pytest.raises(KeyboardInterrupt) as raised:
        benchmark_module.run_ramp(
            (
                benchmark_module.Topology(1, 1, 1),
                benchmark_module.Topology(2, 1, 1),
            ),
            runs=1,
            warmup=0,
            output=output,
            markdown_output=markdown,
        )

    assert raised.value is interruption
    assert child_output is not None
    report = benchmark_module.load_run_report(output)
    assert report.status == "cutoff"
    assert tuple(step.status for step in report.ramp) == (
        "cutoff",
        "not_attempted",
    )
    assert report.ramp[0].reason == report.ramp[1].reason
    assert report.cleanup.complete


def test_cli_ramp_predictive_refusal_never_executes_tmux_binary(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Aggregate environment capture must not contact tmux before admission."""
    marker = tmp_path / "tmux-executed"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_tmux = fake_bin / "tmux"
    fake_tmux.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib\n"
        f"pathlib.Path({str(marker)!r}).touch()\n"
        "print('tmux fake')\n",
        encoding="utf-8",
    )
    fake_tmux.chmod(fake_tmux.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    host_path = tmp_path / "host.json"
    host_path.write_text(
        json.dumps(
            {
                "available_memory_bytes": 16 * 1024**3,
                "physical_memory_bytes": 32 * 1024**3,
                "memory_current_bytes": 1024,
                "memory_max_bytes": 32 * 1024**3,
                "pids_current": 10,
                "pids_max": 12,
                "nofile_soft_limit": 65536,
                "nofile_hard_limit": 65536,
                "memory_pressure_some_avg10": 0.0,
                "source_errors": {},
            }
        ),
        encoding="utf-8",
    )

    completed = _run_cli(
        "ramp",
        "--shapes",
        "1x1x1,2x2x2",
        "--runs",
        "1",
        "--warmup",
        "0",
        "--output",
        str(tmp_path / "ramp.json"),
        "--pid-reserve",
        "1",
        "--_test-host-snapshot",
        str(host_path),
        cwd=tmp_path,
    )

    assert completed.returncode != 0
    assert not marker.exists()


def test_cli_plan_is_a_real_read_only_subprocess(tmp_path: pathlib.Path) -> None:
    """Planning must print admission evidence without creating owned state."""
    completed = _run_cli("plan", "--shape", "2x2x2", cwd=tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert "Sessions" in completed.stdout
    assert "Windows" in completed.stdout
    assert "Panes" in completed.stdout
    assert "Allowed" in completed.stdout
    assert tuple(tmp_path.iterdir()) == ()


def test_markdown_renderer_refuses_invalid_json_evidence(
    benchmark_module: types.ModuleType,
    tmp_path: pathlib.Path,
) -> None:
    """Rendering must validate JSON before replacing an existing summary."""
    report_path = tmp_path / "invalid.json"
    markdown_path = tmp_path / "summary.md"
    report = completed_report(benchmark_module)
    benchmark_module.write_json_atomic(report_path, report)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["phases"][0]["summary"]["count"] = 99
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    markdown_path.write_text("retained\n", encoding="utf-8")

    with pytest.raises(ValueError, match="summary"):
        benchmark_module.render_markdown_summary(report_path, markdown_path)

    assert markdown_path.read_text(encoding="utf-8") == "retained\n"


def test_cli_help_hides_worker_and_private_test_harness_flags(
    tmp_path: pathlib.Path,
) -> None:
    """The worker protocol and injection hooks must not be public CLI surface."""
    root_help = _run_cli("--help", cwd=tmp_path)
    run_help = _run_cli("run", "--help", cwd=tmp_path)

    assert root_help.returncode == 0
    assert "_worker" not in root_help.stdout
    assert "_test" not in root_help.stdout
    assert run_help.returncode == 0
    assert "_test" not in run_help.stdout


@pytest.mark.parametrize(("lane", "mode"), _PHASE_LANES)
def test_cli_run_supports_all_four_engine_mode_lanes(
    tmp_path: pathlib.Path,
    lane: str,
    mode: str,
) -> None:
    """Every explicit engine/mode lane must execute the same phase graph."""
    report_path = tmp_path / f"{lane}-{mode}.json"

    completed = _run_cli(
        "run",
        "--shape",
        "2x2x2",
        "--lane",
        lane,
        "--mode",
        mode,
        "--runs",
        "3",
        "--warmup",
        "1",
        "--output",
        str(report_path),
        "--scratch-root",
        str(tmp_path / "scratch"),
        "--watchdog-seconds",
        "30",
        cwd=tmp_path,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "completed"
    assert (payload["lane"], payload["mode"]) == (lane, mode)
    phases = {phase["name"]: phase for phase in payload["phases"]}
    expected_control = (
        "completed" if (lane, mode) == ("control", "async") else ("not_applicable")
    )
    assert phases["wait.control-stream"]["status"] == expected_control
    assert phases["wait.capture-poll"]["status"] == "completed"
    for phase_name in _RUNNER_REPEATABLE_PHASES:
        assert len(phases[phase_name]["warmup_observations"]) == 1
        assert len(phases[phase_name]["samples"]) == 3
    if expected_control == "completed":
        assert len(phases["wait.control-stream"]["warmup_observations"]) == 1
        assert len(phases["wait.control-stream"]["samples"]) == 3
    _assert_terminal_cleanup(payload)


def test_cli_ramp_phase_failure_marks_later_shapes_not_attempted(
    tmp_path: pathlib.Path,
) -> None:
    """A worker failure must stop later ramp attempts after exact cleanup."""
    report_path = tmp_path / "ramp-failed.json"

    completed = _run_cli(
        "ramp",
        "--shapes",
        "1x1x1,2x1x1",
        "--runs",
        "1",
        "--warmup",
        "0",
        "--output",
        str(report_path),
        "--scratch-root",
        str(tmp_path / "scratch"),
        "--watchdog-seconds",
        "30",
        "--_test-fail-after",
        "setup",
        cwd=tmp_path,
    )

    assert completed.returncode != 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert [step["status"] for step in payload["ramp"]] == [
        "failed",
        "not_attempted",
    ]
    assert payload["ramp"][0]["reason"] == payload["ramp"][1]["reason"]
    child = json.loads(
        pathlib.Path(payload["ramp"][0]["report_path"]).read_text(encoding="utf-8")
    )
    assert child["failed_phase"] == "setup"
    _assert_terminal_cleanup(child)
    assert payload["cleanup"]["complete"] is True
