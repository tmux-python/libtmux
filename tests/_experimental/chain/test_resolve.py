"""Multi-dispatch resolution: independent forward handles, sync + async."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field

import pytest

from libtmux._experimental.chain import (
    AsyncSessionPlanExecutor,
    ForwardPlan,
    SessionPlanExecutor,
    panes,
)
from libtmux._experimental.chain._resolve import Dispatch, _marked_eligible, drive
from libtmux._experimental.chain.plan import PaneTarget

if t.TYPE_CHECKING:
    from libtmux.session import Session


@dataclass
class _FakeResult:
    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)
    returncode: int = 0


def _mark(value: str) -> t.Callable[[t.Any], t.Any]:
    return lambda h: h.cmd.raw("set-option", "-p", "@m", value)


def test_drive_core_is_sans_io_and_substitutes_ids() -> None:
    """The core yields Dispatch, captures ids, and substitutes them -- no tmux.

    A hand-rolled driver feeds fake ids back, proving the resolution logic is a
    pure generator independent of any I/O (just like the sync/async drivers).
    """
    plan = ForwardPlan(PaneTarget("%1"))
    left, right = plan.split(horizontal=True), plan.split()
    left.do(_mark("L"))
    right.do(_mark("R"))

    gen = drive(tuple(plan._steps))
    dispatched: list[tuple[str, ...]] = []
    fake_ids = iter(["%7", "%8"])
    request = next(gen)
    try:
        while True:
            assert isinstance(request, Dispatch)
            dispatched.append(request.argv)
            out = [next(fake_ids)] if request.captures is not None else []
            request = gen.send(_FakeResult(stdout=out))
    except StopIteration as stop:
        resolved = stop.value

    assert dispatched == [
        # each creation dispatched alone with id capture (both split the seed %1):
        ("split-window", "-t", "%1", "-h", "-P", "-F", "#{pane_id}"),
        ("split-window", "-t", "%1", "-v", "-P", "-F", "#{pane_id}"),
        # downstream commands fold into one trailing  \;  chain, ids substituted:
        (
            "set-option",
            "-t",
            "%7",
            "-p",
            "@m",
            "L",
            ";",
            "set-option",
            "-t",
            "%8",
            "-p",
            "@m",
            "R",
        ),
    ]
    assert resolved.bindings == {0: "%7", 1: "%8"}


def _mark_of(session: Session, pane_id: str) -> list[str]:
    return session.server.cmd("display-message", "-p", "-t", pane_id, "#{@m}").stdout


def test_multidispatch_two_handles_sync(session: Session) -> None:
    """Live: two independent forward panes, each captured + decorated correctly."""
    window = session.new_window(window_name="resolve_sync")
    seed = window.active_pane
    assert seed is not None
    assert seed.pane_id is not None

    plan = ForwardPlan(PaneTarget(seed.pane_id))
    left, right = plan.split(horizontal=True), plan.split()
    left.do(_mark("LEFT"))
    right.do(_mark("RIGHT"))

    resolved = plan.run_resolving(SessionPlanExecutor(session))

    assert set(resolved.bindings) == {0, 1}
    assert resolved.bindings[0] != resolved.bindings[1]
    window.refresh()
    assert len(window.panes) == 3  # seed + two independent panes
    assert _mark_of(session, resolved.bindings[0]) == ["LEFT"]
    assert _mark_of(session, resolved.bindings[1]) == ["RIGHT"]


@pytest.mark.asyncio
async def test_multidispatch_two_handles_async(session: Session) -> None:
    """Live async: the same resolution core, driven with await."""
    window = session.new_window(window_name="resolve_async")
    seed = window.active_pane
    assert seed is not None
    assert seed.pane_id is not None

    plan = ForwardPlan(PaneTarget(seed.pane_id))
    plan.split(horizontal=True).do(_mark("AL"))
    plan.split().do(_mark("AR"))

    resolved = await plan.run_resolving_async(AsyncSessionPlanExecutor(session))

    window.refresh()
    assert len(window.panes) == 3
    assert _mark_of(session, resolved.bindings[0]) == ["AL"]
    assert _mark_of(session, resolved.bindings[1]) == ["AR"]


def test_multidispatch_from_query_seed(session: Session) -> None:
    """Live: seed the plan from the first row of a query (resolved at run)."""
    window = session.new_window(window_name="resolve_seed")
    assert window.active_pane is not None

    plan = ForwardPlan.from_query(panes().filter(active=True))
    plan.split(horizontal=True).do(_mark("A"))
    plan.split().do(_mark("B"))

    resolved = plan.run_resolving(SessionPlanExecutor(session))

    assert _mark_of(session, resolved.bindings[0]) == ["A"]
    assert _mark_of(session, resolved.bindings[1]) == ["B"]


def test_handle_scope_guard() -> None:
    """A creation verb on the wrong tmux scope fails fast at build time (pure)."""
    plan = ForwardPlan()
    sess = plan.new_session(name="g")
    win = sess.new_window(name="w")
    pane = win.split()  # window -> split is allowed

    with pytest.raises(TypeError):
        sess.split()  # a session has no single pane to split
    with pytest.raises(TypeError):
        win.new_window()  # only a session creates windows
    with pytest.raises(TypeError):
        pane.new_window()  # ditto for a pane


def test_multidispatch_session_window_pane(session: Session) -> None:
    """Live: one plan builds a session, two independent windows, a split in each.

    Five creations resolve over five dispatches -- a session (``$N``), two
    windows captured via ``new-window -t $N:`` (``@M``), and a split inside each
    window (``%K``) -- proving the builder spans all three tmux scopes.
    """
    server = session.server
    name = "cc_md_swp"
    try:
        plan = ForwardPlan()
        sess = plan.new_session(name=name)
        w_left = sess.new_window(name="left")
        w_right = sess.new_window(name="right")
        w_left.split(horizontal=True).do(_mark("WL"))
        w_right.split().do(_mark("WR"))

        resolved = plan.run_resolving(SessionPlanExecutor(session))

        assert set(resolved.bindings) == {0, 1, 2, 3, 4}
        assert resolved.bindings[0].startswith("$")  # session
        assert resolved.bindings[1].startswith("@")  # left window
        assert resolved.bindings[2].startswith("@")  # right window
        assert resolved.bindings[3].startswith("%")  # pane split into left
        assert resolved.bindings[4].startswith("%")  # pane split into right

        created = next(s for s in server.sessions if s.session_name == name)
        wins = {w.window_name: w for w in created.windows}
        assert {"left", "right"} <= set(wins)
        wins["left"].refresh()
        wins["right"].refresh()
        assert len(wins["left"].panes) == 2  # each window's pane was split
        assert len(wins["right"].panes) == 2
        assert _mark_of(session, resolved.bindings[3]) == ["WL"]
        assert _mark_of(session, resolved.bindings[4]) == ["WR"]
    finally:
        for s in list(server.sessions):
            if s.session_name == name:
                s.kill()


@pytest.mark.asyncio
async def test_multidispatch_session_window_async(session: Session) -> None:
    """Live async: the same session/window/pane span, driven with await."""
    server = session.server
    name = "cc_md_swp_async"
    try:
        plan = ForwardPlan()
        sess = plan.new_session(name=name)
        w_a = sess.new_window(name="a")
        w_b = sess.new_window(name="b")
        w_a.split().do(_mark("A"))
        w_b.split().do(_mark("B"))

        resolved = await plan.run_resolving_async(AsyncSessionPlanExecutor(session))

        assert resolved.bindings[0].startswith("$")
        assert _mark_of(session, resolved.bindings[3]) == ["A"]
        assert _mark_of(session, resolved.bindings[4]) == ["B"]
    finally:
        for s in list(server.sessions):
            if s.session_name == name:
                s.kill()


def test_marked_eligible_classifies_plan_shapes() -> None:
    """The analyzer picks single-dispatch only for a lone pane creation."""
    one_pane = ForwardPlan(PaneTarget("%1"))
    one_pane.split().do(_mark("x"))
    assert _marked_eligible(tuple(one_pane._steps)) is not None

    two_panes = ForwardPlan(PaneTarget("%1"))
    two_panes.split()
    two_panes.split()
    assert _marked_eligible(tuple(two_panes._steps)) is None  # one mark slot only

    one_session = ForwardPlan()
    one_session.new_session(name="x")
    # a detached session has no active pane to mark:
    assert _marked_eligible(tuple(one_session._steps)) is None


def test_marked_single_dispatch_folds_one_handle() -> None:
    """A lone pane handle resolves in ONE ``{marked}`` invocation (pure, no tmux).

    The split captures its id, marks the new (active) pane, the decorate
    addresses it via ``{marked}``, and the mark is cleared -- all one dispatch.
    """
    plan = ForwardPlan(PaneTarget("%1"))
    plan.split(horizontal=True).do(_mark("L"))

    gen = drive(tuple(plan._steps))
    dispatched: list[tuple[str, ...]] = []
    request = next(gen)
    try:
        while True:
            assert isinstance(request, Dispatch)
            dispatched.append(request.argv)
            out = ["%7"] if request.captures is not None else []
            request = gen.send(_FakeResult(stdout=out))
    except StopIteration as stop:
        resolved = stop.value

    assert dispatched == [
        (
            "split-window",
            "-t",
            "%1",
            "-h",
            "-P",
            "-F",
            "#{pane_id}",
            ";",
            "select-pane",
            "-m",
            ";",
            "set-option",
            "-t",
            "{marked}",
            "-p",
            "@m",
            "L",
            ";",
            "select-pane",
            "-M",
        ),
    ]
    assert len(dispatched) == 1  # one invocation, not create + decorate
    assert resolved.bindings == {0: "%7"}


def test_marked_single_dispatch_live(session: Session) -> None:
    """Live: a lone forward pane resolves in one dispatch and leaks no mark."""
    window = session.new_window(window_name="marked_solo")
    seed = window.active_pane
    assert seed is not None
    assert seed.pane_id is not None

    plan = ForwardPlan(PaneTarget(seed.pane_id))
    plan.split(horizontal=True).do(_mark("SOLO"))

    resolved = plan.run_resolving(SessionPlanExecutor(session))

    assert len(resolved.results) == 1  # single invocation, not create + decorate
    new_pane_id = resolved.bindings[0]
    window.refresh()
    assert len(window.panes) == 2
    assert _mark_of(session, new_pane_id) == ["SOLO"]
    # the server-wide mark register is cleared afterward, not leaked:
    marked = session.server.cmd(
        "display-message", "-p", "-t", new_pane_id, "#{pane_marked}"
    ).stdout
    assert marked == ["0"]
