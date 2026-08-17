"""Behavioral checks for the hermetic engine benchmark script."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import textwrap

import pytest


def test_contract_scales_counts_across_sequential_sessions() -> None:
    """An SxWxP scenario counts every session without adding concurrency."""
    root = pathlib.Path(__file__).parents[1]
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)

    completed = subprocess.run(
        (
            "uv",
            "run",
            "scripts/bench_engines.py",
            "contract",
            "--shapes",
            "2x1x1",
        ),
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "2x1x1: 8 requests" in completed.stdout
    assert "plan 8->4 steps" in completed.stdout
    assert "workspace 8->4 steps" in completed.stdout


@pytest.mark.parametrize("scenario", ["0x1x1", "1x0x1", "1x1x0", "wat", "1x1x1x1"])
def test_contract_rejects_invalid_scenarios_without_a_traceback(scenario: str) -> None:
    """Invalid cardinality is a concise CLI usage error, not an internal crash."""
    root = pathlib.Path(__file__).parents[1]
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)

    completed = subprocess.run(
        (
            "uv",
            "run",
            "scripts/bench_engines.py",
            "contract",
            "--shapes",
            scenario,
        ),
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "Invalid value for --shapes" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_matrix_executes_and_reports_a_multi_session_sample(
    tmp_path: pathlib.Path,
) -> None:
    """A live matrix sample builds S sessions serially and reports SxWxP totals."""
    root = pathlib.Path(__file__).parents[1]
    output = tmp_path / "matrix.json"
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)

    completed = subprocess.run(
        (
            "uv",
            "run",
            "scripts/bench_engines.py",
            "matrix",
            "--shapes",
            "2x1x1",
            "--layers",
            "default",
            "--transports",
            "control_mode",
            "--modes",
            "async",
            "--runs",
            "1",
            "--warmup",
            "0",
            "--no-check",
            "--json-out",
            str(output),
        ),
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    rows = json.loads(output.read_text())
    assert len(rows) == 2
    assert {row["n"] for row in rows} == {1}
    assert all("n_ms" not in row for row in rows)
    assert {
        (
            row["scenario"],
            row["sessions"],
            row["windows_per_session"],
            row["panes_per_window"],
            row["total_windows"],
            row["total_panes"],
        )
        for row in rows
    } == {("2x1x1", 2, 1, 1, 2, 2)}
    generated = next(row for row in rows if row["layer"] == "default")
    assert generated["planner_steps_per_session"] == 2
    assert generated["planner_steps"] == 4
    assert generated["engine_calls_per_session"] == 2
    assert generated["engine_calls"] == 4
    assert generated["tmux_requests_per_session"] == 4
    assert generated["tmux_requests"] == 8
    assert generated["batch_sizes_per_session"] == [1, 3]
    assert generated["batch_sizes"] == [1, 3, 1, 3]


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_build_driver_rejects_a_failed_operation(mode: str) -> None:
    """A partial plan failure cannot be recorded as a successful timing sample."""
    root = pathlib.Path(__file__).parents[1]
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    source = textwrap.dedent(
        f"""
        import asyncio

        from libtmux.experimental.engines import (
            AsyncMockEngine,
            CommandResult,
            MockEngine,
        )
        from scripts import bench_engines as bench

        class FailingSync:
            def __init__(self):
                self.inner = MockEngine()

            def run(self, request):
                if request.subcommand == "set-option":
                    return CommandResult(
                        cmd=("tmux", *request.args),
                        stderr=("benchmark sentinel failure",),
                        returncode=1,
                    )
                return self.inner.run(request)

            def run_batch(self, requests):
                return [self.run(request) for request in requests]

        class FailingAsync:
            def __init__(self):
                self.inner = AsyncMockEngine()

            async def run(self, request):
                if request.subcommand == "set-option":
                    return CommandResult(
                        cmd=("tmux", *request.args),
                        stderr=("benchmark sentinel failure",),
                        returncode=1,
                    )
                return await self.inner.run(request)

            async def run_batch(self, requests):
                return [await self.run(request) for request in requests]

        if {mode!r} == "sync":
            bench.build_sync(bench.LAYERS["default"], FailingSync(), "fail", 1, 1)
        else:
            asyncio.run(
                bench.build_async(
                    bench.LAYERS["default"], FailingAsync(), "fail", 1, 1
                )
            )
        """
    )

    completed = subprocess.run(
        ("uv", "run", "--with", "typer", "python", "-c", source),
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "benchmark sentinel failure" in completed.stderr


def test_live_topology_verifier_rejects_a_partial_build() -> None:
    """A command-successful but incomplete tmux hierarchy is not a valid sample."""
    root = pathlib.Path(__file__).parents[1]
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    source = textwrap.dedent(
        """
        from scripts import bench_engines as bench

        server = bench.new_server()
        try:
            server.cmd("new-session", "-d", "-s", "partial", "-n", "w0")
            bench.verify_topology(server, ["partial"], windows=1, panes=2)
        finally:
            server.kill()
        """
    )

    completed = subprocess.run(
        ("uv", "run", "--with", "typer", "python", "-c", source),
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "partial: expected 2 panes, got 1" in completed.stderr


def test_benchmark_server_uses_an_empty_tmux_config() -> None:
    """A benchmark daemon cannot inherit geometry or options from user config."""
    root = pathlib.Path(__file__).parents[1]
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    source = textwrap.dedent(
        """
        import os

        from scripts import bench_engines as bench

        server = bench.new_server()
        try:
            assert server.config_file == os.devnull
            assert f"-f{os.devnull}" in server.connection.args
        finally:
            server.kill()
        """
    )

    completed = subprocess.run(
        ("uv", "run", "--with", "typer", "python", "-c", source),
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    ("option", "value"),
    [("--layers", "bogus"), ("--transports", "bogus"), ("--modes", "bogus")],
)
def test_matrix_rejects_unknown_axis_values(option: str, value: str) -> None:
    """A misspelled matrix axis cannot silently shrink the benchmark grid."""
    root = pathlib.Path(__file__).parents[1]
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)

    completed = subprocess.run(
        (
            "uv",
            "run",
            "scripts/bench_engines.py",
            "matrix",
            "--shapes",
            "1x1x1",
            option,
            value,
            "--runs",
            "1",
            "--warmup",
            "0",
            "--no-check",
        ),
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert f"Invalid value for {option}" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_cleanup_failure_is_rejected() -> None:
    """A failed session cleanup cannot contaminate later timing samples."""
    root = pathlib.Path(__file__).parents[1]
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    source = textwrap.dedent(
        """
        from scripts import bench_engines as bench

        server = bench.new_server()
        try:
            bench._kill_session(server, "missing-benchmark-session")
        finally:
            server.kill()
        """
    )

    completed = subprocess.run(
        ("uv", "run", "--with", "typer", "python", "-c", source),
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "benchmark verification command failed: kill-session" in completed.stderr
