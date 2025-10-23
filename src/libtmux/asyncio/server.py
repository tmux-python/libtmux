"""Async-first server façade built on transports."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from types import TracebackType

from libtmux.errors import CommandError, TransportClosed

from ._types import CommandResult, Transport


@dataclass(slots=True)
class Session:
    """Simple representation of a tmux session."""

    server: Server
    session_id: str
    name: str


class Server:
    r"""Async-first wrapper mirroring a subset of the sync API.

    >>> from libtmux.asyncio.server import Server as AsyncServer
    >>> from libtmux.asyncio.testing import MockTransport, result
    >>> transport = MockTransport(script={
    ...     ('list-sessions', '-F', '#{session_id}:#{session_name}'): result(
    ...         stdout='@1:dev\n@2:db'
    ...     )
    ... })
    >>> async def collect() -> list[str]:
    ...     async with AsyncServer(transport=transport) as srv:
    ...         sessions = await srv.list_sessions()
    ...     return [s.name for s in sessions]
    >>> import asyncio
    >>> asyncio.run(collect())
    ['dev', 'db']
    """

    def __init__(self, *, transport: Transport | None = None, **kwargs: object) -> None:
        self._transport = transport
        self._transport_kwargs = kwargs
        self._started = False

    async def __aenter__(self) -> Server:
        """Enter the async context manager, starting the transport."""
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Exit the async context manager, stopping the transport."""
        await self.stop()

    async def start(self) -> None:
        """Start the underlying transport."""
        if self._transport is None:
            message = (
                "No transport provided; ControlModeTransport implementation pending."
            )
            raise TransportClosed(message)
        if not self._started:
            await self._transport.start()
            self._started = True

    async def stop(self) -> None:
        """Stop the underlying transport if it was started."""
        if self._started and self._transport is not None:
            await self._transport.stop()
        self._started = False

    async def list_sessions(self, *, timeout: float | None = None) -> list[Session]:
        """Return all sessions known to tmux."""
        result = await self._run(
            ("list-sessions", "-F", "#{session_id}:#{session_name}"),
            timeout=timeout,
        )
        sessions: list[Session] = []
        for line in _splitlines(result["stdout"]):
            if not line:
                continue
            session_id, name = line.split(":", 1)
            sessions.append(Session(server=self, session_id=session_id, name=name))
        return sessions

    async def new_session(
        self,
        name: str | None = None,
        *,
        timeout: float | None = None,
    ) -> Session:
        """Create a new detached session and return its representation."""
        argv: list[str] = ["new-session", "-d", "-P"]
        if name:
            argv.extend(["-s", name])
        result = await self._run(tuple(argv), timeout=timeout)
        raw = result["stdout"].strip()
        if raw and ":" in raw:
            session_id, session_name = raw.split(":", 1)
        else:
            session_id = raw or ""
            session_name = name or ""
        return Session(server=self, session_id=session_id, name=session_name)

    async def kill_session(
        self,
        name: str,
        *,
        timeout: float | None = None,
    ) -> None:
        """Kill the session identified by *name*."""
        result = await self._run(("kill-session", "-t", name), timeout=timeout)
        if result["returncode"] != 0:
            raise CommandError(
                stdout=result["stdout"],
                stderr=result["stderr"],
                returncode=result["returncode"],
            )

    async def _run(
        self,
        argv: Sequence[str],
        *,
        timeout: float | None,
    ) -> CommandResult:
        """Execute a tmux command via the configured transport."""
        if self._transport is None:
            message = "transport not started"
            raise TransportClosed(message)
        return await self._transport.run(argv, timeout=timeout)


def _splitlines(value: str) -> Iterable[str]:
    return value.splitlines()


__all__ = ["Server", "Session"]
