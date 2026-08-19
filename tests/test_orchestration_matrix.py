"""Behavioral checks for the orchestration matrix supervisor and renderer."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import types

import pytest


@pytest.fixture()
def matrix_module() -> types.ModuleType:
    """Load the standalone matrix script without installing it."""
    script = pathlib.Path(__file__).parents[1] / "scripts" / "orchestration_matrix.py"
    spec = importlib.util.spec_from_file_location("orchestration_matrix", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _cell_report(
    path: pathlib.Path,
    *,
    lane: str,
    mode: str,
    durations: dict[str, list[int]],
    status: str = "completed",
) -> None:
    """Write a minimal artifact carrying accepted samples for each phase."""
    phases = [
        {
            "name": name,
            "status": "completed",
            "samples": [
                {"duration_ns": value, "accepted": True, "verified": True}
                for value in values
            ],
            "observations": [],
            "warmup_observations": [],
        }
        for name, values in durations.items()
    ]
    path.write_text(
        json.dumps(
            {
                "status": status,
                "failed_phase": None,
                "lane": lane,
                "mode": mode,
                "requested_topology": {
                    "sessions": 80,
                    "windows_per_session": 20,
                    "panes_per_window": 1,
                },
                "phases": phases,
            }
        ),
        encoding="utf-8",
    )


def test_reportable_percentiles_track_sample_count(
    matrix_module: types.ModuleType,
) -> None:
    """A percentile is offered only when the sample count can resolve it."""
    assert matrix_module.reportable_percentiles(1) == ()
    assert matrix_module.reportable_percentiles(2) == ()
    assert matrix_module.reportable_percentiles(10) == (90,)
    assert matrix_module.reportable_percentiles(20) == (90, 95)
    assert matrix_module.reportable_percentiles(100) == (90, 95, 99)


def test_render_matrix_omits_percentiles_the_samples_cannot_support(
    matrix_module: types.ModuleType, tmp_path: pathlib.Path
) -> None:
    """Two samples must never render a p95 or p99 column."""
    root = tmp_path / "matrix"
    (root / "control-async").mkdir(parents=True)
    _cell_report(
        root / "control-async" / "report.json",
        lane="control",
        mode="async",
        durations={"capture.serial": [1_000_000, 2_000_000]},
    )

    rendered = matrix_module.render_matrix(root)

    assert "p95" not in rendered
    assert "p99" not in rendered
    assert "median" in rendered
    assert "2 timed samples" in rendered


def test_render_matrix_reports_per_phase_ratios_not_whole_iteration(
    matrix_module: types.ModuleType, tmp_path: pathlib.Path
) -> None:
    """A lane ratio must be attributable to a phase, not to a summed iteration.

    A whole-iteration ratio is dominated by whichever phase is most expensive,
    so the rendered comparison keys on individual phases and states the limit.
    """
    root = tmp_path / "matrix"
    for lane, mode, capture, mutation in (
        ("subprocess", "sync", 20_000_000_000, 750_000_000),
        ("control", "async", 12_000_000_000, 6_000_000),
    ):
        (root / f"{lane}-{mode}").mkdir(parents=True)
        _cell_report(
            root / f"{lane}-{mode}" / "report.json",
            lane=lane,
            mode=mode,
            durations={
                "capture.serial": [capture] * 10,
                "mutation.bulk": [mutation] * 10,
            },
        )

    rendered = matrix_module.render_matrix(root)

    assert "capture.serial" in rendered
    assert "mutation.bulk" in rendered
    # mutation.bulk is 125x, capture.serial is 1.7x; both must be visible
    # rather than collapsed into one summed-iteration number.
    assert "125.0x" in rendered
    assert "1.7x" in rendered
    assert "sum of timed phases" not in rendered.lower()


def test_render_matrix_marks_a_cell_that_did_not_complete(
    matrix_module: types.ModuleType, tmp_path: pathlib.Path
) -> None:
    """A failed cell must not silently contribute medians to the comparison."""
    root = tmp_path / "matrix"
    (root / "control-sync").mkdir(parents=True)
    _cell_report(
        root / "control-sync" / "report.json",
        lane="control",
        mode="sync",
        durations={"capture.serial": [5_000_000] * 10},
        status="failed",
    )

    rendered = matrix_module.render_matrix(root)

    assert "failed" in rendered.lower()
    assert "control/sync" in rendered
