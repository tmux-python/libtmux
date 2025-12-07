"""Pytest configuration for TextFrame tests."""

from __future__ import annotations

import pytest
from syrupy.assertion import SnapshotAssertion

from libtmux.textframe import TextFrameExtension


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Override default snapshot fixture to use TextFrameExtension.

    Parameters
    ----------
    snapshot : SnapshotAssertion
        The default syrupy snapshot fixture.

    Returns
    -------
    SnapshotAssertion
        Snapshot configured with TextFrame serialization.
    """
    return snapshot.use_extension(TextFrameExtension)
