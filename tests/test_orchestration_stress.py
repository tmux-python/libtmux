"""Behavioral checks for the orchestration pressure ladder."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import types

import pytest


@pytest.fixture()
def stress_module() -> types.ModuleType:
    """Load the standalone stress script without installing it."""
    script = pathlib.Path(__file__).parents[1] / "scripts" / "orchestration_stress.py"
    spec = importlib.util.spec_from_file_location("orchestration_stress", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_each_ladder_varies_exactly_one_dimension(
    stress_module: types.ModuleType,
) -> None:
    """A rung failure is only attributable when one dimension moved."""
    for axis, varying in (
        ("panes", "panes_per_window"),
        ("windows", "windows"),
        ("sessions", "sessions"),
    ):
        rungs = stress_module.ladder(axis)
        fixed = {"sessions", "windows", "panes_per_window"} - {varying}
        for attribute in fixed:
            observed = {getattr(rung, attribute) for rung in rungs}
            assert len(observed) == 1, f"{axis} ladder moved {attribute}"
        moving = [getattr(rung, varying) for rung in rungs]
        assert moving == sorted(moving)
        assert len(set(moving)) == len(moving)


def test_every_ladder_starts_from_the_same_base(
    stress_module: types.ModuleType,
) -> None:
    """Ladders must share a base so axes are comparable at equal pressure."""
    bases = {
        str(stress_module.ladder(axis)[0]) for axis in ("panes", "windows", "sessions")
    }

    assert bases == {"80x20x1"}


def test_ladders_escalate_pane_pressure(stress_module: types.ModuleType) -> None:
    """Each ladder must actually increase load, not merely change shape."""
    for axis in ("panes", "windows", "sessions"):
        panes = [rung.panes for rung in stress_module.ladder(axis)]
        assert panes == sorted(panes)
        assert panes[-1] > panes[0]


def test_watchdog_allowance_grows_with_the_rung(
    stress_module: types.ModuleType,
) -> None:
    """Every rung on a ladder gets at least as much slack as the one below it.

    The benchmark's own default is flat, and one control/async pass measured
    14.3s at 400 panes against 177.5s at 1600. A fixed allowance therefore
    reports the larger rung as stuck when it is only slower, which stops the
    ladder before it reaches anything real.
    """
    for axis in ("panes", "windows", "sessions"):
        allowances = [
            stress_module.watchdog_seconds(rung, 3600.0)
            for rung in stress_module.ladder(axis)
        ]
        assert allowances == sorted(allowances)
        assert allowances[-1] > allowances[0]
        assert min(allowances) > 120.0, "every rung beats the flat default"


def test_watchdog_allowance_never_outlives_the_rung_limit(
    stress_module: types.ModuleType,
) -> None:
    """A stuck rung is still killed by the hard per-rung limit."""
    biggest = max(stress_module.ladder("panes"), key=lambda rung: rung.panes)

    assert stress_module.watchdog_seconds(biggest, 90.0) == 90.0


def test_rung_passes_its_scaled_watchdog_to_the_benchmark(
    stress_module: types.ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """The allowance has to reach the child, not just be computable."""
    shape = stress_module.Shape(80, 20, 1)
    seen: list[tuple[str, ...]] = []

    class _Finished:
        returncode = 0

        def wait(self, timeout: float | None = None) -> int:
            return 0

    def record(command: tuple[str, ...], **kwargs: object) -> _Finished:
        seen.append(tuple(command))
        return _Finished()

    # Resolved rather than probed: child_interpreter() shells out itself, and
    # a Popen stub would otherwise intercept that probe instead of the rung.
    monkeypatch.setattr(stress_module, "child_interpreter", lambda: sys.executable)
    monkeypatch.setattr(stress_module.subprocess, "Popen", record)
    stress_module.run_rung(
        shape,
        lane="control",
        mode="async",
        evidence_root=tmp_path,
        timeout_s=900.0,
    )

    assert seen, "the benchmark was never invoked"
    command = seen[0]
    assert "--watchdog-seconds" in command
    passed = float(command[command.index("--watchdog-seconds") + 1])
    assert passed == stress_module.watchdog_seconds(shape, 900.0)
    assert passed > 120.0


def test_shape_supports_column_alignment(stress_module: types.ModuleType) -> None:
    """The reporting loop aligns shapes, which a bare dataclass rejects."""
    shape = stress_module.Shape(80, 20, 2)

    assert f"{shape:<10}|" == "80x20x2   |"
    assert f"{shape}" == "80x20x2"


def test_rung_outcome_reports_a_missing_artifact_rather_than_raising(
    stress_module: types.ModuleType, tmp_path: pathlib.Path
) -> None:
    """A rung killed before writing evidence must still be recordable."""
    outcome = stress_module.rung_outcome(tmp_path / "absent.json", 2)

    assert outcome["status"] == "no artifact"
    assert outcome["completed"] == 0


def test_render_stress_names_the_phase_that_surrendered(
    stress_module: types.ModuleType, tmp_path: pathlib.Path
) -> None:
    """The useful part of a failed rung is which phase stopped completing."""
    artifact = tmp_path / "report.json"
    artifact.write_text(
        json.dumps(
            {
                "status": "failed",
                "failed_phase": "stabilization",
                "phases": [{"name": "setup", "status": "completed"}],
            }
        ),
        encoding="utf-8",
    )
    outcome = stress_module.rung_outcome(artifact, 2)
    outcome.update({"axis": "panes", "shape": "80x20x4", "panes": 6400, "wall_s": 71.0})

    rendered = stress_module.render_stress([outcome])

    assert "stabilization" in rendered
    assert "80x20x4" in rendered
    assert "6400" in rendered
    assert "never the timing" in rendered
