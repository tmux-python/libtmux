"""Tests for a GraphQL-style nested tmux selection API."""

from __future__ import annotations

from typing_extensions import assert_type

from . import selection_api as api


def test_selection_api_compiles_explicit_depth() -> None:
    """Nested selection makes traversal depth explicit."""
    query = (
        api.TmuxSelection.server()
        .sessions()
        .windows()
        .panes()
        .fields("pane_id", "pane_title")
    )

    plan = query.compile()

    assert_type(query, api.SelectionQuery)
    assert plan.scopes == ("server", "session", "window", "pane")
    assert plan.fields == ("pane_id", "pane_title")


def test_selection_api_runner_materializes_payload() -> None:
    """The runner executes the compiled selection plan."""
    query = api.TmuxSelection.server().sessions().fields("session_id")
    runner = api.StaticSelectionRunner({"session_id": ("$1", "$2")})

    assert query.run(runner) == {"session_id": ("$1", "$2")}
