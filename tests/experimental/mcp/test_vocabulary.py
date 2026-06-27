"""The curated core vocabulary -- intuitive named tmux tools.

Pure tests run the vocabulary against the in-memory ``ConcreteEngine`` (no tmux);
a live test drives a real tmux server end to end (create -> window -> split ->
send -> capture -> rename -> kill) over the subprocess engine.
"""

from __future__ import annotations

import typing as t

from libtmux.experimental.engines import ConcreteEngine, SubprocessEngine
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
from libtmux.experimental.ops._types import SessionId
from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    from pathlib import Path

    from libtmux.session import Session


def test_create_session_returns_typed_result() -> None:
    """create_session yields a typed result with the captured first pane id."""
    result = create_session(ConcreteEngine(), name="dev")
    assert result.session_id == "$1"
    assert result.name == "dev"
    assert result.first_window_id == "@1"
    assert result.first_pane_id == "%1"


def test_create_window_then_split() -> None:
    """create_window captures a first pane id that split_pane can target."""
    engine = ConcreteEngine()
    session = create_session(engine, name="dev")
    window = create_window(engine, session.session_id, name="logs")
    assert window.window_id.startswith("@")
    assert window.first_pane_id is not None
    pane = split_pane(engine, window.first_pane_id, horizontal=True)
    assert pane.pane_id.startswith("%")


def test_new_pane_creates_floating_pane() -> None:
    """new_pane creates a floating pane and returns its id (in-memory)."""
    engine = ConcreteEngine()
    session = create_session(engine, name="dev")
    pane = new_pane(engine, session.first_pane_id or "%1", width=80, height=20)
    assert pane.pane_id.startswith("%")


def test_send_input_is_fire_and_forget() -> None:
    """send_input runs without returning a value (and without raising)."""
    send_input(ConcreteEngine(), "%1", "echo hi", enter=True)


def test_capture_pane_returns_lines() -> None:
    """capture_pane surfaces the pane's lines."""
    engine = ConcreteEngine(capture_lines=("line-1", "line-2"))
    assert capture_pane(engine, "%1").lines == ("line-1", "line-2")


def test_list_tools_return_listings() -> None:
    """The list_* tools return a Listing of format rows."""
    engine = ConcreteEngine()
    assert isinstance(list_sessions(engine).rows, tuple)
    assert isinstance(list_windows(engine).rows, tuple)
    assert isinstance(list_panes(engine).rows, tuple)


def test_target_accepts_string_or_typed() -> None:
    """A vocabulary target may be a string or an already-typed Target."""
    engine = ConcreteEngine()
    assert create_window(engine, "$1").window_id.startswith("@")
    assert create_window(engine, SessionId("$1")).window_id.startswith("@")


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
