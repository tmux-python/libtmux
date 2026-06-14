"""Tests for transparent auto-batch experiments."""

from __future__ import annotations

import pytest
from typing_extensions import assert_type

from . import auto_batch_api as api


def test_auto_batch_api_batches_self_returning_methods() -> None:
    """Self-returning methods can be batched without needing command output."""
    target = api.AutoBatchTarget()

    returned = target.rename_window("work").select_layout("even-horizontal")

    assert_type(returned, api.AutoBatchTarget)
    assert returned is target
    assert target.to_sequence().argv() == (
        "rename-window",
        "work",
        ";",
        "select-layout",
        "even-horizontal",
    )


def test_auto_batch_api_rejects_methods_that_need_deferred_output() -> None:
    """Transparent batching cannot satisfy immediate stdout access."""
    target = api.AutoBatchTarget()

    with pytest.raises(api.DeferredOutputUnavailable):
        target.show_option("@missing")

    assert target.to_sequence().argv() == ("show-option", "-gqv", "@missing")
