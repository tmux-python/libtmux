"""Engine-agnostic operation contract (runs offline via the mock engine).

These assertions hold for *any* engine because they are properties of the
operation executed through the engine: the result is the operation's typed
result class, its argv is the operation's render, and it serializes round-trip.
The mock engine lets the whole matrix run without a tmux server.
"""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.engines import MockEngine
from libtmux.experimental.ops import (
    CapturePane,
    SelectLayout,
    SendKeys,
    SplitWindow,
    result_from_dict,
    result_to_dict,
    run,
)
from libtmux.experimental.ops._types import PaneId, WindowId

if t.TYPE_CHECKING:
    from libtmux.experimental.ops.operation import Operation

_CONTRACT_OPS = [
    pytest.param(SplitWindow(target=WindowId("@1")), id="split_window"),
    pytest.param(CapturePane(target=PaneId("%1")), id="capture_pane"),
    pytest.param(SendKeys(target=PaneId("%1"), keys="echo hi"), id="send_keys"),
    pytest.param(
        SelectLayout(target=WindowId("@1"), layout="tiled"), id="select_layout"
    ),
]


@pytest.mark.parametrize("operation", _CONTRACT_OPS)
def test_result_type_matches_operation(operation: Operation[t.Any]) -> None:
    """An engine returns the operation's declared result type."""
    result = run(operation, MockEngine())
    assert type(result) is operation.result_cls


@pytest.mark.parametrize("operation", _CONTRACT_OPS)
def test_result_argv_is_render(operation: Operation[t.Any]) -> None:
    """The result's argv equals the operation's pure render."""
    result = run(operation, MockEngine())
    assert result.argv == operation.render()
    assert result.ok


@pytest.mark.parametrize("operation", _CONTRACT_OPS)
def test_result_serialization_round_trip(operation: Operation[t.Any]) -> None:
    """A result produced by an engine survives a dict round-trip."""
    result = run(operation, MockEngine())
    assert result_from_dict(result_to_dict(result)) == result


@pytest.mark.parametrize("operation", _CONTRACT_OPS)
def test_same_result_across_engine_instances(operation: Operation[t.Any]) -> None:
    """Two fresh engines yield equal typed results -- determinism contract."""
    first = run(operation, MockEngine())
    second = run(operation, MockEngine())
    assert first == second
