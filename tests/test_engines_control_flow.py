"""Tests for the I/O-free watermark policy in ``libtmux.engines.control.flow``."""

from __future__ import annotations

import pytest

from libtmux.engines.control.flow import Action, Gap, Watermark


def drain(buf: Watermark) -> list[bytes | Gap]:
    """Pop everything, collecting items and ignoring actions."""
    out: list[bytes | Gap] = []
    while buf:
        item, _ = buf.pop()
        assert item is not None
        out.append(item)
    return out


def test_a_producer_below_the_high_mark_is_never_paused() -> None:
    """Bytes under the mark queue without any action."""
    buf = Watermark("%1", high=100, low=10)

    assert [buf.push(b"x" * 10) for _ in range(5)] == [None] * 5
    assert not buf.paused
    assert drain(buf) == [b"x" * 10] * 5


def test_crossing_the_high_mark_asks_for_one_pause() -> None:
    """The first push over the mark pauses; later pushes do not ask again."""
    buf = Watermark("%1", high=10, low=4)

    assert buf.push(b"123456") is None
    assert buf.push(b"7890") is Action.PAUSE
    assert buf.push(b"in flight") is None
    assert buf.paused


def test_the_gap_sits_where_the_pause_took_effect() -> None:
    """Bytes in flight when the pause was sent stay before the gap."""
    buf = Watermark("%1", high=4, low=1)
    buf.push(b"abcd")
    buf.push(b"late")  # was already on the wire
    buf.pause_took_effect()
    buf.continue_took_effect()
    buf.push(b"after")

    assert drain(buf) == [b"abcd", b"late", Gap("%1"), b"after"]
    assert buf.gaps == 1


def test_draining_to_the_low_mark_resumes_the_pane() -> None:
    """The pop that reaches the low mark returns the continue action."""
    buf = Watermark("%1", high=8, low=3)
    buf.push(b"12345678")
    buf.pause_took_effect()

    assert buf.pop() == (b"12345678", Action.CONTINUE)
    assert buf.pop() == (Gap("%1"), None)  # the continue is already requested


def test_a_consumer_already_drained_is_resumed_at_the_pause() -> None:
    """A pause that lands after the queue emptied is resumed at once."""
    buf = Watermark("%1", high=4, low=2)
    assert buf.push(b"abcd") is Action.PAUSE
    buf.pop()

    assert buf.pause_took_effect() is Action.CONTINUE


def test_a_pause_tmux_started_still_gets_a_gap_and_a_resume() -> None:
    """``pause-after`` pauses without being asked; the stream still says so."""
    buf = Watermark("%1", high=100, low=10)
    buf.push(b"x" * 20)

    assert buf.pause_took_effect() is None
    assert buf.pop() == (b"x" * 20, Action.CONTINUE)
    assert drain(buf) == [Gap("%1")]


def test_the_peak_stays_near_the_mark_when_the_pause_is_prompt() -> None:
    """Peak is the high mark plus whatever was already in flight."""
    buf = Watermark("%1", high=1000, low=100)
    for _ in range(10):
        buf.push(b"x" * 100)
    buf.pause_took_effect()
    buf.push(b"y" * 150)  # in flight before the pause

    assert buf.peak == 1150
    assert buf.queued == 1150


def test_loss_with_the_connection_is_a_gap_and_resets_the_pause() -> None:
    """A dead client loses output; the new one starts flowing."""
    buf = Watermark("%1", high=4, low=1)
    buf.push(b"abcd")
    buf.lost()
    buf.lost()  # one gap, not two

    assert not buf.paused
    assert drain(buf) == [b"abcd", Gap("%1")]


def test_a_closed_buffer_takes_no_more_but_keeps_what_it_has() -> None:
    """Close ends the stream after the queue is read."""
    buf = Watermark("%1", high=10, low=2)
    buf.push(b"kept")
    buf.close()
    buf.push(b"dropped")

    assert buf.closed
    assert drain(buf) == [b"kept"]


@pytest.mark.parametrize(("high", "low"), [(10, 10), (5, 9), (10, -1)])
def test_bad_marks_are_refused(high: int, low: int) -> None:
    """``0 <= low < high`` is required."""
    with pytest.raises(ValueError, match="watermarks"):
        Watermark("%1", high=high, low=low)
