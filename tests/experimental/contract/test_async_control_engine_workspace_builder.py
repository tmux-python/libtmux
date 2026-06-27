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
    NewSession,
    NewWindow,
    SelectLayout,
    SendKeys,
    SequentialPlanner,
    SetEnvironment,
    SetOption,
    SetWindowOption,
    SplitWindow,
)
from libtmux.experimental.workspace import (
    Command,
    HostStep,
    Pane,
    Window,
    Workspace,
    WorkspaceCompileError,
    analyze,
    compile_full,
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
    assert [c.cmd for c in ws.windows[0].panes[0].commands] == ["echo top"]
    assert [c.cmd for c in ws.windows[0].panes[1].commands] == [
        "echo bottom-1",
        "echo bottom-2",
    ]
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


# --- Analyzer + IR normalization (offline, no tmux) ---


def test_pane_commands_normalizes_run_forms() -> None:
    """Pane.commands turns run (None / str / Command / sequence) into Commands."""
    assert Pane().commands == ()
    assert [c.cmd for c in Pane(run="vim").commands] == ["vim"]
    assert [c.cmd for c in Pane(run=["cd src", "pytest -q"]).commands] == [
        "cd src",
        "pytest -q",
    ]
    # bare strings default to enter=True; a Command carries its own overrides
    mixed = Pane(run=["plain", Command("typed", enter=False, sleep_after=0.2)]).commands
    assert (mixed[0].cmd, mixed[0].enter) == ("plain", True)
    assert (mixed[1].cmd, mixed[1].enter, mixed[1].sleep_after) == ("typed", False, 0.2)


def test_compile_per_command_enter_and_sleeps() -> None:
    """Command(enter=False) emits send-keys without Enter; per-cmd sleeps host-step."""
    ws = Workspace(
        name="ws-cmd",
        windows=[
            Window(
                "w",
                panes=[
                    Pane(
                        run=[
                            Command("git add -p", enter=False),
                            Command("echo done", sleep_before=0.3, sleep_after=0.4),
                        ],
                    ),
                ],
            ),
        ],
    )
    compiled = compile_full(ws)
    sends = [op for op in compiled.plan.operations if isinstance(op, SendKeys)]
    assert (sends[0].keys, sends[0].enter) == ("git add -p", False)
    assert (sends[1].keys, sends[1].enter) == ("echo done", True)
    send_at = [
        i for i, op in enumerate(compiled.plan.operations) if isinstance(op, SendKeys)
    ]
    assert HostStep("sleep", seconds=0.3) in compiled.host_after[send_at[1] - 1]
    assert HostStep("sleep", seconds=0.4) in compiled.host_after[send_at[1]]


def test_analyze_dimensions_list_and_mapping() -> None:
    """The analyzer coerces both ``[x, y]`` and ``{width, height}`` dimensions."""
    panes = {"windows": [{"panes": ["echo a"]}]}
    listed = analyze({"session_name": "s", "dimensions": [200, 50], **panes})
    mapped = analyze(
        {"session_name": "s", "dimensions": {"width": 100, "height": 40}, **panes},
    )
    unset = analyze({"session_name": "s", **panes})
    assert listed.dimensions == (200, 50)
    assert mapped.dimensions == (100, 40)
    assert unset.dimensions is None


def test_analyze_shell_command_shorthand_forms() -> None:
    """shell_command shorthand expands: bare string, list, and ``{cmd}`` items."""
    ws = analyze(
        {
            "session_name": "s",
            "windows": [
                {
                    "panes": [
                        {"shell_command": "echo solo"},
                        {"shell_command": ["echo a", {"cmd": "echo b"}]},
                        None,
                    ],
                },
            ],
        },
    )
    panes = ws.windows[0].panes
    assert [c.cmd for c in panes[0].commands] == ["echo solo"]
    assert [c.cmd for c in panes[1].commands] == ["echo a", "echo b"]
    assert panes[2].commands == ()  # a None pane is an empty (implicit) pane


def test_analyze_passes_through_session_fields() -> None:
    """Session-level fields (env/options/before_script/on_exists) survive analysis."""
    ws = analyze(
        {
            "session_name": "s",
            "on_exists": "replace",
            "before_script": "echo setup",
            "environment": {"E": "1"},
            "options": {"history-limit": "5000"},
            "windows": [{"panes": ["echo a"]}],
        },
    )
    assert ws.on_exists == "replace"
    assert ws.before_script == "echo setup"
    assert dict(ws.environment) == {"E": "1"}
    assert dict(ws.options) == {"history-limit": "5000"}


def test_analyze_normalizes_pane_orchestration_fields() -> None:
    """Per-pane orchestration (sleeps, start_directory, focus) lands on the Pane."""
    ws = analyze(
        {
            "session_name": "s",
            "windows": [
                {
                    "panes": [
                        {
                            "shell_command": ["echo x"],
                            "sleep_before": 0.1,
                            "sleep_after": 0.2,
                            "start_directory": "/tmp",
                            "focus": True,
                        },
                    ],
                },
            ],
        },
    )
    pane = ws.windows[0].panes[0]
    assert (pane.sleep_before, pane.sleep_after) == (0.1, 0.2)
    assert pane.start_directory == "/tmp"
    assert pane.focus is True


def test_analyze_rejects_non_mapping_yaml() -> None:
    """A YAML scalar (not a mapping) is rejected rather than silently mis-parsed."""
    with pytest.raises(TypeError):
        analyze("just-a-scalar")


def test_analyze_rejects_unsupported_pane() -> None:
    """A pane that is neither None, a string, nor a mapping fails closed."""
    with pytest.raises(TypeError):
        analyze({"session_name": "s", "windows": [{"panes": [123]}]})


# --- Compiler: op emission + host-step schedule (offline, no tmux) ---


def test_compile_threads_dimensions_into_new_session() -> None:
    """Workspace dimensions become the new-session ``-x``/``-y`` width/height."""
    ws = Workspace(
        name="ws-dim",
        dimensions=(120, 40),
        windows=[Window("w", panes=[Pane(run="echo a")])],
    )
    new_session = compile_full(ws).plan.operations[0]
    assert isinstance(new_session, NewSession)  # first op, narrowed for its fields
    assert (new_session.width, new_session.height) == (120, 40)


def test_compile_emits_environment_and_options() -> None:
    """Session env/options and window options compile to their write ops, valued."""
    ws = Workspace(
        name="ws-opts",
        environment={"WS_E": "1"},
        options={"history-limit": "9000"},
        windows=[
            Window("w", options={"main-pane-height": "10"}, panes=[Pane(run="echo a")]),
        ],
    )
    ops = compile_full(ws).plan.operations
    set_env = next(op for op in ops if isinstance(op, SetEnvironment))
    set_opt = next(op for op in ops if isinstance(op, SetOption))
    set_wopt = next(op for op in ops if isinstance(op, SetWindowOption))
    assert (set_env.name, set_env.value) == ("WS_E", "1")
    assert (set_opt.option, set_opt.value) == ("history-limit", "9000")
    assert (set_wopt.option, set_wopt.value) == ("main-pane-height", "10")


def test_compile_emits_global_options() -> None:
    """Workspace.global_options compile to ``set-option -g`` (no target)."""
    ws = Workspace(
        name="ws-global",
        global_options={"status-position": "top"},
        windows=[Window("w", panes=[Pane(run="echo a")])],
    )
    ops = compile_full(ws).plan.operations
    global_opt = next(op for op in ops if isinstance(op, SetOption) and op.global_)
    assert (global_opt.option, global_opt.value) == ("status-position", "top")
    assert global_opt.target is None  # -g options carry no target


def test_compile_folds_first_pane_env_into_creator() -> None:
    """Window/first-pane env rides the creator's ``-e`` (no extra dispatch).

    Window 0 reuses the session's implicit pane, so its env -- and its first
    pane's -- folds into ``new-session -e``; window 2..N fold into ``new-window
    -e``. A *split* pane carries its own ``-e``.
    """
    ws = Workspace(
        name="ws-env",
        windows=[
            Window(
                "editor",
                environment={"WIN_ENV": "w"},
                panes=[
                    Pane(run="vim", environment={"PANE_ENV": "p"}),
                    Pane(run="htop", environment={"SPLIT_ENV": "s"}),
                ],
            ),
            Window("logs", environment={"W2": "x"}, panes=[Pane(run="tail")]),
        ],
    )
    ops = compile_full(ws).plan.operations
    new_session = next(op for op in ops if isinstance(op, NewSession))
    new_window = next(op for op in ops if isinstance(op, NewWindow))
    split = next(op for op in ops if isinstance(op, SplitWindow))
    # window 0 + its first pane fold into new-session -e
    assert new_session.environment == {"WIN_ENV": "w", "PANE_ENV": "p"}
    # window 1 folds into new-window -e
    assert new_window.environment == {"W2": "x"}
    # a split pane carries its own env (falling back to the window's)
    assert split.environment == {"SPLIT_ENV": "s"}


def test_compile_threads_window_and_pane_shell() -> None:
    """window_shell rides new-window; pane.shell (then window_shell) rides split."""
    ws = Workspace(
        name="ws-shell",
        windows=[
            Window("a", panes=[Pane(run="x")]),
            Window(
                "b",
                window_shell="fish",
                panes=[Pane(run="x"), Pane(run="y", shell="zsh")],
            ),
        ],
    )
    ops = compile_full(ws).plan.operations
    new_window = next(op for op in ops if isinstance(op, NewWindow))
    split = next(op for op in ops if isinstance(op, SplitWindow))
    assert new_window.window_shell == "fish"
    assert split.shell == "zsh"  # pane.shell wins over window_shell


def test_compile_emits_options_after_following_layout() -> None:
    """options_after compile to set-window-option *after* the layout op."""
    ws = Workspace(
        name="ws-after",
        windows=[
            Window(
                "w",
                layout="main-vertical",
                options_after={"main-pane-width": "120"},
                panes=[Pane(run="a"), Pane(run="b")],
            ),
        ],
    )
    ops = compile_full(ws).plan.operations
    layout_at = next(i for i, op in enumerate(ops) if isinstance(op, SelectLayout))
    after_at = next(
        i
        for i, op in enumerate(ops)
        if isinstance(op, SetWindowOption) and op.option == "main-pane-width"
    )
    assert after_at > layout_at  # options_after runs once the layout exists


def test_compile_schedules_host_steps_off_the_op_spine() -> None:
    """before_script and pane sleeps become host steps, not recorded operations."""
    ws = Workspace(
        name="ws-hosts",
        start_directory="/tmp",
        before_script="echo hi",
        windows=[
            Window(
                "w",
                panes=[
                    Pane(run="echo a", sleep_before=0.5),
                    Pane(run="echo b", sleep_after=0.7),
                ],
            ),
        ],
    )
    compiled = compile_full(ws)
    operations = compiled.plan.operations

    # no orchestration leaks into the pure op spine
    assert {"sleep", "script"}.isdisjoint(op.kind for op in operations)

    # before_script runs before any op, carrying the session cwd
    assert compiled.pre == (HostStep("script", command="echo hi", cwd="/tmp"),)

    # sleep_before is anchored just before its pane's first send-keys;
    # sleep_after just after the last send-keys -- asserted by position, not index
    sends = [i for i, op in enumerate(operations) if op.kind == "send_keys"]
    assert HostStep("sleep", seconds=0.5) in compiled.host_after[min(sends) - 1]
    assert HostStep("sleep", seconds=0.7) in compiled.host_after[max(sends)]


def test_compile_reuses_first_window_creating_only_the_rest() -> None:
    """Window 0 reuses the session's implicit window; only 2..N create windows."""
    unnamed = compile_full(Workspace(name="s", windows=[Window(panes=[Pane(run="x")])]))
    unnamed_kinds = [op.kind for op in unnamed.plan.operations]
    assert "new_window" not in unnamed_kinds
    assert "rename_window" not in unnamed_kinds  # nothing to rename when unnamed

    named = compile_full(Workspace(name="s", windows=[Window("w", panes=[Pane("x")])]))
    named_kinds = [op.kind for op in named.plan.operations]
    assert "new_window" not in named_kinds
    assert named_kinds.count("rename_window") == 1  # first window renamed in place

    two = compile_full(
        Workspace(
            name="s",
            windows=[Window("a", panes=[Pane("x")]), Window("b", panes=[Pane("y")])],
        ),
    )
    assert [op.kind for op in two.plan.operations].count("new_window") == 1


def test_compile_workspace_method_matches_compile_full_plan() -> None:
    """``Workspace.compile()`` returns exactly ``compile_full().plan`` (same ops)."""
    ws = Workspace(name="s", windows=[Window("w", panes=[Pane("echo a"), Pane("b")])])
    via_method = [op.kind for op in ws.compile().operations]
    via_full = [op.kind for op in compile_full(ws).plan.operations]
    assert via_method == via_full


# --- Runner preflight + confirm negative path (live tmux) ---


def test_workspace_before_script_runs_as_host_step(
    session: Session,
    tmp_path: Path,
) -> None:
    """before_script executes on the host, in start_directory, before the build."""
    server = session.server
    sentinel = tmp_path / "before_script.ran"
    spec = analyze(
        {
            "session_name": "ws-before",
            "start_directory": str(tmp_path),
            "on_exists": "replace",
            # relative path -> proves the step runs with cwd == start_directory
            "before_script": f"echo ok > {sentinel.name}",
            "windows": [{"window_name": "w", "panes": ["echo a"]}],
        },
    )

    result = spec.build(SubprocessEngine.for_server(server))
    assert result.ok
    assert sentinel.exists()
    assert sentinel.read_text().strip() == "ok"


def test_workspace_on_exists_reuse_skips_existing(
    session: Session,
    tmp_path: Path,
) -> None:
    """on_exists='reuse' leaves an existing session untouched and skips the build."""
    server = session.server
    engine = SubprocessEngine.for_server(server)
    spec = analyze(
        {
            "session_name": "ws-reuse",
            "start_directory": str(tmp_path),
            "on_exists": "reuse",
            "windows": [{"window_name": "only", "panes": ["echo a"]}],
        },
    )

    assert spec.build(engine).ok
    before = [
        w.window_id for w in server.sessions.filter(session_name="ws-reuse")[0].windows
    ]

    # the second build sees the session and short-circuits: empty but ok
    second = spec.build(engine)
    assert second.ok
    assert second.results == ()
    after = [
        w.window_id for w in server.sessions.filter(session_name="ws-reuse")[0].windows
    ]
    assert before == after  # untouched -- same windows, not rebuilt


def test_workspace_on_exists_error_raises(
    session: Session,
    tmp_path: Path,
) -> None:
    """on_exists='error' refuses to clobber an existing session of the same name."""
    server = session.server
    engine = SubprocessEngine.for_server(server)
    spec = analyze(
        {
            "session_name": "ws-error",
            "start_directory": str(tmp_path),
            "on_exists": "error",
            "windows": [{"window_name": "w", "panes": ["echo a"]}],
        },
    )

    assert spec.build(engine).ok
    with pytest.raises(FileExistsError):
        spec.build(engine)


def test_workspace_confirm_detects_structural_mismatch(
    session: Session,
    tmp_path: Path,
) -> None:
    """Confirm flags a problem when the live session diverges from the spec."""
    server = session.server
    built = analyze(
        {
            "session_name": "ws-confirm",
            "start_directory": str(tmp_path),
            "on_exists": "replace",
            "windows": [{"window_name": "only", "panes": ["echo a"]}],
        },
    )
    assert built.build(SubprocessEngine.for_server(server)).ok
    assert confirm(built, server).ok  # matches what was actually built

    # a spec declaring more windows than were built must be flagged
    divergent = analyze(
        {
            "session_name": "ws-confirm",
            "windows": [
                {"window_name": "only", "panes": ["echo a"]},
                {"window_name": "extra", "panes": ["echo b"]},
            ],
        },
    )
    report = confirm(divergent, server)
    assert not report.ok
    assert any("window count" in problem for problem in report.problems)
