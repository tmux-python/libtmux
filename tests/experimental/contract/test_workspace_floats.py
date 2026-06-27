"""Tests for floating-pane declarations in the workspace IR (tmux 3.7+)."""

from __future__ import annotations

import pytest

from libtmux.experimental.ops import NewPane, SendKeys
from libtmux.experimental.workspace import (
    Float,
    FloatingPane,
    Pane,
    Window,
    Workspace,
    WorkspaceCompileError,
    analyze,
    compile_workspace,
)
from libtmux.experimental.workspace.compiler import Symbols, _topo_order


def test_float_to_dict_omits_defaults() -> None:
    """Float.to_dict drops fields left at their default."""
    assert Float().to_dict() == {}
    assert Float(width=120, height=40, x="C", y="C", zoom=True).to_dict() == {
        "width": 120,
        "height": 40,
        "x": "C",
        "y": "C",
        "zoom": True,
    }


def test_floating_pane_to_dict() -> None:
    """A FloatingPane serializes as a pane config plus float geometry + attach_to."""
    fp = FloatingPane(
        pane=Pane(run="lazygit"),
        geometry=Float(width="60%"),
        attach_to="editor",
    )
    out = fp.to_dict()
    assert out["shell_command"] == ["lazygit"]
    assert out["float"] == {"width": "60%"}
    assert out["attach_to"] == "editor"


def test_window_floats_default_empty() -> None:
    """A window declared without floats has no overlays."""
    assert Window("editor").floats == ()


def test_window_holds_declared_floats() -> None:
    """Window.floats preserves the declared overlay specs in order."""
    window = Window(
        "editor",
        floats=[
            FloatingPane(pane=Pane(run="lazygit"), attach_to=None),
            FloatingPane(pane=Pane(run="htop"), attach_to="logs"),
        ],
    )
    assert [fp.pane.run for fp in window.floats] == ["lazygit", "htop"]
    assert [fp.attach_to for fp in window.floats] == [None, "logs"]


def test_floats_round_trip_through_to_dict() -> None:
    """analyze(ws.to_dict()) reconstructs an equivalent workspace including floats."""
    ws = Workspace(
        name="dev",
        windows=[
            Window(
                "editor",
                panes=[Pane(run="vim")],
                floats=[
                    FloatingPane(
                        pane=Pane(run="lazygit"),
                        geometry=Float(width="60%", height="50%", zoom=True),
                        attach_to="editor",
                    ),
                ],
            ),
        ],
    )

    revived = analyze(ws.to_dict())
    floated = revived.windows[0].floats[0]
    assert [c.cmd for c in floated.pane.commands] == ["lazygit"]
    assert floated.geometry.width == "60%"
    assert floated.geometry.zoom is True
    assert floated.attach_to == "editor"
    assert revived.to_dict() == ws.to_dict()


def test_compiler_emits_new_pane_after_layout() -> None:
    """A declared float compiles to a new-pane op after the tiled layout."""
    ws = Workspace(
        name="dev",
        windows=[
            Window(
                "editor",
                layout="main-vertical",
                panes=[Pane(run="vim")],
                floats=[
                    FloatingPane(
                        pane=Pane(run="lazygit"),
                        geometry=Float(width=120, height=40),
                    ),
                ],
            ),
        ],
    )
    kinds = [op.kind for op in compile_workspace(ws).operations]
    assert "new_pane" in kinds
    assert kinds.index("new_pane") > kinds.index("select_layout")


def test_compiler_new_pane_geometry_and_command() -> None:
    """The emitted new-pane carries the float geometry and sends its command."""
    ws = Workspace(
        name="dev",
        windows=[
            Window(
                "editor",
                panes=[Pane(run="vim")],
                floats=[
                    FloatingPane(
                        pane=Pane(run="lazygit"),
                        geometry=Float(width="60%", height="50%"),
                    ),
                ],
            ),
        ],
    )
    ops = compile_workspace(ws).operations
    new_pane = next(op for op in ops if isinstance(op, NewPane))
    assert (new_pane.width, new_pane.height) == ("60%", "50%")
    assert any(isinstance(op, SendKeys) and op.keys == "lazygit" for op in ops)


def test_cross_window_float_attaches_to_later_window() -> None:
    """A float on an early window can attach to a window declared later."""
    ws = Workspace(
        name="dev",
        windows=[
            Window(
                "editor",
                panes=[Pane(run="vim")],
                # attach_to a window declared AFTER this one (forward reference)
                floats=[FloatingPane(pane=Pane(run="lazygit"), attach_to="logs")],
            ),
            Window("logs", panes=[Pane(run="tail -f x")]),
        ],
    )
    # Compiles (no raise) and the float op lands after both windows exist.
    kinds = [op.kind for op in compile_workspace(ws).operations]
    assert kinds.count("new_window") == 1  # 'logs' is created
    assert kinds.index("new_pane") > kinds.index("new_window")


def test_cross_window_float_builds_offline() -> None:
    """A cross-window float resolves its target and builds in-memory."""
    from libtmux.experimental.engines import ConcreteEngine

    ws = Workspace(
        name="dev",
        windows=[
            Window(
                "editor",
                panes=[Pane(run="vim")],
                floats=[FloatingPane(pane=Pane(run="htop"), attach_to="logs")],
            ),
            Window("logs", panes=[Pane(run="tail -f x")]),
        ],
    )
    assert ws.build(ConcreteEngine(), preflight=False).ok


def test_unknown_attach_to_raises() -> None:
    """A float attaching to an undeclared window name is rejected."""
    ws = Workspace(
        name="dev",
        windows=[
            Window(
                "editor",
                panes=[Pane(run="vim")],
                floats=[FloatingPane(pane=Pane(run="lazygit"), attach_to="nope")],
            ),
        ],
    )
    with pytest.raises(WorkspaceCompileError, match="names no declared window"):
        compile_workspace(ws)


def test_symbols_resolve_unknown_raises() -> None:
    """Symbols.resolve raises a clear error for an undeclared name."""
    symbols = Symbols()
    with pytest.raises(WorkspaceCompileError, match="names no declared window"):
        symbols.resolve("ghost")


def test_topo_order_orders_dependencies() -> None:
    """_topo_order returns each node after the nodes it depends on."""
    order = _topo_order({"float": {"win"}, "win": set()})
    assert order.index("win") < order.index("float")


def test_topo_order_detects_cycle() -> None:
    """_topo_order rejects a dependency cycle."""
    with pytest.raises(WorkspaceCompileError, match="reference cycle"):
        _topo_order({"a": {"b"}, "b": {"a"}})


def test_offline_build_with_float() -> None:
    """A float-bearing workspace builds over the in-memory engine."""
    from libtmux.experimental.engines import ConcreteEngine

    ws = Workspace(
        name="dev",
        windows=[
            Window(
                "editor",
                panes=[Pane(run="vim")],
                floats=[
                    FloatingPane(
                        pane=Pane(run="lazygit"),
                        geometry=Float(width=120, height=40),
                    ),
                ],
            ),
        ],
    )
    assert ws.build(ConcreteEngine(), preflight=False).ok


def test_events_for_new_pane() -> None:
    """events_for emits a PaneCreated for a new-pane result."""
    from libtmux.experimental.ops import NewPane
    from libtmux.experimental.ops._types import PaneId
    from libtmux.experimental.workspace import PaneCreated
    from libtmux.experimental.workspace.events import events_for

    op = NewPane(target=PaneId("%1"))
    result = op.build_result(returncode=0, stdout=("%9",))
    assert events_for(op, result) == [PaneCreated("%9")]
