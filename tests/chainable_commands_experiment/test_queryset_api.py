"""Tests for a Django QuerySet-style lazy command query API."""

from __future__ import annotations

from typing_extensions import assert_type

from . import queryset_api as api


def test_queryset_api_filters_orders_and_limits_lazily() -> None:
    """Pane queries stack filters until terminal evaluation."""
    rows = (
        api.PaneRow("%2", pane_index=2, active=True, title="shell"),
        api.PaneRow("%1", pane_index=1, active=True, title="editor"),
        api.PaneRow("%3", pane_index=3, active=False, title="logs"),
    )
    runner = api.StaticPaneRunner(rows)
    query = api.PaneQuery().filter(active=True).order_by("pane_index").limit(1)

    result = query.all(runner)

    assert_type(query, api.PaneQuery)
    assert_type(result, list[api.PaneRow])
    assert result == [rows[1]]
    assert query.first(runner) == rows[1]


def test_queryset_api_original_query_stays_unchanged() -> None:
    """Lazy query methods return new query objects."""
    query = api.PaneQuery()
    filtered = query.filter(active=False)

    assert query is not filtered
    assert filtered.all(api.StaticPaneRunner((api.PaneRow("%1", 1, False, "logs"),)))
