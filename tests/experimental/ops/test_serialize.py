"""Tests for operation/result serialization round-trips."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.ops import (
    CapturePane,
    SelectLayout,
    SendKeys,
    SplitWindow,
)
from libtmux.experimental.ops._types import (
    ClientName,
    IndexRef,
    NameRef,
    PaneId,
    SessionId,
    Special,
    WindowId,
)
from libtmux.experimental.ops.exc import UnknownOperation
from libtmux.experimental.ops.serialize import (
    operation_from_dict,
    operation_to_dict,
    result_from_dict,
    result_to_dict,
    target_from_dict,
    target_to_dict,
)

if t.TYPE_CHECKING:
    from libtmux.experimental.ops._types import Target
    from libtmux.experimental.ops.operation import Operation

_OPERATIONS = [
    pytest.param(
        SplitWindow(
            target=PaneId("%1"),
            horizontal=True,
            start_directory="/tmp",
            environment={"FOO": "bar"},
        ),
        id="split_window-full",
    ),
    pytest.param(CapturePane(target=PaneId("%2"), start=0, end=10), id="capture_pane"),
    pytest.param(
        SendKeys(target=PaneId("%3"), keys="echo hi", enter=True),
        id="send_keys",
    ),
    pytest.param(
        SelectLayout(target=WindowId("@4"), layout="tiled"), id="select_layout"
    ),
    pytest.param(SplitWindow(), id="split_window-no-target"),
]


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_operation_round_trip(operation: Operation[t.Any]) -> None:
    """An operation survives a dict round-trip unchanged."""
    assert operation_from_dict(operation_to_dict(operation)) == operation


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_operation_dict_is_plain_data(operation: Operation[t.Any]) -> None:
    """A serialized operation holds only stable, JSON-friendly scalars."""
    data = operation_to_dict(operation)
    assert data["kind"] == operation.kind
    assert isinstance(data["target"], (dict, type(None)))


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_result_round_trip(operation: Operation[t.Any]) -> None:
    """A result (with its operation and payload) survives a dict round-trip."""
    result = operation.build_result(returncode=0, stdout=("%9",))
    assert result_from_dict(result_to_dict(result)) == result


@pytest.mark.parametrize(
    "target",
    [
        pytest.param(PaneId("%1"), id="pane"),
        pytest.param(WindowId("@1"), id="window"),
        pytest.param(SessionId("$1"), id="session"),
        pytest.param(ClientName("/dev/pts/1"), id="client"),
        pytest.param(NameRef("work", exact=True), id="name"),
        pytest.param(IndexRef(2, parent="$1"), id="index"),
        pytest.param(Special("{marked}"), id="special"),
    ],
)
def test_target_round_trip(target: Target) -> None:
    """Every target type survives a dict round-trip."""
    assert target_from_dict(target_to_dict(target)) == target


def test_target_none_round_trip() -> None:
    """A missing target round-trips as ``None``."""
    assert target_from_dict(target_to_dict(None)) is None


def test_from_dict_unknown_kind_fails_closed() -> None:
    """Reviving an unregistered kind raises :class:`UnknownOperation`."""
    with pytest.raises(UnknownOperation):
        operation_from_dict({"kind": "does_not_exist"})
