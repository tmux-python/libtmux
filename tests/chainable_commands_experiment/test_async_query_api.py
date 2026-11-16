"""Tests for a Piccolo-style async command query API."""

from __future__ import annotations

import asyncio

from typing_extensions import assert_type

from . import async_query_api as api


def test_async_query_api_runs_all_and_first() -> None:
    """Async query terminal methods mirror sync query ergonomics."""
    runner = api.AsyncPaneRunner(
        (
            api.AsyncPaneRow("%1", active=True),
            api.AsyncPaneRow("%2", active=False),
        ),
    )
    query = api.AsyncPaneQuery().where(active=True).limit(1)

    rows = asyncio.run(query.all(runner))
    first = asyncio.run(query.first(runner))

    assert_type(query, api.AsyncPaneQuery)
    assert rows == [api.AsyncPaneRow("%1", active=True)]
    assert first == api.AsyncPaneRow("%1", active=True)
