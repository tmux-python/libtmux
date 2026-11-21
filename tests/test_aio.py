"""Tests for libtmux.aio and deterministic ReplayEngine tapes."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import uuid
from typing import TYPE_CHECKING

import pytest

from libtmux import exc
from libtmux.aio import (
    AsyncCommandResult,
    AsyncServer,
    AsyncSubprocessEngine,
    adispatch,
    adispatch_batch,
)
from libtmux.engine import AsyncTmuxEngine, SubprocessEngine, TmuxRequest, TmuxResult
from libtmux.server import Server
from libtmux.test import Exchange, RecordingEngine, ReplayEngine

if TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.session import Session


def test_import_libtmux_does_not_load_aio() -> None:
    """Synchronous import libtmux leaves libtmux.aio and asyncio unloaded."""
    code = (
        "import sys, libtmux; "
        "assert 'libtmux.aio' not in sys.modules; "
        "assert 'asyncio' not in sys.modules"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_async_subprocess_engine_and_server_live(session: Session) -> None:
    """AsyncSubprocessEngine and AsyncServer drive a live server cleanly."""
    sock_name = session.server.socket_name
    assert sock_name is not None
    engine = AsyncSubprocessEngine.for_server(session.server)
    assert isinstance(engine, AsyncTmuxEngine)

    async def exercise() -> tuple[
        AsyncCommandResult, list[AsyncCommandResult], bool, int
    ]:
        srv = AsyncServer(socket_name=sock_name)
        single = await srv.cmd("display-message", "-p", "async-ok")
        batch = await srv.cmd_batch(
            [
                ("display-message", "-p", "one"),
                ("display-message", "-p", "two"),
            ]
        )
        alive = await srv.is_alive()
        rows = await srv.list_sessions()
        return single, batch, alive, len(rows)

    single, batch, alive, row_count = asyncio.run(exercise())
    assert single.stdout == ["async-ok"]
    assert single.ok
    assert [r.stdout for r in batch] == [["one"], ["two"]]
    assert alive
    assert row_count >= 1


def test_adispatch_batch_delegates_to_engine_execute_batch() -> None:
    """adispatch_batch invokes execute_batch once when supported by the engine."""

    class CountingAsync:
        endpoint = None

        def __init__(self) -> None:
            self.batches: list[int] = []

        async def execute(self, request: TmuxRequest) -> TmuxResult:
            return TmuxResult(argv=("tmux", *request.commands[0]), stdout=b"x\n")

        async def execute_batch(
            self,
            requests: Sequence[TmuxRequest],
        ) -> list[TmuxResult]:
            self.batches.append(len(requests))
            return [await self.execute(req) for req in requests]

    counting = CountingAsync()
    results = asyncio.run(
        adispatch_batch(
            counting,
            [
                ("display-message", "-p", "a"),
                ("has-session", "-t", "missing"),
            ],
        )
    )
    assert counting.batches == [2]
    assert len(results) == 2


def test_async_subprocess_cancellation_and_timeout_reap_child(
    session: Session,
) -> None:
    """Timeout and task cancellation kill/terminate the spawned tmux client."""
    engine = AsyncSubprocessEngine.for_server(session.server)
    channel = f"aio-{uuid.uuid4().hex[:8]}"

    async def check_timeout() -> None:
        with pytest.raises(exc.TmuxCommandTimeout):
            await adispatch(engine, "wait-for", channel, timeout=0.15)

    asyncio.run(check_timeout())

    async def check_cancel() -> None:
        task = asyncio.create_task(adispatch(engine, "wait-for", f"{channel}-c"))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(check_cancel())


def test_async_server_validates_conflicting_engine_constraints() -> None:
    """AsyncServer raises EngineConfigurationMismatch on conflicting socket args."""
    pinned = AsyncSubprocessEngine.of(server_args=("-L", "other"))
    with pytest.raises(exc.EngineConfigurationMismatch):
        AsyncServer(socket_name="expected", engine=pinned)


def test_recording_and_replay_engine_offline_round_trip(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RecordingEngine tapes serialize and replay offline, failing closed on misses."""
    recorder = RecordingEngine(SubprocessEngine.for_server(session.server))
    live = Server(socket_name=session.server.socket_name, engine=recorder)
    _ = live.sessions
    _ = live.cmd("display-message", "-p", "replayed")

    payload = json.loads(json.dumps(recorder.to_dict()))
    monkeypatch.setenv("PATH", "")

    replay = ReplayEngine.from_dict(payload)
    offline = Server(socket_name="offline_replay", engine=replay)
    assert len(offline.sessions) >= 1
    assert offline.cmd("display-message", "-p", "replayed").stdout == ["replayed"]

    with pytest.raises(exc.UnscriptedCommand, match="unscripted command"):
        offline.cmd("display-message", "-p", "never-recorded")


def test_replay_engine_exhausts_stateful_sequences() -> None:
    """Varying answers for the same command raise UnscriptedCommand once exhausted."""
    cmd_key = (("list-sessions", "-F", "#S"),)
    tape = [
        Exchange(cmd_key, TmuxResult(argv=("tmux",), stdout=b"before\n")),
        Exchange(cmd_key, TmuxResult(argv=("tmux",), stdout=b"after\n")),
    ]
    replay = ReplayEngine(tape, tmux_version="3.8")
    srv = Server(socket_name="seq", engine=replay)

    assert srv.cmd("list-sessions", "-F", "#S").stdout == ["before"]
    assert srv.cmd("list-sessions", "-F", "#S").stdout == ["after"]
    with pytest.raises(exc.UnscriptedCommand, match="answered 2 times"):
        srv.cmd("list-sessions", "-F", "#S")
