"""Tests for floating-pane declarations in the workspace IR (tmux 3.7+)."""

from __future__ import annotations

from libtmux.experimental.workspace import (
    Float,
    FloatingPane,
    Pane,
    Window,
    Workspace,
    analyze,
)


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
