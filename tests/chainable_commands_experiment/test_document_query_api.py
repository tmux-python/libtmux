"""Tests for a Beanie-style document command query API."""

from __future__ import annotations

from typing_extensions import assert_type

from . import document_query_api as api


def test_document_query_api_filters_command_documents() -> None:
    """Document-shaped metadata supports simple typed filtering."""
    documents = (
        api.CommandDocument(name="capture-pane", scope="pane", chainable=True),
        api.CommandDocument(name="new-window", scope="session", chainable=True),
        api.CommandDocument(name="display-message", scope="server", chainable=False),
    )
    query = (
        api.CommandDocumentQuery(documents)
        .where(scope="pane", chainable=True)
        .where_name("capture-pane")
    )

    result = query.all()

    assert_type(query, api.CommandDocumentQuery)
    assert result == [documents[0]]
