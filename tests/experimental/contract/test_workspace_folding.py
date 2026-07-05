"""The workspace build folds dispatches through the Core planner.

A declarative build drives Core's ``LazyPlan.execute`` with a
:class:`~libtmux.experimental.ops.planner.BoundedPlanner`, so a multi-pane window
collapses to a few tmux calls instead of one per op -- while host steps (sleeps,
pane-ready waits) stay hard fold boundaries. These tests pin the dispatch-count
reduction, the planner-equivalence (same ``PlanResult``), and the boundary rules,
offline and live.
"""

from __future__ import annotations

import dataclasses
import typing as t

from libtmux.experimental.engines import MockEngine, SubprocessEngine
from libtmux.experimental.engines.base import CommandResult
from libtmux.experimental.ops import SequentialPlanner
from libtmux.experimental.workspace import Command, Pane, Window, Workspace, analyze

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.experimental.engines.base import CommandRequest, TmuxEngine
    from libtmux.session import Session


@dataclasses.dataclass
class _RecordingEngine:
    """Record every dispatch's argv; answer a wait_pane cursor as ready.

    A first-class engine arm (not a monkeypatch): it forwards to a real inner
    engine but reports a non-origin cursor for ``display-message`` so the
    runner's pane-readiness poll returns on the first try, keeping the tests
    fast.
    """

    inner: TmuxEngine = dataclasses.field(default_factory=MockEngine)
    calls: list[tuple[str, ...]] = dataclasses.field(default_factory=list)

    def run(self, request: CommandRequest) -> CommandResult:
        """Record the argv and forward (faking a ready cursor for waits)."""
        self.calls.append(request.args)
        if "display-message" in request.args:
            return CommandResult(cmd=("tmux", *request.args), stdout=("1,1",))
        return self.inner.run(request)

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Execute each request in order."""
        return [self.run(req) for req in requests]


def _spec(*, wait_pane: bool = False) -> Workspace:
    """Return a 2-window workspace; the editor window has three command panes."""
    return Workspace(
        name="fold",
        start_directory="/tmp",
        windows=[
            Window(
                "editor",
                panes=[
                    Pane(run="echo a"),
                    Pane(run=["echo b", "echo c"]),
                    Pane(run="echo d"),
                ],
            ),
            Window("logs", panes=[Pane(run="echo log")]),
        ],
        wait_pane=wait_pane,
    )


def test_build_folds_by_default() -> None:
    """A build folds dispatches without the caller choosing a planner."""
    default = _RecordingEngine()
    _spec().build(default, preflight=False)
    sequential = _RecordingEngine()
    _spec().build(sequential, preflight=False, planner=SequentialPlanner())

    assert len(default.calls) < len(sequential.calls)
    assert any(";" in argv for argv in default.calls)  # at least one folded chain


def test_build_planner_equivalence() -> None:
    """The default (folding) build yields the same PlanResult as the sequential one."""
    folded = _spec().build(MockEngine(), preflight=False)
    sequential = _spec().build(
        MockEngine(),
        preflight=False,
        planner=SequentialPlanner(),
    )

    assert [r.argv for r in folded.results] == [r.argv for r in sequential.results]
    assert folded.bindings == sequential.bindings


def test_build_wait_pane_never_folds_create_into_send() -> None:
    """wait_pane keeps the split a fold boundary: no dispatch carries split+send."""
    engine = _RecordingEngine()
    _spec(wait_pane=True).build(engine, preflight=False)

    crossed = [
        argv for argv in engine.calls if "split-window" in argv and "send-keys" in argv
    ]
    assert not crossed


def test_build_sleep_after_forces_boundary() -> None:
    """A sleep between two sends keeps them in separate dispatches."""
    ws = Workspace(
        name="s",
        windows=[
            Window("w", panes=[Pane(run=[Command("a", sleep_after=0.0), "b"])]),
        ],
    )
    engine = _RecordingEngine()
    ws.build(engine, preflight=False)

    folded_both = [argv for argv in engine.calls if argv.count("send-keys") == 2]
    assert not folded_both


def test_build_folds_live_subprocess(session: Session) -> None:
    """A folded build creates the real structure with at least one ; chain."""
    server = session.server
    engine = _RecordingEngine(SubprocessEngine.for_server(server))
    spec = Workspace(
        name="fold-live",
        start_directory="/tmp",
        windows=[
            Window(
                "editor",
                panes=[Pane(run="echo a"), Pane(run="echo b"), Pane(run="echo c")],
            ),
            Window("logs", panes=[Pane(run="echo log")]),
        ],
    )

    result = spec.build(engine)

    assert result.ok
    built = server.sessions.get(session_name="fold-live")
    assert built is not None
    assert [w.window_name for w in built.windows] == ["editor", "logs"]
    assert [len(w.panes) for w in built.windows] == [3, 1]
    # the build folded: at least one ; chain, fewer dispatches than operations
    assert any(";" in argv for argv in engine.calls)
    assert len(engine.calls) < len(spec.compile().operations)


def test_build_int_window_option_folds(session: Session) -> None:
    """A non-str option value (YAML int) folds and builds without a render crash.

    Regression: ``main-pane-height: 35`` reached the ``;``-chain renderer as an
    int, which raised ``AttributeError`` in ``_escape_arg``; analyze now
    stringifies option values so the fold sees only strings.
    """
    server = session.server
    engine = _RecordingEngine(SubprocessEngine.for_server(server))
    spec = analyze(
        {
            "session_name": "int-opt",
            "start_directory": "/tmp",
            "windows": [
                {
                    "window_name": "main",
                    "layout": "main-horizontal",
                    "options": {"main-pane-height": 35},
                    "panes": ["echo a", "echo b", "echo c"],
                },
            ],
        },
    )

    result = spec.build(engine)

    assert result.ok
    built = server.sessions.get(session_name="int-opt")
    assert built is not None
    assert len(built.windows[0].panes) == 3
