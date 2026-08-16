"""Tests for the safety tier-gate wired into the fastmcp adapter."""

from __future__ import annotations

import asyncio
import subprocess
import typing as t

import pytest

from libtmux.experimental.engines import MockEngine
from libtmux.experimental.engines.base import CommandRequest, CommandResult
from libtmux.experimental.ops import (
    BreakPane,
    DisplayMessage,
    KillSession,
    LazyPlan,
    LinkWindow,
    LoadBuffer,
    MoveWindow,
    NewPane,
    NewSession,
    NewWindow,
    PasteBuffer,
    PipePane,
    RespawnPane,
    RespawnWindow,
    RunShell,
    SaveBuffer,
    SendKeys,
    SetEnvironment,
    SetHook,
    SetOption,
    SetWindowOption,
    SourceFile,
    SplitWindow,
    UnlinkWindow,
)
from libtmux.experimental.ops._types import PaneId, SessionId, WindowId
from libtmux.experimental.ops.serialize import operation_to_dict

fastmcp = pytest.importorskip("fastmcp")

from fastmcp.exceptions import ToolError  # noqa: E402 - after importorskip

from libtmux.experimental.mcp import vocabulary  # noqa: E402
from libtmux.experimental.mcp.fastmcp_adapter import build_server  # noqa: E402


class _RecordingEngine(MockEngine):
    """Record every request while retaining the deterministic mock results."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, ...]] = []

    def run(self, request: CommandRequest) -> CommandResult:
        """Record and execute one request."""
        self.calls.append(request.args)
        return super().run(request)


def _names_at(level: str, **kwargs: t.Any) -> set[str]:
    """Return the visible tool names from a server built at *level*."""

    async def main() -> set[str]:
        server = build_server(MockEngine(), safety_level=level, **kwargs)
        async with fastmcp.Client(server) as client:
            return {tool.name for tool in await client.list_tools()}

    return asyncio.run(main())


def test_safety_gate_static_visibility() -> None:
    """Each tier hides the tools above it from the listing."""
    readonly = _names_at("readonly")
    mutating = _names_at("mutating")
    destructive = _names_at("destructive")

    assert "list_sessions" in readonly  # readonly always visible
    assert "create_session" not in readonly  # mutating hidden at readonly
    assert "create_session" in mutating  # ... visible at mutating
    assert "kill_session" not in readonly  # destructive hidden ...
    assert "kill_session" not in mutating  # ... and at mutating
    assert "kill_session" in destructive  # visible only at destructive


def test_safety_gate_keeps_per_op_hidden_at_every_tier() -> None:
    """Regression: the subtractive gate never re-exposes hidden per-op tools."""
    for level in ("readonly", "mutating", "destructive"):
        names = _names_at(level, include_operations=True, expose_operations=False)
        assert not any(name.startswith("op_") for name in names), (
            f"per-op tools leaked into the listing at safety_level={level!r}"
        )
    # expose_operations=True surfaces them (and they still respect the tier)
    exposed = _names_at(
        "destructive",
        include_operations=True,
        expose_operations=True,
    )
    assert any(name.startswith("op_") for name in exposed)


def test_safety_gate_blocks_destructive_call_at_readonly() -> None:
    """A destructive tool cannot be successfully called at the readonly tier."""

    async def main() -> tuple[str, t.Any]:
        server = build_server(MockEngine(), safety_level="readonly")
        async with fastmcp.Client(server) as client:
            try:
                result = await client.call_tool("kill_session", {"target": "$1"})
            except Exception as error:
                return ("raised", type(error).__name__)
            return ("result", result.is_error)

    kind, value = asyncio.run(main())
    # Either the hidden tool is rejected (raised) or surfaced as an error result;
    # never a clean success.
    assert kind == "raised" or value is True


def test_safety_gate_plan_tool_tier() -> None:
    """Plan tools obey the tier too (build_workspace is mutating)."""
    readonly = _names_at("readonly")
    mutating = _names_at("mutating")
    assert "preview_plan" in readonly  # readonly plan tool always visible
    assert "build_workspace" not in readonly  # mutating plan tool hidden ...
    assert "build_workspace" in mutating  # ... visible at mutating


def test_plan_payload_cannot_bypass_destructive_tier() -> None:
    """A serialized destructive operation is rejected before any dispatch."""
    engine = _RecordingEngine()
    server = build_server(engine)
    operations = [
        operation_to_dict(KillSession(target=SessionId("$1"))),
    ]

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool("execute_plan", {"operations": operations})

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert not any(call and call[0] == "kill-session" for call in engine.calls)


def test_preview_can_inspect_destructive_payload_at_readonly() -> None:
    """Plan preview remains a pure inspection tool, not a secrecy boundary."""
    server = build_server(MockEngine(), safety_level="readonly")
    operations = [
        operation_to_dict(KillSession(target=SessionId("$1"))),
    ]

    async def main() -> t.Any:
        async with fastmcp.Client(server) as client:
            return await client.call_tool("preview_plan", {"operations": operations})

    result = asyncio.run(main())
    assert result.structured_content["argv"] == [["kill-session", "-t", "$1"]]


@pytest.mark.parametrize(
    ("operation", "command"),
    (
        (
            RespawnPane(target=PaneId("%1"), kill=True),
            "respawn-pane",
        ),
        (
            RespawnWindow(target=WindowId("@1"), kill=True),
            "respawn-window",
        ),
        (
            LinkWindow(
                target=WindowId("@1"),
                src_target=WindowId("@2"),
                kill=True,
            ),
            "link-window",
        ),
        (
            MoveWindow(
                target=WindowId("@1"),
                src_target=WindowId("@2"),
                kill=True,
            ),
            "move-window",
        ),
        (
            UnlinkWindow(target=WindowId("@1"), kill=True),
            "unlink-window",
        ),
    ),
)
def test_plan_payload_escalates_parameterized_kill(
    operation: t.Any,
    command: str,
) -> None:
    """A mutating operation with ``kill=True`` requires destructive safety."""
    engine = _RecordingEngine()
    server = build_server(engine)
    operations = [operation_to_dict(operation)]

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool("execute_plan", {"operations": operations})

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert not any(call and call[0] == command for call in engine.calls)


def test_plan_payload_preserves_safe_mutating_variant() -> None:
    """The same operation without its kill flag remains usable at mutating."""
    engine = _RecordingEngine()
    server = build_server(engine)
    operations = [
        operation_to_dict(UnlinkWindow(target=WindowId("@1"), kill=False)),
    ]

    async def main() -> t.Any:
        async with fastmcp.Client(server) as client:
            return await client.call_tool("execute_plan", {"operations": operations})

    result = asyncio.run(main())
    assert result.structured_content["ok"] is True
    assert any(call and call[0] == "unlink-window" for call in engine.calls)


def test_plan_payload_preserves_safe_forward_reference() -> None:
    """Caller guards do not reject a normal operation targeting a prior slot."""
    engine = _RecordingEngine()
    server = build_server(engine)
    plan = LazyPlan()
    session = plan.add(NewSession(session_name="dev", capture_panes=True))
    plan.add(SendKeys(target=session.pane, keys="pwd", enter=True))
    operations = [operation_to_dict(operation) for operation in plan.operations]

    async def main() -> t.Any:
        async with fastmcp.Client(server) as client:
            return await client.call_tool("execute_plan", {"operations": operations})

    result = asyncio.run(main())
    assert result.structured_content["ok"] is True
    assert ("send-keys", "-t", "%1", "--", "pwd", "Enter") in engine.calls


@pytest.mark.parametrize(
    ("operation", "command"),
    (
        (RunShell(command_line="arbitrary-host-command"), "run-shell"),
        (SourceFile(path="arbitrary.conf"), "source-file"),
        (
            PipePane(
                target=PaneId("%1"),
                command_line="arbitrary-host-command",
            ),
            "pipe-pane",
        ),
        (
            SetHook(
                name="after-new-window",
                hook_command="run-shell arbitrary-host-command",
            ),
            "set-hook",
        ),
    ),
)
def test_plan_payload_gates_open_world_operations(
    operation: t.Any,
    command: str,
) -> None:
    """Plans cannot execute host shell/config payloads at mutating."""
    engine = _RecordingEngine()
    server = build_server(engine)

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool(
                "execute_plan",
                {"operations": [operation_to_dict(operation)]},
            )

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert not any(call and call[0] == command for call in engine.calls)


def test_source_file_no_exec_remains_available_at_mutating() -> None:
    """The parse-only source-file variant does not inherit execution risk."""
    engine = _RecordingEngine()
    server = build_server(engine)
    operation = SourceFile(path="tmux.conf", no_exec=True)

    async def main() -> t.Any:
        async with fastmcp.Client(server) as client:
            return await client.call_tool(
                "execute_plan",
                {"operations": [operation_to_dict(operation)]},
            )

    result = asyncio.run(main())
    assert result.structured_content["ok"] is True
    assert ("source-file", "-n", "--", "tmux.conf") in engine.calls


@pytest.mark.parametrize(
    "operation",
    (
        NewSession(environment={"PROMPT_COMMAND": "arbitrary-host-command"}),
        NewWindow(
            target=SessionId("$1"),
            environment={"PROMPT_COMMAND": "arbitrary-host-command"},
        ),
        SplitWindow(
            target=PaneId("%1"),
            environment={"PROMPT_COMMAND": "arbitrary-host-command"},
        ),
        NewPane(
            target=PaneId("%1"),
            environment={"PROMPT_COMMAND": "arbitrary-host-command"},
        ),
        RespawnPane(
            target=PaneId("%1"),
            environment={"PROMPT_COMMAND": "arbitrary-host-command"},
        ),
        RespawnWindow(
            target=WindowId("@1"),
            environment={"PROMPT_COMMAND": "arbitrary-host-command"},
        ),
        SetEnvironment(
            name="PROMPT_COMMAND",
            value="arbitrary-host-command",
        ),
    ),
)
def test_plan_payload_gates_environment_injection(operation: t.Any) -> None:
    """Environment injection is open-ended process execution policy."""
    engine = _RecordingEngine()
    server = build_server(engine)

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool(
                "execute_plan",
                {"operations": [operation_to_dict(operation)]},
            )

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert engine.calls == []


def test_environment_removal_and_empty_mappings_remain_mutating() -> None:
    """Removing variables and supplying no overrides do not inject code."""
    from libtmux.experimental.mcp._policy import operation_safety

    operations = (
        NewSession(environment={}),
        SetEnvironment(
            name="PROMPT_COMMAND",
            value="ignored",
            remove=True,
        ),
        SetEnvironment(
            name="PROMPT_COMMAND",
            value="ignored",
            unset=True,
        ),
    )

    assert [operation_safety(operation) for operation in operations] == [
        "mutating",
        "mutating",
        "mutating",
    ]


def test_open_world_operations_preserve_nonexecuting_variants() -> None:
    """Disabling a pane pipe or unsetting a hook remains mutating."""
    engine = _RecordingEngine()
    server = build_server(engine)
    operations = [
        operation_to_dict(PipePane(target=PaneId("%1"))),
        operation_to_dict(SetHook(name="after-new-window", unset=True)),
    ]

    async def main() -> t.Any:
        async with fastmcp.Client(server) as client:
            return await client.call_tool("execute_plan", {"operations": operations})

    result = asyncio.run(main())
    assert result.structured_content["ok"] is True
    assert ("pipe-pane", "-t", "%1") in engine.calls
    assert ("set-hook", "-u", "--", "after-new-window") in engine.calls


@pytest.mark.parametrize(
    "operation",
    (
        NewSession(window_shell="arbitrary-host-command"),
        NewWindow(
            target=SessionId("$1"),
            window_shell="arbitrary-host-command",
        ),
        SplitWindow(
            target=PaneId("%1"),
            shell="arbitrary-host-command",
        ),
        NewPane(
            target=PaneId("%1"),
            shell_command="arbitrary-host-command",
        ),
        RespawnPane(
            target=PaneId("%1"),
            shell="arbitrary-host-command",
        ),
        RespawnWindow(
            target=WindowId("@1"),
            shell="arbitrary-host-command",
        ),
    ),
)
def test_plan_payload_gates_shell_bearing_create_and_respawn(
    operation: t.Any,
) -> None:
    """A nonblank pane-process command requires destructive authorization."""
    engine = _RecordingEngine()
    server = build_server(engine)

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool(
                "execute_plan",
                {"operations": [operation_to_dict(operation)]},
            )

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert engine.calls == []


@pytest.mark.parametrize(
    "operation",
    (
        BreakPane(src_target=PaneId("%1"), name="#(arbitrary-host-command)"),
        DisplayMessage(message="#(arbitrary-host-command)"),
        DisplayMessage(message="#{E:@status}"),
        DisplayMessage(message="#{T:@status}"),
        LoadBuffer(path="#(arbitrary-host-command)"),
        NewSession(session_name="#(arbitrary-host-command)"),
        NewWindow(
            target=SessionId("$1"),
            name="#(arbitrary-host-command)",
        ),
        SaveBuffer(path="#(arbitrary-host-command)"),
        NewPane(
            target=PaneId("%1"),
            message="#(arbitrary-host-command)",
        ),
        NewPane(
            target=PaneId("%1"),
            style="fg=#{E:@probe}",
        ),
        NewPane(
            target=PaneId("%1"),
            active_border_style="fg=#{T:@probe}",
        ),
        NewPane(
            target=PaneId("%1"),
            inactive_border_style="fg=#(arbitrary-host-command)",
        ),
        SetOption(option="status-right", value="#(arbitrary-host-command)"),
        SetWindowOption(
            option="window-status-current-format",
            value="#(arbitrary-host-command)",
        ),
    ),
)
def test_plan_payload_gates_active_or_recursive_formats(operation: t.Any) -> None:
    """Executable and recursively expandable tmux formats fail before dispatch."""
    engine = _RecordingEngine()
    server = build_server(engine)

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool(
                "execute_plan",
                {"operations": [operation_to_dict(operation)]},
            )

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert engine.calls == []


@pytest.mark.parametrize(
    "operation",
    (
        NewPane(
            target=PaneId("%1"),
            width="#(arbitrary-host-command)",
        ),
        NewPane(
            target=PaneId("%1"),
            height="#{E:@probe}",
        ),
        NewPane(
            target=PaneId("%1"),
            x="#{T:@probe}",
        ),
        NewPane(
            target=PaneId("%1"),
            y="#(arbitrary-host-command)",
        ),
    ),
)
def test_plan_payload_gates_floating_geometry_formats(operation: NewPane) -> None:
    """Every string geometry field is format-expanded before pane creation."""
    engine = _RecordingEngine()
    server = build_server(engine)

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool(
                "execute_plan",
                {"operations": [operation_to_dict(operation)]},
            )

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert engine.calls == []


def test_floating_geometry_preserves_bounded_variants() -> None:
    """Cells, percentages, numeric strings, and simple fields stay mutating."""
    from libtmux.experimental.mcp._policy import operation_safety

    operation = NewPane(
        target=PaneId("%1"),
        width=80,
        height="50%",
        x="12",
        y="#{pane_top}",
    )

    assert operation_safety(operation) == "mutating"


def test_format_bearing_names_and_styles_preserve_bounded_variants() -> None:
    """Escaped hashes and simple lookups do not over-escalate create payloads."""
    from libtmux.experimental.mcp._policy import operation_safety

    operations = (
        NewSession(session_name="##(literal)"),
        NewWindow(target=SessionId("$1"), name="#{window_id}"),
        BreakPane(src_target=PaneId("%1"), name="#{@probe}"),
        NewPane(
            target=PaneId("%1"),
            style="fg=#{pane_fg}",
            active_border_style="fg=##(literal)",
        ),
    )

    assert [operation_safety(operation) for operation in operations] == [
        "mutating",
        "mutating",
        "mutating",
        "mutating",
    ]


def test_break_pane_name_is_gated_on_tmux_3_7() -> None:
    """The 3.7 rename follow-up cannot execute an unbounded format."""
    engine = _RecordingEngine()
    server = build_server(engine)
    operation = BreakPane(
        src_target=PaneId("%1"),
        name="#(arbitrary-host-command)",
    )

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool(
                "execute_plan",
                {
                    "operations": [operation_to_dict(operation)],
                    "version": "3.7",
                },
            )

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert engine.calls == []


@pytest.mark.parametrize(
    "message",
    ("plain text", "##(literal)", "#{pane_id}", "#{@probe}"),
)
def test_curated_display_message_preserves_bounded_readonly_formats(
    message: str,
) -> None:
    """Plain, escaped, and simple-field formats remain readonly queries."""
    engine = _RecordingEngine()
    server = build_server(engine, safety_level="readonly")

    async def main() -> t.Any:
        async with fastmcp.Client(server) as client:
            return await client.call_tool(
                "display_message",
                {"target": "%1", "message": message},
            )

    result = asyncio.run(main())
    assert result.is_error is False
    assert ("display-message", "-t", "%1", "-p", "--", message) in engine.calls


@pytest.mark.parametrize(
    "message",
    (
        "#(arbitrary-host-command)",
        "###(arbitrary-host-command)",
        "#{E:@probe}",
        "#{T:@probe}",
        "#{?pane_active,yes,no}",
    ),
)
def test_curated_display_message_escalates_unbounded_formats(message: str) -> None:
    """Jobs, recursive modifiers, and unbounded syntax require destructive."""
    engine = _RecordingEngine()
    server = build_server(engine)

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool(
                "display_message",
                {"target": "%1", "message": message},
            )

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert engine.calls == []


def test_open_world_input_and_buffer_transfer_remain_mutating() -> None:
    """Open-world disclosure does not elevate ordinary pane input or buffers."""
    engine = _RecordingEngine()
    server = build_server(engine)
    operations = [
        operation_to_dict(SendKeys(target=PaneId("%1"), keys="printf ok")),
        operation_to_dict(PasteBuffer(target=PaneId("%1"))),
    ]

    async def main() -> t.Any:
        async with fastmcp.Client(server) as client:
            return await client.call_tool("execute_plan", {"operations": operations})

    result = asyncio.run(main())
    assert result.structured_content["ok"] is True
    assert ("send-keys", "-t", "%1", "--", "printf ok") in engine.calls
    assert ("paste-buffer", "-t", "%1") in engine.calls


def test_per_op_payload_escalates_parameterized_kill() -> None:
    """A direct per-op ``kill=True`` call is rejected at mutating."""
    engine = _RecordingEngine()
    server = build_server(engine, expose_operations=True)

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool(
                "op_respawn_pane",
                {"target": "%1", "kill": True},
            )

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert not any(call and call[0] == "respawn-pane" for call in engine.calls)


def test_per_op_source_file_requires_destructive_tier() -> None:
    """The exposed per-op surface enforces open-world payload safety."""
    engine = _RecordingEngine()
    server = build_server(engine, expose_operations=True)

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool("op_source_file", {"path": "arbitrary.conf"})

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert not any(call and call[0] == "source-file" for call in engine.calls)


def test_per_op_set_environment_requires_destructive_tier() -> None:
    """A direct environment-setting operation cannot bypass its payload gate."""
    engine = _RecordingEngine()
    server = build_server(engine, expose_operations=True)

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool(
                "op_set_environment",
                {
                    "name": "PROMPT_COMMAND",
                    "value": "arbitrary-host-command",
                },
            )

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert engine.calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("width", "#(arbitrary-host-command)"),
        ("height", "#{E:@probe}"),
        ("x", "#{T:@probe}"),
        ("y", "#(arbitrary-host-command)"),
    ),
)
def test_per_op_new_pane_gates_floating_geometry(
    field: str,
    value: str,
) -> None:
    """Direct operation tools gate each format-expanded geometry field."""
    engine = _RecordingEngine()
    server = build_server(engine, expose_operations=True)

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool(
                "op_new_pane",
                {"target": "%1", field: value},
            )

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert engine.calls == []


def test_curated_payload_escalates_parameterized_kill() -> None:
    """The curated respawn tool enforces its parameterized destructive path."""
    engine = _RecordingEngine()
    server = build_server(engine)

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool("respawn_pane", {"target": "%1", "kill": True})

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert not any(call and call[0] == "respawn-pane" for call in engine.calls)


@pytest.mark.parametrize(
    ("tool", "arguments"),
    (
        (
            "break_pane",
            {"src": "%1", "name": "#(arbitrary-host-command)"},
        ),
        (
            "create_session",
            {"name": "#(arbitrary-host-command)"},
        ),
        (
            "create_window",
            {"target": "$1", "name": "#{E:@probe}"},
        ),
        (
            "new_pane",
            {"target": "%1", "shell_command": "arbitrary-host-command"},
        ),
        (
            "respawn_pane",
            {"target": "%1", "shell": "arbitrary-host-command"},
        ),
        (
            "set_option",
            {"option": "status-right", "value": "#(arbitrary-host-command)"},
        ),
    ),
)
def test_curated_payload_gates_shell_and_format_execution(
    tool: str,
    arguments: dict[str, t.Any],
) -> None:
    """Curated wrappers apply the same payload policy as operation tools."""
    engine = _RecordingEngine()
    server = build_server(engine)

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool(tool, arguments)

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert engine.calls == []


def test_curated_create_session_gates_environment_injection() -> None:
    """The curated session creator applies the shared environment policy."""
    engine = _RecordingEngine()
    server = build_server(engine)

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool(
                "create_session",
                {
                    "name": "dev",
                    "environment": {
                        "PROMPT_COMMAND": "arbitrary-host-command",
                    },
                },
            )

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert engine.calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("width", "#(arbitrary-host-command)"),
        ("height", "#{E:@probe}"),
        ("x", "#{T:@probe}"),
        ("y", "#(arbitrary-host-command)"),
    ),
)
def test_curated_new_pane_gates_floating_geometry(
    field: str,
    value: str,
) -> None:
    """The curated floating-pane tool applies the geometry format policy."""
    engine = _RecordingEngine()
    server = build_server(engine)

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool(
                "new_pane",
                {"target": "%1", field: value},
            )

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert engine.calls == []


@pytest.mark.parametrize(
    ("operation", "expected"),
    (
        (
            SetOption(
                option="after-new-window",
                value="run-shell arbitrary-host-command",
            ),
            "destructive",
        ),
        (
            SetOption(
                option="after-new-window[0]",
                value="run-shell arbitrary-host-command",
            ),
            "destructive",
        ),
        (
            SetOption(
                option="after-new-w",
                value="run-shell arbitrary-host-command",
            ),
            "destructive",
        ),
        (
            SetOption(
                option="command-a[9]",
                value="surprise=run-shell arbitrary-host-command",
            ),
            "destructive",
        ),
        (
            SetOption(
                option="default-c",
                value="arbitrary-host-command",
            ),
            "destructive",
        ),
        (
            SetOption(
                option="#{@selected-option}",
                value="run-shell arbitrary-host-command",
            ),
            "destructive",
        ),
        (
            SetOption(
                option="default-command",
                value="arbitrary-host-command",
            ),
            "destructive",
        ),
        (
            SetOption(
                option="update-environment",
                value="PROMPT_COMMAND",
            ),
            "destructive",
        ),
        (
            SetWindowOption(
                option="window-renamed",
                value="run-shell arbitrary-host-command",
            ),
            "destructive",
        ),
        (
            SetOption(
                option="after-new-window",
                value="ignored",
                unset=True,
            ),
            "mutating",
        ),
        (
            SetOption(
                option="#{@selected-option}",
                value="ignored",
                unset=True,
            ),
            "mutating",
        ),
        (
            SetOption(
                option="default-command",
                value=None,
            ),
            "mutating",
        ),
        (
            SetOption(option="status", value="on"),
            "mutating",
        ),
        (
            SetWindowOption(option="mode-keys", value="vi"),
            "mutating",
        ),
        (
            SetOption(option="@custom", value="plain"),
            "mutating",
        ),
        (
            SetOption(
                option="#(arbitrary-host-command)",
                value="ignored",
                unset=True,
            ),
            "destructive",
        ),
    ),
)
def test_option_command_payload_safety(
    operation: SetOption | SetWindowOption,
    expected: str,
) -> None:
    """Command options, hook indexes, abbreviations, and dynamic names gate."""
    from libtmux.experimental.mcp._policy import operation_safety

    assert operation_safety(operation) == expected


@pytest.mark.parametrize(
    "operation",
    (
        SetOption(
            option="default-client-command",
            value="run-shell arbitrary-host-command",
        ),
        SetOption(
            option="command-alias[99]",
            value="surprise=run-shell arbitrary-host-command",
        ),
        SetOption(option="copy-command", value="arbitrary-host-command"),
        SetOption(option="default-command", value="arbitrary-host-command"),
        SetOption(option="default-shell", value="/path/to/arbitrary-program"),
        SetOption(option="editor", value="arbitrary-host-command"),
        SetOption(option="lock-command", value="arbitrary-host-command"),
        SetWindowOption(
            option="window-renamed[0]",
            value="run-shell arbitrary-host-command",
        ),
    ),
)
def test_plan_payload_gates_executable_options(operation: t.Any) -> None:
    """Plain delayed command option values require destructive authorization."""
    engine = _RecordingEngine()
    server = build_server(engine)

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool(
                "execute_plan",
                {"operations": [operation_to_dict(operation)]},
            )

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert engine.calls == []


def test_curated_set_option_gates_plain_delayed_command() -> None:
    """The curated option tool cannot install a plain hook command at mutating."""
    engine = _RecordingEngine()
    server = build_server(engine)

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool(
                "set_option",
                {
                    "option": "after-new-window",
                    "value": "run-shell arbitrary-host-command",
                },
            )

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert engine.calls == []


def test_raw_tmux_is_destructive_only() -> None:
    """The arbitrary-command escape hatch is hidden below destructive safety."""
    mutating = _names_at("mutating")
    destructive = _names_at("destructive")

    assert "run_tmux" not in mutating
    assert "run_tmux" in destructive


def test_raw_tmux_documents_unguarded_escape_boundary() -> None:
    """The raw tool does not imply typed target-aware caller protection."""
    doc = vocabulary.run_tmux.__doc__ or ""

    assert "explicit raw escape hatch" in doc
    assert "Unlike typed operations" in doc
    assert "target-aware caller-liveness checks" in doc


def test_workspace_replace_requires_destructive_tier() -> None:
    """Workspace replacement cannot kill a session at the mutating tier."""
    engine = _RecordingEngine()
    server = build_server(engine)
    spec = {
        "session_name": "dev",
        "on_exists": "replace",
        "windows": [{"window_name": "main", "panes": [""]}],
    }

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool("build_workspace", {"spec": spec})

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert not any(call and call[0] == "kill-session" for call in engine.calls)


def test_workspace_before_script_requires_destructive_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mutating server cannot execute a workspace host-shell hook."""
    host_calls: list[str] = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **_kwargs: host_calls.append(command),
    )
    server = build_server(MockEngine())
    spec = {
        "session_name": "dev",
        "before_script": "arbitrary-host-command",
        "windows": [{"window_name": "main", "panes": [""]}],
    }

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool(
                "build_workspace",
                {"spec": spec, "preflight": False},
            )

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert host_calls == []


def test_async_workspace_before_script_requires_destructive_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The async workspace path applies the same host-shell payload gate."""
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server
    from libtmux.experimental.mcp.vocabulary._bridge import SyncToAsyncEngine

    host_calls: list[str] = []

    async def fake_shell(command: str, **_kwargs: t.Any) -> t.Any:
        host_calls.append(command)

        class Process:
            async def wait(self) -> None:
                return None

        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_shell)
    server = build_async_server(
        SyncToAsyncEngine(MockEngine()),
        events="off",
    )
    spec = {
        "session_name": "dev",
        "before_script": "arbitrary-host-command",
        "windows": [{"window_name": "main", "panes": [""]}],
    }

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool(
                "build_workspace",
                {"spec": spec, "preflight": False},
            )

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert host_calls == []


@pytest.mark.parametrize(
    "spec",
    (
        {
            "session_name": "#(arbitrary-host-command)",
            "windows": [{"panes": [""]}],
        },
        {
            "session_name": "dev",
            "windows": [
                {
                    "window_name": "#{E:@probe}",
                    "panes": [""],
                },
            ],
        },
        {
            "session_name": "dev",
            "windows": [
                {
                    "panes": [""],
                    "floats": [
                        {
                            "float": {
                                "style": "fg=#{E:@probe}",
                            },
                        },
                    ],
                },
            ],
        },
        {
            "session_name": "dev",
            "windows": [
                {
                    "window_shell": "arbitrary-host-command",
                    "panes": [""],
                },
            ],
        },
        {
            "session_name": "dev",
            "windows": [
                {
                    "panes": [
                        "",
                        {"shell": "arbitrary-host-command"},
                    ],
                },
            ],
        },
        {
            "session_name": "dev",
            "options": {"status-right": "#(arbitrary-host-command)"},
            "windows": [{"panes": [""]}],
        },
        {
            "session_name": "dev",
            "options": {"default-command": "arbitrary-host-command"},
            "windows": [{"panes": [""]}],
        },
        {
            "session_name": "dev",
            "environment": {
                "PROMPT_COMMAND": "arbitrary-host-command",
            },
            "windows": [{"panes": [""]}],
        },
        {
            "session_name": "dev",
            "windows": [
                {
                    "panes": [
                        {
                            "environment": {
                                "PROMPT_COMMAND": "arbitrary-host-command",
                            },
                        },
                    ],
                },
            ],
        },
    ),
)
def test_workspace_compiled_plan_requires_payload_safety(
    spec: dict[str, t.Any],
) -> None:
    """Workspace compilation cannot tunnel shell or format payloads."""
    engine = _RecordingEngine()
    server = build_server(engine)

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool(
                "build_workspace",
                {"spec": spec, "preflight": False},
            )

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert engine.calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("width", "#(arbitrary-host-command)"),
        ("height", "#{E:@probe}"),
        ("x", "#{T:@probe}"),
        ("y", "#(arbitrary-host-command)"),
    ),
)
def test_workspace_gates_floating_geometry(
    field: str,
    value: str,
) -> None:
    """Workspace compilation cannot tunnel active geometry formats."""
    engine = _RecordingEngine()
    server = build_server(engine)
    spec = {
        "session_name": "dev",
        "windows": [
            {
                "panes": [""],
                "floats": [{"float": {field: value}}],
            },
        ],
    }

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool(
                "build_workspace",
                {"spec": spec, "preflight": False},
            )

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert engine.calls == []


def test_async_workspace_compiled_plan_requires_payload_safety() -> None:
    """The async workspace path gates its compiled operations before dispatch."""
    from libtmux.experimental.mcp.fastmcp_adapter import build_async_server
    from libtmux.experimental.mcp.vocabulary._bridge import SyncToAsyncEngine

    engine = _RecordingEngine()
    server = build_async_server(
        SyncToAsyncEngine(engine),
        events="off",
    )
    spec = {
        "session_name": "dev",
        "options": {"status-right": "#{E:@probe}"},
        "windows": [{"panes": [""]}],
    }

    async def main() -> None:
        async with fastmcp.Client(server) as client:
            await client.call_tool(
                "build_workspace",
                {"spec": spec, "preflight": False},
            )

    with pytest.raises(ToolError, match="destructive"):
        asyncio.run(main())
    assert not any(
        call and call[0] in {"new-session", "set-option"} for call in engine.calls
    )


def test_workspace_shell_command_input_remains_mutating() -> None:
    """Commands sent into a created pane stay mutating and open-world."""
    engine = _RecordingEngine()
    server = build_server(engine)
    spec = {
        "session_name": "dev",
        "windows": [{"panes": ["printf ok"]}],
    }

    async def main() -> t.Any:
        async with fastmcp.Client(server) as client:
            return await client.call_tool(
                "build_workspace",
                {"spec": spec, "preflight": False},
            )

    result = asyncio.run(main())
    assert result.structured_content["ok"] is True
    assert any(call and call[0] == "send-keys" for call in engine.calls)


def test_safe_plan_and_workspace_annotations_match_capabilities() -> None:
    """Generic execution tools advertise that some payloads are destructive."""
    server = build_server(MockEngine(), safety_level="destructive")

    async def main() -> t.Any:
        async with fastmcp.Client(server) as client:
            return {tool.name: tool for tool in await client.list_tools()}

    tools = asyncio.run(main())
    assert tools["execute_plan"].annotations.destructiveHint is True
    assert tools["execute_plan"].annotations.openWorldHint is True
    assert tools["build_workspace"].annotations.destructiveHint is True
    assert tools["build_workspace"].annotations.openWorldHint is True
    assert tools["run_tmux"].annotations.destructiveHint is True
    assert tools["run_tmux"].annotations.openWorldHint is True
    for name in (
        "break_pane",
        "create_session",
        "create_window",
        "display_message",
        "new_pane",
        "rename_session",
        "rename_window",
        "respawn_pane",
        "set_option",
        "split_pane",
    ):
        assert tools[name].annotations.destructiveHint is True
        assert tools[name].annotations.openWorldHint is True

    for name in ("paste_buffer", "send_input", "set_buffer"):
        assert tools[name].annotations.destructiveHint is False
        assert tools[name].annotations.openWorldHint is True
