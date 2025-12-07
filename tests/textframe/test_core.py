"""Integration tests for TextFrame Syrupy snapshot testing."""

from __future__ import annotations

import typing as t
from contextlib import nullcontext as does_not_raise

import pytest
from syrupy.assertion import SnapshotAssertion

from .core import ContentOverflowError, TextFrame

if t.TYPE_CHECKING:
    from collections.abc import Sequence


class Case(t.NamedTuple):
    """Test case definition for parametrized tests."""

    id: str
    width: int
    height: int
    lines: Sequence[str]
    expected_exception: type[BaseException] | None
    overflow_behavior: t.Literal["error", "truncate"] = "error"


CASES: tuple[Case, ...] = (
    Case(
        id="basic_success",
        width=10,
        height=2,
        lines=["hello", "world"],
        expected_exception=None,
    ),
    Case(
        id="overflow_width",
        width=10,
        height=2,
        lines=["this line is too long", "row 2", "row 3"],
        expected_exception=ContentOverflowError,
    ),
    Case(
        id="empty_frame",
        width=5,
        height=2,
        lines=[],
        expected_exception=None,
    ),
    Case(
        id="truncate_width",
        width=5,
        height=2,
        lines=["hello world", "foo"],
        expected_exception=None,
        overflow_behavior="truncate",
    ),
    Case(
        id="truncate_height",
        width=10,
        height=1,
        lines=["row 1", "row 2", "row 3"],
        expected_exception=None,
        overflow_behavior="truncate",
    ),
    Case(
        id="truncate_both",
        width=5,
        height=2,
        lines=["hello world", "foo bar baz", "extra row"],
        expected_exception=None,
        overflow_behavior="truncate",
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_frame_rendering(case: Case, snapshot: SnapshotAssertion) -> None:
    """Verify TextFrame rendering with Syrupy snapshot.

    Parameters
    ----------
    case : Case
        Test case with frame dimensions and content.
    snapshot : SnapshotAssertion
        Syrupy snapshot fixture configured with TextFrameExtension.
    """
    frame = TextFrame(
        content_width=case.width,
        content_height=case.height,
        overflow_behavior=case.overflow_behavior,
    )

    ctx: t.Any = (
        pytest.raises(case.expected_exception)
        if case.expected_exception
        else does_not_raise()
    )

    with ctx as exc_info:
        frame.set_content(case.lines)

    if case.expected_exception:
        # The Plugin detects the Exception type and renders the ASCII visual diff
        assert exc_info.value == snapshot
    else:
        # The Plugin detects the TextFrame type and renders the ASCII frame
        assert frame == snapshot


def test_nested_serialization(snapshot: SnapshotAssertion) -> None:
    """Verify that nested TextFrame objects serialize correctly.

    This demonstrates that the custom serializer works when TextFrame
    objects are inside collections (lists, dicts).

    Parameters
    ----------
    snapshot : SnapshotAssertion
        Syrupy snapshot fixture configured with TextFrameExtension.
    """
    f1 = TextFrame(content_width=5, content_height=1)
    f1.set_content(["one"])

    f2 = TextFrame(content_width=5, content_height=1)
    f2.set_content(["two"])

    # The serializer will find the frames inside this list and render them
    assert [f1, f2] == snapshot
