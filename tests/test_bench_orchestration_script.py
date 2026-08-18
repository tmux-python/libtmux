"""Behavioral checks for the orchestration benchmark's pure model."""

from __future__ import annotations

import asyncio
import dataclasses
import importlib.util
import json
import os
import pathlib
import signal
import stat
import subprocess
import sys
import types
import typing as t

import pytest

from libtmux.experimental.models import PaneSnapshot, SessionSnapshot, WindowSnapshot


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
        cleanup=benchmark_module.CleanupReport(complete=True),
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


@pytest.mark.parametrize("status", ("refused", "failed", "cutoff"))
def test_validate_report_requires_cleanup_for_terminal_status(
    benchmark_module: types.ModuleType, status: str
) -> None:
    """Terminal evidence is invalid if it leaves benchmark-owned state behind."""
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
        if path == target and not injected:
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
