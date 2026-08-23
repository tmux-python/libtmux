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
    script = (
        pathlib.Path(__file__).parents[1] / "scripts" / "orchestration" / "matrix.py"
    )
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


def test_defaults_are_the_combination_measured_to_fit_the_budget(
    matrix_module: types.ModuleType,
) -> None:
    """Running with no arguments must stay inside the outer-loop budget.

    A four-cell matrix is dominated by the subprocess lanes, whose per-iteration
    cost grows superlinearly with pane count: about 9 seconds at 800 panes
    against roughly 49 at 1,600. The defaults below were measured end to end at
    just under 24 minutes; raising either one pushes a plain invocation past an
    hour, which is why they are pinned rather than left to taste.
    """
    defaults = matrix_module.build_parser().parse_args([])

    assert defaults.shape == "40x20x1"
    assert matrix_module.pane_count(matrix_module.parse_shape(defaults.shape)) == 800
    assert defaults.runs == 20
    assert defaults.warmup == 2
    # Twenty samples is the point where p90 and p95 become reportable at all.
    assert matrix_module.reportable_percentiles(defaults.runs) == (90, 95)


def test_child_interpreter_refuses_and_names_the_remedy(
    matrix_module: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An interpreter without libtmux must be rejected before any child runs.

    Spawning from it produces a bare ModuleNotFoundError inside a child whose
    output nobody reads, so the supervisor checks first and says what to run
    instead.
    """
    system_python = "/usr/bin/python3"
    if not pathlib.Path(system_python).exists():
        pytest.skip("no system interpreter without libtmux available")
    monkeypatch.setattr(matrix_module.sys, "executable", system_python)
    # The probe is cached for the process; a stale entry would mask the guard.
    matrix_module.child_interpreter.cache_clear()

    with pytest.raises(SystemExit) as raised:
        matrix_module.child_interpreter()

    message = str(raised.value)
    assert "libtmux" in message
    assert "uv run python" in message, "the message must name the remedy"


def test_child_interpreter_accepts_an_interpreter_that_can_import(
    matrix_module: types.ModuleType,
) -> None:
    """The supported path must not pay for the guard with a false refusal."""
    assert matrix_module.child_interpreter() == matrix_module.sys.executable


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


def test_median_interval_widens_as_samples_shrink(
    matrix_module: types.ModuleType,
) -> None:
    """A noisy phase must report a wider interval than a steady one."""
    steady = [100.0] * 12
    noisy = [10.0, 200.0, 15.0, 180.0, 20.0, 190.0, 12.0, 175.0, 30.0, 160.0]

    steady_lo, steady_hi = matrix_module.median_interval(steady)
    noisy_lo, noisy_hi = matrix_module.median_interval(noisy)

    assert steady_hi - steady_lo == 0.0
    assert noisy_hi - noisy_lo > 50.0


def test_render_matrix_refuses_a_ratio_inside_the_noise(
    matrix_module: types.ModuleType, tmp_path: pathlib.Path
) -> None:
    """A difference smaller than run-to-run spread must not be claimed.

    Marginal per-phase ratios do not survive this benchmark's variance, so a
    spread whose confidence intervals overlap is reported as unresolved rather
    than as a number a reader would quote.
    """
    root = tmp_path / "matrix"
    # Two cells whose medians differ by ~10% but whose samples overlap heavily.
    noisy_a = [90, 110, 85, 115, 95, 105, 88, 112, 92, 108]
    noisy_b = [99, 121, 94, 127, 105, 116, 97, 123, 101, 119]
    for lane, mode, values in (
        ("subprocess", "sync", noisy_a),
        ("control", "async", noisy_b),
    ):
        (root / f"{lane}-{mode}").mkdir(parents=True)
        _cell_report(
            root / f"{lane}-{mode}" / "report.json",
            lane=lane,
            mode=mode,
            durations={"search.classic.panes.middle": [v * 1_000_000 for v in values]},
        )

    rendered = matrix_module.render_matrix(root)

    assert "unresolved" in rendered.lower()


def test_render_matrix_still_claims_a_ratio_far_outside_the_noise(
    matrix_module: types.ModuleType, tmp_path: pathlib.Path
) -> None:
    """A large, separated effect must still be reported as a ratio."""
    root = tmp_path / "matrix"
    for lane, mode, base in (
        ("subprocess", "sync", 700),
        ("control", "async", 5),
    ):
        (root / f"{lane}-{mode}").mkdir(parents=True)
        _cell_report(
            root / f"{lane}-{mode}" / "report.json",
            lane=lane,
            mode=mode,
            durations={
                "mutation.bulk": [(base + offset) * 1_000_000 for offset in range(10)]
            },
        )

    rendered = matrix_module.render_matrix(root)

    assert "mutation.bulk" in rendered
    assert "x" in rendered
    assert "unresolved" not in rendered.split("mutation.bulk")[1].split("\n")[0]


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
