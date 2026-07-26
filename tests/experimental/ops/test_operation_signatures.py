"""Tests for operation constructor capability boundaries."""

from __future__ import annotations

import inspect

import pytest

from libtmux.experimental.ops import registry
from libtmux.experimental.ops.registry import OpSpec

UNTARGETED_KINDS = frozenset(
    {
        "delete_buffer",
        "kill_server",
        "list_sessions",
        "save_buffer",
        "show_buffer",
        "start_server",
    },
)

SOURCE_TARGET_KINDS = frozenset(
    {
        "break_pane",
        "join_pane",
        "link_window",
        "move_pane",
        "move_window",
        "swap_pane",
        "swap_window",
    },
)


@pytest.mark.parametrize("spec", registry, ids=lambda spec: spec.kind)
def test_operation_signature_exposes_only_supported_targets(spec: OpSpec) -> None:
    """Constructor target fields match the tmux command's accepted flags."""
    parameters = inspect.signature(spec.operation_cls).parameters

    assert ("target" in parameters) is (spec.kind not in UNTARGETED_KINDS)
    assert ("src_target" in parameters) is (spec.kind in SOURCE_TARGET_KINDS)
