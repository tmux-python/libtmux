"""The workspace build batches ready requests through the Core planner.

A declarative build drives Core's ``LazyPlan.execute`` with a
:class:`~libtmux.experimental.ops.planner.BoundedPlanner`, so a multi-pane window
uses fewer planner steps while host steps (sleeps, pane-ready waits) stay hard
batch boundaries. These tests pin the batching, per-operation result equivalence,
and boundary rules offline and live.
"""

from __future__ import annotations

import dataclasses
import typing as t

from libtmux.experimental.engines import ControlModeEngine, MockEngine, SubprocessEngine
from libtmux.experimental.engines.base import CommandResult
from libtmux.experimental.ops import (
    BatchingPlanner,
    LazyPlan,
    RenameWindow,
    SequentialPlanner,
    WindowId,
)
from libtmux.experimental.workspace import Command, Pane, Window, Workspace, analyze

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.experimental.engines.base import CommandRequest, TmuxEngine
    from libtmux.session import Session


@dataclasses.dataclass
class _RecordingEngine:
    """Record each planner-facing call; answer a wait_pane cursor as ready.

    A first-class engine arm (not a monkeypatch): it forwards to a real inner
    engine but reports a non-origin cursor for ``display-message`` so the
    runner's pane-readiness poll returns on the first try, keeping the tests
    fast.
    """

    inner: TmuxEngine = dataclasses.field(default_factory=MockEngine)
    calls: list[tuple[str, ...]] = dataclasses.field(default_factory=list)
    batches: list[tuple[tuple[str, ...], ...]] = dataclasses.field(
        default_factory=list,
    )

    def run(self, request: CommandRequest) -> CommandResult:
        """Record the argv and forward (faking a ready cursor for waits)."""
        self.calls.append(request.args)
        self.batches.append((request.args,))
        if "display-message" in request.args:
            return CommandResult(cmd=("tmux", *request.args), stdout=("1,1",))
        return self.inner.run(request)

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Execute each request in order."""
        requests = tuple(requests)
        self.calls.extend(request.args for request in requests)
        self.batches.append(tuple(request.args for request in requests))
        return self.inner.run_batch(requests)


def _spec(*, wait_pane: bool = False) -> Workspace:
    """Return a 2-window workspace; the editor window has three command panes."""
    return Workspace(
        name="batch",
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


def test_build_batches_by_default() -> None:
    """A build batches ready requests without a planner override."""
    default = _RecordingEngine()
    _spec().build(default, preflight=False)
    sequential = _RecordingEngine()
    _spec().build(sequential, preflight=False, planner=SequentialPlanner())

    assert len(default.batches) < len(sequential.batches)
    assert any(len(batch) > 1 for batch in default.batches)
    assert all(";" not in argv for batch in default.batches for argv in batch)


def test_build_planner_equivalence() -> None:
    """The default batched build yields the same result as sequential execution."""
    batched = _spec().build(MockEngine(), preflight=False)
    sequential = _spec().build(
        MockEngine(),
        preflight=False,
        planner=SequentialPlanner(),
    )

    assert [r.argv for r in batched.results] == [r.argv for r in sequential.results]
    assert batched.bindings == sequential.bindings


def test_build_wait_pane_keeps_create_separate_from_send() -> None:
    """wait_pane keeps the split separate from its dependent send request."""
    engine = _RecordingEngine()
    _spec(wait_pane=True).build(engine, preflight=False)

    crossed = [
        batch
        for batch in engine.batches
        if any("split-window" in argv for argv in batch)
        and any("send-keys" in argv for argv in batch)
    ]
    assert not crossed


def test_build_sleep_after_forces_boundary() -> None:
    """A sleep between two sends keeps them in separate planner steps."""
    ws = Workspace(
        name="s",
        windows=[
            Window("w", panes=[Pane(run=[Command("a", sleep_after=0.0), "b"])]),
        ],
    )
    engine = _RecordingEngine()
    ws.build(engine, preflight=False)

    batched_both = [
        batch
        for batch in engine.batches
        if sum("send-keys" in argv for argv in batch) == 2
    ]
    assert not batched_both


def test_build_batches_live_subprocess(session: Session) -> None:
    """A batched build creates the real structure without joining commands."""
    server = session.server
    engine = _RecordingEngine(SubprocessEngine.for_server(server))
    spec = Workspace(
        name="batch-live",
        start_directory="/tmp",
        windows=[
            Window(
                "editor",
                panes=[Pane(run="echo a"), Pane(run="echo b"), Pane(run="echo c")],
            ),
            Window("logs", panes=[Pane(run="echo log")]),
        ],
    )

    result = spec.build(engine, preflight=False)

    assert result.ok
    built = server.sessions.get(session_name="batch-live")
    assert built is not None
    assert [w.window_name for w in built.windows] == ["editor", "logs"]
    assert [len(w.panes) for w in built.windows] == [3, 1]
    # Ready operations share a batch without losing their result boundary.
    assert any(len(batch) > 1 for batch in engine.batches)
    assert all(";" not in argv for batch in engine.batches for argv in batch)
    assert len(engine.batches) < len(spec.compile().operations)


def test_build_int_window_option_batches(session: Session) -> None:
    """A non-str option value is normalized before request rendering.

    ``main-pane-height: 35`` must become a string before the operation renders.
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


def test_default_workspace_build_preserves_user_mark(session: Session) -> None:
    """Automatic batching never replaces or clears the server's marked pane."""
    server = session.server
    marked = session.active_window.active_pane
    assert marked is not None
    assert marked.pane_id is not None
    marked.select(mark=True)

    def marked_pane_ids() -> list[str]:
        rows = server.cmd(
            "list-panes",
            "-a",
            "-F",
            "#{pane_id} #{pane_marked}",
        ).stdout
        return [row.split()[0] for row in rows if row.endswith(" 1")]

    assert marked_pane_ids() == [marked.pane_id]

    spec = Workspace(
        name="mark-preserving-default",
        windows=[
            Window(
                "editor",
                panes=[Pane(run="echo one"), Pane(run="echo two")],
            ),
        ],
    )
    result = spec.build(SubprocessEngine.for_server(server), preflight=False)

    assert result.ok
    assert marked_pane_ids() == [marked.pane_id]


def test_failed_control_batch_preserves_user_mark(session: Session) -> None:
    """A failed request neither shifts attribution nor mutates the user's mark."""
    server = session.server
    window = session.active_window
    marked = window.active_pane
    assert window.window_id is not None
    assert marked is not None
    assert marked.pane_id is not None
    marked.select(mark=True)

    plan = LazyPlan()
    target = WindowId(window.window_id)
    plan.add(RenameWindow(target=target, name="first"))
    plan.add(RenameWindow(target=WindowId("@999999"), name="missing"))
    plan.add(RenameWindow(target=target, name="continued"))
    with ControlModeEngine.for_server(server) as engine:
        result = plan.execute(engine, planner=BatchingPlanner())

    rows = server.cmd(
        "list-panes",
        "-a",
        "-F",
        "#{pane_id} #{pane_marked}",
    ).stdout
    marked_ids = [row.split()[0] for row in rows if row.endswith(" 1")]
    window.refresh()
    assert [item.status for item in result.results] == [
        "complete",
        "failed",
        "complete",
    ]
    assert window.window_name == "continued"
    assert marked_ids == [marked.pane_id]
