"""Tests for an explicit typed command-batch context API."""

from __future__ import annotations

from typing_extensions import assert_type

from . import context_api as api
from .shared import CommandCall, CommandSequence


def test_context_api_batches_typed_methods() -> None:
    """Context batching keeps completion on explicit batch methods."""
    with api.CommandBatch() as batch:
        call = batch.new_window(window_name="work")
        batch.split_window(horizontal=True, percentage=50)

    assert_type(call, CommandCall)
    assert_type(batch.to_sequence(), CommandSequence)
    assert batch.to_sequence().argv() == (
        "new-window",
        "-d",
        "-n",
        "work",
        ";",
        "split-window",
        "-h",
        "-p",
        "50",
    )
