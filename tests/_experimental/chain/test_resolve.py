"""Multi-dispatch resolution: independent forward handles, sync + async."""

from __future__ import annotations

import pathlib
import typing as t
from dataclasses import dataclass, field

import pytest

from libtmux._experimental.chain import (
    AsyncSessionPlanExecutor,
    ForwardPlan,
    ServerPlanRunner,
    SessionPlanExecutor,
    panes,
)
from libtmux._experimental.chain._resolve import (
    Dispatch,
    ForwardDispatchError,
    _marked_eligible,
    drive,
)
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


def test_creation_options_render() -> None:
    """split/new_session/new_window render -c/-e/size onto the create argv."""
    plan = ForwardPlan(PaneTarget("%1"))
    plan.split(start_directory="/tmp", environment={"FOO": "bar"})
    assert plan._steps[0].call.args == ("-v", "-c/tmp", "-eFOO=bar")

    plan2 = ForwardPlan()
    sess = plan2.new_session(
        name="x", start_directory="/tmp", environment={"A": "1"}, width=200, height=50
    )
    sess.new_window(
        name="w", start_directory="/srv", environment={"B": "2"}, window_shell="zsh"
    )
    assert plan2._steps[0].call.args == (
        "-d",
        "-s",
        "x",
        "-c/tmp",
        "-eA=1",
        "-x",
        "200",
        "-y",
        "50",
    )
    assert plan2._steps[1].call.args == ("-n", "w", "-c/srv", "-eB=2", "zsh")


def test_creation_start_directory_live(
    session: Session, tmp_path: pathlib.Path
) -> None:
    """Live: a forward split honours start_directory."""
    window = session.new_window(window_name="cc_cwd")
    seed = window.active_pane
    assert seed is not None
    assert seed.pane_id is not None

    plan = ForwardPlan(PaneTarget(seed.pane_id))
    plan.split(start_directory=str(tmp_path))
    resolved = plan.run_resolving(SessionPlanExecutor(session))

    cwd = session.server.cmd(
        "display-message", "-p", "-t", resolved.bindings[0], "#{pane_current_path}"
    ).stdout
    assert cwd
    assert pathlib.Path(cwd[0]).resolve() == tmp_path.resolve()


def test_typed_verbs_in_forward_plan(session: Session) -> None:
    """Live: the new typed bound-namespace verbs work as decorates in a plan."""
    window = session.new_window(window_name="cc_verbs")
    seed = window.active_pane
    assert seed is not None
    assert seed.pane_id is not None

    plan = ForwardPlan(PaneTarget(seed.pane_id))
    plan.split().do(lambda h: h.cmd.set_option("@cc_v", "ok"))
    resolved = plan.run_resolving(SessionPlanExecutor(session))

    val = session.server.cmd(
        "display-message", "-p", "-t", resolved.bindings[0], "#{@cc_v}"
    ).stdout
    assert val == ["ok"]


def test_server_plan_runner_creates_session_from_scratch(session: Session) -> None:
    """ServerPlanRunner runs a create-from-scratch plan without a seed session."""
    server = session.server
    name = "cc_server_runner"
    try:
        plan = ForwardPlan()
        sess = plan.new_session(name=name)  # slot 0
        sess.new_window(name="w").split().do(_mark("SR"))  # slots 1, 2
        resolved = plan.run_resolving(ServerPlanRunner(server))

        assert resolved.session(0, server).session_name == name
        assert _mark_of(session, resolved.bindings[2]) == ["SR"]
    finally:
        for s in list(server.sessions):
            if s.session_name == name:
                s.kill()


def test_resolved_maps_slots_to_live_objects(session: Session) -> None:
    """Resolved.pane/window/session(slot, server) return the created libtmux objects."""
    server = session.server
    name = "cc_resolved_objs"
    try:
        plan = ForwardPlan()
        sess = plan.new_session(name=name)  # slot 0 (session)
        win = sess.new_window(name="w")  # slot 1 (window)
        win.split()  # slot 2 (pane)
        resolved = plan.run_resolving(SessionPlanExecutor(session))

        assert resolved.session(0, server).session_id == resolved.bindings[0]
        assert resolved.window(1, server).window_id == resolved.bindings[1]
        assert resolved.pane(2, server).pane_id == resolved.bindings[2]
    finally:
        for s in list(server.sessions):
            if s.session_name == name:
                s.kill()


def test_seed_from_existing_scopes_render() -> None:
    """from_session/from_window/from_pane build creates targeting the seed id."""
    splan = ForwardPlan.from_session("$0")
    splan.new_window(name="w")
    assert splan._steps[0].call.argv() == ("new-window", "-t", "$0:", "-n", "w")

    wplan = ForwardPlan.from_window("@1")
    wplan.split(horizontal=True)
    assert wplan._steps[0].call.argv() == ("split-window", "-t", "@1", "-h")

    pplan = ForwardPlan.from_pane("%5")
    pplan.split()
    assert pplan._steps[0].call.argv() == ("split-window", "-t", "%5", "-v")


def test_seed_handle_decorates_existing_object() -> None:
    """plan.seed exposes the pre-existing seed as a decoratable handle."""
    plan = ForwardPlan.from_pane("%1")
    assert plan.seed.cmd.send_keys("clear", enter=True).argv() == (
        "send-keys",
        "-t",
        "%1",
        "clear",
        "Enter",
    )
    # a query-seeded plan has no concrete seed to hand back:
    qplan = ForwardPlan.from_query(panes().filter(active=True))
    with pytest.raises(ValueError, match="no concrete seed"):
        _ = qplan.seed


def test_seed_from_live_session_adds_window(session: Session) -> None:
    """Live: from_session(live) adds a window + split to the existing session."""
    n_before = len(session.windows)

    plan = ForwardPlan.from_session(session)
    plan.new_window(name="cc_seeded").split().do(_mark("SEED"))
    resolved = plan.run_resolving(SessionPlanExecutor(session))

    session.refresh()
    assert len(session.windows) == n_before + 1
    new_win = next(w for w in session.windows if w.window_name == "cc_seeded")
    new_win.refresh()
    assert len(new_win.panes) == 2  # the window's pane was split
    assert _mark_of(session, resolved.bindings[1]) == ["SEED"]  # slot 1 = split pane


def test_forward_dispatch_error_on_failed_create() -> None:
    """A failed creation dispatch raises ForwardDispatchError, not IndexError."""
    plan = ForwardPlan(PaneTarget("%1"))
    plan.split()

    gen = drive(tuple(plan._steps))
    next(gen)  # the split's capturing dispatch
    with pytest.raises(ForwardDispatchError) as excinfo:
        gen.send(_FakeResult(stdout=[], stderr=["no space for new pane"], returncode=1))

    assert "no space for new pane" in str(excinfo.value)
    assert excinfo.value.argv[0] == "split-window"


def test_forward_dispatch_error_live(session: Session) -> None:
    """Live: splitting against a bogus target fails loudly with the tmux error."""
    plan = ForwardPlan(PaneTarget("%nonexistent999"))
    plan.split()
    with pytest.raises(ForwardDispatchError):
        plan.run_resolving(SessionPlanExecutor(session))


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
