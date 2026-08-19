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
from libtmux.experimental.engines.base import CommandRequest, CommandResult
from libtmux.experimental.engines.control_mode import (
    ControlModeBlock,
    ControlModeError,
)

if t.TYPE_CHECKING:
    from libtmux.session import Session


class _RecordingStdin:
    """Test-only stdin that records every accepted control command."""

    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.written = asyncio.Event()

    def write(self, payload: bytes) -> None:
        self.writes.append(payload)
        self.written.set()

    async def drain(self) -> None:
        return


class _RecordingProcess:
    """Test-only process with observable writes and bounded lifecycle."""

    def __init__(self) -> None:
        self.stdin = _RecordingStdin()
        self.returncode: int | None = None

    def terminate(self) -> None:
        self.returncode = 0

    async def wait(self) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class _ChunkedStdout:
    """Test-only stdout that returns an exact finite chunk sequence."""

    def __init__(self, *chunks: bytes) -> None:
        self.chunks = list(chunks)

    async def read(self, _size: int) -> bytes:
        return self.chunks.pop(0) if self.chunks else b""


class _StartupProcess(_RecordingProcess):
    """Test-only startup process with chunked stdout and no stderr pipe."""

    def __init__(self, *chunks: bytes) -> None:
        super().__init__()
        self.stdout = _ChunkedStdout(*chunks)
        self.stderr = None


class _GatedReconnectEngine(AsyncControlModeEngine):
    """Test-only engine whose second connection waits on an explicit gate."""

    def __init__(self) -> None:
        super().__init__()
        self.disconnect = asyncio.Event()
        self.second_spawn_started = asyncio.Event()
        self.release_second_spawn = asyncio.Event()
        self.second_connected = asyncio.Event()
        self.disconnect_second = asyncio.Event()
        self.gate_third_spawn = False
        self.third_spawn_started = asyncio.Event()
        self.release_third_spawn = asyncio.Event()
        self.third_connected = asyncio.Event()
        self.reader_hold = asyncio.Event()
        self.processes: list[_RecordingProcess] = []
        self.spawn_count = 0

    async def _find_attach_target(self) -> str | None:
        return "$0"

    async def _spawn(self) -> None:
        self.spawn_count += 1
        if self.spawn_count == 2:
            self.second_spawn_started.set()
            await self.release_second_spawn.wait()
        elif self.spawn_count == 3 and self.gate_third_spawn:
            self.third_spawn_started.set()
            await self.release_third_spawn.wait()
        proc = _RecordingProcess()
        self.processes.append(proc)
        self._proc = t.cast("asyncio.subprocess.Process", proc)
        if self.spawn_count == 2:
            self.second_connected.set()
        elif self.spawn_count == 3:
            self.third_connected.set()

    async def _reader(self) -> None:
        if self.spawn_count == 1:
            await self.disconnect.wait()
            self.processes[-1].returncode = 17
            self._mark_dead(self._died("simulated EOF"))
            return
        if self.spawn_count == 2:
            await self.disconnect_second.wait()
            self.processes[-1].returncode = 18
            self._mark_dead(self._died("replacement EOF"))
            return
        await self.reader_hold.wait()

    @staticmethod
    def _backoff(_attempt: int) -> float:
        return 0.0


def test_desired_subscriptions_recorded_idempotently() -> None:
    """``add_subscription`` records desired specs idempotently."""
    engine = AsyncControlModeEngine()
    engine.add_subscription("agentstate:%*:#{@agent_state}")
    engine.add_subscription("agentstate:%*:#{@agent_state}")  # idempotent
    assert engine._desired_subscriptions == ["agentstate:%*:#{@agent_state}"]


def test_no_output_state_changes_every_later_spawn_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Muted reconnects must never attach before their client flag applies."""
    commands: list[tuple[object, ...]] = []

    class _Probe(AsyncControlModeEngine):
        async def _find_attach_target(self) -> str | None:
            return "$0"

        async def _consume_startup(self) -> None:
            return None

        async def run(self, request: CommandRequest) -> CommandResult:
            assert self._desired_no_output
            assert request.args == ("refresh-client", "-f", "no-output")
            return CommandResult(cmd=("tmux", *request.args))

    async def _fake_exec(*args: object, **_kwargs: object) -> _StartupProcess:
        commands.append(args)
        return _StartupProcess()

    async def main() -> None:
        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        engine = _Probe(tmux_bin="tmux")
        await engine._spawn()
        await engine._spawn()
        await engine.disable_output_notifications()
        await engine._spawn()
        await engine._spawn()
        await engine.aclose()

    asyncio.run(main())
    assert commands[:2] == [
        ("tmux", "-C", "attach-session", "-E", "-t", "$0"),
        ("tmux", "-C", "attach-session", "-E", "-t", "$0"),
    ]
    assert commands[2:] == [
        (
            "tmux",
            "-C",
            "attach-session",
            "-f",
            "no-output",
            "-E",
            "-t",
            "$0",
        ),
        (
            "tmux",
            "-C",
            "attach-session",
            "-f",
            "no-output",
            "-E",
            "-t",
            "$0",
        ),
    ]


def test_no_output_state_linearizes_with_process_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A process cannot be created from stale desired client flags."""
    creation_started = asyncio.Event()
    release_creation = asyncio.Event()
    mute_entered = asyncio.Event()
    observations: list[tuple[tuple[object, ...], bool]] = []

    class _Probe(AsyncControlModeEngine):
        async def _find_attach_target(self) -> str | None:
            return "$0"

        async def _consume_startup(self) -> None:
            return None

        async def disable_output_notifications(self) -> None:
            mute_entered.set()
            await super().disable_output_notifications()

        async def run(self, request: CommandRequest) -> CommandResult:
            assert request.args == ("refresh-client", "-f", "no-output")
            return CommandResult(cmd=("tmux", *request.args))

    async def _fake_exec(*args: object, **_kwargs: object) -> _StartupProcess:
        creation_started.set()
        await release_creation.wait()
        observations.append((args, engine._desired_no_output))
        return _StartupProcess()

    async def main() -> None:
        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        spawn = asyncio.create_task(engine._spawn())
        await creation_started.wait()
        mute = asyncio.create_task(engine.disable_output_notifications())
        await mute_entered.wait()
        release_creation.set()
        await spawn
        await mute
        await engine.aclose()

    engine = _Probe(tmux_bin="tmux")
    asyncio.run(asyncio.wait_for(main(), timeout=1.0))
    assert observations == [(("tmux", "-C", "attach-session", "-E", "-t", "$0"), False)]
    assert engine._desired_no_output


def test_no_output_waiter_cannot_change_state_after_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mute request queued behind process creation cannot outlive close."""
    creation_started = asyncio.Event()
    release_creation = asyncio.Event()
    mute_entered = asyncio.Event()
    close_transitioned = asyncio.Event()

    class _Probe(AsyncControlModeEngine):
        async def _find_attach_target(self) -> str | None:
            return "$0"

        async def disable_output_notifications(self) -> None:
            mute_entered.set()
            await super().disable_output_notifications()

        async def _close_locked(self) -> None:
            close_transitioned.set()
            await super()._close_locked()

    async def _fake_exec(*_args: object, **_kwargs: object) -> _StartupProcess:
        creation_started.set()
        await release_creation.wait()
        return _StartupProcess()

    async def main() -> tuple[object, object]:
        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        start = asyncio.create_task(engine.start())
        await creation_started.wait()
        mute = asyncio.create_task(engine.disable_output_notifications())
        await mute_entered.wait()
        close = asyncio.create_task(engine.aclose())
        await close_transitioned.wait()
        release_creation.set()
        start_result = (await asyncio.gather(start, return_exceptions=True))[0]
        mute_result = (await asyncio.gather(mute, return_exceptions=True))[0]
        await close
        return start_result, mute_result

    engine = _Probe(tmux_bin="tmux")
    start_result, mute_result = asyncio.run(asyncio.wait_for(main(), timeout=1.0))
    assert isinstance(start_result, ControlModeError)
    assert isinstance(mute_result, ControlModeError)
    assert not engine._desired_no_output
    assert engine._proc is None
    assert not engine._started


@pytest.mark.parametrize("failure", ("nonzero", "connection"))
def test_no_output_records_desired_state_before_live_failure(failure: str) -> None:
    """A failed acknowledgement must retain reconnect-safe desired state."""
    requests: list[tuple[str, ...]] = []

    class _Probe(AsyncControlModeEngine):
        async def run(self, request: CommandRequest) -> CommandResult:
            assert self._desired_no_output
            requests.append(request.args)
            if failure == "connection":
                message = "connection lost before acknowledgement"
                raise ControlModeError(message)
            return CommandResult(
                cmd=("tmux", *request.args),
                stderr=("client rejected flag",),
                returncode=1,
            )

    async def main() -> bool:
        engine = _Probe()
        match = (
            "client rejected flag"
            if failure == "nonzero"
            else "connection lost before acknowledgement"
        )
        with pytest.raises(ControlModeError, match=match):
            await engine.disable_output_notifications()
        return engine._desired_no_output

    assert asyncio.run(main())
    assert requests == [("refresh-client", "-f", "no-output")]


def test_command_waits_for_reconnect_generation_before_writing() -> None:
    """A reconnect-window command writes only to the replacement process."""

    async def main() -> tuple[bool, tuple[bytes, ...], tuple[bytes, ...], object]:
        waiter_arrived = asyncio.Event()
        engine: _Probe

        class _Probe(_GatedReconnectEngine):
            @staticmethod
            async def _wait_start_attempt(
                attempt: asyncio.Future[None],
            ) -> None:
                if engine.second_spawn_started.is_set():
                    waiter_arrived.set()
                await AsyncControlModeEngine._wait_start_attempt(attempt)

        engine = _Probe()
        await engine.start()
        first = engine.processes[0]
        engine.disconnect.set()
        await engine.second_spawn_started.wait()

        command = asyncio.create_task(
            engine.run(CommandRequest.from_args("list-sessions"))
        )
        await waiter_arrived.wait()
        pending_before_release = not command.done()

        engine.release_second_spawn.set()
        await engine.second_connected.wait()
        replacement = engine.processes[1]
        written = asyncio.create_task(replacement.stdin.written.wait())
        done, _pending = await asyncio.wait(
            (command, written),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if written in done:
            engine._dispatch_block(
                ControlModeBlock(
                    number=1,
                    flags=1,
                    is_error=False,
                    body=(b"replacement",),
                )
            )
        else:
            written.cancel()
            await asyncio.gather(written, return_exceptions=True)
        outcome = (await asyncio.gather(command, return_exceptions=True))[0]
        first_writes = tuple(first.stdin.writes)
        replacement_writes = tuple(replacement.stdin.writes)
        await engine.aclose()
        return pending_before_release, first_writes, replacement_writes, outcome

    pending, first_writes, replacement_writes, outcome = asyncio.run(
        asyncio.wait_for(main(), timeout=2.0)
    )
    assert pending
    assert first_writes == ()
    assert replacement_writes == (b"list-sessions\n",)
    assert isinstance(outcome, CommandResult)
    assert outcome.stdout == ("replacement",)


def test_generation_change_before_write_rejoins_readiness() -> None:
    """A generation change under the write lock loops before any write."""

    async def main() -> tuple[bool, tuple[bytes, ...], tuple[bytes, ...], object]:
        first_waiter_arrived = asyncio.Event()
        second_readiness_finished = asyncio.Event()
        joined_third_readiness = asyncio.Event()
        engine: _Probe

        class _Probe(_GatedReconnectEngine):
            @staticmethod
            async def _wait_start_attempt(
                attempt: asyncio.Future[None],
            ) -> None:
                if engine.second_spawn_started.is_set() and engine.spawn_count == 2:
                    first_waiter_arrived.set()
                elif engine.third_spawn_started.is_set() and engine.spawn_count == 3:
                    joined_third_readiness.set()
                await AsyncControlModeEngine._wait_start_attempt(attempt)
                if engine.spawn_count == 2:
                    second_readiness_finished.set()

        engine = _Probe()
        engine.gate_third_spawn = True
        await engine.start()
        engine.disconnect.set()
        await engine.second_spawn_started.wait()
        await engine._write_lock.acquire()
        command = asyncio.create_task(
            engine.run(CommandRequest.from_args("list-sessions"))
        )
        await first_waiter_arrived.wait()

        engine.release_second_spawn.set()
        await engine.second_connected.wait()
        replacement = engine.processes[1]
        await second_readiness_finished.wait()
        engine.disconnect_second.set()
        await engine.third_spawn_started.wait()
        engine._write_lock.release()

        joined = asyncio.create_task(joined_third_readiness.wait())
        stale_write = asyncio.create_task(replacement.stdin.written.wait())
        done, _pending = await asyncio.wait(
            (joined, stale_write),
            return_when=asyncio.FIRST_COMPLETED,
        )
        rejoined_before_write = joined in done
        for event_task in (joined, stale_write):
            if not event_task.done():
                event_task.cancel()
        await asyncio.gather(joined, stale_write, return_exceptions=True)

        engine.release_third_spawn.set()
        await engine.third_connected.wait()
        current = engine.processes[2]
        if rejoined_before_write:
            await current.stdin.written.wait()
            engine._dispatch_block(
                ControlModeBlock(
                    number=1,
                    flags=1,
                    is_error=False,
                    body=(b"current",),
                )
            )
        else:
            command.cancel()
        outcome = (await asyncio.gather(command, return_exceptions=True))[0]
        stale_writes = tuple(replacement.stdin.writes)
        current_writes = tuple(current.stdin.writes)
        await engine.aclose()
        return rejoined_before_write, stale_writes, current_writes, outcome

    rejoined, stale_writes, current_writes, outcome = asyncio.run(
        asyncio.wait_for(main(), timeout=2.0)
    )
    assert rejoined
    assert stale_writes == ()
    assert current_writes == (b"list-sessions\n",)
    assert isinstance(outcome, CommandResult)
    assert outcome.stdout == ("current",)


def test_written_command_is_not_replayed_after_eof() -> None:
    """EOF fails an accepted command without writing it to the replacement."""

    async def main() -> tuple[object, tuple[bytes, ...], tuple[bytes, ...]]:
        engine = _GatedReconnectEngine()
        await engine.start()
        original = engine.processes[0]
        command = asyncio.create_task(
            engine.run(CommandRequest.from_args("list-sessions"))
        )
        await original.stdin.written.wait()

        engine.disconnect.set()
        await engine.second_spawn_started.wait()
        outcome = (await asyncio.gather(command, return_exceptions=True))[0]
        engine.release_second_spawn.set()
        await engine.second_connected.wait()
        replacement = engine.processes[1]
        original_writes = tuple(original.stdin.writes)
        replacement_writes = tuple(replacement.stdin.writes)
        await engine.aclose()
        return outcome, original_writes, replacement_writes

    outcome, original_writes, replacement_writes = asyncio.run(
        asyncio.wait_for(main(), timeout=2.0)
    )
    assert isinstance(outcome, ControlModeError)
    assert "simulated EOF" in str(outcome)
    assert original_writes == (b"list-sessions\n",)
    assert replacement_writes == ()


def test_reader_eof_publishes_reconnect_readiness_before_cleanup() -> None:
    """An EOF blocks new writes before connection cleanup can yield."""

    async def main() -> tuple[bool, tuple[bytes, ...], object]:
        cleanup_started = asyncio.Event()
        release_cleanup = asyncio.Event()
        pending_readiness_joined = asyncio.Event()
        engine: _Probe

        class _Probe(AsyncControlModeEngine):
            async def _find_attach_target(self) -> str | None:
                return "$0"

            async def _stop_connection(
                self,
                proc: asyncio.subprocess.Process,
            ) -> None:
                cleanup_started.set()
                await release_cleanup.wait()
                t.cast("t.Any", proc).returncode = 17
                if self._proc is proc:
                    self._proc = None

            @staticmethod
            async def _wait_start_attempt(
                attempt: asyncio.Future[None],
            ) -> None:
                if cleanup_started.is_set() and not attempt.done():
                    pending_readiness_joined.set()
                await AsyncControlModeEngine._wait_start_attempt(attempt)

        engine = _Probe()
        proc = _StartupProcess(b"")
        engine._proc = t.cast("asyncio.subprocess.Process", proc)
        engine._generation = 1
        engine._started = True
        engine._start_attempt = engine._new_start_attempt()
        engine._start_attempt.set_result(None)

        reader = asyncio.create_task(engine._reader())
        await cleanup_started.wait()
        command = asyncio.create_task(
            engine.run(CommandRequest.from_args("list-sessions"))
        )
        readiness = asyncio.create_task(pending_readiness_joined.wait())
        stale_write = asyncio.create_task(proc.stdin.written.wait())
        done, _pending = await asyncio.wait(
            (readiness, stale_write),
            return_when=asyncio.FIRST_COMPLETED,
        )
        joined_before_write = readiness in done
        writes_before_cleanup = tuple(proc.stdin.writes)
        for event_task in (readiness, stale_write):
            if not event_task.done():
                event_task.cancel()
        await asyncio.gather(readiness, stale_write, return_exceptions=True)

        release_cleanup.set()
        await reader
        await engine.aclose()
        outcome = (await asyncio.gather(command, return_exceptions=True))[0]
        return joined_before_write, writes_before_cleanup, outcome

    joined, writes, outcome = asyncio.run(asyncio.wait_for(main(), timeout=2.0))
    assert joined
    assert writes == ()
    assert isinstance(outcome, ControlModeError)


def test_connected_exit_publishes_death_before_gated_eof() -> None:
    """A connected ``%exit`` reaches subscribers and blocks later writes."""

    async def main() -> tuple[str, bool, tuple[bytes, ...], object]:
        eof_read_started = asyncio.Event()
        release_eof = asyncio.Event()
        pending_readiness_joined = asyncio.Event()
        engine: _Probe

        class _Stdout:
            reads = 0

            async def read(self, _size: int) -> bytes:
                self.reads += 1
                if self.reads == 1:
                    return b"%exit too far behind\n"
                eof_read_started.set()
                await release_eof.wait()
                return b""

        class _Proc(_RecordingProcess):
            def __init__(self) -> None:
                super().__init__()
                self.stdout = _Stdout()

        class _Probe(AsyncControlModeEngine):
            async def _find_attach_target(self) -> str | None:
                return "$0"

            @staticmethod
            async def _wait_start_attempt(
                attempt: asyncio.Future[None],
            ) -> None:
                if eof_read_started.is_set() and not attempt.done():
                    pending_readiness_joined.set()
                await AsyncControlModeEngine._wait_start_attempt(attempt)

        engine = _Probe()
        proc = _Proc()
        engine._proc = t.cast("asyncio.subprocess.Process", proc)
        engine._generation = 1
        engine._started = True
        engine._start_attempt = engine._new_start_attempt()
        engine._start_attempt.set_result(None)

        notifications: asyncio.Queue[t.Any] = asyncio.Queue()
        engine._subscribers.add(notifications)
        reader = asyncio.create_task(engine._reader())
        await eof_read_started.wait()
        notification = await notifications.get()

        command = asyncio.create_task(
            engine.run(CommandRequest.from_args("list-sessions"))
        )
        readiness = asyncio.create_task(pending_readiness_joined.wait())
        stale_write = asyncio.create_task(proc.stdin.written.wait())
        done, _pending = await asyncio.wait(
            (readiness, stale_write),
            return_when=asyncio.FIRST_COMPLETED,
        )
        joined_before_write = readiness in done
        writes_before_eof = tuple(proc.stdin.writes)
        for event_task in (readiness, stale_write):
            if not event_task.done():
                event_task.cancel()
        await asyncio.gather(readiness, stale_write, return_exceptions=True)

        engine._subscribers.discard(notifications)
        release_eof.set()
        await reader
        await engine.aclose()
        outcome = (await asyncio.gather(command, return_exceptions=True))[0]
        return notification.kind, joined_before_write, writes_before_eof, outcome

    kind, joined, writes, outcome = asyncio.run(asyncio.wait_for(main(), timeout=2.0))
    assert kind == "exit"
    assert joined
    assert writes == ()
    assert isinstance(outcome, ControlModeError)


def test_exit_reason_survives_same_chunk_dispatch_failure() -> None:
    """A fallible block dispatch cannot discard a same-chunk ``%exit``."""

    async def main() -> str:
        proc = _StartupProcess(b"%begin 1 1 1\n%end 1 1 1\n%exit too far behind\n")
        proc.returncode = 17
        engine = AsyncControlModeEngine()
        engine._generation = 4
        engine._proc = t.cast("asyncio.subprocess.Process", proc)
        await engine._reader()
        assert engine._dead is not None
        return str(engine._dead)

    message = asyncio.run(asyncio.wait_for(main(), timeout=2.0))
    assert "no pending request" in message
    assert "too far behind" in message
    assert "return code 17" in message
    assert "generation 4" in message


def test_completed_block_in_exit_chunk_keeps_its_result() -> None:
    """A completed solicited block remains successful beside ``%exit``."""

    async def main() -> tuple[object, tuple[bytes, ...]]:
        release_chunk = asyncio.Event()

        class _Stdout:
            reads = 0

            async def read(self, _size: int) -> bytes:
                self.reads += 1
                if self.reads == 1:
                    await release_chunk.wait()
                    return b"%begin 1 1 1\ncomplete\n%end 1 1 1\n%exit done\n"
                return b""

        class _Proc(_RecordingProcess):
            def __init__(self) -> None:
                super().__init__()
                self.stdout = _Stdout()

        engine = AsyncControlModeEngine()
        proc = _Proc()
        engine._proc = t.cast("asyncio.subprocess.Process", proc)
        engine._started = True
        engine._start_attempt = engine._new_start_attempt()
        engine._start_attempt.set_result(None)
        reader = asyncio.create_task(engine._reader())
        command = asyncio.create_task(
            engine.run(CommandRequest.from_args("list-sessions"))
        )
        await proc.stdin.written.wait()
        release_chunk.set()
        outcome = (await asyncio.gather(command, return_exceptions=True))[0]
        await reader
        writes = tuple(proc.stdin.writes)
        await engine.aclose()
        return outcome, writes

    outcome, writes = asyncio.run(asyncio.wait_for(main(), timeout=2.0))
    assert isinstance(outcome, CommandResult)
    assert outcome.stdout == ("complete",)
    assert writes == (b"list-sessions\n",)


def test_cancelled_reconnect_waiter_does_not_cancel_shared_readiness() -> None:
    """Cancelling one reconnect waiter leaves its peer and readiness alive."""

    async def main() -> tuple[object, object, bool, tuple[bytes, ...]]:
        waiters_arrived = asyncio.Event()
        waiter_count = 0
        engine: _Probe

        class _Probe(_GatedReconnectEngine):
            @staticmethod
            async def _wait_start_attempt(
                attempt: asyncio.Future[None],
            ) -> None:
                nonlocal waiter_count
                if engine.second_spawn_started.is_set():
                    waiter_count += 1
                    if waiter_count == 2:
                        waiters_arrived.set()
                await AsyncControlModeEngine._wait_start_attempt(attempt)

        engine = _Probe()
        await engine.start()
        engine.disconnect.set()
        await engine.second_spawn_started.wait()
        cancelled = asyncio.create_task(
            engine.run(CommandRequest.from_args("display-message", "first"))
        )
        survivor = asyncio.create_task(
            engine.run(CommandRequest.from_args("display-message", "second"))
        )
        await waiters_arrived.wait()
        shared = engine._start_attempt
        assert shared is not None

        cancelled.cancel()
        cancelled_outcome = (await asyncio.gather(cancelled, return_exceptions=True))[0]
        shared_survived = not shared.cancelled()
        engine.release_second_spawn.set()
        await engine.second_connected.wait()
        replacement = engine.processes[1]
        written = asyncio.create_task(replacement.stdin.written.wait())
        done, _pending = await asyncio.wait(
            (survivor, written),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if written in done:
            engine._dispatch_block(
                ControlModeBlock(
                    number=1,
                    flags=1,
                    is_error=False,
                    body=(b"survivor",),
                )
            )
        else:
            written.cancel()
            await asyncio.gather(written, return_exceptions=True)
        survivor_outcome = (await asyncio.gather(survivor, return_exceptions=True))[0]
        writes = tuple(replacement.stdin.writes)
        await engine.aclose()
        return cancelled_outcome, survivor_outcome, shared_survived, writes

    cancelled, survivor, shared_survived, writes = asyncio.run(
        asyncio.wait_for(main(), timeout=2.0)
    )
    assert isinstance(cancelled, asyncio.CancelledError)
    assert isinstance(survivor, CommandResult)
    assert survivor.stdout == ("survivor",)
    assert shared_survived
    assert writes == (b"display-message second\n",)


def test_transient_spawn_failure_preserves_reconnect_readiness() -> None:
    """A transient replacement failure leaves the shared readiness pending."""

    async def main() -> tuple[bool, bool, object, tuple[bytes, ...]]:
        waiter_arrived = asyncio.Event()
        release_failed_spawn = asyncio.Event()
        engine: _Probe

        class _Probe(_GatedReconnectEngine):
            @staticmethod
            async def _wait_start_attempt(
                attempt: asyncio.Future[None],
            ) -> None:
                if engine.second_spawn_started.is_set():
                    waiter_arrived.set()
                await AsyncControlModeEngine._wait_start_attempt(attempt)

            async def _spawn(self) -> None:
                self.spawn_count += 1
                if self.spawn_count == 2:
                    self.second_spawn_started.set()
                    await release_failed_spawn.wait()
                    msg = "transient spawn failure"
                    raise ControlModeError(msg)
                if self.spawn_count == 3:
                    self.third_spawn_started.set()
                    await self.release_third_spawn.wait()
                proc = _RecordingProcess()
                self.processes.append(proc)
                self._proc = t.cast("asyncio.subprocess.Process", proc)
                if self.spawn_count == 3:
                    self.third_connected.set()

        engine = _Probe()
        await engine.start()
        engine.disconnect.set()
        await engine.second_spawn_started.wait()
        command = asyncio.create_task(
            engine.run(CommandRequest.from_args("list-sessions"))
        )
        await waiter_arrived.wait()
        shared = engine._start_attempt
        assert shared is not None

        release_failed_spawn.set()
        await engine.third_spawn_started.wait()
        still_pending = not command.done() and not shared.done()
        same_readiness = engine._start_attempt is shared
        engine.release_third_spawn.set()
        await engine.third_connected.wait()
        current = engine.processes[1]
        await current.stdin.written.wait()
        engine._dispatch_block(
            ControlModeBlock(
                number=1,
                flags=1,
                is_error=False,
                body=(b"recovered",),
            )
        )
        outcome = (await asyncio.gather(command, return_exceptions=True))[0]
        writes = tuple(current.stdin.writes)
        await engine.aclose()
        return still_pending, same_readiness, outcome, writes

    pending, same_readiness, outcome, writes = asyncio.run(
        asyncio.wait_for(main(), timeout=2.0)
    )
    assert pending
    assert same_readiness
    assert isinstance(outcome, CommandResult)
    assert outcome.stdout == ("recovered",)
    assert writes == (b"list-sessions\n",)


def test_close_during_reconnect_releases_every_waiter() -> None:
    """Intentional close fails gated reconnect waiters and owns all cleanup."""

    async def main() -> tuple[
        list[CommandResult | BaseException | None],
        bool,
        bool,
        tuple[str, ...],
    ]:
        waiters_arrived = asyncio.Event()
        waiter_count = 0
        engine: _Probe

        class _Probe(_GatedReconnectEngine):
            @staticmethod
            async def _wait_start_attempt(
                attempt: asyncio.Future[None],
            ) -> None:
                nonlocal waiter_count
                if engine.second_spawn_started.is_set():
                    waiter_count += 1
                    if waiter_count == 2:
                        waiters_arrived.set()
                await AsyncControlModeEngine._wait_start_attempt(attempt)

        engine = _Probe()
        await engine.start()
        engine.disconnect.set()
        await engine.second_spawn_started.wait()
        waiters = [
            asyncio.create_task(engine.start()),
            asyncio.create_task(engine.run(CommandRequest.from_args("list-sessions"))),
        ]
        await waiters_arrived.wait()
        await engine.aclose()
        outcomes = list(await asyncio.gather(*waiters, return_exceptions=True))
        leaked = tuple(
            sorted(
                task.get_name()
                for task in asyncio.all_tasks()
                if task is not asyncio.current_task()
                and not task.done()
                and task.get_name().startswith("libtmux-async-control-")
            )
        )
        return (
            outcomes,
            engine._supervisor_task is None,
            engine._proc is None,
            leaked,
        )

    outcomes, supervisor_absent, process_absent, leaked = asyncio.run(
        asyncio.wait_for(main(), timeout=2.0)
    )
    assert all(isinstance(outcome, ControlModeError) for outcome in outcomes)
    assert all("closed" in str(outcome) for outcome in outcomes)
    assert supervisor_absent
    assert process_absent
    assert leaked == ()


def test_command_waiting_on_write_lock_cannot_reopen_after_close() -> None:
    """A pre-close dispatch cannot create a new lifecycle after close wins."""

    async def main() -> tuple[bool, object]:
        readiness_passed = asyncio.Event()
        reopened = asyncio.Event()
        reader_hold = asyncio.Event()
        engine: _Probe

        class _Probe(AsyncControlModeEngine):
            initial_attempt: asyncio.Future[None]

            async def _find_attach_target(self) -> str | None:
                return "$0"

            async def _spawn(self) -> None:
                reopened.set()
                self._proc = t.cast(
                    "asyncio.subprocess.Process",
                    _RecordingProcess(),
                )

            async def _reader(self) -> None:
                await reader_hold.wait()

            @staticmethod
            async def _wait_start_attempt(
                attempt: asyncio.Future[None],
            ) -> None:
                await AsyncControlModeEngine._wait_start_attempt(attempt)
                if attempt is engine.initial_attempt:
                    readiness_passed.set()

        engine = _Probe()
        engine._started = True
        engine._proc = t.cast("asyncio.subprocess.Process", _RecordingProcess())
        engine.initial_attempt = engine._new_start_attempt()
        engine.initial_attempt.set_result(None)
        engine._start_attempt = engine.initial_attempt
        await engine._write_lock.acquire()

        command = asyncio.create_task(
            engine.run(CommandRequest.from_args("list-sessions"))
        )
        await readiness_passed.wait()
        await engine.aclose()
        engine._write_lock.release()

        reopened_wait = asyncio.create_task(reopened.wait())
        done, _pending = await asyncio.wait(
            (command, reopened_wait),
            return_when=asyncio.FIRST_COMPLETED,
        )
        reopened_after_close = reopened_wait in done
        if not reopened_wait.done():
            reopened_wait.cancel()
            await asyncio.gather(reopened_wait, return_exceptions=True)
        await engine.aclose()
        outcome = (await asyncio.gather(command, return_exceptions=True))[0]
        return reopened_after_close, outcome

    reopened, outcome = asyncio.run(asyncio.wait_for(main(), timeout=2.0))
    assert not reopened
    assert isinstance(outcome, ControlModeError)
    assert "closed" in str(outcome)


def test_terminal_reconnect_replay_failure_releases_waiters_and_restarts() -> None:
    """A terminal replay error reaches waiters and permits a fresh supervisor."""

    async def main() -> tuple[list[CommandResult | BaseException], int, bool]:
        waiters_arrived = asyncio.Event()
        waiter_count = 0
        replay_failed = asyncio.Event()
        engine: _Probe

        class _Probe(_GatedReconnectEngine):
            replay_count = 0

            @staticmethod
            async def _wait_start_attempt(
                attempt: asyncio.Future[None],
            ) -> None:
                nonlocal waiter_count
                if engine.second_spawn_started.is_set() and engine.spawn_count == 2:
                    waiter_count += 1
                    if waiter_count == 2:
                        waiters_arrived.set()
                await AsyncControlModeEngine._wait_start_attempt(attempt)

            async def _replay_subscriptions(self) -> None:
                self.replay_count += 1
                if self.replay_count == 2:
                    self.processes[-1].returncode = 23
                    replay_failed.set()
                    msg = "replay failed"
                    raise RuntimeError(msg)

        engine = _Probe()
        await engine.start()
        engine.disconnect.set()
        await engine.second_spawn_started.wait()
        waiters = [
            asyncio.create_task(engine.run(CommandRequest.from_args("list-sessions"))),
            asyncio.create_task(engine.run(CommandRequest.from_args("list-windows"))),
        ]
        await waiters_arrived.wait()
        old_supervisor = engine._supervisor_task
        assert old_supervisor is not None
        engine.release_second_spawn.set()
        await replay_failed.wait()
        await asyncio.wait((old_supervisor,))
        outcomes = list(await asyncio.gather(*waiters, return_exceptions=True))

        await engine.start()
        restarted = engine.third_connected.is_set()
        replay_count = engine.replay_count
        await engine.aclose()
        return outcomes, replay_count, restarted

    outcomes, replay_count, restarted = asyncio.run(
        asyncio.wait_for(main(), timeout=2.0)
    )
    assert all(isinstance(outcome, ControlModeError) for outcome in outcomes)
    assert all("replay failed" in str(outcome) for outcome in outcomes)
    assert all("return code 23" in str(outcome) for outcome in outcomes)
    assert all("generation 2" in str(outcome) for outcome in outcomes)
    assert replay_count == 3
    assert restarted


def test_empty_server_fallback_remains_lazy_and_structured() -> None:
    """Concurrent dead-engine calls retain the structured subprocess fallback."""

    async def main() -> tuple[list[CommandResult], bool, bool, int]:
        bootstrap_started = asyncio.Event()
        release_bootstrap = asyncio.Event()

        class _Bootstrap:
            calls = 0

            async def run_batch(
                self,
                requests: t.Sequence[CommandRequest],
            ) -> list[CommandResult]:
                self.calls += 1
                bootstrap_started.set()
                await release_bootstrap.wait()
                return [
                    CommandResult(
                        cmd=("tmux", *request.args),
                        stdout=("fallback",),
                    )
                    for request in requests
                ]

        class _Probe(AsyncControlModeEngine):
            async def _find_attach_target(self) -> str | None:
                return None

        engine = _Probe()
        bootstrap = _Bootstrap()
        engine._bootstrap = t.cast("t.Any", bootstrap)
        engine._started = True
        engine._dead = ControlModeError("connection lost")
        engine._start_attempt = engine._new_start_attempt()
        engine._start_attempt.set_result(None)
        first = asyncio.create_task(
            engine.run(CommandRequest.from_args("list-sessions"))
        )
        await bootstrap_started.wait()
        second = asyncio.create_task(
            engine.run(CommandRequest.from_args("list-windows"))
        )
        while bootstrap.calls < 2:
            await asyncio.sleep(0)
        release_bootstrap.set()
        results = list(await asyncio.gather(first, second))
        started = engine._started
        process_created = engine._proc is not None
        await engine.aclose()
        return results, started, process_created, bootstrap.calls

    results, started, process_created, calls = asyncio.run(
        asyncio.wait_for(main(), timeout=2.0)
    )
    assert [result.stdout for result in results] == [("fallback",), ("fallback",)]
    assert not started
    assert not process_created
    assert calls == 2


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


def test_spawn_keeps_dead_through_startup_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A startup ACK alone cannot publish reconnect readiness.

    Desired-state replay follows startup. The prior death sentinel therefore
    remains set both while the ACK is consumed and after ``_spawn`` returns;
    only the supervisor may clear it when replay has completed.
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
    assert observed["dead_during_startup"] is not None
    assert observed["dead_after"] is not None
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


def test_async_death_diagnostic_keeps_stderr_with_generation() -> None:
    """Generation evidence augments rather than displaces bounded stderr."""
    async_engine = AsyncControlModeEngine()
    async_engine._generation = 4
    async_engine._append_stderr(b"server-side reason\n")
    message = str(async_engine._died("tmux -C closed stdout"))
    assert "tmux -C closed stdout" in message
    assert "generation 4" in message
    assert "server-side reason" in message


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


def test_startup_exit_reason_is_retained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A startup ``%exit`` reason survives connection cleanup."""

    async def main() -> str:
        proc = _StartupProcess(b"%exit too far behind\n")

        async def _fake_exec(
            *_args: object,
            **_kwargs: object,
        ) -> _StartupProcess:
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        engine = AsyncControlModeEngine(tmux_bin="tmux")
        engine._next_attach_target = "$0"
        try:
            with pytest.raises(ControlModeError) as caught:
                await engine._spawn()
            return str(caught.value)
        finally:
            await engine.aclose()

    assert "too far behind" in asyncio.run(asyncio.wait_for(main(), timeout=2.0))


def test_startup_ack_with_exit_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A startup ACK cannot make a simultaneous ``%exit`` ready."""

    async def main() -> str:
        proc = _StartupProcess(b"%begin 1 1 0\n%end 1 1 0\n%exit too far behind\n")

        async def _fake_exec(
            *_args: object,
            **_kwargs: object,
        ) -> _StartupProcess:
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        engine = AsyncControlModeEngine(tmux_bin="tmux")
        engine._next_attach_target = "$0"
        try:
            with pytest.raises(ControlModeError) as caught:
                await engine._spawn()
            return str(caught.value)
        finally:
            await engine.aclose()

    assert "too far behind" in asyncio.run(asyncio.wait_for(main(), timeout=2.0))


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


def test_reader_death_includes_bounded_exit_reason_code_and_generation() -> None:
    """A final ``%exit`` explains one connection death without unbounded text."""

    async def main() -> str:
        reason = b"too far behind " + (b"x" * 20_000)
        chunks = [b"%exit " + reason + b"\n", b""]

        class _Stdout:
            async def read(self, _size: int) -> bytes:
                return chunks.pop(0)

        class _FakeProc(_RecordingProcess):
            def __init__(self) -> None:
                super().__init__()
                self.stdout = _Stdout()
                self.returncode = 17

        engine = AsyncControlModeEngine()
        engine._generation = 7
        proc = _FakeProc()
        engine._proc = t.cast("asyncio.subprocess.Process", proc)
        await engine._reader()
        assert engine._dead is not None
        return str(engine._dead)

    message = asyncio.run(main())
    assert "too far behind" in message
    assert "return code 17" in message
    assert "generation 7" in message
    assert len(message) < 5_000


def test_exit_reason_is_reset_before_replacement_generation() -> None:
    """A replacement connection cannot inherit the prior ``%exit`` reason."""

    async def main() -> list[str]:
        messages: list[str] = []

        class _Probe(AsyncControlModeEngine):
            spawn_count = 0

            async def _spawn(self) -> None:
                self.spawn_count += 1
                proc = _RecordingProcess()
                proc.returncode = 10 + self.spawn_count
                self._proc = t.cast("asyncio.subprocess.Process", proc)

            async def _reader(self) -> None:
                if self.spawn_count == 1:
                    self._publish(b"%exit prior generation")
                failure = self._died("simulated EOF")
                messages.append(str(failure))
                self._mark_dead(failure)
                if self.spawn_count == 2:
                    self._closing = True

            @staticmethod
            def _backoff(_attempt: int) -> float:
                return 0.0

        engine = _Probe()
        await engine.start()
        supervisor = engine._supervisor_task
        assert supervisor is not None
        await asyncio.wait((supervisor,))
        await engine.aclose()
        return messages

    first, second = asyncio.run(main())
    assert "prior generation" in first
    assert "prior generation" not in second
    assert "generation 1" in first
    assert "generation 2" in second


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
