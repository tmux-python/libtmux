"""Workspace sets batch declarative builds without losing plan semantics."""

from __future__ import annotations

import asyncio
import dataclasses
import typing as t

from libtmux.experimental.engines import AsyncConcreteEngine, ConcreteEngine
from libtmux.experimental.engines.base import CommandResult
from libtmux.experimental.ops import SequentialPlanner
from libtmux.experimental.ops._types import SlotRef
from libtmux.experimental.workspace import (
    BuildEvent,
    Pane,
    Window,
    Workspace,
    WorkspaceBuilt,
    WorkspaceSet,
    build_workspaces,
    compile_workspaces,
)

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.experimental.engines.base import CommandRequest, TmuxEngine


@dataclasses.dataclass
class _RecordingEngine:
    """Record dispatches while forwarding to an inner engine."""

    inner: TmuxEngine = dataclasses.field(default_factory=ConcreteEngine)
    calls: list[tuple[str, ...]] = dataclasses.field(default_factory=list)

    def run(self, request: CommandRequest) -> CommandResult:
        """Record the argv and forward, faking a ready cursor for waits."""
        self.calls.append(request.args)
        if "display-message" in request.args:
            return CommandResult(cmd=("tmux", *request.args), stdout=("1,1",))
        return self.inner.run(request)

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Execute each request in order."""
        return [self.run(req) for req in requests]


def _workspace(name: str, *, wait_pane: bool = False) -> Workspace:
    """Return a two-pane workspace with a command after a split."""
    return Workspace(
        name=name,
        windows=[
            Window(
                "editor",
                panes=[
                    Pane(run="echo first"),
                    Pane(run=["echo second", "echo third"]),
                ],
            ),
        ],
        wait_pane=wait_pane,
    )


def test_workspace_set_from_variants_expands_base() -> None:
    """WorkspaceSet.from_variants delegates to expand and preserves ordering."""
    base = Workspace(name="dev-${app}", windows=[Window("w", panes=[Pane("${cmd}")])])
    workspace_set = WorkspaceSet.from_variants(
        base,
        [{"app": "api", "cmd": "pytest"}, {"app": "docs", "cmd": "sphinx-build"}],
    )

    assert [ws.name for ws in workspace_set.workspaces] == ["dev-api", "dev-docs"]
    assert [
        ws.windows[0].panes[0].commands[0].cmd for ws in workspace_set.workspaces
    ] == ["pytest", "sphinx-build"]


def test_compile_workspaces_rebases_slot_refs_and_host_steps() -> None:
    """Merged plans offset later workspaces' SlotRefs and host-step targets."""
    compiled = compile_workspaces(
        [
            _workspace("one"),
            _workspace("two", wait_pane=True),
        ],
    )
    first_len = len(_workspace("one").compile().operations)
    second_ops = compiled.plan.operations[first_len:]
    send_ops = [op for op in second_ops if op.kind == "send_keys"]
    assert send_ops
    deferred_targets = [op.target for op in send_ops if isinstance(op.target, SlotRef)]
    assert min(target.slot for target in deferred_targets) >= first_len

    wait_steps = [
        step
        for steps in compiled.host_after.values()
        for step in steps
        if step.kind == "wait_pane"
    ]
    assert wait_steps
    assert all(
        step.pane is not None and step.pane.slot >= first_len for step in wait_steps
    )


def test_build_workspaces_folds_across_workspace_boundaries() -> None:
    """Batch builds still use the folding planner over the merged operation stream."""
    default = _RecordingEngine()
    build_workspaces([_workspace("one"), _workspace("two")], default, preflight=False)
    sequential = _RecordingEngine()
    build_workspaces(
        [_workspace("one"), _workspace("two")],
        sequential,
        preflight=False,
        planner=SequentialPlanner(),
    )

    assert len(default.calls) < len(sequential.calls)
    assert any(";" in argv for argv in default.calls)


def test_workspace_set_all_reused_returns_noop_result() -> None:
    """Preflight reuse skips every existing workspace without executing the plan."""
    reused = Workspace(
        name="already",
        windows=[Window("w", panes=[Pane("echo nope")])],
        on_exists="reuse",
    )
    engine = ConcreteEngine()

    first = build_workspaces([reused], engine, preflight=False)
    second = build_workspaces([reused], engine)

    assert first.ok
    assert second.ok
    assert second.reused == ("already",)
    assert second.result.results == ()


def test_workspace_set_emits_built_event_per_workspace() -> None:
    """Each workspace emits its own WorkspaceBuilt event."""
    events: list[BuildEvent] = []
    outcome = build_workspaces(
        [_workspace("one"), _workspace("two")],
        ConcreteEngine(),
        preflight=False,
        on_event=events.append,
    )

    built = [event for event in events if isinstance(event, WorkspaceBuilt)]
    assert outcome.ok
    assert len(built) == 2


def test_workspace_set_async_build_matches_sync_shape() -> None:
    """The async runner exposes the same result shape as the sync runner."""
    workspace_set = WorkspaceSet((_workspace("one"), _workspace("two")))
    outcome = asyncio.run(
        workspace_set.abuild(AsyncConcreteEngine(), preflight=False),
    )

    assert outcome.ok
    assert outcome.sessions == ("one", "two")
    assert len(outcome.result.results) == len(
        compile_workspaces(workspace_set.workspaces).plan.operations,
    )
