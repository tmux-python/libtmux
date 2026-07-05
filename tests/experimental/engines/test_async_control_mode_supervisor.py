"""The engine reconnects and replays desired state after the proc dies."""

from __future__ import annotations

import asyncio
import typing as t

from libtmux.experimental.engines.async_control_mode import AsyncControlModeEngine
from libtmux.experimental.engines.control_mode import ControlModeError

if t.TYPE_CHECKING:
    import pytest

    from libtmux.server import Server
    from libtmux.session import Session


def test_desired_subscriptions_recorded_idempotently() -> None:
    """``add_subscription`` records desired specs idempotently."""
    engine = AsyncControlModeEngine()
    engine.add_subscription("agentstate:%*:#{@agent_state}")
    engine.add_subscription("agentstate:%*:#{@agent_state}")  # idempotent
    assert engine._desired_subscriptions == ["agentstate:%*:#{@agent_state}"]


def test_reconnects_after_proc_exits(server: Server) -> None:
    """The supervisor reconnects and bumps generation after the proc dies."""

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

    Across a reconnect ``_connected`` stays set, so a command racing the
    reconnect's startup window must still hit the dead-guard rather than have its
    reply drained and discarded by ``_consume_startup``. The fix keeps ``_dead``
    set until the ACK is fully consumed; this asserts that ordering deterministically
    (no real proc, no timing) by observing ``_dead`` from inside startup.
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

    async def _fake_exec(*_a: object, **_k: object) -> _FakeProc:
        return _FakeProc()

    async def main() -> None:
        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        engine = _Probe(tmux_bin="tmux")
        engine._dead = ControlModeError("prior EOF")  # simulate post-disconnect
        await engine._spawn()
        observed["dead_after"] = engine._dead

    asyncio.run(main())
    assert observed["dead_during_startup"] is not None  # dead-guard still active
    assert observed["dead_after"] is None  # cleared only once the ACK is consumed


def test_concurrent_start_all_raise_on_first_connect_failure() -> None:
    """Every concurrent ``start()`` raising on a first-connect spawn failure.

    The supervisor records the spawn error in ``_spawn_error`` then returns. The
    first ``start()`` waiter must not null it out from under a second concurrent
    waiter, or that second caller would observe ``_spawn_error is None`` and
    return "success" against a dead engine. Both gathered ``start()`` calls must
    raise the same spawn error.

    Deterministic: ``_spawn`` always raises (no real proc, no timing); the two
    waiters wake FIFO from the supervisor's single ``_connected.set()``.
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


def test_aclose_releases_start_waiter_before_first_connect() -> None:
    """``aclose`` racing a never-connected ``start`` must not hang the waiter.

    If the supervisor is cancelled before it ever sets ``_connected``, an
    in-flight ``start()`` blocked on ``_connected.wait()`` would hang forever.
    The supervisor's ``finally`` plus ``aclose``'s own ``_connected.set()`` release
    it deterministically.
    """

    async def main() -> None:
        block = asyncio.Event()  # never set: the supervisor hangs until cancelled

        class _Probe(AsyncControlModeEngine):
            async def _spawn(self) -> None:
                await block.wait()  # park in spawn, before _connected is ever set

        engine = _Probe()
        start_task = asyncio.create_task(engine.start())
        # Let start() launch the supervisor and park on _connected.wait(), and the
        # supervisor park in _spawn (so it has entered its try/finally).
        for _ in range(5):
            await asyncio.sleep(0)
        await engine.aclose()  # cancels the supervisor before it ever connected
        await asyncio.wait_for(start_task, timeout=1.0)  # must NOT hang

    asyncio.run(main())
