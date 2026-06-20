"""Forward (lazily-resolved) refs: the dual-purpose PaneRef/WindowRef/SessionRef."""

from __future__ import annotations

import typing as t

import pytest

from libtmux._experimental.chain import (
    ForwardDataUnavailable,
    PaneRef,
    SessionPlanExecutor,
    new_session,
)

if t.TYPE_CHECKING:
    from libtmux.session import Session


def _seed(pane: t.Any) -> PaneRef:
    return PaneRef.concrete(
        pane_id=pane.pane_id,
        window_id=pane.window_id,
        session_id=pane.session_id,
        pane_index=int(pane.pane_index or 0),
        active=pane.pane_active == "1",
        title=pane.pane_title or "",
    )


def test_forward_is_same_type_reuses_namespaces_and_guards_metadata() -> None:
    """A forward ref is a PaneRef; .cmd is reused; metadata is guarded."""
    seed = PaneRef.concrete(
        pane_id="%1",
        window_id="@1",
        session_id="$0",
        pane_index=0,
        active=True,
        title="editor",
    )
    child = seed.split(horizontal=True)

    assert isinstance(child, PaneRef)  # SAME type, not a parallel object
    assert child.is_forward and not seed.is_forward
    # The pane id is pending (no -t = active), but the window is still the
    # concrete @1 the split happened in -- propagated, so it stays addressable:
    assert child.cmd.send_keys("htop").argv() == ("send-keys", "htop")
    assert child.window.select_layout("tiled").argv() == (
        "select-layout",
        "-t",
        "@1",
        "tiled",
    )

    assert seed.title == "editor"  # concrete metadata: typed str
    with pytest.raises(ForwardDataUnavailable):
        _ = child.title  # forward metadata: guarded (pending-attribute pattern)


def test_forward_do_threads_commands_and_compiles_one_chain() -> None:
    """`.do()` reuses the namespaces fluently and compiles to one chain (pure)."""
    seed = PaneRef.concrete(
        pane_id="%1",
        window_id="@1",
        session_id="$0",
        pane_index=0,
        active=True,
        title="x",
    )
    plan = (
        seed.split(horizontal=True)  # split %1 -> forward B
        .split()  # split B -> forward C
        .do(lambda p: p.cmd.send_keys("htop", enter=True))  # reuse .cmd
    )
    assert plan.to_chain().argvs() == (
        ("split-window", "-t", "%1", "-h"),
        ("split-window", "-v"),
        ("send-keys", "htop", "Enter"),
    )


def test_forward_pane_resolves_to_newly_created_pane(session: Session) -> None:
    """Live: split a pane, split that pane, mark the deepest -- one dispatch."""
    window = session.new_window(window_name="fwd_pane")
    seed_pane = window.active_pane
    assert seed_pane is not None

    (
        _seed(seed_pane)
        .split(horizontal=True)
        .split()
        .do(lambda p: p.cmd.raw("set-option", "-p", "@cc_mark", "DEEP"))
        .run(session.server)
    )

    window.refresh()
    assert len(window.panes) == 3
    marked = [
        p
        for p in window.panes
        if "DEEP" in p.cmd("display-message", "-p", "#{@cc_mark}").stdout
    ]
    assert len(marked) == 1
    assert marked[0].pane_active == "1"
    assert marked[0].pane_id != seed_pane.pane_id  # forward ref resolved


def test_forward_window_scope_creates_window_then_splits(session: Session) -> None:
    """Live: session -> new_window (forward WindowRef) -> split inside it."""
    from libtmux._experimental.chain import SessionRef, SessionTarget

    assert session.session_id is not None
    sref = SessionRef.concrete(
        session_id=SessionTarget(session.session_id),
        session_name=session.session_name or "",
    )
    n_before = len(session.windows)

    sref.new_window(name="fwd_win").split(horizontal=True).run(session.server)

    session.refresh()
    assert len(session.windows) == n_before + 1
    new_win = next(w for w in session.windows if w.window_name == "fwd_win")
    new_win.refresh()
    assert len(new_win.panes) == 2  # the new window's pane was split


def test_forward_session_scope_creates_session(session: Session) -> None:
    """Live: new_session (forward SessionRef) -> new_window, one dispatch."""
    server = session.server
    name = "cc_v2_fwd_sess"
    try:
        new_session(name=name).new_window(name="built").run(server)

        created = next((s for s in server.sessions if s.session_name == name), None)
        assert created is not None  # the forward session was created
        assert "built" in {w.window_name for w in created.windows}
    finally:
        for s in list(server.sessions):
            if s.session_name == name:
                s.kill()


def test_forward_paneref_runs_through_executor(session: Session) -> None:
    """A forward plan also dispatches through SessionPlanExecutor."""
    window = session.new_window(window_name="fwd_exec")
    seed_pane = window.active_pane
    assert seed_pane is not None

    _seed(seed_pane).split().split().run(SessionPlanExecutor(session))

    window.refresh()
    assert len(window.panes) == 3
