"""Tests for the engine latency benchmark."""

from __future__ import annotations

import importlib.util
import pathlib
import typing as t

import pytest

from libtmux.engines import ControlModeEngine, SubprocessEngine

if t.TYPE_CHECKING:
    import types

    from libtmux.session import Session

_BENCH = pathlib.Path(__file__).parents[3] / "scripts" / "bench"


@pytest.fixture(scope="module")
def engine_latency() -> types.ModuleType:
    """Load the benchmark by path; ``scripts`` is not a package."""
    spec = importlib.util.spec_from_file_location(
        "engine_latency", _BENCH / "engine_latency.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_control_mode_spawns_a_fixed_number_of_processes(
    engine_latency: types.ModuleType,
    session: Session,
) -> None:
    """The point of the benchmark: fork-per-command against one client."""
    server = session.server
    forked = engine_latency.measure(SubprocessEngine.for_server(server), 5)
    with ControlModeEngine.for_server(server) as control:
        persistent = engine_latency.measure(control, 5)

    assert forked["processes_spawned"] == forked["commands"] == 11
    assert persistent["processes_spawned"] == 2
    assert persistent["commands"] == 11
    assert persistent["display-message"]["median"] > 0
