"""Tests for pure workspace variant expansion."""

from __future__ import annotations

from libtmux.experimental.workspace import Pane, Window, Workspace, expand


def test_expand_renders_variants_without_mutating_base() -> None:
    """Expand returns one rendered workspace per variant and leaves the base pure."""
    base = Workspace(
        name="svc-$app",
        start_directory="${root}/$app",
        environment={"APP": "$app", "UNCHANGED": "$HOME"},
        windows=[
            Window(
                name="$app",
                panes=[
                    Pane(
                        run=["cd ${root}/$app", "$cmd", "echo $(pwd) #{pane_id}"],
                        environment={"APP": "$app"},
                    ),
                ],
            ),
        ],
    )

    expanded = expand(
        base,
        [
            {"app": "api", "cmd": "uvicorn app:app"},
            {"app": "worker", "cmd": "python worker.py"},
        ],
        variables={"root": "/srv"},
    )

    assert [ws.name for ws in expanded] == ["svc-api", "svc-worker"]
    assert expanded[0].start_directory == "/srv/api"
    assert expanded[1].windows[0].name == "worker"
    assert [cmd.cmd for cmd in expanded[0].windows[0].panes[0].commands] == [
        "cd /srv/api",
        "uvicorn app:app",
        "echo $(pwd) #{pane_id}",
    ]
    assert expanded[0].environment == {"APP": "api", "UNCHANGED": "$HOME"}
    assert expanded[0].windows[0].panes[0].environment == {"APP": "api"}
    assert base.name == "svc-$app"
    assert base.windows[0].panes[0].commands[0].cmd == "cd ${root}/$app"


def test_expand_name_callable_controls_workspace_name() -> None:
    """A name callable can build names outside the template strings."""
    base = Workspace(name="dev", windows=[Window("py-$python", panes=[Pane("tox")])])

    expanded = expand(
        base,
        [{"python": "3.12"}, {"python": "3.13"}],
        name=lambda base_name, variant: f"{base_name}-py{variant['python']}",
    )

    assert [ws.name for ws in expanded] == ["dev-py3.12", "dev-py3.13"]
    assert [ws.windows[0].name for ws in expanded] == ["py-3.12", "py-3.13"]


def test_expand_empty_variants_returns_empty_tuple() -> None:
    """No variants means no expanded workspaces."""
    assert expand(Workspace(name="dev"), []) == ()
