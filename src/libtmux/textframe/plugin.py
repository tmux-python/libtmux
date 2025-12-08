"""Syrupy snapshot extension and pytest hooks for TextFrame.

This module provides:
- TextFrameExtension: A syrupy extension for .frame snapshot files
- pytest_assertrepr_compare: Rich assertion output for TextFrame comparisons
- textframe_snapshot: Pre-configured snapshot fixture

When installed via `pip install libtmux[textframe]`, this plugin is
auto-discovered by pytest through the pytest11 entry point.
"""

from __future__ import annotations

import difflib
import typing as t

import pytest
from syrupy.assertion import SnapshotAssertion
from syrupy.extensions.single_file import SingleFileSnapshotExtension, WriteMode

from libtmux.textframe.core import ContentOverflowError, TextFrame


class TextFrameExtension(SingleFileSnapshotExtension):
    """Single-file extension for TextFrame snapshots (.frame files).

    Each test snapshot is stored in its own .frame file, providing cleaner
    git diffs compared to the multi-snapshot .ambr format.

    Notes
    -----
    This extension serializes:
    - TextFrame objects → their render() output
    - ContentOverflowError → their overflow_visual attribute
    - Other types → str() representation
    """

    _write_mode = WriteMode.TEXT
    file_extension = "frame"

    def serialize(
        self,
        data: t.Any,
        *,
        exclude: t.Any = None,
        include: t.Any = None,
        matcher: t.Any = None,
    ) -> str:
        """Serialize data to ASCII frame representation.

        Parameters
        ----------
        data : Any
            The data to serialize.
        exclude : Any
            Properties to exclude (unused for TextFrame).
        include : Any
            Properties to include (unused for TextFrame).
        matcher : Any
            Custom matcher (unused for TextFrame).

        Returns
        -------
        str
            ASCII representation of the data.
        """
        if isinstance(data, TextFrame):
            return data.render()
        if isinstance(data, ContentOverflowError):
            return data.overflow_visual
        return str(data)


# pytest hooks (auto-discovered via pytest11 entry point)


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
        lines.extend(difflib.ndiff(right_render, left_render))

    return lines


@pytest.fixture
def textframe_snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Snapshot fixture configured with TextFrameExtension.

    This fixture is auto-discovered when libtmux[textframe] is installed.
    It provides a pre-configured snapshot for TextFrame objects.

    Parameters
    ----------
    snapshot : SnapshotAssertion
        The default syrupy snapshot fixture.

    Returns
    -------
    SnapshotAssertion
        Snapshot configured with TextFrame serialization.

    Examples
    --------
    >>> def test_my_frame(textframe_snapshot):
    ...     frame = TextFrame(content_width=10, content_height=2)
    ...     frame.set_content(["hello", "world"])
    ...     assert frame == textframe_snapshot
    """
    return snapshot.use_extension(TextFrameExtension)
