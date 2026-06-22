"""Declarative WorkspaceBuilder over the typed-ops Core, on real tmux.

Replicates a tmuxp-style workspace build through the Declarative tier
(:mod:`libtmux.experimental.workspace`): a YAML/dict is analyzed into a structural
``Workspace`` spec, compiled to a Core ``LazyPlan``, and executed. Two tracks:

* **offline** -- compile against the in-memory ``ConcreteEngine`` and assert the
  op sequence and planner-equivalence (no tmux);
* **live** -- build over the async control-mode engine *and* the sync subprocess
  engine against a real tmux server, then confirm the live structure matches the
  spec. The same spec drives every engine and both sync and async.
"""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.experimental.engines import (
    AsyncControlModeEngine,
    ConcreteEngine,
    SubprocessEngine,
)
from libtmux.experimental.ops import (
    FoldingPlanner,
    LazyPlan,
    MarkedPlanner,
    SequentialPlanner,
)
from libtmux.experimental.workspace import (
    Workspace,
    WorkspaceCompileError,
    analyze,
    confirm,
)
from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    from pathlib import Path

    from libtmux.experimental.ops.plan import PlanResult
    from libtmux.session import Session

_YAML = """
session_name: ws-offline
start_directory: /tmp
windows:
  - window_name: editor
    layout: main-vertical
    panes:
      - echo top
      - shell_command:
          - echo bottom-1
          - echo bottom-2
        focus: true
  - window_name: logs
    focus: true
    panes:
      - echo logging
"""


def _spec(start_directory: str, name: str = "ws-live") -> Workspace:
    """Return a two-window workspace spec rooted at *start_directory*."""
    return analyze(
        {
            "session_name": name,
            "start_directory": start_directory,
            "on_exists": "replace",
            "windows": [
                {
                    "window_name": "editor",
                    "layout": "main-vertical",
                    "panes": [
                        # First pane focused in a multi-pane window -- the case the
                        # spike broke; first-pane-id capture makes it work.
                        {"shell_command": ["echo top"], "focus": True},
                        "echo bottom",
                    ],
                },
                {"window_name": "logs", "focus": True, "panes": ["echo logging"]},
            ],
        },
    )


def test_workspace_analyze_normalizes_shorthand() -> None:
    """The analyzer expands tmuxp shorthand into the canonical spec tree."""
    ws = analyze(_YAML)
    assert ws.name == "ws-offline"
    assert [w.name for w in ws.windows] == ["editor", "logs"]
    assert ws.windows[0].panes[0].commands == ("echo top",)
    assert ws.windows[0].panes[1].commands == ("echo bottom-1", "echo bottom-2")
    assert ws.windows[0].panes[1].focus is True


def test_workspace_compiles_to_core_ops() -> None:
    """Compiling the declared workspace emits Core ops in tmuxp-faithful order."""
    kinds = [op.kind for op in analyze(_YAML).compile().operations]
    assert kinds[0] == "new_session"
    assert kinds.count("new_window") == 1  # window 1 is reused, window 2 created
    assert "split_window" in kinds
    assert "select_layout" in kinds
    assert kinds[-1] == "select_window"  # window focus is emitted last


def test_workspace_offline_build_and_planner_equivalence() -> None:
    """The compiled plan runs offline and the optimizer preserves the result."""
    plan = analyze(_YAML).compile()
    sequential = plan.execute(ConcreteEngine(), planner=SequentialPlanner())
    folded = plan.execute(ConcreteEngine(), planner=FoldingPlanner())
    assert sequential.ok
    assert folded.ok
    assert [r.status for r in sequential.results] == [r.status for r in folded.results]


def test_first_pane_focus_multipane_compiles() -> None:
    """Focusing the first pane of a multi-pane window now compiles (captured id)."""
    ws = analyze(
        {
            "session_name": "ws-focus",
            "windows": [
                {
                    "window_name": "w",
                    "panes": [{"shell_command": ["echo a"], "focus": True}, "echo b"],
                },
            ],
        },
    )
    plan = ws.compile()
    assert "select_pane" in [op.kind for op in plan.operations]
    # offline execution resolves the first-pane sub-ref without error
    assert plan.execute(ConcreteEngine()).ok


def test_empty_workspace_is_rejected() -> None:
    """A workspace with no windows fails closed at compile."""
    with pytest.raises(WorkspaceCompileError):
        Workspace(name="empty").compile()


def test_workspace_builder_async_control_live(
    session: Session,
    tmp_path: Path,
) -> None:
    """Build a workspace over the async control engine; confirm live structure."""
    server = session.server
    spec = _spec(str(tmp_path), name="ws-async")

    async def main() -> PlanResult:
        async with AsyncControlModeEngine.for_server(server) as engine:
            return await spec.abuild(engine)

    result = asyncio.run(main())
    assert result.ok
    report = confirm(spec, server)
    assert report.ok, report.problems


def test_workspace_builder_subprocess_live(
    session: Session,
    tmp_path: Path,
) -> None:
    """The same spec builds synchronously over the subprocess engine (neutrality)."""
    server = session.server
    spec = _spec(str(tmp_path), name="ws-sync")

    result = spec.build(SubprocessEngine.for_server(server))
    assert result.ok
    report = confirm(spec, server)
    assert report.ok, report.problems


# --- Robust QA: a rich workspace exercising the full feature surface ---


def _rich_spec(start_directory: str, name: str = "ws-rich") -> Workspace:
    """Return a three-window workspace: layouts, options, env, focus, multi-pane."""
    return analyze(
        {
            "session_name": name,
            "start_directory": start_directory,
            "on_exists": "replace",
            "environment": {"WS_BUILDER": "1"},
            "options": {"history-limit": "5000"},
            "windows": [
                {
                    "window_name": "editor",
                    "layout": "main-vertical",
                    "options": {"main-pane-height": "12"},
                    "panes": [
                        {"shell_command": ["echo EDITORZERO"], "focus": True},
                        "echo editor-one",
                    ],
                },
                {"window_name": "logs", "panes": ["echo logs-zero"]},
                {
                    "window_name": "shell",
                    "focus": True,
                    "panes": [
                        "echo shell-zero",
                        {"shell_command": ["echo SHELLONE"], "focus": True},
                        "echo shell-two",
                    ],
                },
            ],
        },
    )


def test_workspace_plan_serializes_round_trip(tmp_path: Path) -> None:
    """The compiled plan (incl. SlotRef sub-refs) round-trips through to_list."""
    plan = _rich_spec(str(tmp_path)).compile()
    data = plan.to_list()
    restored = LazyPlan.from_list(data)
    assert restored.to_list() == data
    assert [o.kind for o in restored.operations] == [o.kind for o in plan.operations]


def test_workspace_all_planners_agree(tmp_path: Path) -> None:
    """Sequential, Folding, and Marked planners give an identical PlanResult."""
    plan = _rich_spec(str(tmp_path)).compile()
    runs = {
        name: plan.execute(ConcreteEngine(), planner=planner())
        for name, planner in (
            ("sequential", SequentialPlanner),
            ("folding", FoldingPlanner),
            ("marked", MarkedPlanner),
        )
    }
    statuses = {name: [r.status for r in run.results] for name, run in runs.items()}
    assert all(run.ok for run in runs.values())
    assert statuses["sequential"] == statuses["folding"] == statuses["marked"]


def test_workspace_builder_rich_subprocess(session: Session, tmp_path: Path) -> None:
    """A rich workspace builds correctly: structure, focus, options, env, cwd, cmds."""
    server = session.server
    spec = _rich_spec(str(tmp_path), name="ws-rich-sync")

    result = spec.build(SubprocessEngine.for_server(server))
    assert result.ok
    report = confirm(spec, server)
    assert report.ok, report.problems

    built = server.sessions.filter(session_name="ws-rich-sync")[0]
    windows = list(built.windows)

    # structure: names, order, per-window pane counts
    assert [w.window_name for w in windows] == ["editor", "logs", "shell"]
    assert [len(list(w.panes)) for w in windows] == [2, 1, 3]

    # window focus -> shell is the active window
    assert built.active_window.window_name == "shell"

    # pane focus: editor's first pane + shell's middle pane are active in-window
    editor, shell = windows[0], windows[2]
    assert editor.active_pane is not None
    assert editor.active_pane.pane_id == next(iter(editor.panes)).pane_id
    assert shell.active_pane is not None
    assert shell.active_pane.pane_id == list(shell.panes)[1].pane_id

    # session + window options applied
    assert str(built.show_option("history-limit")) == "5000"
    assert str(editor.show_option("main-pane-height")) == "12"

    # session environment set
    assert built.show_environment().get("WS_BUILDER") == "1"

    # start_directory honored on a split pane (cwd settles after the shell starts)
    want_cwd = str(tmp_path)
    split_pane_id = list(editor.panes)[1].pane_id

    def _cwd_ok() -> bool:
        pane = server.panes.get(pane_id=split_pane_id)
        return pane is not None and pane.pane_current_path == want_cwd

    assert retry_until(_cwd_ok, 5, raises=False)

    # a command actually ran in the right pane
    first_pane_id = next(iter(editor.panes)).pane_id

    def _cmd_ran() -> bool:
        pane = server.panes.get(pane_id=first_pane_id)
        return pane is not None and "EDITORZERO" in "\n".join(pane.capture_pane())

    assert retry_until(_cmd_ran, 5, raises=False)


def test_workspace_builder_rich_async(session: Session, tmp_path: Path) -> None:
    """The rich spec builds identically over the async control engine (neutrality)."""
    server = session.server
    spec = _rich_spec(str(tmp_path), name="ws-rich-async")

    async def main() -> PlanResult:
        async with AsyncControlModeEngine.for_server(server) as engine:
            return await spec.abuild(engine)

    result = asyncio.run(main())
    assert result.ok
    report = confirm(spec, server)
    assert report.ok, report.problems

    built = server.sessions.filter(session_name="ws-rich-async")[0]
    assert [w.window_name for w in built.windows] == ["editor", "logs", "shell"]
    assert built.active_window.window_name == "shell"
    assert str(built.show_option("history-limit")) == "5000"
