"""The engine reconnects and replays desired state after the proc dies."""

from __future__ import annotations

import asyncio
import contextlib
import pathlib
import stat
import sys
import typing as t

import pytest

from libtmux.experimental.engines.async_control_mode import (
    _STDERR_TAIL_BYTES,
    AsyncControlModeEngine,
)
from libtmux.experimental.engines.control_mode import (
    ControlModeEngine,
    ControlModeError,
)

if t.TYPE_CHECKING:
    from libtmux.session import Session


def test_desired_subscriptions_recorded_idempotently() -> None:
    """``add_subscription`` records desired specs idempotently."""
    engine = AsyncControlModeEngine()
    engine.add_subscription("agentstate:%*:#{@agent_state}")
    engine.add_subscription("agentstate:%*:#{@agent_state}")  # idempotent
    assert engine._desired_subscriptions == ["agentstate:%*:#{@agent_state}"]


def test_reconnects_after_proc_exits(session: Session) -> None:
    """The supervisor reconnects and bumps generation after the proc dies."""
    server = session.server

    async def main() -> int:
        engine = AsyncControlModeEngine.for_server(server)
        await engine.start()
        gen0 = engine._generation
        # simulate the control proc dying
        assert engine._proc is not None
        engine._proc.terminate()
        await asyncio.sleep(1.5)  # supervisor backoff + reconnect
        # a fresh run must succeed over the reconnected proc
        from libtmux.experimental.engines.base import CommandRequest

        result = await engine.run(CommandRequest.from_args("list-sessions"))
        await engine.aclose()
        assert result.returncode == 0
        return engine._generation - gen0

    bumped = asyncio.run(main())
    assert bumped >= 1


def test_attach_replayed_on_reconnect(session: Session) -> None:
    """A reconnect runs the attach replay without optimistically caching.

    A fresh ``tmux -C`` proc is attached to nothing, so the supervisor replays
    ``attach-session`` on every (re)connect. That replay is fire-and-forget, so
    it must NOT cache ``_attached_session`` -- that cache is owned by the events
    layer (set only on a confirmed attach, re-attached on a miss), so a session
    that vanished during the disconnect surfaces a real error rather than a
    silently-empty capture. This pins that the cache stays unset across a
    *reconnect*, not just the first connect.
    """

    async def main() -> str | None:
        from libtmux.experimental.engines.base import CommandRequest

        sid = session.session_id
        assert sid is not None  # a live session always has an id
        engine = AsyncControlModeEngine.for_server(session.server)
        engine.set_attach_targets([sid])
        await engine.start()
        # The first connect replayed the attach but did not cache it.
        assert engine._attached_session is None
        # Kill the proc; the supervisor reconnects and replays the attach again.
        assert engine._proc is not None
        engine._proc.terminate()
        await asyncio.sleep(1.6)  # backoff + reconnect + replay
        # A fresh command confirms the reconnected proc is live; by the time it
        # returns the reconnect has run past _replay_attach.
        await engine.run(CommandRequest.from_args("list-sessions"))
        cached = engine._attached_session
        await engine.aclose()
        return cached

    assert asyncio.run(main()) is None


def test_spawn_keeps_dead_until_startup_ack_consumed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_spawn`` clears ``_dead`` only *after* the startup ACK is consumed.

    Across a reconnect the original start attempt is already resolved, so a
    command racing the startup window must still hit the dead-guard rather than
    have its reply drained and discarded by ``_consume_startup``. This asserts
    that ordering deterministically (no real proc, no timing) by observing
    ``_dead`` from inside startup.
    """
    observed: dict[str, object] = {}

    class _FakeProc:
        # _spawn only stores the proc; the overridden _consume_startup never
        # reads it, so a bare placeholder process is enough here.
        returncode: int | None = None

    class _Probe(AsyncControlModeEngine):
        async def _consume_startup(self) -> None:
            # liveness state at the instant the startup ACK begins draining
            observed["dead_during_startup"] = self._dead

    created_cmd: tuple[object, ...] = ()

    async def _fake_exec(*args: object, **_kwargs: object) -> _FakeProc:
        nonlocal created_cmd
        created_cmd = args
        return _FakeProc()

    async def main() -> None:
        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        engine = _Probe(tmux_bin="tmux")
        engine._dead = ControlModeError("prior EOF")  # simulate post-disconnect
        engine._next_attach_target = "$7"
        await engine._spawn()
        observed["dead_after"] = engine._dead

    asyncio.run(main())
    assert observed["dead_during_startup"] is not None  # dead-guard still active
    assert observed["dead_after"] is None  # cleared only once the ACK is consumed
    assert created_cmd == ("tmux", "-C", "attach-session", "-E", "-t", "$7")


def test_concurrent_start_all_raise_on_first_connect_failure() -> None:
    """Every concurrent ``start()`` raising on a first-connect spawn failure.

    Every caller keeps the immutable future for the attempt it joined. One
    caller handling the error must not replace the outcome observed by another.
    ``_spawn`` always raises, so this needs no real process or timing.
    """

    async def main() -> list[object]:
        class _Probe(AsyncControlModeEngine):
            async def _spawn(self) -> None:
                msg = "spawn failed"
                raise ControlModeError(msg)

        engine = _Probe()
        return list(
            await asyncio.gather(engine.start(), engine.start(), return_exceptions=True)
        )

    results = asyncio.run(main())
    assert len(results) == 2
    assert all(isinstance(r, ControlModeError) for r in results)


def test_failed_start_waiter_cannot_observe_new_attempt() -> None:
    """A delayed waiter keeps the immutable result of its original attempt."""

    async def main() -> None:
        release_old_waiter = asyncio.Event()
        second_spawn_started = asyncio.Event()
        release_second_spawn = asyncio.Event()
        reader_hold = asyncio.Event()
        waiter_count = 0

        class _Probe(AsyncControlModeEngine):
            attempts = 0

            async def _spawn(self) -> None:
                self.attempts += 1
                if self.attempts == 1:
                    msg = "first attempt failed"
                    raise ControlModeError(msg)
                second_spawn_started.set()
                await release_second_spawn.wait()

            async def _reader(self) -> None:
                await reader_hold.wait()

            @staticmethod
            async def _wait_start_attempt(
                attempt: asyncio.Future[None],
            ) -> None:
                nonlocal waiter_count
                index = waiter_count
                waiter_count += 1
                if index == 1:
                    await release_old_waiter.wait()
                await AsyncControlModeEngine._wait_start_attempt(attempt)

        engine = _Probe()
        first = asyncio.create_task(engine.start())
        delayed = asyncio.create_task(engine.start())
        with pytest.raises(ControlModeError, match="first attempt failed"):
            await first

        retry = asyncio.create_task(engine.start())
        await second_spawn_started.wait()
        release_old_waiter.set()
        with pytest.raises(ControlModeError, match="first attempt failed"):
            await delayed

        release_second_spawn.set()
        await retry
        await engine.aclose()

    asyncio.run(main())


def test_cancelled_only_start_waiter_does_not_poison_retry() -> None:
    """A failed attempt is finalized by its supervisor, not by a live waiter."""

    async def main() -> tuple[int, list[dict[str, object]]]:
        first_spawn_started = asyncio.Event()
        release_first_spawn = asyncio.Event()
        reader_hold = asyncio.Event()
        loop = asyncio.get_running_loop()
        diagnostics: list[dict[str, object]] = []
        loop.set_exception_handler(
            lambda _loop, context: diagnostics.append(dict(context))
        )

        class _Probe(AsyncControlModeEngine):
            attempts = 0

            async def _spawn(self) -> None:
                self.attempts += 1
                if self.attempts == 1:
                    first_spawn_started.set()
                    await release_first_spawn.wait()
                    msg = "first attempt failed"
                    raise ControlModeError(msg)

            async def _reader(self) -> None:
                await reader_hold.wait()

        engine = _Probe()
        cancelled = asyncio.create_task(engine.start())
        await first_spawn_started.wait()
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled

        release_first_spawn.set()
        for _ in range(20):
            if not engine._started:
                break
            await asyncio.sleep(0)
        assert not engine._started

        await engine.start()
        attempts = engine.attempts
        await engine.aclose()
        await asyncio.sleep(0)
        return attempts, diagnostics

    attempts, diagnostics = asyncio.run(main())
    assert attempts == 2
    assert diagnostics == []


def test_close_cancels_and_waits_for_bootstrap_dispatch() -> None:
    """Closing cancels an in-flight bootstrap before it returns."""

    async def main() -> tuple[bool, bool]:
        bootstrap_started = asyncio.Event()
        bootstrap_cancelled = asyncio.Event()

        class _Bootstrap:
            async def run_batch(self, requests: object) -> list[object]:
                bootstrap_started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    bootstrap_cancelled.set()
                    raise
                msg = "bootstrap unexpectedly resumed"
                raise AssertionError(msg)

        class _Probe(AsyncControlModeEngine):
            async def _find_attach_target(self) -> str | None:
                return None

        engine = _Probe()
        engine._bootstrap = t.cast("t.Any", _Bootstrap())
        run_task = asyncio.create_task(engine.run_batch([t.cast("t.Any", object())]))
        await bootstrap_started.wait()
        await engine.aclose()
        with pytest.raises(asyncio.CancelledError):
            await run_task
        return bootstrap_cancelled.is_set(), engine._closing

    assert asyncio.run(main()) == (True, True)


def test_cancelled_close_finishes_process_reap() -> None:
    """Caller cancellation cannot make close lose ownership of a live process."""

    async def main() -> tuple[bool, object | None]:
        stop_started = asyncio.Event()
        release_stop = asyncio.Event()

        class _FakeProc:
            returncode: int | None = None

        class _Probe(AsyncControlModeEngine):
            @staticmethod
            async def _stop_process(proc: t.Any) -> None:
                stop_started.set()
                await release_stop.wait()
                proc.returncode = 0

        engine = _Probe()
        engine._started = True
        engine._proc = t.cast("asyncio.subprocess.Process", _FakeProc())
        close_task = asyncio.create_task(engine.aclose())
        await stop_started.wait()
        close_task.cancel()
        await asyncio.sleep(0)
        close_task.cancel()
        await asyncio.sleep(0)
        cleanup_survived = not close_task.done()
        release_stop.set()
        with pytest.raises(asyncio.CancelledError):
            await close_task
        return cleanup_survived, engine._proc

    assert asyncio.run(main()) == (True, None)


def test_aclose_releases_start_waiter_before_first_connect() -> None:
    """``aclose`` racing a never-connected ``start`` must not hang the waiter.

    If the supervisor is cancelled before it resolves the shared start future,
    an in-flight ``start()`` could hang forever. The supervisor's ``finally``
    publishes the close outcome deterministically.
    """

    async def main() -> None:
        block = asyncio.Event()  # never set: the supervisor hangs until cancelled

        class _Probe(AsyncControlModeEngine):
            async def _spawn(self) -> None:
                await block.wait()  # park before the shared attempt resolves

        engine = _Probe()
        start_task = asyncio.create_task(engine.start())
        # Let start() launch the supervisor and let _spawn enter its try/finally.
        for _ in range(5):
            await asyncio.sleep(0)
        await engine.aclose()  # cancels the supervisor before it ever connected
        with pytest.raises(ControlModeError, match="closed before connecting"):
            await asyncio.wait_for(start_task, timeout=1.0)

    asyncio.run(main())


def test_start_waits_for_an_in_progress_close() -> None:
    """A restart cannot replace lifecycle state while close awaits cancellation."""

    async def main() -> None:
        close_entered = asyncio.Event()
        release_close = asyncio.Event()

        class _Probe(AsyncControlModeEngine):
            async def _supervisor(
                self,
                first_attempt: asyncio.Future[None] | None = None,
            ) -> None:
                if first_attempt is not None:
                    first_attempt.set_result(None)
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    close_entered.set()
                    await release_close.wait()
                    raise

        engine = _Probe()
        await engine.start()
        close_task = asyncio.create_task(engine.aclose())
        await close_entered.wait()

        restart_task = asyncio.create_task(engine.start())
        await asyncio.sleep(0)
        assert not restart_task.done()

        release_close.set()
        await close_task
        await restart_task
        assert engine._started
        assert engine._supervisor_task is not None
        assert not engine._supervisor_task.done()
        await engine.aclose()

    asyncio.run(main())


def test_dead_engine_bootstraps_after_server_loses_all_sessions(
    session: Session,
) -> None:
    """A used engine can recreate an empty server through async subprocess."""
    server = session.server

    async def main() -> tuple[int, int]:
        from libtmux.experimental.engines.base import CommandRequest

        engine = AsyncControlModeEngine.for_server(server)
        await engine.start()
        server.cmd("kill-server")
        for _ in range(100):
            if engine._dead is not None:
                break
            await asyncio.sleep(0.01)
        assert engine._dead is not None

        created = await engine.run(
            CommandRequest.from_args(
                "new-session",
                "-d",
                "-s",
                "recovered",
            ),
        )
        listed = await engine.run(CommandRequest.from_args("list-sessions"))
        await engine.aclose()
        return created.returncode, listed.returncode

    assert asyncio.run(main()) == (0, 0)
    assert server.is_alive()


def test_connect_then_die_escalates_backoff() -> None:
    """A flapping connect-then-die escalates the backoff, not a fixed spin.

    Regression: the supervisor reset ``attempt`` to 0 on every spawn-success, so a
    proc that connected then immediately EOF'd kept reconnecting at ``_backoff(0)``
    forever instead of escalating. The reset is now gated on connection lifetime.
    """
    seen: list[int] = []

    class _Probe(AsyncControlModeEngine):
        async def _spawn(self) -> None:
            return  # connect "succeeds" instantly; _proc stays None

        async def _reader(self) -> None:
            return  # reader returns at once: a connect-then-die

        @staticmethod
        def _backoff(attempt: int) -> float:
            seen.append(attempt)
            return 0.0  # no real delay, so the test runs fast

    async def main() -> None:
        engine = _Probe()
        task = asyncio.create_task(engine._supervisor())
        for _ in range(30):  # let several connect-then-die iterations run
            await asyncio.sleep(0)
        engine._closing = True
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(main())
    assert seen[:3] == [0, 1, 2]  # escalates, not pinned at 0


def test_large_reconnect_attempt_has_bounded_backoff() -> None:
    """Backoff arithmetic remains finite after arbitrarily many failures."""
    assert AsyncControlModeEngine._backoff(10_000) <= 5.06


def test_unexpected_supervisor_failure_reaps_and_allows_retry() -> None:
    """An error outside spawn preserves its cause, reaps, and resets lifecycle."""

    async def main() -> tuple[int, int, bool]:
        reader_hold = asyncio.Event()

        class _FakeProc:
            def __init__(self) -> None:
                self.returncode: int | None = None
                self.terminate_calls = 0

            def terminate(self) -> None:
                self.terminate_calls += 1
                self.returncode = 0

            async def wait(self) -> int:
                return 0

        processes: list[_FakeProc] = []

        class _Probe(AsyncControlModeEngine):
            replay_attempts = 0

            async def _spawn(self) -> None:
                proc = _FakeProc()
                processes.append(proc)
                self._proc = t.cast("asyncio.subprocess.Process", proc)
                self._dead = None

            async def _replay_subscriptions(self) -> None:
                self.replay_attempts += 1
                if self.replay_attempts == 1:
                    msg = "replay failed"
                    raise RuntimeError(msg)

            async def _reader(self) -> None:
                await reader_hold.wait()

        engine = _Probe()
        with pytest.raises(ControlModeError, match="replay failed"):
            await engine.start()
        first_terminated = processes[0].terminate_calls
        await engine.start()
        attempts = engine.replay_attempts
        await engine.aclose()
        return first_terminated, attempts, engine._proc is None

    assert asyncio.run(main()) == (1, 2, True)


def test_spawn_terminates_a_live_prior_proc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_spawn terminates a still-alive prior proc so a reconnect can't orphan it.

    On a reader-EXCEPTION reconnect (vs a clean EOF) the old tmux -C is still
    alive; overwriting _proc without terminating it would leak a control client.
    """
    terminated: list[bool] = []

    class _AliveProc:
        returncode: int | None = None

        def terminate(self) -> None:
            terminated.append(True)
            self.returncode = 0

        async def wait(self) -> int:
            return 0

    class _NewProc:
        returncode: int | None = None

    async def _fake_exec(*_a: object, **_k: object) -> _NewProc:
        return _NewProc()

    class _Probe(AsyncControlModeEngine):
        async def _consume_startup(self) -> None:
            return  # skip the real startup drain (the fake proc has no stdout)

    async def main() -> None:
        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        engine = _Probe(tmux_bin="tmux")
        # a prior, still-alive control client (as a reader-exception reconnect leaves)
        engine._proc = t.cast("asyncio.subprocess.Process", _AliveProc())
        engine._next_attach_target = "$0"
        await engine._spawn()

    asyncio.run(main())
    assert terminated == [True]  # the prior live proc was terminated


def test_spawn_drains_bounded_stderr_during_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Startup drains stderr concurrently and retains only its bounded tail."""

    async def main() -> tuple[list[str], bool, int]:
        stderr_started = asyncio.Event()

        class _Stdout:
            async def read(self, _size: int) -> bytes:
                await stderr_started.wait()
                return b"%begin 1 1 0\n%end 1 1 0\n"

        class _Stderr:
            reads = 0

            async def read(self, _size: int) -> bytes:
                self.reads += 1
                stderr_started.set()
                if self.reads == 1:
                    return b"".join(f"line-{index}\n".encode() for index in range(25))
                return b""

        class _FakeProc:
            def __init__(self) -> None:
                self.returncode: int | None = None
                self.stdout = _Stdout()
                self.stderr = _Stderr()
                self.stdin = None
                self.terminate_calls = 0

            def terminate(self) -> None:
                self.terminate_calls += 1
                self.returncode = 0

            async def wait(self) -> int:
                return 0

        proc = _FakeProc()

        async def _fake_exec(*_args: object, **_kwargs: object) -> _FakeProc:
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        engine = AsyncControlModeEngine(tmux_bin="tmux")
        engine._next_attach_target = "$0"
        await asyncio.wait_for(engine._spawn(), timeout=2.0)
        tail = list(engine._stderr_lines())
        task = engine._stderr_task
        await engine.aclose()
        return tail, bool(task and task.done()), proc.terminate_calls

    tail, task_done, terminate_calls = asyncio.run(main())
    assert tail == [f"line-{index}" for index in range(5, 25)]
    assert task_done
    assert terminate_calls == 1


def test_stderr_tail_reassembles_lines_across_read_chunks() -> None:
    """Chunk boundaries do not turn one stderr line into several diagnostics."""
    engine = AsyncControlModeEngine()
    engine._append_stderr(b"first")
    engine._append_stderr(b" line\nsecond")
    engine._append_stderr(b" line\n")
    assert engine._stderr_lines() == ("first line", "second line")


def test_death_diagnostic_shape_matches_sync_control_engine() -> None:
    """Both control transports append tmux stderr to the same base failure."""
    sync_engine = ControlModeEngine()
    sync_engine._stderr_tail.extend(["server-side reason"])
    async_engine = AsyncControlModeEngine()
    async_engine._append_stderr(b"server-side reason\n")
    assert str(async_engine._died("tmux -C closed stdout")) == str(
        sync_engine._died("tmux -C closed stdout"),
    )


def test_startup_protocol_error_includes_stderr_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An attach protocol failure carries tmux's concurrently drained stderr."""

    async def main() -> str:
        stderr_drained = asyncio.Event()

        class _Stdout:
            async def read(self, _size: int) -> bytes:
                await stderr_drained.wait()
                return b"%begin 1 1 0\nattach body\n%error 1 1 0\n"

        class _Stderr:
            reads = 0

            async def read(self, _size: int) -> bytes:
                self.reads += 1
                stderr_drained.set()
                return b"tmux diagnostic\n" if self.reads == 1 else b""

        class _FakeProc:
            def __init__(self) -> None:
                self.returncode: int | None = None
                self.stdout = _Stdout()
                self.stderr = _Stderr()
                self.stdin = None

            def terminate(self) -> None:
                self.returncode = 1

            async def wait(self) -> int:
                return 1

        proc = _FakeProc()

        async def _fake_exec(*_args: object, **_kwargs: object) -> _FakeProc:
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        engine = AsyncControlModeEngine(tmux_bin="tmux")
        engine._next_attach_target = "$0"
        with pytest.raises(ControlModeError) as caught:
            await asyncio.wait_for(engine._spawn(), timeout=2.0)
        assert engine._proc is None
        assert engine._stderr_task is None
        return str(caught.value)

    message = asyncio.run(main())
    assert "attach body" in message
    assert "tmux diagnostic" in message


def test_cancelled_startup_reaps_process_and_stderr_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelling startup cannot orphan its process or stderr reader task."""

    async def main() -> tuple[int, bool, bool]:
        stderr_started = asyncio.Event()
        stopped = asyncio.Event()
        terminate_called = asyncio.Event()
        allow_reap = asyncio.Event()

        class _Stdout:
            async def read(self, _size: int) -> bytes:
                await stopped.wait()
                return b""

        class _Stderr:
            async def read(self, _size: int) -> bytes:
                stderr_started.set()
                await stopped.wait()
                return b""

        class _FakeProc:
            def __init__(self) -> None:
                self.returncode: int | None = None
                self.stdout = _Stdout()
                self.stderr = _Stderr()
                self.stdin = None
                self.terminate_calls = 0

            def terminate(self) -> None:
                self.terminate_calls += 1
                self.returncode = 0
                stopped.set()
                terminate_called.set()

            async def wait(self) -> int:
                await allow_reap.wait()
                return 0

        proc = _FakeProc()

        async def _fake_exec(*_args: object, **_kwargs: object) -> _FakeProc:
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        engine = AsyncControlModeEngine(tmux_bin="tmux")
        engine._next_attach_target = "$0"
        startup = asyncio.create_task(engine._spawn())
        await asyncio.wait_for(stderr_started.wait(), timeout=2.0)
        stderr_task = engine._stderr_task
        startup.cancel()
        await asyncio.wait_for(terminate_called.wait(), timeout=2.0)
        startup.cancel()
        await asyncio.sleep(0)
        assert not startup.done()
        allow_reap.set()
        with pytest.raises(asyncio.CancelledError):
            await startup
        return (
            proc.terminate_calls,
            bool(stderr_task and stderr_task.done()),
            engine._proc is None and engine._stderr_task is None,
        )

    assert asyncio.run(main()) == (1, True, True)


def test_cancelled_process_creation_still_reaps_created_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation during subprocess setup cannot abandon the eventual child."""

    async def main() -> tuple[int, bool, bool]:
        creation_started = asyncio.Event()
        release_creation = asyncio.Event()
        stopped = asyncio.Event()

        class _Stream:
            async def read(self, _size: int) -> bytes:
                await stopped.wait()
                return b""

        class _FakeProc:
            def __init__(self) -> None:
                self.returncode: int | None = None
                self.stdout = _Stream()
                self.stderr = _Stream()
                self.stdin = None
                self.terminate_calls = 0

            def terminate(self) -> None:
                self.terminate_calls += 1
                self.returncode = 0
                stopped.set()

            async def wait(self) -> int:
                await stopped.wait()
                return 0

        proc = _FakeProc()

        async def _fake_exec(*_args: object, **_kwargs: object) -> _FakeProc:
            creation_started.set()
            await release_creation.wait()
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        engine = AsyncControlModeEngine(tmux_bin="tmux")
        engine._next_attach_target = "$0"
        startup = asyncio.create_task(engine._spawn())
        await asyncio.wait_for(creation_started.wait(), timeout=2.0)
        startup.cancel()
        await asyncio.sleep(0)
        startup.cancel()
        assert not startup.done()
        release_creation.set()
        with pytest.raises(asyncio.CancelledError):
            await startup
        return (
            proc.terminate_calls,
            engine._proc is None,
            engine._stderr_task is None,
        )

    assert asyncio.run(main()) == (1, True, True)


def test_reader_death_includes_stderr_tail() -> None:
    """A stdout EOF reports tmux's stderr after joining the drain task."""

    async def main() -> str:
        stdout = asyncio.StreamReader()
        stdout.feed_eof()
        stderr = asyncio.StreamReader()
        stderr.feed_data(b"server-side reason\n")
        stderr.feed_eof()

        class _FakeProc:
            def __init__(self) -> None:
                self.returncode: int | None = 1
                self.stdout = stdout
                self.stderr = stderr
                self.stdin = None

            async def wait(self) -> int:
                return 1

        engine = AsyncControlModeEngine()
        proc = _FakeProc()
        engine._proc = t.cast("asyncio.subprocess.Process", proc)
        engine._start_stderr_reader(t.cast("asyncio.subprocess.Process", proc))
        await engine._reader()
        assert engine._dead is not None
        return str(engine._dead)

    assert "server-side reason" in asyncio.run(main())


def test_real_subprocess_drains_stderr_past_pipe_capacity(
    tmp_path: pathlib.Path,
) -> None:
    """A real child can fill stderr before its ACK without deadlocking startup."""
    executable = tmp_path / "stderr-before-ack"
    executable.write_text(
        f"""#!{sys.executable}
import os
import sys

remaining = 2 * 1024 * 1024
chunk = b"x" * 65536
while remaining:
    written = os.write(2, chunk[:remaining])
    remaining -= written
os.write(1, b"%begin 1 1 0\\n%end 1 1 0\\n")
sys.stdin.buffer.read()
""",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)

    async def main() -> tuple[int, bool, bool, int]:
        engine = AsyncControlModeEngine(tmux_bin=str(executable))
        engine._next_attach_target = "$0"
        await asyncio.wait_for(engine._spawn(), timeout=3.0)
        proc = engine._proc
        stderr_task = engine._stderr_task
        retained = len(engine._stderr_tail)
        assert proc is not None
        assert stderr_task is not None
        await engine.aclose()
        leaked = any(
            task.get_name() == "libtmux-async-control-stderr" and not task.done()
            for task in asyncio.all_tasks()
        )
        return proc.returncode or 0, stderr_task.done(), leaked, retained

    returncode, task_done, leaked, retained = asyncio.run(main())
    assert returncode != 0
    assert task_done
    assert not leaked
    assert 0 < retained <= _STDERR_TAIL_BYTES
