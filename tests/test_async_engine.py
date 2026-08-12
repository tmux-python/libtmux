"""Async engines dispatch through the same adaptations as synchronous ones."""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux import exc
from libtmux.common import adispatch
from libtmux.engines import AsyncSubprocessEngine, AsyncTmuxEngine, CommandResult

if t.TYPE_CHECKING:
    from libtmux.engines import CommandRequest
    from libtmux.session import Session


def test_async_subprocess_engine_runs(session: Session) -> None:
    """The shipped async engine reaches the same server as the object API."""
    engine = AsyncSubprocessEngine.for_server(session.server)

    async def main() -> CommandResult:
        return await adispatch(engine, "display-message", "-p", "hi")

    result = asyncio.run(main())

    assert result.stdout == ["hi"]
    assert result.ok


def test_adispatch_applies_the_has_session_adaptation() -> None:
    """Async gets tmux's has-session quirk handled, exactly as sync does."""

    class Fake(AsyncTmuxEngine):
        async def run(self, request: CommandRequest) -> CommandResult:
            return CommandResult(
                cmd=("tmux", *request.args),
                stderr=("can't find session: nope",),
                returncode=1,
            )

    async def main() -> CommandResult:
        return await adispatch(Fake(), "has-session", "-t", "nope")

    assert asyncio.run(main()).stdout == ["can't find session: nope"]


def test_async_run_batch_default_awaits(session: Session) -> None:
    """The inherited run_batch awaits each command in order."""
    engine = AsyncSubprocessEngine.for_server(session.server)

    async def main() -> list[CommandResult]:
        from libtmux.engines import CommandRequest

        return await engine.run_batch(
            [
                CommandRequest.from_args("display-message", "-p", "one"),
                CommandRequest.from_args("display-message", "-p", "two"),
            ],
        )

    assert [r.stdout[0] for r in asyncio.run(main())] == ["one", "two"]


def test_server_still_rejects_an_async_engine(session: Session) -> None:
    """Server is synchronous; an async engine is refused where it is supplied."""
    from libtmux.server import Server

    with pytest.raises(exc.LibTmuxException, match="async"):
        Server(engine=AsyncSubprocessEngine.for_server(session.server))  # type: ignore[arg-type]
