"""Pytest configuration for TextFrame tests."""

from __future__ import annotations

import typing as t
from difflib import ndiff

import pytest
from syrupy.assertion import SnapshotAssertion

from libtmux.textframe import TextFrame

from .plugin import TextFrameExtension


def pytest_assertrepr_compare(
    config: pytest.Config,
    op: str,
    left: t.Any,
    right: t.Any,
) -> list[str] | None:
    """Provide rich assertion output for TextFrame comparisons.

    This hook provides detailed diff output when two TextFrame objects
    are compared with ==, showing dimension mismatches and content diffs.

    Parameters
    ----------
    config : pytest.Config
        The pytest configuration object.
    op : str
        The comparison operator (e.g., "==", "!=").
    left : Any
        The left operand of the comparison.
    right : Any
        The right operand of the comparison.

    Returns
    -------
    list[str] | None
        List of explanation lines, or None to use default behavior.
    """
    if not isinstance(left, TextFrame) or not isinstance(right, TextFrame):
        return None
    if op != "==":
        return None

    lines = ["TextFrame comparison failed:"]

    # Dimension mismatch
    if left.content_width != right.content_width:
        lines.append(f"  width: {left.content_width} != {right.content_width}")
    if left.content_height != right.content_height:
        lines.append(f"  height: {left.content_height} != {right.content_height}")

    # Content diff
    left_render = left.render().splitlines()
    right_render = right.render().splitlines()
    if left_render != right_render:
        lines.append("")
        lines.append("Content diff:")
        lines.extend(ndiff(right_render, left_render))

    return lines


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
