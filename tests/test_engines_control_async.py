"""Tests for :class:`libtmux.engines.control.aio.AsyncControlModeEngine`.

Every test runs under :func:`tests._aio.run_checked`: asyncio debug mode, a 50 ms
slow-callback limit, and ``ResourceWarning`` / un-awaited coroutine / destroyed
pending task reported as failures. Client counts come from ``ps``, and the
tests that must control timing drive a fake ``tmux`` that speaks the protocol.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import os
import pathlib
import signal
import stat
import sys
import textwrap
import typing as t
import uuid

import pytest

from libtmux import exc
from libtmux.engines import (
    AsyncSubprocessEngine,
    AsyncTmuxEngine,
    CommandRequest,
    CommandSeparator,
    SubprocessEngine,
)
from libtmux.engines.control import aio as control_aio, protocol
from libtmux.engines.control.aio import (
    RECONNECTED,
    AsyncControlModeEngine,
    Lagged,
)
from libtmux.engines.control.flow import Gap
from libtmux.server import Server

from ._aio import SpawnCounter, processes, run_checked
from .test_engines_exec import Shims, shims  # noqa: F401  (a fixture)

if t.TYPE_CHECKING:
    from libtmux.session import Session


def request(*args: str, **kwargs: t.Any) -> CommandRequest:
    """Build a request."""
    return CommandRequest.from_args(*args, **kwargs)


def control_clients(server: Server) -> list[str]:
    """Return live control-mode clients of *server*."""
    return processes(f"-L{server.socket_name}", " -C ", "attach-session")


FAKE_TMUX = textwrap.dedent(
    """\
    #!{python}
    import shlex, sys, time
    argv = sys.argv[1:]
    if "list-sessions" in argv:
        print("$0 0")
        sys.exit(0)
    if "-C" in argv:
        n = 1
        sys.stdout.write("%%begin 1 %d 0\\n%%end 1 %d 0\\n" % (n, n))
        sys.stdout.flush()
        for line in sys.stdin:
            n += 1
            words = shlex.split(line)
            if "garbage" in words:
                sys.stdout.write("%begin nonsense\\n"); sys.stdout.flush()
                continue
            if "slow" in words:
                time.sleep(0.4)
            if "exit" in words:
                sys.exit(3)
            body = " ".join(words)
            sys.stdout.write("%%begin 1 %d 1\\nok:%s\\n%%end 1 %d 1\\n" % (n, body, n))
            sys.stdout.flush()
        if any("hang" in a for a in argv):
            time.sleep(300)  # EOF on stdin does not make this client detach
        sys.exit(0)
    sys.exit(1)
    """,
)


@pytest.fixture
def fake_tmux(tmp_path: pathlib.Path) -> str:
    """Return a fake ``tmux`` whose replies a test can delay or corrupt."""
    script = tmp_path / "tmux"
    script.write_text(FAKE_TMUX.replace("{python}", sys.executable))
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


def test_engine_satisfies_the_async_protocol(server: Server) -> None:
    """It is an async engine, bound to the server's socket."""
    engine = AsyncControlModeEngine.for_server(server)

    assert isinstance(engine, AsyncTmuxEngine)
    assert engine.server_args[0].startswith("-L")
    assert engine.generation == 0
    assert not engine.connected


@pytest.mark.parametrize(
    "args",
    [
        ("display-message", "-p", "#{session_name}"),
        ("display-message", "-p", "café 'quoted' \"dq\" $HOME ; semi"),
        ("list-sessions", "-F", "#{session_id}"),
        ("has-session", "-t", "no_such_session"),
        ("no-such-command",),
        (
            "display-message",
            "-p",
            "a",
            CommandSeparator(";"),
            "display-message",
            "-p",
            "b",
        ),
    ],
)
def test_results_match_the_subprocess_engine(
    server: Server,
    session: Session,
    args: tuple[str, ...],
) -> None:
    """Same request, same lines, same status as a forked client."""
    reference = SubprocessEngine.for_server(server).run(request(*args))

    async def main() -> t.Any:
        async with AsyncControlModeEngine.for_server(server) as engine:
            return await engine.run(request(*args))

    result = run_checked(main)

    assert result.stdout == reference.stdout
    assert result.stderr == reference.stderr
    assert result.returncode == reference.returncode
    assert result.cmd == reference.cmd


def test_replies_reach_the_caller_that_asked(server: Server, session: Session) -> None:
    """A hundred concurrent calls each get their own reply.

    More tasks than this in one loop turn make asyncio debug mode, which records
    a stack per task, the slow callback rather than the engine.
    """

    async def main() -> list[tuple[str, ...]]:
        async with AsyncControlModeEngine.for_server(server) as engine:
            results = await asyncio.gather(
                *(
                    engine.run(request("display-message", "-p", f"n{n}"))
                    for n in range(100)
                ),
            )
            assert engine.generation == 1
            return [r.stdout for r in results]

    assert run_checked(main) == [(f"n{n}",) for n in range(100)]
    assert control_clients(server) == []


def test_a_batch_is_pipelined_in_order(server: Server, session: Session) -> None:
    """``run_batch`` writes together and returns results in request order."""

    async def main() -> list[tuple[str, ...]]:
        async with AsyncControlModeEngine.for_server(server) as engine:
            results = await engine.run_batch(
                [request("display-message", "-p", str(n)) for n in range(25)],
            )
            return [r.stdout for r in results]

    assert run_checked(main) == [(str(n),) for n in range(25)]


def test_with_no_session_it_falls_back_and_creates_nothing(server: Server) -> None:
    """No session to attach to: run in a subprocess, never invent a session."""

    async def main() -> tuple[int, int, bool]:
        async with AsyncControlModeEngine.for_server(server) as engine:
            result = await engine.run(request("has-session", "-t", "none"))
            return result.returncode, engine.generation, engine.connected

    returncode, generation, connected = run_checked(main)

    assert returncode == 1
    assert (generation, connected) == (0, False)
    assert server.sessions == []


def test_a_session_that_appears_is_used_on_the_next_call(server: Server) -> None:
    """The first call falls back; once a session exists the client attaches."""

    async def main() -> tuple[int, int]:
        async with AsyncControlModeEngine.for_server(server) as engine:
            first = await engine.run(
                request("new-session", "-d", "-s", f"late_{uuid.uuid4().hex[:8]}"),
            )
            assert first.ok
            await engine.run(request("display-message", "-p", "x"))
            return engine.generation, int(engine.connected)

    assert run_checked(main) == (1, 1)
    assert control_clients(server) == []


def test_blocking_commands_do_not_hold_the_connection(
    server: Server,
    session: Session,
) -> None:
    """``wait-for`` goes to a subprocess, so a fast command is not queued behind it."""

    async def main() -> tuple[tuple[str, ...], bool]:
        async with AsyncControlModeEngine.for_server(server) as engine:
            await engine.run(request("display-message", "-p", "attach"))
            blocked = asyncio.ensure_future(
                engine.run(request("wait-for", "aio_control_hold")),
            )
            fast = asyncio.ensure_future(
                engine.run(request("display-message", "-p", "fast")),
            )
            done, _ = await asyncio.wait({fast}, timeout=5)
            still_waiting = not blocked.done()
            if fast not in done:
                msg = "a fast command was held behind wait-for"
                raise AssertionError(msg)
            await engine.run(request("wait-for", "-S", "aio_control_hold"))
            await blocked
            return fast.result().stdout, still_waiting

    assert run_checked(main) == (("fast",), True)


def test_input_goes_to_a_subprocess(server: Server, session: Session) -> None:
    """A request with stdin never rides the connection."""

    async def main() -> tuple[str, ...]:
        async with AsyncControlModeEngine.for_server(server) as engine:
            loaded = await engine.run(
                request("load-buffer", "-b", "aio_ctl", "-", input="from stdin"),
            )
            assert loaded.ok
            return (await engine.run(request("show-buffer", "-b", "aio_ctl"))).stdout

    assert run_checked(main) == ("from stdin",)


def test_cancelling_calls_keeps_replies_aligned(
    server: Server,
    session: Session,
) -> None:
    """Cancel a call right after its line is written: later replies still match."""

    async def main() -> list[tuple[str, ...]]:
        out: list[tuple[str, ...]] = []
        async with AsyncControlModeEngine.for_server(server) as engine:
            await engine.run(request("display-message", "-p", "attach"))
            for n in range(60):
                doomed = asyncio.ensure_future(
                    engine.run(
                        request(
                            "display-message",
                            "-p",
                            "a",
                            CommandSeparator(";"),
                            "display-message",
                            "-p",
                            "b",
                        ),
                    ),
                )
                await asyncio.sleep(0)  # let the line be written
                doomed.cancel()
                kept = await engine.run(request("display-message", "-p", f"k{n}"))
                out.append(kept.stdout)
            assert engine.generation == 1
        return out

    assert run_checked(main) == [(f"k{n}",) for n in range(60)]


def test_a_timeout_abandons_the_reply_and_keeps_the_connection(
    fake_tmux: str,
) -> None:
    """The slow reply is read and dropped; the next call gets its own."""

    async def main() -> tuple[str, tuple[str, ...], int]:
        async with AsyncControlModeEngine(fake_tmux) as engine:
            with pytest.raises(exc.TmuxTimeout) as excinfo:
                await engine.run(request("slow", timeout=0.05))
            after = await engine.run(request("echo", "after"))
            return str(excinfo.value.timeout), after.stdout, engine.generation

    assert run_checked(main) == ("0.05", ("ok:echo after",), 1)


def test_cancelling_a_slow_call_keeps_replies_aligned(fake_tmux: str) -> None:
    """A cancelled slow call leaves its reply to be dropped, not mispaired."""

    async def main() -> list[tuple[str, ...]]:
        async with AsyncControlModeEngine(fake_tmux) as engine:
            doomed = asyncio.ensure_future(engine.run(request("slow")))
            await asyncio.sleep(0)
            doomed.cancel()
            a, b = await asyncio.gather(
                engine.run(request("echo", "one")),
                engine.run(request("echo", "two")),
            )
            return [a.stdout, b.stdout]

    assert run_checked(main) == [("ok:echo one",), ("ok:echo two",)]


def test_a_dead_server_fails_what_the_client_owed(
    server: Server,
    session: Session,
) -> None:
    """Stop the server, queue a call, kill the server: ``ControlConnectionLost``.

    The client process is not in the data path (tmux hands its pipes to the
    server), so stopping the server is what leaves a call owed a reply.
    """
    server_pid = int(server.cmd("display-message", "-p", "#{pid}").stdout[0])

    async def main() -> tuple[str, int, bool]:
        async with AsyncControlModeEngine.for_server(server) as engine:
            await engine.run(request("display-message", "-p", "attach"))
            os.kill(server_pid, signal.SIGSTOP)
            pending = asyncio.ensure_future(
                engine.run(request("display-message", "-p", "lost")),
            )
            await asyncio.sleep(0)
            os.kill(server_pid, signal.SIGKILL)
            with pytest.raises(exc.ControlConnectionLost) as excinfo:
                await pending
            return str(excinfo.value), engine.generation, engine.connected

    message, generation, connected = run_checked(main)

    assert message.startswith("the control client exited")
    assert (generation, connected) == (1, False)


def test_the_next_call_reconnects_after_the_client_dies(
    server: Server,
    session: Session,
) -> None:
    """Kill the client, wait for the reader to notice, then call again."""

    async def main() -> tuple[int, tuple[str, ...]]:
        async with AsyncControlModeEngine.for_server(server) as engine:
            await engine.run(request("display-message", "-p", "attach"))
            link = engine._link
            assert link is not None
            os.kill(link.process.pid, signal.SIGKILL)
            await link.dead.wait()
            assert not engine.connected
            again = await engine.run(request("display-message", "-p", "back"))
            return engine.generation, again.stdout

    assert run_checked(main) == (2, ("back",))


def test_the_supervisor_reconnects_for_a_subscriber(
    server: Server,
    session: Session,
) -> None:
    """With a subscriber, a dead client is replaced without any call, and told."""

    async def main() -> tuple[int, str]:
        async with AsyncControlModeEngine.for_server(server) as engine:
            await engine.run(request("display-message", "-p", "attach"))
            with engine.notifications() as events:
                link = engine._link
                assert link is not None
                os.kill(link.process.pid, signal.SIGKILL)
                async for event in events:
                    if (
                        isinstance(event, protocol.Notification)
                        and event.name == RECONNECTED
                    ):
                        return engine.generation, event.args
        msg = "stream ended without a reconnect"
        raise AssertionError(msg)

    assert run_checked(main) == (2, "2")


def test_aclose_leaves_no_client_and_ends_every_iterator(
    server: Server,
    session: Session,
) -> None:
    """Closing detaches the client and ends subscribers; a second close is fine."""

    async def main() -> int:
        engine = AsyncControlModeEngine.for_server(server)
        await engine.run(request("display-message", "-p", "attach"))
        events = engine.notifications()
        ended = asyncio.ensure_future(_drain(events))
        assert engine.connected
        await engine.aclose()
        await engine.aclose()
        await asyncio.wait_for(ended, 5)
        with pytest.raises(exc.EngineClosed):
            await engine.run(request("display-message", "-p", "late"))
        return 0

    # `ps` and `list-clients` fork a process, so they run outside the loop.
    assert run_checked(main) == 0
    assert control_clients(server) == []
    assert server.cmd("list-clients").stdout == []


async def _drain(stream: t.AsyncIterator[t.Any]) -> None:
    async for _ in stream:
        pass


def test_a_protocol_error_discards_the_connection(fake_tmux: str) -> None:
    """Malformed framing raises, kills the client, and the next call reconnects."""

    async def main() -> tuple[int, tuple[str, ...]]:
        async with AsyncControlModeEngine(fake_tmux) as engine:
            await engine.run(request("echo", "first"))
            with pytest.raises(exc.ControlProtocolError):
                await engine.run(request("garbage"))
            again = await engine.run(request("echo", "second"))
            return engine.generation, again.stdout

    assert run_checked(main) == (2, ("ok:echo second",))


def test_cancelling_during_connect_leaves_no_client(
    server: Server,
    session: Session,
    spawns: SpawnCounter,
) -> None:
    """Cancel after the control client is spawned, at every point until attach."""

    async def main() -> None:
        engine = AsyncControlModeEngine.for_server(server)
        for turns in range(10):
            # Two spawns per attempt: the `list-sessions` probe, then the client.
            spawned = spawns.expect(spawns.started + 2)
            task = asyncio.ensure_future(
                engine.run(request("display-message", "-p", "x")),
            )
            await spawned.wait()
            for _ in range(turns):
                await asyncio.sleep(0)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if engine._link is not None:  # it attached before the cancel landed
                await engine.aclose()
                engine = AsyncControlModeEngine.for_server(server)
        await engine.aclose()

    run_checked(main)

    assert control_clients(server) == []


def test_aclose_kills_a_client_that_will_not_detach(
    fake_tmux: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A client that ignores EOF on stdin is killed and reaped, not left behind."""
    monkeypatch.setattr(control_aio, "_DETACH_TIMEOUT", 0.05)

    async def main() -> int | None:
        engine = AsyncControlModeEngine(fake_tmux, server_args=("-Lhang",))
        await engine.run(request("echo", "up"))
        link = engine._link
        assert link is not None
        await engine.aclose()
        return link.process.returncode

    assert run_checked(main) == -signal.SIGKILL


def test_notifications_fan_out(server: Server, session: Session) -> None:
    """Every subscriber sees a notification, with the tmux name and arguments."""

    async def main() -> tuple[list[str], list[str]]:
        async with AsyncControlModeEngine.for_server(server) as engine:
            await engine.run(request("display-message", "-p", "attach"))
            with engine.notifications() as one, engine.notifications() as two:
                await engine.run(
                    request("rename-session", "-t", str(session.session_id), "renamed"),
                )
                return await _first_named(one, "session-renamed"), await _first_named(
                    two,
                    "session-renamed",
                )

    first, second = run_checked(main)

    assert first == second
    assert first[0].endswith(" renamed")


async def _first_named(stream: t.AsyncIterator[t.Any], name: str) -> list[str]:
    async for event in stream:
        if isinstance(event, protocol.Notification) and event.name == name:
            return [event.args]
    return []


def test_a_slow_subscriber_sees_lag_where_it_happened(
    server: Server,
    session: Session,
) -> None:
    """Overflow is an in-order ``Lagged``, never a silent drop or a bare counter."""
    renames = 40

    async def main() -> list[t.Any]:
        async with AsyncControlModeEngine.for_server(server) as engine:
            await engine.run(request("display-message", "-p", "attach"))
            with engine.notifications(maxsize=5) as events:
                for n in range(renames):
                    await engine.run(
                        request(
                            "rename-session",
                            "-t",
                            str(session.session_id),
                            f"name{n}",
                        ),
                    )
                await engine.run(request("display-message", "-p", "sync"))
            return [event async for event in events]

    items = run_checked(main)

    assert isinstance(items[-1], Lagged)
    assert all(isinstance(i, protocol.Notification) for i in items[:5])
    delivered = sum(1 for i in items if isinstance(i, protocol.Notification))
    lagged = sum(i.count for i in items if isinstance(i, Lagged))
    assert delivered == 5
    assert delivered + lagged >= renames


def test_a_closed_engine_hands_out_ended_streams(server: Server) -> None:
    """``notifications`` and ``output`` after close return iterators already ended."""

    async def main() -> tuple[list[t.Any], list[t.Any]]:
        engine = AsyncControlModeEngine.for_server(server)
        await engine.aclose()
        return (
            [item async for item in engine.notifications()],
            [item async for item in engine.output("%0")],
        )

    assert run_checked(main) == ([], [])


def test_remote_control_through_a_transport(
    server: Server,
    session: Session,
    shims: Shims,  # noqa: F811
) -> None:
    """``prefix=`` puts one persistent client behind a transport command."""

    async def main() -> tuple[tuple[str, ...], int]:
        async with AsyncControlModeEngine(
            server_args=(f"-L{server.socket_name}",),
            prefix=("docker", "exec", "-i", "box"),
        ) as engine:
            result = await engine.run(request("display-message", "-p", "remote"))
            await engine.run(request("display-message", "-p", "again"))
            return result.stdout, engine.generation

    assert run_checked(main) == (("remote",), 1)
    calls = shims.calls()
    assert any("-C" in call for call in calls)
    assert sum("-C" in call for call in calls) == 1


async def flood(server: Server, pane_id: str, lines: int) -> None:
    """Print *lines* numbered lines in *pane_id*, then signal ``flood_done``.

    The pane then prints ``SENTINEL`` every 50 ms, so the stream has something
    to deliver once a paused pane resumes. The word is split in the typed line,
    so the echo of that line is not mistaken for it.
    """
    engine = AsyncSubprocessEngine.for_server(server)
    done = f"tmux -L{server.socket_name} wait-for -S flood_done"
    await engine.run(
        request(
            "send-keys",
            "-t",
            pane_id,
            f"i=1; while [ $i -le {lines} ]; do echo L$i; i=$((i+1)); done; {done}; "
            "while :; do echo SEN''TINEL; sleep 0.05; done",
            "Enter",
        ),
    )


def numbers(chunks: list[bytes]) -> list[int]:
    """Return the ``L<n>`` numbers in a byte stream, in order."""
    text = b"".join(chunks).decode("utf-8", "replace").replace("\r", " ")
    return [int(w[1:]) for w in text.split() if w[:1] == "L" and w[1:].isdigit()]


def test_output_stream_is_bounded_and_reports_every_gap(server: Server) -> None:
    """A slow consumer: the queue stays bounded and loss only ever shows as a Gap."""
    session = server.new_session("flood", window_command="sh")
    pane = session.active_window.active_pane
    assert pane is not None
    pane_id = str(pane.pane_id)
    total = 6000
    high = 8192

    async def consume(channel: t.Any) -> list[list[bytes]]:
        segments: list[list[bytes]] = [[]]
        async for item in channel:
            if isinstance(item, Gap):
                segments.append([])
                continue
            segments[-1].append(item)
            await asyncio.sleep(0.002)  # a consumer slower than the shell
            if b"SENTINEL" in item:
                break
        return segments

    async def main() -> tuple[list[list[bytes]], int, int]:
        async with AsyncControlModeEngine.for_server(server) as engine:
            await engine.run(request("display-message", "-p", "attach"))
            channel = engine.output(pane_id, high=high, low=2048)
            consumer = asyncio.ensure_future(consume(channel))
            finished = asyncio.ensure_future(
                AsyncSubprocessEngine.for_server(server).run(
                    request("wait-for", "flood_done"),
                ),
            )
            await flood(server, pane_id, total)
            await asyncio.wait_for(finished, 60)
            segments = await asyncio.wait_for(consumer, 60)
            channel.close()
            return segments, channel.peak, channel.gaps

    segments, peak, gaps = run_checked(main)

    # Inside a segment the numbers are consecutive, so a hole can only sit at a
    # Gap: nothing was dropped silently.
    for segment in segments:
        nums = numbers(segment)
        for before, after in itertools.pairwise(nums):
            assert after == before + 1, (before, after)
    assert gaps >= 1
    assert len(segments) == gaps + 1
    assert peak < high * 8


def test_watch_output_wakes_on_output_and_times_out_when_quiet(
    server: Server,
) -> None:
    """A watch returns when the pane prints, and ``False`` when it stays quiet."""
    session = server.new_session("watch", window_command="sh")
    pane = session.active_window.active_pane
    assert pane is not None
    pane_id = str(pane.pane_id)

    async def main() -> tuple[bool, bool]:
        async with AsyncControlModeEngine.for_server(server) as engine:
            await engine.run(request("display-message", "-p", "attach"))
            with engine.watch_output(pane_id) as watch:
                await engine.run(
                    request("send-keys", "-t", pane_id, "echo hi", "Enter")
                )
                woke = await watch.changed(timeout=5)
                await watch.changed(timeout=0.2)  # drain the echo of the prompt
                await watch.changed(timeout=0.2)
                quiet = await watch.changed(timeout=0.1)
            return woke, quiet

    assert run_checked(main) == (True, False)


def test_output_is_off_until_someone_listens(server: Server) -> None:
    """The client asks for no pane output, and turns it on only for a listener."""
    session = server.new_session("gate", window_command="sh")
    pane = session.active_window.active_pane
    assert pane is not None
    pane_id = str(pane.pane_id)

    async def main() -> tuple[str, str]:
        async with AsyncControlModeEngine.for_server(server) as engine:
            await engine.run(request("display-message", "-p", "attach"))
            quiet = await engine.run(
                request("list-clients", "-F", "#{client_control_mode} #{client_flags}")
            )
            with engine.watch_output(pane_id):
                await engine.run(request("display-message", "-p", "sync"))
                loud = await engine.run(
                    request(
                        "list-clients", "-F", "#{client_control_mode} #{client_flags}"
                    )
                )
            return quiet.stdout[0], loud.stdout[0]

    quiet, loud = run_checked(main)

    assert "no-output" in quiet
    assert "no-output" not in loud


def test_a_stream_gap_marks_a_reconnect(server: Server) -> None:
    """When the client dies, an open stream is told output may have been lost."""
    session = server.new_session("regap", window_command="sh")
    pane = session.active_window.active_pane
    assert pane is not None
    pane_id = str(pane.pane_id)

    async def main() -> bool:
        async with AsyncControlModeEngine.for_server(server) as engine:
            await engine.run(request("display-message", "-p", "attach"))
            channel = engine.output(pane_id)
            link = engine._link
            assert link is not None
            os.kill(link.process.pid, signal.SIGKILL)
            async for item in channel:
                if isinstance(item, Gap):
                    return True
        return False

    assert run_checked(main)


@contextlib.contextmanager
def _unused() -> t.Iterator[None]:  # pragma: no cover
    yield
