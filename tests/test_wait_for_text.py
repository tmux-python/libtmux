"""Tests for :meth:`libtmux.pane.Pane.wait_for_text` and ``wait_for_idle``.

Covers the anchor contract (only rows written after it match, and never the
echo of the command that produced them), the loss contract (a destroyed
anchor is reported, not hidden), and the timeout contract (every tmux read is
bounded and an unmet condition raises :exc:`~libtmux.exc.WaitTimeout`).
"""

from __future__ import annotations

import collections
import threading
import time
import typing as t

import pytest

from libtmux import capture, exc
from libtmux.common import has_gte_version
from libtmux.pane import Pane
from libtmux.test.retry import retry_until
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


def test_a_stop_pattern_ends_the_wait_early_with_a_stopped_outcome(
    session: Session,
) -> None:
    """A failure marker returns at once, naming the ``stop`` that hit."""
    pane = _quiet_pane(session, "wait_text_stop")
    start = pane.capture_since().cursor

    pane.send_keys("echo WAIT_STOP_FAIL_MARK", enter=True)
    started = time.monotonic()
    hit = pane.wait_for_text(
        "WAIT_STOP_NEVER",
        stop=["WAIT_STOP_OTHER", "WAIT_STOP_FAIL_MARK"],
        since=start,
        timeout=30,
    )

    assert time.monotonic() - started < 10
    assert hit.outcome == "stopped"
    assert hit.stop_index == 1
    assert hit.match.string == "WAIT_STOP_FAIL_MARK"


def test_a_pattern_hit_reports_matched_and_no_stop_index(session: Session) -> None:
    """Without a ``stop`` hit the outcome stays ``matched``."""
    pane = _quiet_pane(session, "wait_text_matched")
    start = pane.capture_since().cursor

    pane.send_keys("echo WAIT_MATCHED_MARK", enter=True)
    hit = pane.wait_for_text(
        "WAIT_MATCHED_MARK", stop="WAIT_MATCHED_NEVER", since=start, timeout=5
    )

    assert hit.outcome == "matched"
    assert hit.stop_index is None
    assert hit.alternate_screen is False


def test_stop_wins_when_one_read_holds_both_a_stop_and_a_pattern_row(
    session: Session,
) -> None:
    """A broad ``pattern`` must not swallow a failure row read beside it."""
    pane = _quiet_pane(session, "wait_text_tie")
    start = pane.capture_since().cursor

    pane.send_keys("echo WAIT_TIE_OK; echo WAIT_TIE_BAD", enter=True)
    quiesce(pane)
    hit = pane.wait_for_text(
        "WAIT_TIE_OK", stop=r"WAIT_TIE_BAD", regex=True, since=start, timeout=5
    )

    assert hit.outcome == "stopped"


def _enter_alternate_screen(pane: Pane) -> None:
    pane.send_keys("printf '\\033[?1049h'", enter=True)
    retry_until(
        lambda: pane.cmd("display-message", "-p", "#{alternate_on}").stdout == ["1"], 5
    )


def test_a_timeout_on_the_alternate_screen_raises_wait_alternate_screen(
    session: Session,
) -> None:
    """A TUI that never lets rows be searched is not a missing pattern."""
    pane = _quiet_pane(session, "wait_text_alt")
    start = pane.capture_since().cursor
    _enter_alternate_screen(pane)

    with pytest.raises(exc.WaitAlternateScreen, match="alternate screen") as caught:
        pane.wait_for_text("WAIT_ALT_NEVER", since=start, timeout=0.3)

    assert isinstance(caught.value, exc.WaitTimeout)


def test_a_match_after_the_alternate_screen_ends_reports_that_it_was_seen(
    session: Session,
) -> None:
    """The wait resumes when the program exits and records that it paused."""
    pane = _quiet_pane(session, "wait_text_alt_exit")
    start = pane.capture_since().cursor
    _enter_alternate_screen(pane)
    left: list[bool] = []

    def leave_once_seen(tick: capture.WaitProgress) -> None:
        if tick.alternate_screen and not left:
            left.append(True)
            pane.send_keys("printf '\\033[?1049l'; echo WAIT_ALT_BACK_MARK", enter=True)

    hit = pane.wait_for_text(
        "WAIT_ALT_BACK_MARK", since=start, timeout=10, progress=leave_once_seen
    )

    assert hit.alternate_screen is True
    assert hit.outcome == "matched"


def test_progress_is_called_every_tick_with_elapsed_and_budget(
    session: Session,
) -> None:
    """A callback hears the elapsed time and the timeout on each tick."""
    pane = _quiet_pane(session, "wait_text_progress")
    ticks: list[capture.WaitProgress] = []

    with pytest.raises(exc.WaitTimeout):
        pane.wait_for_text("WAIT_PROGRESS_NEVER", timeout=0.3, progress=ticks.append)

    assert len(ticks) >= 2
    assert ticks[0].elapsed < 0.25
    assert [tick.elapsed for tick in ticks] == sorted(tick.elapsed for tick in ticks)
    assert {tick.timeout for tick in ticks} == {0.3}
    assert ticks[-1].remaining is not None


def test_an_exception_from_progress_ends_the_wait(session: Session) -> None:
    """A caller can cancel a wait from its callback."""
    pane = _quiet_pane(session, "wait_text_progress_raise")

    class Cancelled(Exception):
        pass

    def cancel(tick: capture.WaitProgress) -> None:
        raise Cancelled

    with pytest.raises(Cancelled):
        pane.wait_for_text("WAIT_PROGRESS_NEVER", timeout=30, progress=cancel)


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


needs_tmux_3_8 = pytest.mark.skipif(
    not has_gte_version("3.8"),
    reason="pane_output_generation needs tmux 3.8",
)


def _count_tmux_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> collections.Counter[str]:
    """Count the tmux commands issued through :meth:`Pane.cmd`, by name."""
    counts: collections.Counter[str] = collections.Counter()
    real_cmd = Pane.cmd

    def counting_cmd(self: Pane, cmd: str, *args: t.Any, **kwargs: t.Any) -> t.Any:
        counts[cmd] += 1
        return real_cmd(self, cmd, *args, **kwargs)

    monkeypatch.setattr(Pane, "cmd", counting_cmd)
    return counts


def _quiet_pane(session: Session, name: str) -> Pane:
    pane = session.new_window(window_name=name).active_pane
    assert pane is not None
    run_and_wait(pane, "true")
    quiesce(pane)
    return pane


@needs_tmux_3_8
def test_wait_for_text_does_not_read_a_pane_that_has_not_changed(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Equal pane state means no output, so a quiet pane is not re-read per tick."""
    pane = _quiet_pane(session, "wait_text_quiet")
    counts = _count_tmux_commands(monkeypatch)

    with pytest.raises(exc.WaitTimeout):
        pane.wait_for_text("WAIT_TEXT_NEVER", timeout=0.6)

    assert counts["capture-pane"] <= 6
    assert counts["display-message"] >= 5, "the quiet pane was not even polled"


def test_wait_for_text_reads_every_tick_without_the_output_counter(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Before tmux 3.8 the state has no counter, so every tick reads the rows."""
    monkeypatch.setattr(
        capture,
        "PANE_STATE_FORMAT",
        capture.PANE_STATE_FORMAT.removesuffix("|#{pane_output_generation}"),
    )
    pane = _quiet_pane(session, "wait_text_nocounter")
    counts = _count_tmux_commands(monkeypatch)

    with pytest.raises(exc.WaitTimeout):
        pane.wait_for_text("WAIT_TEXT_NEVER", timeout=0.6)

    assert counts["capture-pane"] >= 10


def test_wait_for_text_finds_output_after_a_quiet_stretch(session: Session) -> None:
    """A pane that was skipped as unchanged is read again when it writes."""
    pane = _quiet_pane(session, "wait_text_late")
    writer = threading.Timer(
        0.6, lambda: pane.send_keys("echo WAIT_TEXT_LATE_MARK", enter=True)
    )
    writer.start()
    try:
        start = time.monotonic()
        hit = pane.wait_for_text("WAIT_TEXT_LATE_MARK", timeout=10)
    finally:
        writer.join()

    assert hit.match.string == "WAIT_TEXT_LATE_MARK"
    assert time.monotonic() - start < 3


@needs_tmux_3_8
def test_wait_for_idle_does_not_read_a_pane_that_has_not_changed(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The quiet period is measured on pane state, not on a capture per tick."""
    pane = _quiet_pane(session, "wait_idle_quiet")
    counts = _count_tmux_commands(monkeypatch)

    pane.wait_for_idle(quiet=0.6, timeout=10)

    assert counts["capture-pane"] <= 8


@needs_tmux_3_8
def test_a_read_torn_by_invisible_output_is_retried(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Output that moves no row and no cursor still fails the before/after check.

    Saving the cursor, homing it and restoring it changes nothing the state
    held before tmux 3.8 and bumps ``pane_output_generation``.
    """
    pane = _quiet_pane(session, "wait_text_torn")
    tty = pane.pane_tty
    real_capture_rows = capture._capture_rows
    calls = 0

    def capture_rows_then_write(*args: t.Any, **kwargs: t.Any) -> t.Any:
        nonlocal calls
        calls += 1
        rows = real_capture_rows(*args, **kwargs)
        if calls == 1:
            pane.cmd("run-shell", f"printf '\\0337\\033[H\\0338' > {tty}")
        return rows

    monkeypatch.setattr(capture, "_capture_rows", capture_rows_then_write)

    capture._read_stable_visible(pane)

    assert calls > 2, "the torn read was returned without a retry"
