"""A dead engine must CLOSE subscriber generators, not hang them."""

from __future__ import annotations

import asyncio
import typing as t

from libtmux.experimental.engines.async_control_mode import (
    AsyncControlModeEngine,
    ControlNotification,
)
from libtmux.experimental.engines.control_mode import ControlModeError


def test_subscribe_ends_when_engine_marked_dead() -> None:
    """A subscriber generator must finish (not hang) when the engine is marked dead."""

    async def main() -> list[ControlNotification]:
        engine = AsyncControlModeEngine()
        # do not spawn tmux: drive subscribe() + _mark_dead directly
        started = asyncio.Event()
        seen: list[ControlNotification] = []

        async def consume() -> None:
            started.set()  # signalled before the async for registers its queue
            # collect via async comprehension (avoids PERF401 lint)
            seen.extend([note async for note in engine.subscribe()])

        task = asyncio.create_task(consume())
        await started.wait()  # consumer registered its queue and is on queue.get()
        engine._mark_dead(ControlModeError("boom"))
        await asyncio.wait_for(task, timeout=1.0)  # must NOT hang
        return seen

    asyncio.run(main())


def test_subscribe_ends_when_dead_with_full_queue() -> None:
    """The death sentinel must land even when a subscriber queue is at maxsize.

    A slow consumer can let its bounded queue fill to ``maxsize`` (the
    drop-oldest ``_offer`` path). The death broadcast must still close such a
    consumer, so it evicts the oldest entry to make room for the sentinel
    instead of silently dropping it.
    """

    async def main() -> list[ControlNotification]:
        engine = AsyncControlModeEngine(event_queue_size=2)
        started = asyncio.Event()
        seen: list[ControlNotification] = []

        async def consume() -> None:
            started.set()
            seen.extend([note async for note in engine.subscribe()])

        task = asyncio.create_task(consume())
        await started.wait()  # queue registered, consumer blocked on queue.get()

        queue: asyncio.Queue[t.Any] = next(iter(engine._subscribers))
        first = ControlNotification.parse(b"%output %1 first")
        second = ControlNotification.parse(b"%output %2 second")
        queue.put_nowait(first)
        queue.put_nowait(second)  # queue now at maxsize=2 (full)

        engine._mark_dead(ControlModeError("boom"))
        await asyncio.wait_for(task, timeout=1.0)  # must NOT hang despite full queue
        # the oldest item was evicted so the sentinel could land
        assert first not in seen
        return seen

    asyncio.run(main())
