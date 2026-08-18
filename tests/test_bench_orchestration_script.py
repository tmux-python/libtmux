"""Behavioral checks for the orchestration benchmark's pure model."""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import pathlib
import subprocess
import sys
import types
import typing as t

import pytest


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
