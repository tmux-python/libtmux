"""Tests for the lazy plan and deferred-ref resolution."""

from __future__ import annotations

import asyncio

import pytest

from libtmux.experimental.engines import AsyncConcreteEngine, ConcreteEngine
from libtmux.experimental.ops import (
    LazyPlan,
    SendKeys,
    SplitWindow,
)
from libtmux.experimental.ops._types import PaneId, WindowId
from libtmux.experimental.ops.exc import OperationError


def test_plan_records_without_executing() -> None:
    """Building a plan touches no engine; it just records operations."""
    plan = LazyPlan()
    plan.add(SplitWindow(target=WindowId("@1")))
    plan.add(SendKeys(target=PaneId("%1"), keys="x"))
    assert len(plan) == 2
    assert [op.kind for op in plan] == ["split_window", "send_keys"]


def test_plan_resolves_forward_ref() -> None:
    """A later step can target the pane an earlier split creates."""
    plan = LazyPlan()
    pane = plan.add(SplitWindow(target=WindowId("@1")))
    plan.add(SendKeys(target=pane, keys="vim", enter=True))

    outcome = plan.execute(ConcreteEngine())

    assert outcome.bindings == {0: "%1"}
    assert outcome.results[1].argv == ("send-keys", "-t", "%1", "vim", "Enter")
    assert outcome.ok


def test_plan_aexecute_matches_execute() -> None:
    """The async driver resolves refs identically to the sync driver."""
    plan = LazyPlan()
    pane = plan.add(SplitWindow(target=WindowId("@1")))
    plan.add(SendKeys(target=pane, keys="vim", enter=True))

    outcome = asyncio.run(plan.aexecute(AsyncConcreteEngine()))

    assert outcome.bindings == {0: "%1"}
    assert outcome.results[1].argv == ("send-keys", "-t", "%1", "vim", "Enter")


def test_plan_serialization_round_trip() -> None:
    """A plan (including its SlotRef targets) survives a list round-trip."""
    plan = LazyPlan()
    pane = plan.add(SplitWindow(target=WindowId("@1")))
    plan.add(SendKeys(target=pane, keys="x"))

    revived = LazyPlan.from_list(plan.to_list())

    assert revived.operations == plan.operations


def test_plan_unresolvable_ref_fails_closed() -> None:
    """Targeting a step that creates nothing raises a clear error."""
    plan = LazyPlan()
    typed = plan.add(SendKeys(target=PaneId("%1"), keys="x"))  # creates no id
    plan.add(SendKeys(target=typed, keys="y"))
    with pytest.raises(OperationError, match="no captured id"):
        plan.execute(ConcreteEngine())
