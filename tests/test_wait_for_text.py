"""Tests for :meth:`libtmux.pane.Pane.wait_for_text` and ``wait_for_idle``.

Covers the anchor contract (only rows written after it match, and never the
echo of the command that produced them), the loss contract (a destroyed
anchor is reported, not hidden), and the timeout contract (every tmux read is
bounded and an unmet condition raises :exc:`~libtmux.exc.WaitTimeout`).
"""

from __future__ import annotations

import time
import typing as t

import pytest

from libtmux import exc
from libtmux.pane import Pane
from tests.test_capture_since import (
    _pane_with_history_limit,
    quiesce,
    run_and_wait,
)

if t.TYPE_CHECKING:
    from libtmux.session import Session


def test_matches_the_output_row_not_the_echoed_command(session: Session) -> None:
    """The text is in the command and in its output; only the output matches."""
    pane = session.new_window(window_name="wait_text_echo").active_pane
    assert pane is not None
    run_and_wait(pane, "true")
    quiesce(pane)
    start = pane.capture_since().cursor

    pane.send_keys("echo WAIT_TEXT_ECHO_MARK", enter=True)
    hit = pane.wait_for_text("WAIT_TEXT_ECHO_MARK", since=start, timeout=5)

    assert hit.match.string == "WAIT_TEXT_ECHO_MARK"
    assert hit.lines_missed is False


def test_text_already_on_screen_does_not_match(session: Session) -> None:
    """Rows written before the call are not searched."""
    pane = session.new_window(window_name="wait_text_old").active_pane
    assert pane is not None
    run_and_wait(pane, "echo WAIT_TEXT_OLD_MARK")
    quiesce(pane)

    with pytest.raises(exc.WaitTimeout):
        pane.wait_for_text("WAIT_TEXT_OLD_MARK", timeout=0.3)


def test_matches_output_that_lands_on_a_blank_anchor_row(session: Session) -> None:
    """Output printed on the row the cursor sat on is output, not an echo."""
    pane = session.new_window(
        window_name="wait_text_blank",
        window_shell="stty -echo; read line; echo WAIT_TEXT_BLANK_MARK; sleep 30",
    ).active_pane
    assert pane is not None
    start = pane.capture_since().cursor

    pane.send_keys("", enter=True)
    hit = pane.wait_for_text("WAIT_TEXT_BLANK_MARK", since=start, timeout=5)

    assert hit.match.string == "WAIT_TEXT_BLANK_MARK"


def test_a_missing_text_raises_wait_timeout(session: Session) -> None:
    """An unmet condition raises ``WaitTimeout`` after about ``timeout``."""
    pane = session.new_window(window_name="wait_text_timeout").active_pane
    assert pane is not None
    quiesce(pane)

    started = time.monotonic()
    with pytest.raises(exc.WaitTimeout, match="WAIT_TEXT_NEVER"):
        pane.wait_for_text("WAIT_TEXT_NEVER", timeout=0.3)

    assert time.monotonic() - started < 2


def test_reports_lines_missed_when_a_flood_destroys_the_anchor(
    session: Session,
) -> None:
    """A match found after the anchor was lost says so."""
    pane = _pane_with_history_limit(session, "wait_text_flood", 100)
    run_and_wait(pane, "seq 1 150")
    quiesce(pane)
    start = pane.capture_since().cursor

    pane.send_keys("seq 1000 3000; printf '%s%s\\n' FLOOD_ END", enter=True)
    hit = pane.wait_for_text("FLOOD_END", since=start, timeout=10)

    assert hit.lines_missed is True


def test_every_tmux_read_in_a_wait_is_bounded(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wedged tmux must hit ``TmuxTimeout``, so no read may be unbounded."""
    pane = session.new_window(window_name="wait_text_bounded").active_pane
    assert pane is not None
    run_and_wait(pane, "true")
    quiesce(pane)
    start = pane.capture_since().cursor
    pane.send_keys("printf '%s%s\\n' WAIT_TEXT_ BOUNDED", enter=True)

    seen: list[float | None] = []
    real_cmd = Pane.cmd

    def recording_cmd(self: Pane, *args: t.Any, **kwargs: t.Any) -> t.Any:
        seen.append(kwargs.get("timeout"))
        return real_cmd(self, *args, **kwargs)

    monkeypatch.setattr(Pane, "cmd", recording_cmd)
    pane.wait_for_text("WAIT_TEXT_BOUNDED", since=start, timeout=5)

    assert seen
    assert None not in seen


def test_wait_for_idle_returns_the_output_once_the_screen_settles(
    session: Session,
) -> None:
    """The wait outlasts gaps shorter than ``quiet`` and collects the output."""
    pane = session.new_window(window_name="wait_idle").active_pane
    assert pane is not None
    run_and_wait(pane, "true")
    quiesce(pane)
    start = pane.capture_since().cursor

    pane.send_keys(
        "for i in 1 2 3 4; do echo WAIT_IDLE_$i; sleep 0.1; done",
        enter=True,
    )
    settled = pane.wait_for_idle(quiet=0.4, since=start, timeout=10)

    assert any(line == "WAIT_IDLE_4" for line in settled.lines)


def test_wait_for_idle_times_out_on_a_screen_that_keeps_changing(
    session: Session,
) -> None:
    """A pane that never holds still raises ``WaitTimeout``."""
    pane = session.new_window(window_name="wait_idle_busy").active_pane
    assert pane is not None
    pane.send_keys("while true; do date +%N; sleep 0.05; done", enter=True)

    with pytest.raises(exc.WaitTimeout, match="quiet"):
        pane.wait_for_idle(quiet=0.4, timeout=0.8)
