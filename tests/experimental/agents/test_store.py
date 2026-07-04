"""Tests for the durable store + reducer."""

from __future__ import annotations

import json
import pathlib
import typing as t

import pytest

from libtmux.experimental.agents.merge import Stamp
from libtmux.experimental.agents.state import AgentState
from libtmux.experimental.agents.store import (
    AgentStore,
    JsonFile,
    Observed,
    Vanished,
    apply,
)


def _observed(state: str, counter: int) -> Observed:
    """Create an Observed event with default values."""
    return Observed(
        pane_id="%1",
        key="%1",
        name="claude",
        state=AgentState.from_signal(state),
        stamp=Stamp(counter, "option"),
        source="option",
        pid=42,
    )


def test_apply_keeps_latest_and_ignores_stale() -> None:
    """Test that stale updates don't override newer ones."""
    store = AgentStore()
    store = apply(store, _observed("running", 2), now=10.0)
    # a stale (lower-counter) update must not clobber the fresher one
    store = apply(store, _observed("idle", 1), now=11.0)
    assert store.agents["%1"].state is AgentState.RUNNING


def test_apply_advances_on_newer() -> None:
    """Test that newer updates advance the agent state."""
    store = AgentStore()
    store = apply(store, _observed("running", 1), now=10.0)
    store = apply(store, _observed("awaiting_input", 2), now=11.0)
    assert store.agents["%1"].state is AgentState.AWAITING_INPUT


def test_vanished_marks_exited() -> None:
    """Test that a vanished pane marks the agent as exited."""
    store = AgentStore()
    store = apply(store, _observed("running", 1), now=10.0)
    store = apply(store, Vanished(pane_id="%1"), now=12.0)
    assert store.agents["%1"].state is AgentState.EXITED
    assert store.agents["%1"].alive is False


def test_jsonfile_atomic_roundtrip(tmp_path: pathlib.Path) -> None:
    """Test that JsonFile saves and loads atomically without leaving temp files."""
    store = AgentStore()
    store = apply(store, _observed("running", 1), now=10.0)
    sink = JsonFile(tmp_path / "agents.json")
    sink.save(store.to_dict())
    # a partial temp file must never be left behind
    assert not list(tmp_path.glob("*.tmp"))
    loaded_data = sink.load()
    assert loaded_data is not None
    restored = AgentStore.from_dict(loaded_data)
    assert restored.agents["%1"].state is AgentState.RUNNING
    # the saved file is valid JSON
    assert json.loads((tmp_path / "agents.json").read_text())["agents"]


class StateCase(t.NamedTuple):
    """A persisted ``state`` string and the AgentState from_dict should yield."""

    test_id: str
    stored: str
    expected: AgentState


STATE_CASES = (
    StateCase("known_round_trips", "running", AgentState.RUNNING),
    StateCase("done_round_trips", "done", AgentState.DONE),
    StateCase("unknown_future_state", "paused", AgentState.UNKNOWN),
    StateCase("garbage", "???", AgentState.UNKNOWN),
)


@pytest.mark.parametrize("case", STATE_CASES, ids=[c.test_id for c in STATE_CASES])
def test_from_dict_tolerates_unknown_state(case: StateCase) -> None:
    """from_dict round-trips known states and degrades unknown ones to UNKNOWN.

    A store written by a newer version (a state the current enum lacks) must not
    crash the monitor on startup, so deserialization mirrors signal ingestion.
    """
    data = {
        "agents": {
            "%1": {
                "pane_id": "%1",
                "key": "%1",
                "name": "claude",
                "state": case.stored,
                "since": 1.0,
                "source": "option",
                "pid": 42,
                "alive": True,
            },
        },
        "stamps": {"%1": [1, "option"]},
    }
    store = AgentStore.from_dict(data)
    assert store.agents["%1"].state is case.expected
