"""The engine reconnects and replays desired state after the proc dies."""

from __future__ import annotations

import asyncio
import contextlib
import typing as t

import pytest

from libtmux.experimental.engines.async_control_mode import AsyncControlModeEngine
from libtmux.experimental.engines.control_mode import ControlModeError

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

        class _Probe(AsyncControlModeEngine):
            attempts = 0
            waiters = 0

            async def _spawn(self) -> None:
                self.attempts += 1
                if self.attempts == 1:
                    msg = "first attempt failed"
                    raise ControlModeError(msg)
                second_spawn_started.set()
                await release_second_spawn.wait()

            async def _reader(self) -> None:
                await reader_hold.wait()

            async def _wait_start_attempt(
                self,
                attempt: asyncio.Future[None],
            ) -> None:
                index = self.waiters
                self.waiters += 1
                if index == 1:
                    await release_old_waiter.wait()
                await super()._wait_start_attempt(attempt)

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
