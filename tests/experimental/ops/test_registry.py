"""Tests for the operation registry."""

from __future__ import annotations

import pytest

from libtmux.experimental.ops import SplitWindow, registry
from libtmux.experimental.ops.exc import DuplicateOperation, UnknownOperation
from libtmux.experimental.ops.registry import OperationRegistry, OpSpec


def test_seed_operations_registered() -> None:
    """All seed operations are present in the default registry."""
    assert set(registry.kinds()) >= {
        "split_window",
        "capture_pane",
        "send_keys",
        "select_layout",
    }


def test_get_unknown_fails_closed() -> None:
    """Looking up an unregistered kind raises :class:`UnknownOperation`."""
    with pytest.raises(UnknownOperation, match="does_not_exist"):
        registry.get("does_not_exist")


def test_operation_lookup_returns_class() -> None:
    """``operation`` returns the registered class for a kind."""
    assert registry.operation("split_window") is SplitWindow


def test_spec_from_operation_reads_classvars() -> None:
    """An :class:`OpSpec` mirrors the operation's class variables."""
    spec = OpSpec.from_operation(SplitWindow)
    assert spec.kind == "split_window"
    assert spec.command == "split-window"
    assert spec.scope == "window"
    assert spec.result_cls is SplitWindow.result_cls
    assert spec.effects.creates == "pane"


def test_list_predicate_filters() -> None:
    """``list`` filters by a predicate and stays sorted by kind."""
    readonly = [
        spec.kind for spec in registry.list(lambda spec: spec.safety == "readonly")
    ]
    assert readonly == ["capture_pane", "list_panes", "list_sessions", "list_windows"]


def test_register_duplicate_fails_closed() -> None:
    """Registering an existing kind raises unless ``replace=True``."""
    local = OperationRegistry()
    local.register(SplitWindow)
    with pytest.raises(DuplicateOperation, match="split_window"):
        local.register(SplitWindow)
    local.register(SplitWindow, replace=True)
    assert "split_window" in local


def test_unregister() -> None:
    """Unregistering removes the kind; unregistering a missing kind raises."""
    local = OperationRegistry()
    local.register(SplitWindow)
    local.unregister("split_window")
    assert "split_window" not in local
    with pytest.raises(UnknownOperation):
        local.unregister("split_window")


def test_len_and_iter() -> None:
    """The default registry is sized and iterable in kind order."""
    assert len(registry) == len(registry.kinds())
    assert [spec.kind for spec in registry] == sorted(registry.kinds())
