"""Testing helpers for the async libtmux API."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from dataclasses import dataclass

from libtmux.errors import CommandError, OperationTimeout

from ._types import CommandResult, TmuxEvent, Transport


def result(
    *,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
    cmd_id: int = 1,
) -> CommandResult:
    """Return a scripted command result."""
    return {
        "stdout": stdout,
        "stderr": stderr,
        "returncode": returncode,
        "cmd_id": cmd_id,
    }


def error(
    *,
    stdout: str = "",
    stderr: str = "error",
    returncode: int = 1,
) -> CommandError:
    """Return a scripted command error."""
    return CommandError(stdout=stdout, stderr=stderr, returncode=returncode)


def ev(
    kind: str,
    *,
    pane_id: str | None,
    data: str | None,
    raw: str | None = None,
) -> TmuxEvent:
    """Create a scripted event for transport tests."""
    raw_payload = raw or f"%{kind} {pane_id or ''} {data or ''}".strip()
    return {
        "kind": kind,
        "pane_id": pane_id,
        "data": data,
        "raw": raw_payload,
    }


@dataclass
class _ScriptEntry:
    value: CommandResult | CommandError
    delay: float


class MockTransport(Transport):
    """In-memory transport used in doctests and unit tests."""

    def __init__(
        self,
        *,
        script: Mapping[tuple[str, ...], CommandResult | CommandError] | None = None,
        events: Iterable[TmuxEvent] | None = None,
        delays: Mapping[tuple[str, ...], float] | None = None,
    ) -> None:
        self._script: dict[tuple[str, ...], _ScriptEntry] = {}
        for key, value in (script or {}).items():
            delay = (delays or {}).get(key, 0.0)
            self._script[key] = _ScriptEntry(value=value, delay=delay)
        self._events: asyncio.Queue[TmuxEvent] = asyncio.Queue()
        for event in events or []:
            self._events.put_nowait(event)
        self._started = False

    async def start(self) -> None:
        """Mark the transport as started."""
        self._started = True

    async def stop(self) -> None:
        """Reset the transport to an unstarted state and drain events."""
        self._started = False
        while not self._events.empty():
            self._events.get_nowait()

    async def run(self, argv: Sequence[str], *, timeout: float | None) -> CommandResult:
        """Replay a scripted command result or raise a scripted error."""
        if not self._started:
            message = "MockTransport not started"
            raise RuntimeError(message)

        entry = self._script.get(tuple(argv))

        async def _execute() -> CommandResult:
            if entry and entry.delay:
                await asyncio.sleep(entry.delay)
            if entry is None:
                return result()
            if isinstance(entry.value, CommandError):
                raise entry.value
            return entry.value

        try:
            if timeout is None:
                return await _execute()
            async with asyncio.timeout(timeout):
                return await _execute()
        except TimeoutError as exc:  # pragma: no cover - defensive guard
            message = "operation timed out"
            raise OperationTimeout(message) from exc

    def events(self) -> AsyncIterator[TmuxEvent]:
        """Yield scripted events forever."""

        async def iterator() -> AsyncIterator[TmuxEvent]:
            while True:
                yield await self._events.get()

        return iterator()


__all__ = ["MockTransport", "error", "ev", "result"]
