"""Tests for :class:`libtmux.engines.subprocess.AsyncSubprocessEngine`.

Every test runs under :func:`tests._aio.run_checked`: asyncio debug mode, a 50 ms
slow-callback limit, and ``ResourceWarning`` / un-awaited coroutine / destroyed
pending task reported as failures. The cancellation tests count real processes.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import os
import pathlib
import signal
import typing as t

import pytest

from libtmux import exc
from libtmux.engines import (
    AsyncSubprocessEngine,
    AsyncTmuxEngine,
    CommandRequest,
    SubprocessEngine,
    subprocess as engines_subprocess,
)
from libtmux.server import Server

from ._aio import SpawnCounter, processes, run_checked


def request(*args: str, **kwargs: t.Any) -> CommandRequest:
    """Build a request."""
    return CommandRequest.from_args(*args, **kwargs)


def clients(server: Server, subcommand: str = "wait-for") -> list[str]:
    """Return live tmux clients of *server* that run *subcommand*."""
    return processes(f"-L{server.socket_name}", subcommand)


def test_engine_is_an_async_engine(server: Server) -> None:
    """The engine satisfies the protocol and is awaitable, not blocking."""
    engine = AsyncSubprocessEngine.for_server(server)

    assert isinstance(engine, AsyncTmuxEngine)
    assert inspect.iscoroutinefunction(engine.run)
    assert inspect.iscoroutinefunction(engine.aclose)


@pytest.mark.parametrize(
    "args",
    [
        ("display-message", "-p", "#{session_name}"),
        ("has-session", "-t", "no_such_session"),
        ("display-message", "-p", "café \\ back"),
        ("list-sessions", "-F", "#{session_id}"),
        ("no-such-command",),
    ],
)
def test_result_matches_the_blocking_engine(
    server: Server,
    session: t.Any,
    args: tuple[str, ...],
) -> None:
    """Same request, same lines, same status as ``SubprocessEngine``."""
    blocking = SubprocessEngine.for_server(server).run(request(*args))
    engine = AsyncSubprocessEngine.for_server(server)

    async def main() -> t.Any:
        return await engine.run(request(*args))

    result = run_checked(main)

    assert result.cmd == blocking.cmd
    assert result.stdout == blocking.stdout
    assert result.stderr == blocking.stderr
    assert result.returncode == blocking.returncode


def test_input_round_trips(server: Server, session: t.Any) -> None:
    """A 60 KB payload through ``load-buffer -`` comes back line for line."""
    lines = [f"line {n} caf\u00e9" for n in range(5000)]
    payload = "\n".join(lines).encode()
    engine = AsyncSubprocessEngine.for_server(server)

    async def main() -> tuple[str, ...]:
        loaded = await engine.run(
            request("load-buffer", "-b", "aio_input", "-", input=payload),
        )
        assert loaded.ok
        return (await engine.run(request("save-buffer", "-b", "aio_input", "-"))).stdout

    assert len(payload) > 50_000
    assert run_checked(main) == tuple(lines)


def test_run_batch_is_ordered(server: Server, session: t.Any) -> None:
    """Results come back in request order."""
    engine = AsyncSubprocessEngine.for_server(server)

    async def main() -> list[tuple[str, ...]]:
        results = await engine.run_batch(
            [request("display-message", "-p", str(n)) for n in range(5)],
        )
        return [r.stdout for r in results]

    assert run_checked(main) == [(str(n),) for n in range(5)]


def test_missing_binary_is_tmux_command_not_found() -> None:
    """A binary that does not exist is an engine failure, not a result."""
    engine = AsyncSubprocessEngine.of("/nonexistent/tmux")

    async def main() -> None:
        await engine.run(request("list-sessions"))

    with pytest.raises(exc.TmuxCommandNotFound):
        run_checked(main)


def test_closed_engine_refuses_work(server: Server) -> None:
    """After ``aclose`` a call raises ``EngineClosed`` and starts nothing."""
    engine = AsyncSubprocessEngine.for_server(server)

    async def main() -> None:
        await engine.aclose()
        await engine.aclose()  # twice is fine
        await engine.run(request("list-sessions"))

    with pytest.raises(exc.EngineClosed):
        run_checked(main)


def test_timeout_kills_and_reaps_the_client(server: Server, session: t.Any) -> None:
    """A request ``timeout`` raises ``TmuxTimeout`` and leaves no client."""
    engine = AsyncSubprocessEngine.for_server(server)

    async def main() -> exc.TmuxTimeout:
        try:
            await engine.run(request("wait-for", "aio_timeout", timeout=0.2))
        except exc.TmuxTimeout as error:
            return error
        msg = "wait-for returned"
        raise AssertionError(msg)

    error = run_checked(main)

    assert error.timeout == 0.2
    assert clients(server) == []


def test_cancelling_in_flight_commands_leaves_no_client(
    server: Server,
    session: t.Any,
    spawns: SpawnCounter,
) -> None:
    """Cancel ten blocked commands: ten started, zero tmux clients remain."""
    engine = AsyncSubprocessEngine.for_server(server)
    count = 10

    async def main() -> tuple[int, int]:
        started = spawns.expect(count)
        tasks = [
            asyncio.ensure_future(engine.run(request("wait-for", f"aio_cancel_{n}")))
            for n in range(count)
        ]
        await started.wait()
        for task in tasks:
            task.cancel()
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(o, asyncio.CancelledError) for o in outcomes)
        # Reaped by the time the cancelled calls returned, not eventually.
        assert [p.returncode for p in spawns.processes] == [-9] * count
        return spawns.started, len(outcomes)

    started, cancelled = run_checked(main)

    assert (started, cancelled) == (count, count)
    assert clients(server) == []


def test_cancel_during_reap_still_reaps(
    server: Server,
    session: t.Any,
    spawns: SpawnCounter,
) -> None:
    """A second cancel while the first is cleaning up cannot leave a zombie."""
    engine = AsyncSubprocessEngine.for_server(server)

    async def main() -> None:
        started = spawns.expect(1)
        task = asyncio.ensure_future(engine.run(request("wait-for", "aio_twice")))
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)  # let the first cancel start the cleanup
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        (process,) = spawns.processes
        assert process.returncode == -9  # the second cancel did not skip the reap

    run_checked(main)

    assert clients(server) == []


def test_cancelled_engine_keeps_serving(server: Server, session: t.Any) -> None:
    """A cancelled call does not poison the engine: the next one works."""
    engine = AsyncSubprocessEngine.for_server(server)

    async def main() -> tuple[str, ...]:
        task = asyncio.ensure_future(engine.run(request("wait-for", "aio_after")))
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return (await engine.run(request("display-message", "-p", "again"))).stdout

    assert run_checked(main) == ("again",)


def test_concurrent_commands_never_hold_the_loop(
    server: Server,
    session: t.Any,
) -> None:
    """Twenty commands in flight: no callback holds the loop past 50 ms.

    :func:`run_checked` fails the run on any slow callback, so a blocking call
    hidden in the engine, such as a synchronous ``subprocess.run``, fails here.
    """
    engine = AsyncSubprocessEngine.for_server(server)

    async def main() -> int:
        results = await asyncio.gather(
            *(engine.run(request("display-message", "-p", str(n))) for n in range(20)),
        )
        return len(results)

    assert run_checked(main) == 20


def test_async_engine_is_refused_by_the_blocking_server(server: Server) -> None:
    """``Server`` takes a blocking engine only; an async one is named in the error."""
    blocked = Server(
        socket_name=server.socket_name,
        engine=AsyncSubprocessEngine(),  # type: ignore[arg-type]
    )

    with pytest.raises(exc.AsyncEngineMismatch):
        blocked.cmd("list-sessions")


def test_cancel_kills_the_whole_process_group(
    tmp_path: pathlib.Path,
    spawns: SpawnCounter,
) -> None:
    """A transport's children die with it: no grandchild outlives a cancel."""
    pid_file = tmp_path / "grandchild.pid"
    cmd = ("sh", "-c", 'sleep 300 & echo $! > "$0"; wait', str(pid_file))

    async def main() -> int:
        started = spawns.expect(1)
        task = asyncio.ensure_future(
            engines_subprocess.run_argv_async(cmd, request("x")),
        )
        await started.wait()
        while not pid_file.exists() or not pid_file.read_text().strip():
            await asyncio.sleep(0.005)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return int(pid_file.read_text())

    grandchild = run_checked(main)

    try:
        with pytest.raises(ProcessLookupError):
            os.kill(grandchild, 0)
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(grandchild, signal.SIGKILL)
