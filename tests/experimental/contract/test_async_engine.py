"""Async engine against a real tmux server, and parity with the classic engine.

Uses :func:`asyncio.run` to drive :func:`arun` so the async transport is
exercised end to end without a pytest-asyncio dependency.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys
import typing as t

import pytest

from libtmux.experimental.engines import AsyncSubprocessEngine, SubprocessEngine
from libtmux.experimental.ops import SendKeys, SplitWindow, arun, run
from libtmux.experimental.ops._types import PaneId, WindowId
from libtmux.experimental.ops.results import SplitWindowResult

if t.TYPE_CHECKING:
    import pathlib

    from libtmux.session import Session


def test_async_run_cancellation_suppresses_terminate_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation propagates even when terminate() races a process exit."""
    from libtmux.experimental.engines.base import CommandRequest

    class _FakeProc:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            raise asyncio.CancelledError

        def terminate(self) -> None:
            raise ProcessLookupError

        async def wait(self) -> int:
            return 0

    async def _fake_exec(*_args: object, **_kwargs: object) -> _FakeProc:
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    engine = AsyncSubprocessEngine(tmux_bin="tmux")

    async def _check() -> None:
        with pytest.raises(asyncio.CancelledError):
            await engine.run(CommandRequest.from_args("display-message", "-p", "x"))

    asyncio.run(_check())


def test_async_cancellation_shields_escalation_from_second_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated cancellation cannot bypass bounded kill or leak pipe tasks."""
    import libtmux.experimental.engines.asyncio as asyncio_engine
    from libtmux.experimental.engines.base import CommandRequest

    class _FakeProc:
        returncode: int | None = None

        def __init__(self) -> None:
            self.communicating = asyncio.Event()
            self.communication_finished = asyncio.Event()
            self.terminated = asyncio.Event()
            self.signals: list[str] = []

        async def communicate(self) -> tuple[bytes, bytes]:
            self.communicating.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.communication_finished.set()
            return (b"", b"")

        def terminate(self) -> None:
            self.signals.append("terminate")
            self.terminated.set()

        def kill(self) -> None:
            self.signals.append("kill")
            self.returncode = -signal.SIGKILL

        async def wait(self) -> int:
            await asyncio.Event().wait()
            return t.cast("int", self.returncode)

    process = _FakeProc()

    async def _fake_exec(*_args: object, **_kwargs: object) -> _FakeProc:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(asyncio_engine, "_TERMINATE_TIMEOUT", 0.01, raising=False)
    monkeypatch.setattr(asyncio_engine, "_KILL_TIMEOUT", 0.01, raising=False)

    async def _check() -> None:
        engine = AsyncSubprocessEngine(tmux_bin="tmux")
        task = asyncio.create_task(
            engine.run(CommandRequest.from_args("display-message", "-p", "x")),
        )
        await process.communicating.wait()
        task.cancel()
        await process.terminated.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=0.25)

        assert process.signals == ["terminate", "kill"]
        assert process.communication_finished.is_set()
        assert asyncio.all_tasks() == {asyncio.current_task()}

    asyncio.run(_check())


def test_async_cancellation_reaps_real_sigterm_ignoring_child(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bounded escalation reaps a real child and its pipe-reader task."""
    import libtmux.experimental.engines.asyncio as asyncio_engine
    from libtmux.experimental.engines.base import CommandRequest

    monkeypatch.setattr(asyncio_engine, "_TERMINATE_TIMEOUT", 0.05, raising=False)
    monkeypatch.setattr(asyncio_engine, "_KILL_TIMEOUT", 0.05, raising=False)
    tmux_bin = tmp_path / "tmux-blocking"
    pid_file = tmp_path / "child.pid"
    tmux_bin.write_text(
        f"""#!{sys.executable}
import os
import pathlib
import signal
import sys

signal.signal(signal.SIGTERM, signal.SIG_IGN)
pathlib.Path(sys.argv[-1]).write_text(str(os.getpid()), encoding="utf-8")
signal.pause()
""",
        encoding="utf-8",
    )
    tmux_bin.chmod(0o755)

    async def _check() -> None:
        child_pid: int | None = None
        task = asyncio.create_task(
            AsyncSubprocessEngine(tmux_bin=tmux_bin).run(
                CommandRequest.from_args("display-message", pid_file),
            ),
        )
        try:
            for _ in range(100):
                if pid_file.exists():
                    break
                await asyncio.sleep(0.01)
            assert pid_file.exists()
            child_pid = int(pid_file.read_text(encoding="utf-8"))

            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            with pytest.raises(ProcessLookupError):
                os.kill(child_pid, 0)
            assert asyncio.all_tasks() == {asyncio.current_task()}
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if child_pid is not None:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(child_pid, signal.SIGKILL)

    asyncio.run(_check())


def test_async_cancellation_drains_a_killed_childs_full_pipe(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation keeps pipe readers alive through TERM, KILL, and EOF."""
    import libtmux.experimental.engines.asyncio as asyncio_engine
    from libtmux.experimental.engines.base import CommandRequest

    monkeypatch.setattr(asyncio_engine, "_TERMINATE_TIMEOUT", 0.05, raising=False)
    monkeypatch.setattr(asyncio_engine, "_KILL_TIMEOUT", 0.05, raising=False)
    tmux_bin = tmp_path / "tmux-full-pipe"
    pid_file = tmp_path / "child.pid"
    tmux_bin.write_text(
        f"""#!{sys.executable}
import os
import pathlib
import signal
import sys
import time

signal.signal(signal.SIGTERM, signal.SIG_IGN)
pathlib.Path(sys.argv[-1]).write_text(str(os.getpid()), encoding="utf-8")
chunk = b"x" * 65536
while True:
    os.write(sys.stdout.fileno(), chunk)
    time.sleep(0.001)
""",
        encoding="utf-8",
    )
    tmux_bin.chmod(0o755)
    real_exec = asyncio.create_subprocess_exec
    processes: list[asyncio.subprocess.Process] = []

    async def _tracked_exec(
        *args: object,
        **kwargs: object,
    ) -> asyncio.subprocess.Process:
        process = await real_exec(*args, **kwargs)  # type: ignore[arg-type]
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _tracked_exec)

    async def _check() -> None:
        loop = asyncio.get_running_loop()
        diagnostics: list[dict[str, t.Any]] = []
        loop.set_debug(True)
        loop.set_exception_handler(lambda _loop, context: diagnostics.append(context))
        task = asyncio.create_task(
            AsyncSubprocessEngine(tmux_bin=tmux_bin).run(
                CommandRequest.from_args("display-message", pid_file),
            ),
        )
        for _ in range(100):
            if pid_file.exists():
                break
            await asyncio.sleep(0.01)
        assert pid_file.exists()
        await asyncio.sleep(0.05)

        started = loop.time()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert loop.time() - started < 0.5

        process = processes[0]
        assert process.returncode == -signal.SIGKILL
        transport = t.cast("t.Any", process)._transport
        stdout_transport = t.cast("t.Any", process.stdout)._transport
        assert transport.is_closing()
        assert stdout_transport.is_closing()
        assert asyncio.all_tasks() == {asyncio.current_task()}
        await asyncio.sleep(0)
        assert diagnostics == []

    asyncio.run(_check())


@pytest.mark.parametrize("reported", ("3.4a", "next-3.8", "master"))
def test_async_version_probe_matches_sync_and_is_cached(
    reported: str,
    tmp_path: pathlib.Path,
) -> None:
    """Native async version I/O matches sync normalization and probes once."""
    tmux_bin = tmp_path / "tmux-version"
    tmux_bin.write_text(
        f"#!{sys.executable}\nprint('tmux {reported}')\n",
        encoding="utf-8",
    )
    tmux_bin.chmod(0o755)
    sync_version = SubprocessEngine(tmux_bin=tmux_bin).tmux_version()

    async def _probe_twice() -> tuple[str | None, str | None]:
        engine = AsyncSubprocessEngine(tmux_bin=tmux_bin)
        first = await engine.atmux_version()
        tmux_bin.unlink()
        return first, await engine.atmux_version()

    first, second = asyncio.run(_probe_twice())
    assert first == second == sync_version
    assert first is not None


def test_async_subprocess_preserves_global_option_semicolon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Async direct argv applies semicolon encoding after global options."""
    from libtmux.experimental.engines.base import CommandRequest

    captured: list[object] = []

    class _FakeProc:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return (b"", b"")

    async def _fake_exec(*cmd: object, **_kwargs: object) -> _FakeProc:
        captured.extend(cmd)
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    request = CommandRequest.from_args(
        "-L",
        "socket;",
        "display-message",
        "literal;",
    )

    async def _check() -> None:
        await AsyncSubprocessEngine(tmux_bin="tmux").run(request)

    asyncio.run(_check())

    assert captured == [
        "tmux",
        "-L",
        "socket;",
        "display-message",
        "literal\\;",
    ]


def test_async_split_creates_real_pane(session: Session) -> None:
    """An async split returns a typed result whose new pane really exists."""
    server = session.server
    window = session.active_window
    assert window.window_id is not None
    engine = AsyncSubprocessEngine.for_server(server)

    result = asyncio.run(arun(SplitWindow(target=WindowId(window.window_id)), engine))

    assert isinstance(result, SplitWindowResult)
    assert result.ok
    assert result.new_pane_id is not None
    assert server.panes.get(pane_id=result.new_pane_id) is not None


def test_async_sync_parity(session: Session) -> None:
    """The async and sync classic engines agree on result type and argv."""
    server = session.server
    window = session.active_window
    assert window.window_id is not None
    operation = SplitWindow(target=WindowId(window.window_id))

    sync_result = run(operation, SubprocessEngine.for_server(server))
    async_result = asyncio.run(
        arun(operation, AsyncSubprocessEngine.for_server(server)),
    )

    assert type(sync_result) is type(async_result) is SplitWindowResult
    assert sync_result.argv == async_result.argv == operation.render()
    assert sync_result.ok and async_result.ok


def test_async_literal_target_cannot_start_command(session: Session) -> None:
    """Async typed arguments cannot become a second tmux command."""
    pane = session.active_pane
    assert pane is not None
    pane_id = pane.pane_id
    assert pane_id is not None
    operation = SendKeys(
        target=PaneId(f"{pane_id};"),
        keys="kill-server",
    )

    result = asyncio.run(
        arun(operation, AsyncSubprocessEngine.for_server(session.server)),
    )

    assert result.failed
    assert session.server.is_alive()
