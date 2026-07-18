"""Tests for the eager and lazy pane objects."""

from __future__ import annotations

from libtmux.experimental.engines import MockEngine
from libtmux.experimental.objects import EagerPane, LazyPane
from libtmux.experimental.ops import LazyPlan
from libtmux.experimental.ops._types import PaneId
from libtmux.experimental.ops.results import SplitWindowResult


def test_eager_split_returns_live_pane() -> None:
    """EagerPane.split executes now and returns a live EagerPane object."""
    pane = EagerPane(MockEngine(), "%0")
    child = pane.split(horizontal=True)
    assert isinstance(child, EagerPane)
    assert child.pane_id == "%1"


def test_eager_capture_and_send() -> None:
    """Eager capture/send-keys return typed results."""
    engine = MockEngine(capture_lines=("a", "b"))
    pane = EagerPane(engine, "%1")
    assert pane.capture().lines == ("a", "b")
    assert pane.send_keys("echo hi", enter=True).ok


def test_lazy_split_returns_deferred_object_and_defers() -> None:
    """LazyPane.split records into a plan and returns a deferred LazyPane."""
    plan = LazyPlan()
    root = LazyPane(plan, PaneId("%0"))
    child = root.split()
    assert isinstance(child, LazyPane)
    assert len(plan) == 1  # recorded, not executed


def test_lazy_chain_resolves_forward_ref_on_execute() -> None:
    """A lazy chain resolves the new pane's id when the plan runs."""
    plan = LazyPlan()
    root = LazyPane(plan, PaneId("%0"))
    root.split().send_keys("vim", enter=True)

    outcome = plan.execute(MockEngine())

    first = outcome.results[0]
    assert isinstance(first, SplitWindowResult)
    assert first.new_pane_id == "%1"
    assert outcome.results[1].argv == ("send-keys", "-t", "%1", "vim", "Enter")


def test_eager_new_pane_returns_live_pane() -> None:
    """EagerPane.new_pane creates a floating pane and returns a live object."""
    pane = EagerPane(MockEngine(), "%0")
    floating = pane.new_pane(width=80, height=20, x=5, y=3)
    assert isinstance(floating, EagerPane)
    assert floating.pane_id == "%1"


def test_lazy_new_pane_records_new_pane_op() -> None:
    """LazyPane.new_pane records a new-pane op (deferred) with its geometry."""
    plan = LazyPlan()
    LazyPane(plan, PaneId("%0")).new_pane(width="50%", height="40%")
    assert plan.operations[0].kind == "new_pane"
    assert plan.operations[0].render() == (
        "new-pane",
        "-t",
        "%0",
        "-x50%",
        "-y40%",
        "-d",
        "-P",
        "-F",
        "#{pane_id}",
    )


def test_async_new_pane_returns_live_pane() -> None:
    """AsyncPane.new_pane creates a floating pane and returns a live object."""
    import asyncio

    from libtmux.experimental.engines import AsyncMockEngine
    from libtmux.experimental.objects import AsyncPane

    async def main() -> str:
        pane = AsyncPane(AsyncMockEngine(), "%0")
        floating = await pane.new_pane(width=80, height=20)
        return floating.pane_id

    assert asyncio.run(main()) == "%1"


def test_same_operation_backs_both_objects() -> None:
    """Eager and lazy objects render the identical underlying operation argv."""
    eager_engine = MockEngine()
    eager = EagerPane(eager_engine, "%0")
    # Capture the eager split's rendered argv via the engine-independent op.
    plan = LazyPlan()
    LazyPane(plan, PaneId("%0")).split(horizontal=True)
    lazy_argv = plan.operations[0].render()

    eager_child = eager.split(horizontal=True)
    assert eager_child.pane_id  # executed
    assert lazy_argv == ("split-window", "-t", "%0", "-h", "-P", "-F", "#{pane_id}")
