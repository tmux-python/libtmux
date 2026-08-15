"""Tests for :meth:`libtmux.pane.Pane.capture_since` and its cursor.

Covers the delta contract (only new rows come back), the anchor-loss
contract (``lines_missed`` is set rather than returning a silently
incomplete delta), and the lifecycle contract (a cursor never reads a
different process's output).
"""

from __future__ import annotations

import itertools
import typing as t
import uuid

import pytest

from libtmux import capture, exc
from libtmux.capture import CaptureCursor
from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    from libtmux.pane import Pane
    from libtmux.session import Session


def run_and_wait(pane: Pane, payload: str) -> None:
    """Run ``payload`` in ``pane`` and block until the shell finishes it.

    Polls rather than signalling through ``tmux wait-for``: a missed
    signal on a channel blocks forever, while a poll degrades to a
    :exc:`~libtmux.exc.WaitTimeout`.

    The sentinel is assembled by ``printf`` from two arguments, so the
    string being polled for never appears in the command line the shell
    echoes back. Polling for text that is present in the typed command
    matches that echo and returns before the payload has run at all.
    """
    token = uuid.uuid4().hex[:8].upper()
    sentinel = f"SETTLED{token}"
    pane.send_keys(f"{payload}; printf '%s%s\\n' SETTLED {token}", enter=True)
    retry_until(
        lambda: any(sentinel in line for line in pane.capture_pane()),
        5,
        raises=True,
    )


def test_first_call_returns_visible_screen_and_cursor(session: Session) -> None:
    """An initial call captures visible content and opens a cursor."""
    pane = session.new_window(window_name="capture_since_first").active_pane
    assert pane is not None
    marker = "CAPTURE_SINCE_INITIAL"
    run_and_wait(pane, f"echo {marker}")

    result = pane.capture_since()

    assert result.cursor.pane_id == pane.pane_id
    assert result.lines_missed is False
    assert any(marker in line for line in result.lines)


def test_followup_returns_only_new_output(session: Session) -> None:
    """Follow-up calls return content written after the previous cursor."""
    pane = session.new_window(window_name="capture_since_delta").active_pane
    assert pane is not None
    old_marker = "CAPTURE_SINCE_OLD"
    new_marker = "CAPTURE_SINCE_NEW"
    run_and_wait(pane, f"echo {old_marker}")
    first = pane.capture_since()

    run_and_wait(pane, f"echo {new_marker}")
    second = pane.capture_since(first.cursor)
    third = pane.capture_since(second.cursor)

    assert any(new_marker in line for line in second.lines)
    assert not any(old_marker in line for line in second.lines)
    assert third.lines == []


def test_capture_since_does_not_mutate_the_cursor(session: Session) -> None:
    """Replaying one cursor twice yields the same delta (#740)."""
    pane = session.new_window(window_name="capture_since_pure").active_pane
    assert pane is not None
    marker = "CAPTURE_SINCE_REPLAY"
    first = pane.capture_since()
    snapshot = first.cursor

    run_and_wait(pane, f"echo {marker}")
    once = pane.capture_since(first.cursor)
    twice = pane.capture_since(first.cursor)

    assert first.cursor == snapshot
    assert once.lines == twice.lines


def test_follows_anchor_into_retained_history(session: Session) -> None:
    """A cursor stays exact after its anchor scrolls into history."""
    pane = session.new_window(window_name="capture_since_scroll").active_pane
    assert pane is not None
    first = pane.capture_since()
    pane_height = int(pane.display_message("#{pane_height}", get_text=True)[0])
    markers = [f"CAPTURE_SINCE_SCROLL_{index:02d}" for index in range(pane_height + 8)]

    run_and_wait(pane, "printf '%s\\n' " + " ".join(markers))
    second = pane.capture_since(first.cursor)

    assert second.lines_missed is False
    assert any(markers[-1] in line for line in second.lines)


def test_reports_same_row_rewrite(session: Session) -> None:
    """Carriage-return rewrites on the cursor row count as new content."""
    pane = session.new_window(window_name="capture_since_rewrite").active_pane
    assert pane is not None
    script = (
        "printf OLD_REWRITE_CAPTURE_SINCE; "
        "IFS= read -r line; "
        "printf '\\r%s' \"$line\"; "
        "sleep 60"
    )

    def on_screen(marker: str) -> bool:
        return any(marker in line for line in pane.capture_pane())

    pane.respawn(kill=True, shell=f"sh -c '{script}'")
    retry_until(lambda: on_screen("OLD_REWRITE_CAPTURE_SINCE"), 5, raises=True)
    first = pane.capture_since()

    pane.send_keys("NEW_REWRITE_CAPTURE_SINCE", enter=True)
    retry_until(lambda: on_screen("NEW_REWRITE_CAPTURE_SINCE"), 5, raises=True)
    second = pane.capture_since(first.cursor)

    assert any("NEW_REWRITE_CAPTURE_SINCE" in line for line in second.lines)


def test_marks_lines_missed_after_history_clear(session: Session) -> None:
    """Lost history returns current visible content with ``lines_missed``."""
    pane = session.new_window(window_name="capture_since_clear").active_pane
    assert pane is not None
    fill = "; ".join(f"echo CAPTURE_SINCE_HISTORY_{i}" for i in range(40))
    run_and_wait(pane, fill)
    first = pane.capture_since()

    pane.cmd("clear-history")
    run_and_wait(pane, "echo CAPTURE_SINCE_AFTER_CLEAR")
    second = pane.capture_since(first.cursor)

    assert second.lines_missed is True
    assert any("CAPTURE_SINCE_AFTER_CLEAR" in line for line in second.lines)


def test_marks_lines_missed_after_clear_history_with_resize(session: Session) -> None:
    """``clear-history`` plus a pane grow still detects anchor loss.

    Regression: an early ``pane_height`` guard returned False when the
    pane grew after ``clear-history``, masking the complete history wipe.
    """
    window = session.new_window(window_name="capture_since_resize")
    pane = window.split()
    fill = "; ".join(f"echo RESIZE_CLEAR_{i}" for i in range(40))
    run_and_wait(pane, fill)
    first = pane.capture_since()

    pane.cmd("clear-history")
    assert pane.pane_height is not None
    pane.set_height(int(pane.pane_height) + 3)
    run_and_wait(pane, "echo AFTER_RESIZE_CLEAR")
    second = pane.capture_since(first.cursor)

    assert second.lines_missed is True
    assert any("AFTER_RESIZE_CLEAR" in line for line in second.lines)


def test_marks_lines_missed_after_history_limit_trim(session: Session) -> None:
    """History-limit trims return visible content with ``lines_missed``.

    Floods past ``history-limit`` then clears history to guarantee the
    anchor is destroyed. The flood alone is not deterministic -- tmux
    retains enough of the original prompt that the fingerprint search
    can legitimately re-anchor on a surviving hash.
    """
    session.cmd("set-option", "-g", "history-limit", "20")
    window = session.new_window(window_name="capture_since_trim")
    pane = window.split()

    def hlimit_locked() -> bool:
        raw = pane.display_message("#{history_limit}", get_text=True)
        return bool(raw) and int(raw[0]) == 20

    retry_until(hlimit_locked, 5, raises=True)
    run_and_wait(
        pane,
        "for i in $(seq 1 25); do printf 'PREFILL_%03d\\n' \"$i\"; done",
    )
    first = pane.capture_since()

    run_and_wait(
        pane,
        "for i in $(seq 1 120); do printf 'TRIM_%03d\\n' \"$i\"; done",
    )
    pane.cmd("clear-history")
    run_and_wait(pane, "echo TRIM_DONE")
    second = pane.capture_since(first.cursor)

    assert second.lines_missed is True
    assert any("TRIM" in line for line in second.lines)


def test_rejects_malformed_cursor() -> None:
    """Malformed cursor strings fail loudly instead of guessing."""
    with pytest.raises(exc.InvalidCaptureCursor, match="unsupported cursor format"):
        CaptureCursor.from_str("not-a-valid-cursor")


def test_rejects_cursor_for_a_different_pane(session: Session) -> None:
    """A cursor cannot be replayed against a different pane."""
    window = session.new_window(window_name="capture_since_other")
    pane = window.active_pane
    assert pane is not None
    first = pane.capture_since()
    other_pane = window.split()

    with pytest.raises(exc.InvalidCaptureCursor, match="cursor pane"):
        other_pane.capture_since(first.cursor)


def test_rejects_respawned_pane_cursor(session: Session) -> None:
    """Pane respawn invalidates the cursor's process identity."""
    pane = session.new_window(window_name="capture_since_respawn").active_pane
    assert pane is not None
    first = pane.capture_since()

    pane.respawn(kill=True, shell="sleep 60")

    with pytest.raises(exc.PaneLifecycleChanged, match="respawned"):
        pane.capture_since(first.cursor)


def test_rejects_dead_pane_cursor(session: Session) -> None:
    """Pane death invalidates the cursor instead of returning stale rows."""
    window = session.new_window(window_name="capture_since_dead")
    pane = window.active_pane
    assert pane is not None
    first = pane.capture_since()
    window.cmd("set-option", "-w", "remain-on-exit", "on")
    pane.respawn(kill=True, shell="true")

    def is_dead() -> bool:
        out = pane.cmd("display-message", "-p", "#{pane_dead}").stdout
        return bool(out) and out[0].strip() == "1"

    retry_until(is_dead, 5, raises=True)

    with pytest.raises(exc.PaneLifecycleChanged, match="died"):
        pane.capture_since(first.cursor)


def test_rejects_a_dead_pane_without_a_cursor(session: Session) -> None:
    """A first call on an already-dead pane refuses rather than reading it."""
    window = session.new_window(window_name="capture_since_dead_first")
    pane = window.active_pane
    assert pane is not None
    window.cmd("set-option", "-w", "remain-on-exit", "on")
    pane.respawn(kill=True, shell="true")

    def is_dead() -> bool:
        out = pane.cmd("display-message", "-p", "#{pane_dead}").stdout
        return bool(out) and out[0].strip() == "1"

    retry_until(is_dead, 5, raises=True)

    with pytest.raises(exc.PaneLifecycleChanged, match="died"):
        pane.capture_since()


def test_a_failed_capture_raises_instead_of_reading_as_empty(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tmux capture failure is never reported as "nothing was written".

    ``Pane.capture_pane`` returns tmux's stdout without inspecting stderr,
    so a failed capture and a blank pane are indistinguishable there. Uses
    ``monkeypatch`` because provoking a real ``capture-pane`` failure
    against a live, healthy pane is not otherwise reachable.
    """
    pane = session.new_window(window_name="capture_since_failed_read").active_pane
    assert pane is not None
    real_cmd = type(pane).cmd

    def failing_capture(self: Pane, *args: str) -> t.Any:
        proc = real_cmd(self, *args)
        if args and args[0] == "capture-pane":
            proc.stderr = ["no such pane"]
            proc.stdout = []
        return proc

    monkeypatch.setattr(type(pane), "cmd", failing_capture)

    with pytest.raises(exc.LibTmuxException, match="capture-pane"):
        pane.capture_since()


def test_cursor_round_trips_through_a_string(session: Session) -> None:
    """A serialized cursor decodes back to an equal cursor."""
    pane = session.new_window(window_name="capture_since_codec").active_pane
    assert pane is not None
    first = pane.capture_since()

    encoded = str(first.cursor)
    decoded = CaptureCursor.from_str(encoded)

    assert encoded.startswith("capture-since-v1:")
    assert decoded == first.cursor


def test_deserialized_cursor_still_captures_a_delta(session: Session) -> None:
    """A cursor that survived serialization behaves like the original."""
    pane = session.new_window(window_name="capture_since_codec_delta").active_pane
    assert pane is not None
    marker = "CAPTURE_SINCE_CODEC"
    first = pane.capture_since()

    run_and_wait(pane, f"echo {marker}")
    second = pane.capture_since(CaptureCursor.from_str(str(first.cursor)))

    assert any(marker in line for line in second.lines)


def never_settles(pane: Pane, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every pane-state sample differ from the one before it.

    Simulates a pane written to continuously, so no read ever brackets a
    capture with two matching snapshots. ``monkeypatch`` rather than a
    real busy pane because the retry loop guards a race: a genuine pane
    cannot be made to move between *every* pair of samples on demand, so
    the condition has to be injected to be asserted on at all.
    """
    steady = capture._read_pane_state(pane)
    samples = itertools.count()
    monkeypatch.setattr(
        capture,
        "_read_pane_state",
        lambda _pane: steady._replace(cursor_y=next(samples) % 5),
    )


def test_unstable_pane_reports_a_missed_first_read(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pane that never holds still reports a missed read, not a torn one."""
    pane = session.new_window(window_name="capture_since_unstable").active_pane
    assert pane is not None
    never_settles(pane, monkeypatch)

    assert pane.capture_since().lines_missed is True


def test_unstable_pane_reports_a_missed_delta(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The delta path degrades the same way when the grid keeps moving.

    The injected states leave the anchor valid, so a missed read can only
    come from the stability retry giving up -- not from anchor loss.
    """
    pane = session.new_window(window_name="capture_since_unstable_delta").active_pane
    assert pane is not None
    first = pane.capture_since()
    never_settles(pane, monkeypatch)

    assert pane.capture_since(first.cursor).lines_missed is True
