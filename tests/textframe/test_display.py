"""Tests for TextFrame.display() interactive viewer.

Note on MagicMock usage: These tests require MagicMock to create mock curses.window
objects with configurable return values and side effects. pytest's monkeypatch
fixture patches existing attributes but doesn't create mock objects with the
call tracking and behavior configuration needed for curses window simulation.
"""

from __future__ import annotations

import curses
import io
import os
import sys
import typing as t
import unittest.mock

import pytest

from libtmux.textframe import TextFrame


class ExitKeyCase(t.NamedTuple):
    """Test case for exit key handling."""

    id: str
    key: int | None
    side_effect: type[BaseException] | None = None


EXIT_KEY_CASES: tuple[ExitKeyCase, ...] = (
    ExitKeyCase(
        id="quit_on_q",
        key=ord("q"),
    ),
    ExitKeyCase(
        id="quit_on_escape",
        key=27,
    ),
    ExitKeyCase(
        id="quit_on_ctrl_c",
        key=None,
        side_effect=KeyboardInterrupt,
    ),
)


@pytest.fixture
def mock_curses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock curses module-level functions that require initscr()."""
    monkeypatch.setattr(curses, "curs_set", lambda x: None)
    monkeypatch.setattr(curses, "A_REVERSE", 0)


def test_display_raises_when_not_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify display() raises RuntimeError when stdout is not a TTY."""
    frame = TextFrame(content_width=10, content_height=2)
    frame.set_content(["hello", "world"])

    monkeypatch.setattr(sys, "stdout", io.StringIO())

    with pytest.raises(RuntimeError, match="interactive terminal"):
        frame.display()


def test_display_calls_curses_wrapper_when_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify display() calls curses.wrapper when stdout is a TTY."""
    frame = TextFrame(content_width=10, content_height=2)
    frame.set_content(["hello", "world"])

    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    mock_wrapper = unittest.mock.MagicMock()
    monkeypatch.setattr(curses, "wrapper", mock_wrapper)

    frame.display()
    mock_wrapper.assert_called_once()
    args = mock_wrapper.call_args[0]
    assert args[0].__name__ == "_curses_display"


@pytest.mark.parametrize("case", EXIT_KEY_CASES, ids=lambda c: c.id)
def test_curses_display_exit_keys(
    case: ExitKeyCase,
    mock_curses_env: None,
) -> None:
    """Verify viewer exits on various exit keys/events."""
    frame = TextFrame(content_width=10, content_height=2)
    frame.set_content(["hello", "world"])

    mock_stdscr = unittest.mock.MagicMock()

    if case.side_effect:
        mock_stdscr.getch.side_effect = case.side_effect
    else:
        mock_stdscr.getch.return_value = case.key

    # Should exit cleanly without error
    frame._curses_display(mock_stdscr)
    mock_stdscr.clear.assert_called()


def test_curses_display_scroll_navigation(mock_curses_env: None) -> None:
    """Verify scroll navigation works with arrow keys."""
    frame = TextFrame(content_width=10, content_height=10)
    frame.set_content([f"line {i}" for i in range(10)])

    mock_stdscr = unittest.mock.MagicMock()

    # Simulate: down arrow, then quit
    mock_stdscr.getch.side_effect = [curses.KEY_DOWN, ord("q")]

    frame._curses_display(mock_stdscr)

    # Verify multiple refresh cycles occurred (initial + after navigation)
    assert mock_stdscr.refresh.call_count >= 2


def test_curses_display_status_line(mock_curses_env: None) -> None:
    """Verify status line shows position and dimensions."""
    frame = TextFrame(content_width=10, content_height=2)
    frame.set_content(["hello", "world"])

    mock_stdscr = unittest.mock.MagicMock()
    mock_stdscr.getch.return_value = ord("q")

    frame._curses_display(mock_stdscr)

    # Find the addstr call that contains status info
    status_calls = [
        call
        for call in mock_stdscr.addstr.call_args_list
        if len(call[0]) >= 3 and "q:quit" in str(call[0][2])
    ]
    assert len(status_calls) > 0, "Status line should be displayed"


def test_curses_display_uses_shutil_terminal_size(
    mock_curses_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify terminal size is queried via shutil.get_terminal_size().

    This approach works reliably in tmux/multiplexers because it directly
    queries the terminal via ioctl(TIOCGWINSZ) on each loop iteration,
    rather than relying on curses KEY_RESIZE events.
    """
    frame = TextFrame(content_width=10, content_height=2)
    frame.set_content(["hello", "world"])

    mock_stdscr = unittest.mock.MagicMock()
    mock_stdscr.getch.return_value = ord("q")

    mock_get_size = unittest.mock.MagicMock(return_value=os.terminal_size((120, 40)))
    monkeypatch.setattr(
        "libtmux.textframe.core.shutil.get_terminal_size",
        mock_get_size,
    )

    frame._curses_display(mock_stdscr)
    mock_get_size.assert_called()
