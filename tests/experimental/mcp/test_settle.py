"""The pure settle accumulator -- decoder, per-pane filter, and the fold.

Driven offline with literal strings and fake async generators plus an injected
clock, so every stop reason (settled, byte_cap, time_cap, stream_end) and the
cancellation teardown are exercised deterministically without a real tmux ``-C``
connection or ``pytest-asyncio``.
"""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.experimental.mcp._settle import (
    accumulate_until_settle,
    decode_output,
    output_payload,
)

if t.TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable


def test_decode_output_octal_and_passthrough() -> None:
    """Octal escapes decode; an escaped backslash collapses; plain text is kept."""
    assert decode_output("a\\012b") == "a\nb"
    assert decode_output("tab\\011x") == "tab\tx"
    assert decode_output("a\\134b") == "a\\b"
    assert decode_output("plain, spaces kept") == "plain, spaces kept"
    assert decode_output("trailing\\") == "trailing\\"


def test_output_payload_preserves_internal_whitespace() -> None:
    """The per-pane filter slices the data body without collapsing inner spaces."""
    assert output_payload("%output %1 a  b", "%1") == "a  b"
    assert output_payload("%output %2 x", "%1") is None
    assert output_payload("%window-add @3", "%1") is None


def test_accumulate_settles_on_idle() -> None:
    """A pane that emits then goes quiet returns reason='settled'."""

    async def quiet_after_two() -> AsyncGenerator[str, None]:
        yield "hello "
        yield "world"
        await asyncio.Event().wait()

    out = asyncio.run(
        accumulate_until_settle(
            quiet_after_two(),
            settle_ms=10,
            timeout_ms=2000,
            max_bytes=4096,
        ),
    )
    assert out.reason == "settled"
    assert out.text == "hello world"
    assert out.byte_count == 11
    assert out.frame_count == 2
    assert out.truncated is False
    # On 'settled', idle_ms_observed is exactly the settle_ms threshold.
    assert out.idle_ms_observed == 10


def test_accumulate_byte_cap_keeps_tail() -> None:
    """A flood past max_bytes truncates, preserving the tail."""

    async def flood() -> AsyncGenerator[str, None]:
        for _ in range(100):
            yield "abcde"

    out = asyncio.run(
        accumulate_until_settle(
            flood(),
            settle_ms=50,
            timeout_ms=2000,
            max_bytes=8,
        ),
    )
    assert out.reason == "byte_cap"
    assert out.byte_count == 8
    assert out.truncated is True
    assert out.text == "cdeabcde"  # last 8 bytes of "abcdeabcde"


def test_accumulate_stream_end() -> None:
    """An exhausted stream returns reason='stream_end'."""

    async def two_then_done() -> AsyncGenerator[str, None]:
        yield "a"
        yield "b"

    out = asyncio.run(
        accumulate_until_settle(
            two_then_done(),
            settle_ms=50,
            timeout_ms=2000,
            max_bytes=64,
        ),
    )
    assert out.reason == "stream_end"
    assert out.text == "ab"


def test_accumulate_time_cap_with_scripted_clock() -> None:
    """A slow-but-never-idle pane hits the wall-clock cap via the injected clock."""

    def make_clock(step: float = 0.5) -> Callable[[], float]:
        state = {"t": -step}

        def clock() -> float:
            state["t"] += step
            return state["t"]

        return clock

    async def forever() -> AsyncGenerator[str, None]:
        while True:
            yield "x"

    out = asyncio.run(
        accumulate_until_settle(
            forever(),
            settle_ms=50,
            timeout_ms=1000,
            max_bytes=100000,
            now=make_clock(),
        ),
    )
    assert out.reason == "time_cap"
    assert out.frame_count >= 1


def test_accumulate_closes_stream_on_cancel() -> None:
    """Cancelling the fold closes the stream, so no consumer is leaked."""
    closed = {"value": False}

    async def blocking() -> AsyncGenerator[str, None]:
        try:
            yield "first"
            await asyncio.Event().wait()
        finally:
            closed["value"] = True

    async def main() -> bool:
        task = asyncio.ensure_future(
            accumulate_until_settle(
                blocking(),
                settle_ms=10000,
                timeout_ms=10000,
                max_bytes=4096,
            ),
        )
        await asyncio.sleep(0.05)  # let the fold park on the blocking stream
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return closed["value"]

    assert asyncio.run(main()) is True
