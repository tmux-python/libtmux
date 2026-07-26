"""Executable contracts for the async control-plan tutorial."""

from __future__ import annotations

import asyncio
import dataclasses
import pathlib
import re
import shlex
import typing as t

from doctest_docutils import DocutilsDocTestFinder

from libtmux.experimental.engines import AsyncControlModeEngine
from libtmux.experimental.engines.base import (
    CommandRequest,
    CommandResult,
    CommandSeparator,
    is_command_separator,
)
from libtmux.experimental.ops import (
    DisplayMessage,
    LazyPlan,
    MarkedPlanner,
    SetOption,
    SplitWindow,
    WindowId,
)

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.experimental.ops.plan import PlanResult
    from libtmux.session import Session

_ROOT = pathlib.Path(__file__).parents[2]
_TUTORIAL = _ROOT / "docs" / "experimental" / "tutorials" / "async-control-plans.md"
_PLANS_PAGE = _ROOT / "docs" / "experimental" / "plans.md"
_TAB_PATTERN = re.compile(
    r"^`````\{tab\} (?P<label>[^\n]+)\n"
    r"(?P<body>.*?)"
    r"^`````$",
    re.MULTILINE | re.DOTALL,
)
_CONSOLE_PATTERN = re.compile(
    r"^```console\n(?P<body>.*?)^```$",
    re.MULTILINE | re.DOTALL,
)
_PLAN_API_TARGETS = {
    "libtmux.experimental.ops._chain.OpChain",
    "libtmux.experimental.ops._types.PaneId",
    "libtmux.experimental.ops._types.SlotRef",
    "libtmux.experimental.ops.operation.Operation",
    "libtmux.experimental.ops.plan.LazyPlan",
    "libtmux.experimental.ops.plan.PlanResult",
    "libtmux.experimental.ops.planner.BoundedPlanner",
    "libtmux.experimental.ops.planner.FoldingPlanner",
    "libtmux.experimental.ops.planner.MarkedPlanner",
    "libtmux.experimental.ops.planner.Planner",
    "libtmux.experimental.ops.planner.SequentialPlanner",
    "libtmux.experimental.fluent.PlanBuilder",
    "libtmux.experimental.fluent.SessionRef",
    "libtmux.experimental.fluent.WindowRef",
}


@dataclasses.dataclass
class _RecordingAsyncEngine:
    """Record requests while forwarding every call to a real async engine."""

    inner: AsyncControlModeEngine
    calls: list[tuple[str, ...]] = dataclasses.field(default_factory=list)

    def tmux_version(self) -> str | None:
        """Return the real engine's connected tmux version."""
        return self.inner.tmux_version()

    async def run(self, request: CommandRequest) -> CommandResult:
        """Record and execute one real request."""
        self.calls.append(request.args)
        return await self.inner.run(request)

    async def run_batch(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Record and execute one real request batch."""
        self.calls.extend(request.args for request in requests)
        return await self.inner.run_batch(requests)


def _tutorial_tabs() -> dict[str, str]:
    """Return the tutorial's native inline-tab bodies by label."""
    text = _TUTORIAL.read_text(encoding="utf-8")
    return {
        match.group("label"): match.group("body")
        for match in _TAB_PATTERN.finditer(text)
    }


def _console_argvs(body: str) -> list[tuple[str, ...]]:
    """Parse copyable console commands from one inline-tab body."""
    argvs: list[tuple[str, ...]] = []
    for match in _CONSOLE_PATTERN.finditer(body):
        lines = match.group("body").splitlines()
        assert lines and lines[0].startswith("$ ")
        command = "\n".join((lines[0][2:], *lines[1:])).replace("\\\n", " ")
        argvs.append(tuple(shlex.split(command)))
    return argvs


def _plan(window_id: str) -> LazyPlan:
    """Build the exact forward-reference plan taught by the tutorial."""
    operation_plan = LazyPlan()
    worker = operation_plan.add(SplitWindow(target=WindowId(window_id)))
    operation_plan.add_chain(
        SetOption(
            target=worker,
            pane=True,
            option="@role",
            value="worker",
        )
        >> SetOption(
            target=worker,
            pane=True,
            option="@state",
            value="ready",
        ),
    )
    operation_plan.add(
        DisplayMessage(
            target=worker,
            message="#{@role}:#{@state}",
        ),
    )
    return operation_plan


def test_tutorial_uses_native_tabs_with_discoverable_live_doctest() -> None:
    """The tabbed Python story remains visible to the prose-doctest collector."""
    text = _TUTORIAL.read_text(encoding="utf-8")
    tabs = _tutorial_tabs()

    assert set(tabs) == {"Python plan", "Compiled tmux sequence"}
    assert tabs["Python plan"].count("```python") == 1
    assert tabs["Compiled tmux sequence"].count("```console") == 2
    assert "MockEngine" not in text
    assert "AsyncMockEngine" not in text
    assert "# doctest: +SKIP" not in text
    assert "testsetup" not in text

    tests = DocutilsDocTestFinder().find(text, str(_TUTORIAL))
    assert len(tests) == 1
    assert tests[0].examples


def test_plans_page_routes_execution_to_live_examples() -> None:
    """The Plans landing does not teach execution with simulated output."""
    text = _PLANS_PAGE.read_text(encoding="utf-8")

    assert "MockEngine" not in text
    assert "AsyncMockEngine" not in text
    assert "{doc}`tutorials/async-control-plans`" in text
    assert text.count("SubprocessEngine.for_server(server)") == 3


def test_plans_page_owns_api_destinations_for_tutorial_links() -> None:
    """Every plan API linked by the tutorial has an autodoc destination."""
    text = _PLANS_PAGE.read_text(encoding="utf-8")

    for target in _PLAN_API_TARGETS:
        assert f".. autoclass:: {target}" in text
    assert ".. autofunction:: libtmux.experimental.fluent.plan" in text


def test_compiled_tab_matches_real_async_control_dispatch(session: Session) -> None:
    """Visible shell equivalents match requests executed by real control mode."""
    server = session.server
    window_id = session.active_window.window_id
    assert window_id is not None
    plan = _plan(window_id)

    async def execute() -> tuple[PlanResult, list[tuple[str, ...]]]:
        async with AsyncControlModeEngine.for_server(server) as live:
            recording = _RecordingAsyncEngine(live)
            result = await plan.aexecute(recording, planner=MarkedPlanner())
            return result, recording.calls

    outcome, calls = asyncio.run(execute())
    pane_id = outcome.bindings[0]
    visible = _console_argvs(_tutorial_tabs()["Compiled tmux sequence"])

    assert outcome.ok
    assert [result.status for result in outcome.results] == [
        "complete",
        "complete",
        "complete",
        "complete",
    ]
    assert outcome.results[-1].text == "worker:ready"
    assert server.panes.get(pane_id=pane_id) is not None
    assert len(calls) == len(visible) == 2
    assert sum(is_command_separator(token) for token in calls[0]) == 4
    assert all(
        type(token) is CommandSeparator
        for token in calls[0]
        if is_command_separator(token)
    )

    first_visible = tuple(
        window_id if token == "@WINDOW" else token for token in visible[0][1:]
    )
    second_visible = tuple(
        pane_id if token == "%PANE" else token for token in visible[1][1:]
    )
    assert tuple(map(str, calls[0])) == first_visible
    assert tuple(map(str, calls[1])) == second_visible
