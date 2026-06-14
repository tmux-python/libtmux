"""Tests for an Ibis-style typed expression API."""

from __future__ import annotations

from typing_extensions import assert_type

from . import expression_api as api


def test_expression_api_compiles_typed_fields_and_predicates() -> None:
    """Expression trees compile before execution."""
    pane = api.PaneTable()
    expr = pane.where(pane.active.eq(True)).select(pane.id, pane.title)

    compiled = expr.compile()

    assert_type(expr, api.TableExpression)
    assert compiled.fields == ("pane_id", "pane_title")
    assert compiled.predicates == ("pane_active=True",)


def test_expression_api_executes_against_backend_rows() -> None:
    """A backend runner owns materialization."""
    pane = api.PaneTable()
    expr = pane.where(pane.active.eq(True)).select(pane.id)
    runner = api.ExpressionRunner(
        (
            {"pane_id": "%1", "pane_active": True},
            {"pane_id": "%2", "pane_active": False},
        ),
    )

    assert expr.execute(runner) == [{"pane_id": "%1"}]
