"""The curated core vocabulary -- intuitive named tmux tools.

Pure tests run the vocabulary against the in-memory ``MockEngine`` (no tmux);
a live test drives a real tmux server end to end (create -> window -> split ->
send -> capture -> rename -> kill) over the subprocess engine.
"""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.experimental.engines import MockEngine, SubprocessEngine
from libtmux.experimental.engines.base import (
    AsyncTmuxEngine,
    CommandRequest,
    CommandResult,
    TmuxEngine,
)
from libtmux.experimental.mcp import (
    capture_pane,
    create_session,
    create_window,
    kill_session,
    list_panes,
    list_sessions,
    list_windows,
    new_pane,
    rename_window,
    send_input,
    split_pane,
)
from libtmux.experimental.mcp.vocabulary import (
    abreak_pane,
    acreate_session,
    acreate_window,
    anew_pane,
    asplit_pane,
    break_pane,
)
from libtmux.experimental.ops._types import SessionId
from libtmux.experimental.ops.exc import MissingCreateIdError
from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    from pathlib import Path

    from libtmux.session import Session


class _MissingCaptureEngine:
    """Return successful commands with controlled capture output."""

    def __init__(self, stdout: tuple[str, ...]) -> None:
        self.stdout = stdout

    def run(self, request: CommandRequest) -> CommandResult:
        """Return the configured output for one successful command."""
        return CommandResult(
            cmd=("tmux", *request.args),
            stdout=self.stdout,
            returncode=0,
        )

    def run_batch(
        self,
        requests: t.Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Run each request in order."""
        return [self.run(request) for request in requests]


class _AsyncMissingCaptureEngine:
    """Async sibling of :class:`_MissingCaptureEngine`."""

    def __init__(self, stdout: tuple[str, ...]) -> None:
        self.stdout = stdout

    async def run(self, request: CommandRequest) -> CommandResult:
        """Return the configured output for one successful command."""
        return CommandResult(
            cmd=("tmux", *request.args),
            stdout=self.stdout,
            returncode=0,
        )

    async def run_batch(
        self,
        requests: t.Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Run each request in order."""
        return [await self.run(request) for request in requests]


class _CreateCase(t.NamedTuple):
    """One curated create tool with sync and async invocations."""

    name: str
    sync_call: t.Callable[[TmuxEngine], object]
    async_call: t.Callable[
        [AsyncTmuxEngine],
        t.Coroutine[t.Any, t.Any, object],
    ]


_CREATE_CASES = (
    _CreateCase(
        "create_session",
        lambda engine: create_session(engine),
        lambda engine: acreate_session(engine),
    ),
    _CreateCase(
        "create_window",
        lambda engine: create_window(engine, "$1"),
        lambda engine: acreate_window(engine, "$1"),
    ),
    _CreateCase(
        "split_pane",
        lambda engine: split_pane(engine, "%1"),
        lambda engine: asplit_pane(engine, "%1"),
    ),
    _CreateCase(
        "new_pane",
        lambda engine: new_pane(engine, "%1"),
        lambda engine: anew_pane(engine, "%1"),
    ),
    _CreateCase(
        "break_pane",
        lambda engine: break_pane(engine, "%1"),
        lambda engine: abreak_pane(engine, "%1"),
    ),
)

_MISSING_OUTPUTS = (
    pytest.param((), id="absent"),
    pytest.param(("",), id="blank"),
    pytest.param((" \t ",), id="whitespace"),
)


@pytest.mark.parametrize("case", _CREATE_CASES, ids=lambda case: case.name)
@pytest.mark.parametrize("stdout", _MISSING_OUTPUTS)
def test_curated_sync_create_requires_captured_id(
    case: _CreateCase,
    stdout: tuple[str, ...],
) -> None:
    """A successful sync create cannot return an empty typed identifier."""
    with pytest.raises(MissingCreateIdError):
        case.sync_call(_MissingCaptureEngine(stdout))


@pytest.mark.parametrize("case", _CREATE_CASES, ids=lambda case: case.name)
@pytest.mark.parametrize("stdout", _MISSING_OUTPUTS)
def test_curated_async_create_requires_captured_id(
    case: _CreateCase,
    stdout: tuple[str, ...],
) -> None:
    """A successful async create cannot return an empty typed identifier."""
    with pytest.raises(MissingCreateIdError):
        asyncio.run(case.async_call(_AsyncMissingCaptureEngine(stdout)))


@pytest.mark.parametrize(
    ("call", "stdout"),
    (
        (lambda engine: create_session(engine), ("$1",)),
        (lambda engine: create_session(engine), ("$1 @2",)),
        (lambda engine: create_window(engine, "$1"), ("@2",)),
    ),
)
def test_curated_create_requires_promised_child_ids(
    call: t.Callable[[TmuxEngine], object],
    stdout: tuple[str, ...],
) -> None:
    """A create that requests child ids rejects a partial capture line."""
    with pytest.raises(MissingCreateIdError):
        call(_MissingCaptureEngine(stdout))


@pytest.mark.parametrize(
    ("call", "stdout"),
    (
        (lambda engine: acreate_session(engine), ("$1",)),
        (lambda engine: acreate_session(engine), ("$1 @2",)),
        (lambda engine: acreate_window(engine, "$1"), ("@2",)),
    ),
)
def test_curated_async_create_requires_promised_child_ids(
    call: t.Callable[
        [AsyncTmuxEngine],
        t.Coroutine[t.Any, t.Any, object],
    ],
    stdout: tuple[str, ...],
) -> None:
    """The async create path also rejects a partial child-id capture."""
    with pytest.raises(MissingCreateIdError):
        asyncio.run(call(_AsyncMissingCaptureEngine(stdout)))


def test_create_session_returns_typed_result() -> None:
    """create_session yields a typed result with the captured first pane id."""
    result = create_session(MockEngine(), name="dev")
    assert result.session_id == "$1"
    assert result.name == "dev"
    assert result.first_window_id == "@1"
    assert result.first_pane_id == "%1"


def test_create_window_then_split() -> None:
    """create_window captures a first pane id that split_pane can target."""
    engine = MockEngine()
    session = create_session(engine, name="dev")
    window = create_window(engine, session.session_id, name="logs")
    assert window.window_id.startswith("@")
    assert window.first_pane_id is not None
    pane = split_pane(engine, window.first_pane_id, horizontal=True)
    assert pane.pane_id.startswith("%")


def test_new_pane_creates_floating_pane() -> None:
    """new_pane creates a floating pane and returns its id (in-memory)."""
    engine = MockEngine()
    session = create_session(engine, name="dev")
    pane = new_pane(engine, session.first_pane_id or "%1", width=80, height=20)
    assert pane.pane_id.startswith("%")


def test_send_input_is_fire_and_forget() -> None:
    """send_input runs without returning a value (and without raising)."""
    send_input(MockEngine(), "%1", "echo hi", enter=True)


def test_capture_pane_returns_lines() -> None:
    """capture_pane surfaces the pane's lines."""
    engine = MockEngine(capture_lines=("line-1", "line-2"))
    assert capture_pane(engine, "%1").lines == ("line-1", "line-2")


def test_list_tools_return_listings() -> None:
    """The list_* tools return a Listing of format rows."""
    engine = MockEngine()
    assert isinstance(list_sessions(engine).rows, tuple)
    assert isinstance(list_windows(engine).rows, tuple)
    assert isinstance(list_panes(engine).rows, tuple)


def test_target_accepts_string_or_typed() -> None:
    """A vocabulary target may be a string or an already-typed Target."""
    engine = MockEngine()
    assert create_window(engine, "$1").window_id.startswith("@")
    assert create_window(engine, SessionId("$1")).window_id.startswith("@")


def test_break_pane_named_tmux_3_7_path_live(session: Session) -> None:
    """The curated tool returns a name only after live tmux applies it."""
    pane = session.active_pane
    assert pane is not None and pane.pane_id is not None
    engine = SubprocessEngine.for_server(session.server)
    split = split_pane(engine, pane.pane_id)

    broken = break_pane(
        engine,
        split.pane_id,
        name="mcp-broken",
        version="3.7",
    )

    live = session.server.windows.get(window_id=broken.window_id)
    assert live is not None
    assert broken.name == live.window_name == "mcp-broken"


def test_vocabulary_live(session: Session, tmp_path: Path) -> None:
    """Drive a real tmux server through the curated vocabulary end to end."""
    server = session.server
    engine = SubprocessEngine.for_server(server)

    created = create_session(engine, name="vocab-live", start_directory=str(tmp_path))
    try:
        assert server.sessions.filter(session_name="vocab-live")
        assert created.first_pane_id is not None

        window = create_window(engine, created.session_id, name="extra")
        assert window.first_pane_id is not None
        pane = split_pane(engine, window.first_pane_id, horizontal=True)
        send_input(engine, pane.pane_id, "echo VOCABMARK", enter=True)

        def _ran() -> bool:
            live = server.panes.get(pane_id=pane.pane_id)
            return live is not None and "VOCABMARK" in "\n".join(live.capture_pane())

        assert retry_until(_ran, 5, raises=False)

        rename_window(engine, window.window_id, "renamed")
        renamed = server.windows.get(window_id=window.window_id)
        assert renamed is not None
        assert renamed.window_name == "renamed"
    finally:
        kill_session(engine, created.session_id)
        assert not server.sessions.filter(session_name="vocab-live")
