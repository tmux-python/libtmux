"""Async engine against a real tmux server, and parity with the classic engine.

Uses :func:`asyncio.run` to drive :func:`arun` so the async transport is
exercised end to end without a pytest-asyncio dependency.
"""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.experimental.engines import AsyncSubprocessEngine, SubprocessEngine
from libtmux.experimental.ops import SendKeys, SplitWindow, arun, run
from libtmux.experimental.ops._types import PaneId, WindowId
from libtmux.experimental.ops.results import SplitWindowResult

if t.TYPE_CHECKING:
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
