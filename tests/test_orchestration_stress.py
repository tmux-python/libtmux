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
