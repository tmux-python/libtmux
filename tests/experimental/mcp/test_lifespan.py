"""Tests for the engine-probe lifespan."""

from __future__ import annotations

import asyncio
import typing as t

import pytest

fastmcp = pytest.importorskip("fastmcp")


class _ClosableEngine:
    """A complete async engine double with observable close behavior."""

    def __init__(
        self,
        *,
        run_error: Exception | None = None,
        close_error: BaseException | None = None,
    ) -> None:
        self.run_error = run_error
        self.close_error = close_error
        self.close_calls = 0

    async def run(self, _request: t.Any) -> t.Any:
        if self.run_error is not None:
            raise self.run_error
        from libtmux.experimental.engines.base import CommandResult

        return CommandResult(cmd=("tmux", "list-sessions"), returncode=0)

    async def run_batch(self, requests: t.Any) -> t.Any:
        return [await self.run(request) for request in requests]

    async def aclose(self) -> None:
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


class _DelayedCloseEngine(_ClosableEngine):
    """A closable engine whose cleanup can be cancelled while suspended."""

    def __init__(self) -> None:
        super().__init__()
        self.close_started = asyncio.Event()
        self.allow_close = asyncio.Event()
        self.close_finished = asyncio.Event()

    async def aclose(self) -> None:
        self.close_calls += 1
        self.close_started.set()
        await self.allow_close.wait()
        self.close_finished.set()


async def _enter_server(server: t.Any) -> None:
    """Enter and exit one real FastMCP client/server lifespan."""
    async with fastmcp.Client(server):
        pass


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


def test_borrowed_async_server_leaves_engine_open() -> None:
    """An injected engine remains usable after its server exits."""
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server

    engine = _ClosableEngine()
    server = build_async_server(t.cast("t.Any", engine), events="off")

    asyncio.run(_enter_server(server))

    assert engine.close_calls == 0


def test_owned_async_server_closes_engine_once() -> None:
    """An explicitly transferred engine closes once on normal server exit."""
    from libtmux.experimental.mcp.fastmcp_adapter import (
        EngineOwnership,
        build_async_server,
    )

    engine = _ClosableEngine()
    server = build_async_server(
        t.cast("t.Any", engine),
        events="off",
        engine_ownership=EngineOwnership.OWNED,
    )

    asyncio.run(_enter_server(server))

    assert engine.close_calls == 1


def test_owned_async_server_requires_lifespan() -> None:
    """Ownership transfer cannot be combined with disabled lifecycle hooks."""
    from libtmux.experimental.mcp.fastmcp_adapter import (
        EngineOwnership,
        build_async_server,
    )

    with pytest.raises(ValueError, match="lifespan"):
        build_async_server(
            t.cast("t.Any", _ClosableEngine()),
            events="off",
            lifespan=False,
            engine_ownership=EngineOwnership.OWNED,
        )


def test_owned_async_server_requires_closable_engine() -> None:
    """Ownership transfer rejects an engine without asynchronous close."""
    from libtmux.experimental.mcp.fastmcp_adapter import (
        EngineOwnership,
        build_async_server,
    )

    with pytest.raises(TypeError, match="aclose"):
        build_async_server(
            t.cast("t.Any", _TmuxErrorEngine()),
            events="off",
            engine_ownership=EngineOwnership.OWNED,
        )


def test_owned_lifespan_closes_engine_on_body_exception() -> None:
    """A server-body failure still closes its owned engine exactly once."""
    from libtmux.experimental.mcp._lifespan import EngineOwnership, make_lifespan

    engine = _ClosableEngine()
    lifespan = make_lifespan(
        t.cast("t.Any", engine),
        ownership=EngineOwnership.OWNED,
    )

    async def main() -> None:
        async with lifespan(t.cast("t.Any", None)):
            msg = "body failed"
            raise LookupError(msg)

    with pytest.raises(LookupError, match="body failed"):
        asyncio.run(main())
    assert engine.close_calls == 1


def test_owned_lifespan_closes_engine_on_cancellation() -> None:
    """Cancelling the server body closes its owned engine exactly once."""
    from libtmux.experimental.mcp._lifespan import EngineOwnership, make_lifespan

    engine = _ClosableEngine()
    lifespan = make_lifespan(
        t.cast("t.Any", engine),
        ownership=EngineOwnership.OWNED,
    )

    async def main() -> None:
        entered = asyncio.Event()

        async def serve() -> None:
            async with lifespan(t.cast("t.Any", None)):
                entered.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(serve())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
    assert engine.close_calls == 1


def test_owned_lifespan_drains_close_through_repeated_cancellation() -> None:
    """Repeated cancellation cannot interrupt owned-engine cleanup."""
    from libtmux.experimental.mcp._lifespan import EngineOwnership, make_lifespan

    engine = _DelayedCloseEngine()
    lifespan = make_lifespan(
        t.cast("t.Any", engine),
        ownership=EngineOwnership.OWNED,
    )

    async def main() -> None:
        entered = asyncio.Event()
        body_cancellations: list[asyncio.CancelledError] = []

        async def serve() -> None:
            async with lifespan(t.cast("t.Any", None)):
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError as error:
                    body_cancellations.append(error)
                    raise

        task = asyncio.create_task(serve())
        await entered.wait()
        task.cancel()
        await engine.close_started.wait()
        task.cancel()
        await asyncio.sleep(0)
        remained_pending = not task.done()
        engine.allow_close.set()

        with pytest.raises(asyncio.CancelledError) as raised:
            await task

        assert remained_pending
        assert raised.value is body_cancellations[0]

    asyncio.run(main())
    assert engine.close_calls == 1
    assert engine.close_finished.is_set()


def test_owned_lifespan_propagates_close_error_after_clean_body() -> None:
    """A cleanup failure propagates when no earlier failure is in flight."""
    from libtmux.experimental.mcp._lifespan import EngineOwnership, make_lifespan

    close_error = RuntimeError("close failed")
    engine = _ClosableEngine(close_error=close_error)
    lifespan = make_lifespan(
        t.cast("t.Any", engine),
        ownership=EngineOwnership.OWNED,
    )

    async def main() -> None:
        async with lifespan(t.cast("t.Any", None)):
            pass

    with pytest.raises(RuntimeError, match="close failed") as raised:
        asyncio.run(main())
    assert raised.value is close_error
    assert engine.close_calls == 1


def test_owned_lifespan_chains_close_error_behind_body_error() -> None:
    """A cleanup failure cannot mask an exception from the server body."""
    from libtmux.experimental.mcp._lifespan import EngineOwnership, make_lifespan

    close_error = RuntimeError("close failed")
    engine = _ClosableEngine(close_error=close_error)
    lifespan = make_lifespan(
        t.cast("t.Any", engine),
        ownership=EngineOwnership.OWNED,
    )

    async def main() -> None:
        async with lifespan(t.cast("t.Any", None)):
            msg = "body failed"
            raise LookupError(msg)

    with pytest.raises(LookupError, match="body failed") as raised:
        asyncio.run(main())
    assert raised.value.__cause__ is close_error
    assert engine.close_calls == 1


def test_owned_lifespan_chains_close_error_behind_cancellation() -> None:
    """A cleanup failure cannot replace cancellation of the server body."""
    from libtmux.experimental.mcp._lifespan import EngineOwnership, make_lifespan

    close_error = RuntimeError("close failed")
    engine = _ClosableEngine(close_error=close_error)
    lifespan = make_lifespan(
        t.cast("t.Any", engine),
        ownership=EngineOwnership.OWNED,
    )

    async def main() -> None:
        async with lifespan(t.cast("t.Any", None)):
            task = asyncio.current_task()
            assert task is not None
            task.cancel()
            await asyncio.sleep(0)

    with pytest.raises(asyncio.CancelledError) as raised:
        asyncio.run(main())
    assert raised.value.__cause__ is close_error
    assert engine.close_calls == 1


def test_owned_lifespan_closes_engine_on_preflight_failure() -> None:
    """A failed startup probe closes its owned engine exactly once."""
    from libtmux.experimental.mcp._lifespan import EngineOwnership, make_lifespan

    engine = _ClosableEngine(run_error=ConnectionError("connection lost"))
    lifespan = make_lifespan(
        t.cast("t.Any", engine),
        ownership=EngineOwnership.OWNED,
    )

    async def main() -> None:
        async with lifespan(t.cast("t.Any", None)):
            pass

    with pytest.raises(RuntimeError, match="preflight failed"):
        asyncio.run(main())
    assert engine.close_calls == 1


def test_default_async_server_owns_created_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The convenience factory transfers its created engine to the lifespan."""
    from libtmux.experimental import engines
    from libtmux.experimental.mcp import default_async_server

    engine = _ClosableEngine()
    monkeypatch.setattr(engines, "AsyncControlModeEngine", lambda **_kwargs: engine)

    server = default_async_server(events="off")
    asyncio.run(_enter_server(server))

    assert engine.close_calls == 1


def test_async_cli_owns_created_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """The async CLI transfers its created engine to the server lifespan."""
    from libtmux.experimental import engines
    from libtmux.experimental.mcp import main

    engine = _ClosableEngine()
    servers: list[t.Any] = []
    monkeypatch.setattr(engines, "AsyncControlModeEngine", lambda **_kwargs: engine)
    monkeypatch.setattr(
        fastmcp.FastMCP,
        "run",
        lambda server, **_kwargs: servers.append(server),
    )

    main(["--events", "off", "--no-caller-socket"])
    assert len(servers) == 1
    asyncio.run(_enter_server(servers[0]))

    assert engine.close_calls == 1
