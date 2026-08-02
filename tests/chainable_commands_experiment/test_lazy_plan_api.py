"""Tests for a Polars-style lazy command plan API."""

from __future__ import annotations

from typing_extensions import assert_type

from . import lazy_plan_api as api
from .shared import CommandCall


def test_lazy_plan_api_filters_selects_and_collects() -> None:
    """Lazy plans collect command rows only at the terminal boundary."""
    plan = api.LazyCommandPlan.from_calls(
        (
            api.PlannedCall("window", CommandCall("rename-window", ("work",))),
            api.PlannedCall("pane", CommandCall("capture-pane", ("-p",), target="%1")),
        ),
    )
    selected = plan.filter_scope("pane").select("name", "target")

    rows = selected.collect()

    assert_type(selected, api.LazyCommandPlan)
    assert rows == [api.CommandRow(name="capture-pane", target="%1")]


def test_lazy_plan_api_explains_optimization_boundary() -> None:
    """The demo exposes an explicit plan boundary before collection."""
    plan = api.LazyCommandPlan.from_calls(()).filter_scope("pane").select("name")

    optimized = plan.optimize()

    assert optimized.explain() == (
        "filter_scope=pane",
        "select=name",
    )
