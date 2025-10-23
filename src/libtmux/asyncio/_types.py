"""Shared typed structures for the async libtmux API."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol, TypedDict, runtime_checkable


class CommandResult(TypedDict):
    """Result returned by an async tmux command."""

    stdout: str
    stderr: str
    returncode: int
    cmd_id: int


class TmuxEvent(TypedDict, total=False):
    """Event emitted by the transport."""

    kind: str
    raw: str
    pane_id: str | None
    data: str | None


@runtime_checkable
class Transport(Protocol):
    """Protocol that async transports must satisfy."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def run(
        self, argv: Sequence[str], *, timeout: float | None
    ) -> CommandResult: ...

    def events(self) -> AsyncIterator[TmuxEvent]: ...


__all__ = ["CommandResult", "TmuxEvent", "Transport"]
