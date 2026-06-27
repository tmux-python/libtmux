"""Tests for the ``new-pane`` (floating pane) operation."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.common import has_gte_version
from libtmux.experimental.ops import (
    NewPane,
    operation_from_dict,
    operation_to_dict,
    registry,
    result_from_dict,
    result_to_dict,
    run,
)
from libtmux.experimental.ops._types import PaneId
from libtmux.experimental.ops.exc import VersionUnsupported

if t.TYPE_CHECKING:
    from libtmux.session import Session


class RenderCase(t.NamedTuple):
    """A ``NewPane`` op and the exact argv it renders."""

    test_id: str
    op: NewPane
    expected: tuple[str, ...]


RENDER_CASES = (
    RenderCase(
        test_id="geometry",
        op=NewPane(target=PaneId("%1"), width=80, height=15, x=5, y=3),
        expected=(
            "new-pane",
            "-t",
            "%1",
            "-x80",
            "-y15",
            "-X5",
            "-Y3",
            "-d",
            "-P",
            "-F",
            "#{pane_id}",
        ),
    ),
    RenderCase(
        test_id="percentage_zoom",
        op=NewPane(target=PaneId("%1"), width="50%", height="40%", zoom=True),
        expected=(
            "new-pane",
            "-t",
            "%1",
            "-x50%",
            "-y40%",
            "-Z",
            "-d",
            "-P",
            "-F",
            "#{pane_id}",
        ),
    ),
    RenderCase(
        test_id="attach_no_detach",
        op=NewPane(target=PaneId("%1"), width=80, height=15, detach=False),
        expected=(
            "new-pane",
            "-t",
            "%1",
            "-x80",
            "-y15",
            "-P",
            "-F",
            "#{pane_id}",
        ),
    ),
    RenderCase(
        test_id="styles_env_shell",
        op=NewPane(
            target=PaneId("%1"),
            start_directory="/tmp",
            environment={"E": "1"},
            style="bg=default",
            active_border_style="fg=magenta",
            inactive_border_style="fg=cyan",
            message="done",
            empty=True,
            shell_command="lazygit",
        ),
        expected=(
            "new-pane",
            "-t",
            "%1",
            "-d",
            "-c/tmp",
            "-eE=1",
            "-sbg=default",
            "-Sfg=magenta",
            "-Rfg=cyan",
            "-mdone",
            "-E",
            "-P",
            "-F",
            "#{pane_id}",
            "lazygit",
        ),
    ),
)


@pytest.mark.parametrize(
    list(RenderCase._fields),
    RENDER_CASES,
    ids=[c.test_id for c in RENDER_CASES],
)
def test_new_pane_render(
    test_id: str,
    op: NewPane,
    expected: tuple[str, ...],
) -> None:
    """Each ``NewPane`` configuration renders the exact tmux argv."""
    assert op.render() == expected


@pytest.mark.parametrize(
    list(RenderCase._fields),
    RENDER_CASES,
    ids=[c.test_id for c in RENDER_CASES],
)
def test_new_pane_round_trips(
    test_id: str,
    op: NewPane,
    expected: tuple[str, ...],
) -> None:
    """The op and its result round-trip through dicts."""
    assert operation_from_dict(operation_to_dict(op)) == op
    result = op.build_result(returncode=0, stdout=("%2",))
    assert result_from_dict(result_to_dict(result)) == result


def test_new_pane_is_registered() -> None:
    """``NewPane`` is discoverable in the operation registry by kind."""
    assert "new_pane" in registry
    assert registry.operation("new_pane") is NewPane


def test_new_pane_captures_new_pane_id() -> None:
    """new-pane parses the captured pane id into the typed result."""
    result = NewPane(target=PaneId("%1")).build_result(returncode=0, stdout=("%2",))
    assert result.new_pane_id == "%2"
    assert result.created_id == "%2"


def test_new_pane_requires_tmux_3_7() -> None:
    """Rendering against tmux older than 3.7 raises (the spine's first gate)."""
    op = NewPane(target=PaneId("%1"), width=80, height=15)
    with pytest.raises(VersionUnsupported, match=r"requires tmux >= 3.7"):
        op.render(version="3.6")


def test_new_pane_renders_on_supported_version() -> None:
    """No version (latest) or tmux >= 3.7 renders without error."""
    op = NewPane(target=PaneId("%1"), width=80, height=15)
    assert op.render()[0] == "new-pane"
    assert op.render(version="3.7")[0] == "new-pane"


@pytest.mark.skipif(
    not has_gte_version("3.7"),
    reason="new-pane (floating panes) requires tmux 3.7+",
)
def test_new_pane_live(session: Session) -> None:
    """new-pane creates a real floating pane against tmux 3.7+."""
    from libtmux.experimental.engines import SubprocessEngine

    engine = SubprocessEngine.for_server(session.server)
    pane = session.active_pane
    assert pane is not None and pane.pane_id is not None

    result = run(
        NewPane(target=PaneId(pane.pane_id), width=40, height=10, x=5, y=3),
        engine,
    )
    assert result.ok
    assert result.new_pane_id is not None
    assert session.server.panes.get(pane_id=result.new_pane_id) is not None

    floating = session.server.cmd(
        "display-message",
        "-p",
        "-t",
        result.new_pane_id,
        "#{pane_floating_flag}",
    )
    assert floating.stdout == ["1"]
