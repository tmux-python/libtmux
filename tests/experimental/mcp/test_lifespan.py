"""Tests for the engine-probe lifespan."""

from __future__ import annotations

import asyncio
import typing as t

import pytest

pytest.importorskip("fastmcp")


class _BrokenEngine:
    """An engine whose every command raises (a broken connection)."""

    async def run(self, _request: t.Any) -> t.Any:
        msg = "connection lost"
        raise ConnectionError(msg)

    async def run_batch(self, requests: t.Any) -> t.Any:
        return await self.run(requests)


class _TmuxErrorEngine:
    """An engine that returns a tmux-side failure as data (never raises)."""

    async def run(self, _request: t.Any) -> t.Any:
        from libtmux.experimental.engines.base import CommandResult

        return CommandResult(
            cmd=("tmux", "list-sessions"),
            returncode=1,
            stderr=("no server running",),
        )

    async def run_batch(self, requests: t.Any) -> t.Any:
        return [await self.run(requests)]


def test_lifespan_raises_on_broken_engine() -> None:
    """A broken engine (raises) fails the startup preflight loudly."""
    from libtmux.experimental.mcp._lifespan import make_lifespan

    lifespan = make_lifespan(t.cast("t.Any", _BrokenEngine()))

    async def main() -> None:
        async with lifespan(t.cast("t.Any", None)):
            pass

    with pytest.raises(RuntimeError, match="preflight failed"):
        asyncio.run(main())


def test_lifespan_tolerates_tmux_side_error() -> None:
    """A tmux-side error (returned as data) does not fail startup."""
    from libtmux.experimental.mcp._lifespan import make_lifespan

    lifespan = make_lifespan(t.cast("t.Any", _TmuxErrorEngine()))
    entered = False

    async def main() -> None:
        nonlocal entered
        async with lifespan(t.cast("t.Any", None)):
            entered = True

    asyncio.run(main())
    assert entered
