"""Tests for libtmux.test.screen."""

from __future__ import annotations

import operator
import textwrap
import typing as t

import pytest

from libtmux.test.screen import assert_screen, eventually, screen_diff

if t.TYPE_CHECKING:
    from libtmux.pane import Pane
    from libtmux.session import Session


class SequencePane:
    """Stand-in pane whose screen changes on each capture.

    A real pane needs wall-clock waits to change between captures; this one
    lets a test count captures and keep the retry loop instant.
    """

    def __init__(self, *screens: list[str]) -> None:
        self.screens = list(screens)
        self.captures = 0

    def capture_pane(self) -> list[str]:
        """Return the next screen, repeating the last."""
        self.captures += 1
        return self.screens[min(self.captures, len(self.screens)) - 1]


def static_pane(session: Session) -> Pane:
    """Return a pane showing two fixed lines."""
    pane = session.new_window(window_shell="printf 'hello\\nworld\\n'; cat").active_pane
    assert pane is not None
    assert eventually(pane, timeout=5) == "hello\nworld"
    return pane


def test_assert_screen_modes(session: Session) -> None:
    """Whole-screen, row, and contains checks pass against a real pane."""
    pane = static_pane(session)

    assert_screen(pane, "hello\nworld\n\n", timeout=0)
    assert_screen(pane, ["hello", "world"], timeout=0)
    assert_screen(pane, "world", row=1, timeout=0)
    assert_screen(pane, "o\nw", contains=True, timeout=0)
    assert_screen(pane, "", row=9, timeout=0)


def test_assert_screen_failure_carries_diff(session: Session) -> None:
    """A mismatch raises with a diff of the last capture."""
    pane = static_pane(session)

    with pytest.raises(AssertionError) as excinfo:
        assert_screen(pane, "hello\nthere", timeout=0)

    assert str(excinfo.value).splitlines() == [
        "the screen did not equal expected within 0s",
        "--- expected",
        "+++ actual",
        "  hello",
        "- there",
        "+ world",
    ]


def test_assert_screen_retries_until_match() -> None:
    """A screen that settles later passes; one that never does fails."""
    pane = SequencePane(["booting"], ["booting"], ["ready"])

    assert_screen(t.cast("Pane", pane), "ready", interval=0)

    assert pane.captures == 3

    stuck = SequencePane(["booting"])
    with pytest.raises(AssertionError, match="did not equal"):
        assert_screen(t.cast("Pane", stuck), "ready", timeout=0.05, interval=0)


def test_eventually_operators() -> None:
    """``==``, ``!=`` and ``in`` retry; each returns False once time is up."""
    pane = t.cast("Pane", SequencePane(["a"], ["b"]))
    assert eventually(pane, row=0, interval=0) != "a"

    pane = t.cast("Pane", SequencePane(["a"], ["a", "b"]))
    assert "b" in eventually(pane, interval=0)

    pane = t.cast("Pane", SequencePane(["x"]))
    waiting = eventually(pane, timeout=0, interval=0)
    assert operator.eq(waiting, "y") is False
    assert operator.ne(waiting, "x") is False
    assert "y" not in waiting


def test_screen_diff_shows_every_line() -> None:
    """The diff keeps matching lines, so a row's position is visible."""
    assert screen_diff("a\nb\nc", "a\nx\nc").splitlines() == [
        "--- expected",
        "+++ actual",
        "  a",
        "- b",
        "+ x",
        "  c",
    ]


def test_pytest_explains_matcher_failures(pytester: pytest.Pytester) -> None:
    """A failed ``eventually`` comparison reports a line diff under pytest."""
    pytester.makepyfile(
        textwrap.dedent(
            """
            from libtmux.test.screen import eventually

            def new_pane(session):
                return session.new_window(window_shell="echo hi; cat").active_pane

            def test_eq(session):
                assert eventually(new_pane(session), timeout=0.2) == "bye"

            def test_in(session):
                assert "bye" in eventually(new_pane(session), timeout=0.2)
            """,
        ),
    )

    result = pytester.runpytest()

    result.assert_outcomes(failed=2)
    result.stdout.fnmatch_lines(
        [
            "*screen did not equal expected within 0.2s*",
            "*- bye*",
            "*+ hi*",
            "*'bye' not found in screen within 0.2s*",
        ],
    )
