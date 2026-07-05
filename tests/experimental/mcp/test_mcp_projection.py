"""The framework-agnostic MCP projection tier (no fastmcp required).

Exercises descriptor generation from the operation registry, agent target
resolution, plan preview/execute with forward-ref bindings, result-schema
introspection, and the build_workspace tool -- all against the in-memory
``MockEngine`` so the projection is provably correct offline.
"""

from __future__ import annotations

from libtmux.experimental.engines import MockEngine
from libtmux.experimental.mcp import (
    OperationToolRegistry,
    build_workspace,
    build_workspaces,
    execute_plan,
    explain_plan,
    preview_plan,
    resolve_target,
    result_schema,
)
from libtmux.experimental.ops import (
    LazyPlan,
    MarkedPlanner,
    NewSession,
    SendKeys,
    SplitWindow,
    registry,
)
from libtmux.experimental.ops._types import NameRef, PaneId, SessionId, WindowId
from libtmux.experimental.ops.serialize import bindings_from_dict, bindings_to_dict


def test_every_operation_has_a_descriptor() -> None:
    """The registry projects one valid descriptor per registered operation kind."""
    reg = OperationToolRegistry()
    descriptors = reg.descriptors()
    assert {d.name for d in descriptors} == set(registry.kinds())
    for d in descriptors:
        schema = d.input_schema()
        assert schema["type"] == "object"
        assert d.safety in {"readonly", "mutating", "destructive"}


def test_split_window_descriptor_shape() -> None:
    """A per-op descriptor carries typed params, scope, safety, and annotations."""
    desc = OperationToolRegistry().descriptor("split_window")
    assert desc.name == "split_window"
    assert desc.scope == "window"
    assert desc.safety == "mutating"
    assert desc.annotations == {"readOnlyHint": False}
    assert desc.result_type == "SplitWindowResult"
    assert desc.params["horizontal"].origin == "bool"
    assert desc.params["horizontal"].is_required is False


def test_min_version_surfaced_on_descriptor() -> None:
    """A whole-op min_version projects onto the descriptor and its description."""
    desc = OperationToolRegistry().descriptor("new_pane")
    assert desc.min_version == "3.7"
    assert "tmux >= 3.7" in desc.description


def test_ungated_op_has_no_min_version() -> None:
    """An op without a whole-command gate carries no min_version."""
    assert OperationToolRegistry().descriptor("split_window").min_version is None


def test_readonly_op_annotation() -> None:
    """A readonly operation projects a readOnlyHint annotation + tag."""
    desc = OperationToolRegistry().descriptor("has_session")
    assert desc.annotations == {"readOnlyHint": True}
    assert "readonly" in desc.tags


def test_descriptor_build_resolves_targets() -> None:
    """ToolDescriptor.build turns agent params into a typed operation."""
    desc = OperationToolRegistry().descriptor("split_window")
    op = desc.build(target="@1", horizontal=True)
    assert isinstance(op, SplitWindow)
    assert op.target == WindowId("@1")
    assert op.render() == ("split-window", "-t", "@1", "-h", "-P", "-F", "#{pane_id}")


def test_resolve_target_forms() -> None:
    """resolve_target coerces every supported spec into a typed Target."""
    assert resolve_target("%1") == PaneId("%1")
    assert resolve_target("@2") == WindowId("@2")
    assert resolve_target("$0") == SessionId("$0")
    assert resolve_target("work") == NameRef("work")
    assert resolve_target({"type": "PaneId", "value": "%3"}) == PaneId("%3")
    assert resolve_target(PaneId("%4")) == PaneId("%4")
    assert resolve_target(None) is None


def test_bindings_round_trip() -> None:
    """Plan bindings (incl. sub-ref tuple keys) survive a JSON round-trip."""
    original: dict[int | tuple[int, str], str] = {0: "$1", (0, "pane"): "%2", 1: "@3"}
    assert bindings_from_dict(bindings_to_dict(original)) == original


def test_preview_plan_marks_unresolved_forward_refs() -> None:
    """preview_plan renders a pure dry-run; forward-ref steps render as None."""
    plan = LazyPlan()
    pane = plan.add(SplitWindow(target=WindowId("@1")))
    plan.add(SendKeys(target=pane, keys="vim", enter=True))
    preview = preview_plan(plan)
    assert preview.argv[0] is not None
    assert preview.argv[1] is None  # SendKeys targets the not-yet-created pane
    assert preview.ok is False


def test_explain_plan_reports_boundary_reasons() -> None:
    """explain_plan annotates each dispatch step with why it can't fold further."""
    plan = LazyPlan()
    pane = plan.add(SplitWindow(target=WindowId("@1")))
    plan.add(SendKeys(target=pane, keys="vim", enter=True))
    steps = explain_plan(plan, planner=MarkedPlanner()).steps
    assert len(steps) == 1
    assert steps[0]["indices"] == [0, 1]
    assert steps[0]["kinds"] == ["split_window", "send_keys"]
    assert steps[0]["reason"] == "marked-fold"


def test_execute_plan_returns_bindings() -> None:
    """execute_plan resolves forward refs and returns a JSON bindings map."""
    plan = LazyPlan()
    session = plan.add(NewSession(session_name="dev", capture_panes=True))
    plan.add(SendKeys(target=session.pane, keys="vim", enter=True))
    outcome = execute_plan(plan, MockEngine())
    assert outcome.ok
    assert outcome.bindings["0"].startswith("$")
    assert outcome.bindings["0:pane"].startswith("%")
    assert outcome.results[1]["argv"][0] == "send-keys"


def test_result_schema_introspection() -> None:
    """result_schema reports the id fields an agent can bind downstream."""
    split = result_schema(OperationToolRegistry(), "split_window")
    assert split.result_type == "SplitWindowResult"
    assert "new_pane_id" in split.binding_fields

    session = result_schema(OperationToolRegistry(), "new_session")
    assert "first_pane_id" in session.binding_fields
    assert "first_window_id" in session.binding_fields


def test_build_workspace_tool_offline() -> None:
    """build_workspace runs the declarative tier as one tool call (offline)."""
    outcome = build_workspace(
        {
            "session_name": "dev",
            "windows": [{"window_name": "editor", "panes": ["vim", "pytest -q"]}],
        },
        MockEngine(),
        preflight=False,
    )
    assert outcome.ok
    assert outcome.bindings["0"].startswith("$")


def test_build_workspaces_tool_offline() -> None:
    """build_workspaces runs multiple declarative specs as one tool call."""
    outcome = build_workspaces(
        [
            {"session_name": "api", "windows": [{"window_name": "w", "panes": ["a"]}]},
            {"session_name": "docs", "windows": [{"window_name": "w", "panes": ["b"]}]},
        ],
        MockEngine(),
        preflight=False,
    )

    assert outcome.ok
    assert outcome.sessions == ["api", "docs"]
    assert outcome.reused == []
    assert outcome.bindings["0"].startswith("$")
