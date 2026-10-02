"""Run a coroutine the way the asyncio tests demand, and fail on what it leaks.

:func:`run_checked` runs one coroutine on a fresh event loop in asyncio debug
mode and turns every asyncio hygiene complaint into a test failure:

- a callback that held the loop longer than ``slow`` seconds (default 50 ms),
- a coroutine that was never awaited,
- a task destroyed while still pending,
- a transport, socket or pipe that was never closed (``ResourceWarning``).

It also reports the worst delay of a 1 ms ticker, which is how long anything
actually kept the loop from running.
"""

from __future__ import annotations

import asyncio
import contextlib
import gc
import logging
import os
import subprocess
import typing as t
import warnings

import pytest

T = t.TypeVar("T")

SLOW_CALLBACK_SECONDS = 0.05


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record.getMessage())


class LoopReport(t.NamedTuple):
    """What a checked run observed about the loop."""

    max_lag: float
    complaints: list[str]


def run_checked(
    main: t.Callable[[], t.Coroutine[t.Any, t.Any, T]],
    *,
    slow: float = SLOW_CALLBACK_SECONDS,
    attempts: int = 3,
) -> T:
    """Run ``main()`` under asyncio debug mode and fail on any hygiene problem.

    Parameters
    ----------
    main : callable
        Returns the coroutine to run; called on the new loop's thread.
    slow : float
        Seconds a single callback may hold the loop before the run fails.
    attempts : int
        Runs allowed when the *only* complaint is a slow callback. On a busy
        machine the operating system can pause a healthy callback for tens of
        milliseconds, but a callback that really blocks is slow on every run,
        so a failure has to repeat to count. Every other complaint fails at
        once.

    Returns
    -------
    object
        What the coroutine returned.

    Raises
    ------
    AssertionError
        asyncio reported a slow callback, an unawaited coroutine, a destroyed
        pending task, or a resource that was not closed.
    """
    for attempt in range(1, attempts + 1):
        value, report = run_reported(main, slow=slow)
        if report.complaints and attempt < attempts and _only_slow(report.complaints):
            continue
        assert not report.complaints, "\n".join(report.complaints)
        return value
    raise AssertionError  # pragma: no cover


def _only_slow(complaints: list[str]) -> bool:
    return all(c.startswith("Executing ") for c in complaints)


def run_reported(
    main: t.Callable[[], t.Coroutine[t.Any, t.Any, T]],
    *,
    slow: float = SLOW_CALLBACK_SECONDS,
) -> tuple[T, LoopReport]:
    """Run like :func:`run_checked` but return the report instead of asserting."""
    collector = _Collector()
    asyncio_logger = logging.getLogger("asyncio")
    asyncio_logger.addHandler(collector)
    lags: list[float] = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        loop = asyncio.new_event_loop()
        loop.set_debug(True)
        loop.slow_callback_duration = slow
        try:
            value = loop.run_until_complete(_with_ticker(main, lags))
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.run_until_complete(loop.shutdown_default_executor())
            finally:
                loop.close()
                gc.collect()
                asyncio_logger.removeHandler(collector)
    complaints = list(collector.records)
    complaints += [
        f"{w.category.__name__}: {w.message}"
        for w in caught
        if issubclass(w.category, (ResourceWarning, RuntimeWarning))
    ]
    return value, LoopReport(max(lags, default=0.0), complaints)


async def _with_ticker(
    main: t.Callable[[], t.Coroutine[t.Any, t.Any, T]],
    lags: list[float],
) -> T:
    loop = asyncio.get_running_loop()

    async def tick() -> None:
        last = loop.time()
        while True:
            await asyncio.sleep(0.001)
            now = loop.time()
            lags.append(now - last - 0.001)
            last = now

    ticker = asyncio.ensure_future(tick())
    try:
        return await main()
    finally:
        ticker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await ticker


def processes(*needles: str) -> list[str]:
    """Return the command lines of live processes containing every *needle*.

    Counts real operating-system processes, so a test can prove a cancelled
    call left no tmux client behind. Zombies are listed too: a client that was
    killed but never reaped still shows.
    """
    out = subprocess.run(
        ["ps", "-axo", "pid=,stat=,args="],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    me = str(os.getpid())
    found = []
    for line in out.splitlines():
        pid, _, rest = line.strip().partition(" ")
        if pid == me or "ps -axo" in rest:
            continue
        if all(needle in rest for needle in needles):
            found.append(rest)
    return found


class SpawnCounter:
    """Count the clients the async engines start, and signal when N exist.

    Lets a test wait for "ten commands are in flight" as an event instead of a
    sleep: the spy wraps :func:`asyncio.create_subprocess_exec` and sets an
    :class:`asyncio.Event` once enough children have been spawned.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.started = 0
        self.processes: list[asyncio.subprocess.Process] = []
        self.target = 0
        self.reached: asyncio.Event | None = None
        real = asyncio.create_subprocess_exec

        async def spy(*args: t.Any, **kwargs: t.Any) -> t.Any:
            process = await real(*args, **kwargs)
            self.started += 1
            self.processes.append(process)
            if self.reached is not None and self.started >= self.target:
                self.reached.set()
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)

    def expect(self, count: int) -> asyncio.Event:
        """Return an event set once *count* clients have been started."""
        self.target = count
        self.reached = asyncio.Event()
        return self.reached
