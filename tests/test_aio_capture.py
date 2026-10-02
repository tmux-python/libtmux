"""Tests for :mod:`libtmux.aio.capture`: ``capture_since`` and ``wait_for_text``.

Every test runs under :func:`tests._aio.run_checked`.
"""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux import exc
from libtmux.aio.capture import capture_since, wait_for_text
from libtmux.engines import (
    AsyncControlModeEngine,
    AsyncSubprocessEngine,
    CommandRequest,
    CommandResult,
)
from libtmux.server import Server

from ._aio import processes, run_checked

if t.TYPE_CHECKING:
    from libtmux.pane import Pane


def request(*args: str, **kwargs: t.Any) -> CommandRequest:
    """Build a request."""
    return CommandRequest.from_args(*args, **kwargs)


class Counting:
    """An async engine wrapper that counts what it is asked to run."""

    def __init__(self, inner: t.Any) -> None:
        self.inner = inner
        self.subcommands: list[str] = []

    def __getattr__(self, name: str) -> t.Any:
        """Forward everything else, such as ``watch_output``, to the engine."""
        return getattr(self.inner, name)

    async def run(self, req: CommandRequest) -> CommandResult:
        """Count the subcommand, then run it."""
        self.subcommands.append(req.subcommand)
        result: CommandResult = await self.inner.run(req)
        return result

    async def run_batch(self, reqs: t.Sequence[CommandRequest]) -> list[CommandResult]:
        """Run in order through :meth:`run`."""
        return [await self.run(req) for req in reqs]

    async def aclose(self) -> None:
        """Close the wrapped engine."""
        await self.inner.aclose()


def shell_pane(server: Server, name: str) -> Pane:
    """Return the pane of a new ``sh`` session."""
    session = server.new_session(name, window_command="sh")
    pane = session.active_window.active_pane
    assert pane is not None
    return pane


def test_capture_since_matches_the_blocking_api(server: Server) -> None:
    """The same cursor rules: first read is the screen, a second read is empty."""
    pane = shell_pane(server, "parity")
    pane_id = str(pane.pane_id)
    pane.send_keys("echo one; echo two")
    sync_first = pane.capture_since()

    async def main() -> tuple[t.Any, t.Any]:
        engine = AsyncSubprocessEngine.for_server(server)
        first = await capture_since(engine, pane_id)
        again = await capture_since(engine, pane_id, first.cursor)
        return first, again

    first, again = run_checked(main)

    assert first.lines == sync_first.lines
    assert again.lines == []
    assert not again.lines_missed
    # A cursor is a value both drivers read.
    assert pane.capture_since(first.cursor).lines == []


def test_a_cursor_for_another_pane_is_refused(server: Server) -> None:
    """Reading pane B with pane A's cursor is an error, not a guess."""
    pane_a = shell_pane(server, "cursor_a")
    pane_b = shell_pane(server, "cursor_b")

    async def main() -> None:
        engine = AsyncSubprocessEngine.for_server(server)
        cursor = (await capture_since(engine, str(pane_a.pane_id))).cursor
        await capture_since(engine, str(pane_b.pane_id), cursor)

    with pytest.raises(exc.InvalidCaptureCursor):
        run_checked(main)


def test_text_printed_before_the_wait_is_found_at_once(server: Server) -> None:
    """Subscribe, read once, find it: no sleep, no second read."""
    pane = shell_pane(server, "early")
    pane_id = str(pane.pane_id)

    async def main() -> tuple[str, int, float]:
        async with AsyncControlModeEngine.for_server(server) as inner:
            engine = Counting(inner)
            await engine.run(request("display-message", "-p", "attach"))
            anchor = (await capture_since(engine, pane_id)).cursor
            await engine.run(
                request(
                    "send-keys", "-t", pane_id, "printf '%s%s\\n' early_ text", "Enter"
                ),
            )
            # Let the pane print before the wait begins.
            await _until_printed(engine, pane_id, "early_text")
            engine.subcommands.clear()
            started = asyncio.get_running_loop().time()
            hit = await wait_for_text(
                engine,
                pane_id,
                "early_text",
                since=anchor,
                timeout=10,
                fallback=5.0,
            )
            took = asyncio.get_running_loop().time() - started
            return hit.match.string, engine.subcommands.count("capture-pane"), took

    row, captures, took = run_checked(main)

    assert row == "early_text"
    assert captures <= 3  # the first read and its cursor rows, not a poll loop
    assert took < 2.5  # found by the first read, not after a fallback sleep


async def _until_printed(engine: t.Any, pane_id: str, text: str) -> None:
    """Return once *text* is on the pane's screen; reads, never sleeps blindly."""
    watch = engine.watch_output(pane_id)
    try:
        while True:
            rows = await engine.run(request("capture-pane", "-p", "-t", pane_id))
            if text in "\n".join(rows.stdout).replace(" ", ""):
                return
            await watch.changed(5)
    finally:
        watch.close()


def test_text_that_never_comes_times_out_without_polling(server: Server) -> None:
    """A quiet pane costs a couple of reads for the whole wait, not one per tick."""
    pane = shell_pane(server, "quiet")
    pane_id = str(pane.pane_id)

    async def main() -> tuple[exc.WaitTimeout, int]:
        async with AsyncControlModeEngine.for_server(server) as inner:
            engine = Counting(inner)
            await engine.run(request("display-message", "-p", "attach"))
            engine.subcommands.clear()
            try:
                await wait_for_text(engine, pane_id, "never_printed", timeout=0.6)
            except exc.WaitTimeout as error:
                return error, engine.subcommands.count("capture-pane")
        msg = "found text that was never printed"
        raise AssertionError(msg)

    error, captures = run_checked(main)

    assert "never_printed" in str(error)
    assert captures <= 8  # polling at 10 ms would be about sixty


def test_text_printed_during_the_wait_wakes_it(server: Server) -> None:
    """The wait sleeps until the pane prints, then finds the text."""
    pane = shell_pane(server, "late")
    pane_id = str(pane.pane_id)

    async def main() -> str:
        async with AsyncControlModeEngine.for_server(server) as engine:
            await engine.run(request("display-message", "-p", "attach"))
            anchor = (await capture_since(engine, pane_id)).cursor
            waiter = asyncio.ensure_future(
                wait_for_text(engine, pane_id, "late_marker", since=anchor, timeout=30),
            )
            await engine.run(
                request(
                    "send-keys", "-t", pane_id, "printf '%s%s\\n' late_ marker", "Enter"
                ),
            )
            return (await waiter).match.string

    assert run_checked(main) == "late_marker"


def test_the_typed_command_is_not_the_text(server: Server) -> None:
    """The echo of the command that produces the text does not satisfy the wait."""
    pane = shell_pane(server, "echo")
    pane_id = str(pane.pane_id)

    async def main() -> tuple[str, int]:
        async with AsyncControlModeEngine.for_server(server) as engine:
            await engine.run(request("display-message", "-p", "attach"))
            anchor = (await capture_since(engine, pane_id)).cursor
            waiter = asyncio.ensure_future(
                wait_for_text(engine, pane_id, "needle", since=anchor, timeout=30),
            )
            await engine.run(
                request(
                    "send-keys", "-t", pane_id, "printf '%s%s\\n' nee dle", "Enter"
                ),
            )
            hit = await waiter
            return hit.match.string, int(hit.lines_missed)

    assert run_checked(main) == ("needle", 0)


def test_a_wait_works_without_a_control_connection(server: Server) -> None:
    """A subprocess engine has no wake-ups, so the wait polls, and still finds it."""
    pane = shell_pane(server, "poll")
    pane_id = str(pane.pane_id)

    async def main() -> str:
        engine = AsyncSubprocessEngine.for_server(server)
        anchor = (await capture_since(engine, pane_id)).cursor
        waiter = asyncio.ensure_future(
            wait_for_text(engine, pane_id, "poll_marker", since=anchor, timeout=30),
        )
        await engine.run(
            request(
                "send-keys", "-t", pane_id, "printf '%s%s\\n' poll_ marker", "Enter"
            ),
        )
        return (await waiter).match.string

    assert run_checked(main) == "poll_marker"


def test_cancelling_a_wait_leaves_no_watch_and_no_process(server: Server) -> None:
    """Cancel mid-wait: the output watch is closed and no tmux client is left."""
    pane = shell_pane(server, "cancel_wait")
    pane_id = str(pane.pane_id)

    async def main() -> tuple[int, int]:
        engine = AsyncControlModeEngine.for_server(server)
        await engine.run(request("display-message", "-p", "attach"))
        waiter = asyncio.ensure_future(
            wait_for_text(engine, pane_id, "never_printed", timeout=60),
        )
        # Let the wait subscribe and take its first read.
        while pane_id not in engine._watches:
            await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        watches = sum(len(w) for w in engine._watches.values())
        await engine.aclose()
        return watches, len(engine._outputs)

    assert run_checked(main) == (0, 0)
    assert processes(f"-L{server.socket_name}", " -C ", "attach-session") == []
