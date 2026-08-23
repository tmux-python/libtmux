"""Tests for the current-API benchmark at the command execution seam."""

from __future__ import annotations

import importlib.util
import pathlib
import typing as t

import pytest

if t.TYPE_CHECKING:
    import types

    from libtmux.server import Server

_BENCH = pathlib.Path(__file__).parent.parent / "scripts" / "bench"


@pytest.fixture(scope="module")
def current_api() -> types.ModuleType:
    """Load the benchmark by path; ``scripts`` is not a package."""
    spec = importlib.util.spec_from_file_location(
        "current_api", _BENCH / "current_api.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_benchmark_reaches_tmux_without_the_experimental_package(
    current_api: types.ModuleType,
) -> None:
    """The baseline must measure what ships, not what is being proposed.

    A benchmark that quietly imported the experimental engines would report a
    number for the current API that the current API cannot produce.
    """
    source = (_BENCH / "current_api.py").read_text(encoding="utf-8")

    assert "libtmux.experimental" not in source
    assert "from libtmux.engines import" in source
    assert "from libtmux.server import Server" in source


def test_the_baseline_uses_the_shared_ruler(current_api: types.ModuleType) -> None:
    """Statistics come from bench_primitives, not a second implementation.

    Two benchmarks quoting different percentiles for the same samples would be
    worse than having no baseline at all.
    """
    summarised = current_api._ms([1_000_000, 2_000_000, 3_000_000])

    assert summarised["n"] == 3.0
    assert summarised["min"] == 1.0
    assert summarised["max"] == 3.0
    assert "p95" in summarised


def test_enumeration_counts_the_live_hierarchy(
    current_api: types.ModuleType, server: Server
) -> None:
    """The classic read returns the rows the topology actually has."""
    built = current_api.build_topology(server, sessions=2, shape="2x1")
    assert built["sessions"] == 2
    assert built["windows"] == 4

    measured = current_api.enumerate_classic(server, rounds=2)

    assert measured["rows"]["sessions"] == 2
    assert measured["rows"]["windows"] == 4
    assert measured["timings"]["panes"]["n"] == 2.0
    assert measured["timings"]["sessions"]["median"] > 0


def test_dispatch_separates_requests_from_the_commands_they_carry(
    current_api: types.ModuleType, server: Server
) -> None:
    """A command group is one dispatch carrying two tmux commands.

    This is the distinction the benchmark exists to keep visible: a change that
    moves work from requests into inlining is movement, not a saving, and the
    two counters are what make that legible.
    """
    current_api.build_topology(server, sessions=1, shape="1x1")

    measured = current_api.dispatch_through_seam(server, rounds=3)
    observed = measured["observed"]

    # three rounds, each running one plain request and one two-command group
    assert observed["requests"] == 6
    assert observed["tmux_commands"] == 9
    assert observed["inlined"] == 3
    assert observed["elapsed_ms"] > 0


def test_a_shape_smaller_than_one_is_refused(
    current_api: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty shape measures nothing, so it is rejected rather than run."""
    monkeypatch.setattr("sys.argv", ["current_api.py", "--sessions", "0"])

    with pytest.raises(SystemExit) as excinfo:
        current_api.main()

    assert excinfo.value.code == 2
