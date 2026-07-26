"""Tests for the object matrix (scope x mode) over the shared spine."""

from __future__ import annotations

import asyncio
import typing as t

import pytest

import libtmux.experimental.ops.exc as ops_exc
from libtmux.experimental.engines import AsyncMockEngine, MockEngine
from libtmux.experimental.engines.base import (
    AsyncTmuxEngine,
    CommandRequest,
    CommandResult,
    TmuxEngine,
)
from libtmux.experimental.objects import (
    AsyncPane,
    AsyncServer,
    AsyncSession,
    AsyncWindow,
    EagerPane,
    EagerServer,
    EagerSession,
    EagerWindow,
    LazyWindow,
)
from libtmux.experimental.ops import LazyPlan
from libtmux.experimental.ops._types import WindowId

if t.TYPE_CHECKING:
    from libtmux.session import Session


class _MissingCaptureEngine:
    """Return successful commands without the create id tmux was asked to print."""

    def __init__(self, stdout: tuple[str, ...]) -> None:
        """Store the raw create output returned by each command."""
        self.stdout = stdout

    def run(self, request: CommandRequest) -> CommandResult:
        """Return a successful result with the configured stdout."""
        return CommandResult(cmd=("tmux", *request.args), stdout=self.stdout)

    def run_batch(
        self,
        requests: t.Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Run each request in order."""
        return [self.run(request) for request in requests]


class _AsyncMissingCaptureEngine:
    """Async sibling of the missing-capture engine."""

    def __init__(self, stdout: tuple[str, ...]) -> None:
        """Store the raw create output returned by each command."""
        self.stdout = stdout

    async def run(self, request: CommandRequest) -> CommandResult:
        """Return a successful result with the configured stdout."""
        return CommandResult(cmd=("tmux", *request.args), stdout=self.stdout)

    async def run_batch(
        self,
        requests: t.Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Run each request in order."""
        return [await self.run(request) for request in requests]


class _EagerCreateCase(t.NamedTuple):
    """An eager object create call that requires a captured id.

    Attributes
    ----------
    test_id : str
        Stable pytest parameter id.
    call : Callable[[TmuxEngine], object]
        Object create call under test.
    """

    test_id: str
    call: t.Callable[[TmuxEngine], object]


_EAGER_CREATE_CASES = (
    _EagerCreateCase(
        "server_new_session",
        lambda engine: EagerServer(engine).new_session(),
    ),
    _EagerCreateCase(
        "session_new_window",
        lambda engine: EagerSession(engine, "$1").new_window(),
    ),
    _EagerCreateCase(
        "window_split",
        lambda engine: EagerWindow(engine, "@1").split(),
    ),
    _EagerCreateCase(
        "pane_split",
        lambda engine: EagerPane(engine, "%1").split(),
    ),
    _EagerCreateCase(
        "pane_new_pane",
        lambda engine: EagerPane(engine, "%1").new_pane(),
    ),
)


class _AsyncCreateCase(t.NamedTuple):
    """An async object create call that requires a captured id.

    Attributes
    ----------
    test_id : str
        Stable pytest parameter id.
    call : Callable[[AsyncTmuxEngine], Coroutine[Any, Any, object]]
        Async object create call under test.
    """

    test_id: str
    call: t.Callable[[AsyncTmuxEngine], t.Coroutine[t.Any, t.Any, object]]


_ASYNC_CREATE_CASES = (
    _AsyncCreateCase(
        "server_new_session",
        lambda engine: AsyncServer(engine).new_session(),
    ),
    _AsyncCreateCase(
        "session_new_window",
        lambda engine: AsyncSession(engine, "$1").new_window(),
    ),
    _AsyncCreateCase(
        "window_split",
        lambda engine: AsyncWindow(engine, "@1").split(),
    ),
    _AsyncCreateCase(
        "pane_split",
        lambda engine: AsyncPane(engine, "%1").split(),
    ),
    _AsyncCreateCase(
        "pane_new_pane",
        lambda engine: AsyncPane(engine, "%1").new_pane(),
    ),
)

_MISSING_CAPTURE_OUTPUTS = (
    pytest.param((), id="absent_stdout"),
    pytest.param(("",), id="empty_line"),
    pytest.param((" \t ",), id="whitespace_line"),
)


@pytest.mark.parametrize(
    "case",
    _EAGER_CREATE_CASES,
    ids=[case.test_id for case in _EAGER_CREATE_CASES],
)
@pytest.mark.parametrize("stdout", _MISSING_CAPTURE_OUTPUTS)
def test_eager_create_without_captured_id_raises(
    case: _EagerCreateCase,
    stdout: tuple[str, ...],
) -> None:
    """Eager object navigation rejects a successful create with no captured id."""
    with pytest.raises(ops_exc.OperationError) as exc_info:
        case.call(_MissingCaptureEngine(stdout))

    assert isinstance(exc_info.value, ops_exc.MissingCreateIdError)
    assert exc_info.value.result.status == "complete"


@pytest.mark.parametrize(
    "case",
    _ASYNC_CREATE_CASES,
    ids=[case.test_id for case in _ASYNC_CREATE_CASES],
)
@pytest.mark.parametrize("stdout", _MISSING_CAPTURE_OUTPUTS)
def test_async_create_without_captured_id_raises(
    case: _AsyncCreateCase,
    stdout: tuple[str, ...],
) -> None:
    """Async object navigation rejects a successful create with no captured id."""
    with pytest.raises(ops_exc.OperationError) as exc_info:
        asyncio.run(case.call(_AsyncMissingCaptureEngine(stdout)))

    assert isinstance(exc_info.value, ops_exc.MissingCreateIdError)
    assert exc_info.value.result.status == "complete"


def test_eager_full_navigation_offline() -> None:
    """Eager Server->Session->Window->Pane navigation via the mock engine."""
    server = EagerServer(MockEngine())
    session = server.new_session(name="work")
    assert session.session_id == "$1"
    window = session.new_window(name="build")
    assert window.window_id == "@1"
    pane = window.split(horizontal=True)
    assert isinstance(pane, EagerPane)
    assert pane.pane_id == "%1"


def test_eager_window_methods() -> None:
    """EagerWindow rename/select_layout/kill return successful results."""
    window = EagerWindow(MockEngine(), "@1")
    assert window.rename("x").ok
    assert window.select_layout("tiled").ok
    assert window.kill().ok


def test_lazy_window_records_and_executes() -> None:
    """LazyWindow records ops and resolves the new pane on execute."""
    plan = LazyPlan()
    window = LazyWindow(plan, WindowId("@1"))
    window.split()
    window.rename("build")
    assert len(plan) == 2

    outcome = plan.execute(MockEngine())
    assert outcome.ok
    assert outcome.results[0].created_id == "%1"


def test_async_window_and_pane() -> None:
    """Async objects mirror the eager ones via await."""

    async def main() -> tuple[str, bool, bool]:
        window = AsyncWindow(AsyncMockEngine(), "@1")
        pane = await window.split()
        assert isinstance(pane, AsyncPane)
        sent = await pane.send_keys("echo hi", enter=True)
        laid_out = await window.select_layout("tiled")  # parity with eager/lazy
        return pane.pane_id, sent.ok, laid_out.ok

    pane_id, ok, laid_out = asyncio.run(main())
    assert pane_id == "%1"
    assert ok
    assert laid_out


def test_eager_navigation_live(session: Session) -> None:
    """Eager object builds a real session/window/pane against tmux, then cleans up."""
    server = session.server
    server_obj = EagerServer.for_server(server)

    created = server_obj.new_session(name="object-matrix-test")
    try:
        assert created.session_id.startswith("$")
        assert server.sessions.get(session_id=created.session_id) is not None

        window = created.new_window(name="built")
        assert window.window_id.startswith("@")
        assert server.windows.get(window_id=window.window_id) is not None

        pane = window.split(horizontal=True)
        assert pane.pane_id.startswith("%")
        assert server.panes.get(pane_id=pane.pane_id) is not None
    finally:
        created.kill()
