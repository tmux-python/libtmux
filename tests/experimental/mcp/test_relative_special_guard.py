"""The relative-special-target guard and the composed relative tools.

``capture_pane`` / ``grep_pane`` / ``send_input`` must reject a directional
special target (``{up-of}`` …) with a hint -- those resolve against this MCP's
control client, not the caller. Anchor specials (``{marked}`` / ``{last}``) must
still pass through. The composed ``capture_relative_pane`` resolves the neighbour
to a concrete ``%N`` first (live).
"""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.engines import ConcreteEngine, SubprocessEngine
from libtmux.experimental.mcp.vocabulary import (
    break_pane,
    capture_pane,
    capture_relative_pane,
    create_session,
    grep_pane,
    join_pane,
    kill_pane,
    kill_session,
    resize_pane,
    respawn_pane,
    select_pane,
    send_input,
    split_pane,
    swap_pane,
)

fastmcp = pytest.importorskip("fastmcp")
from fastmcp.exceptions import ToolError  # noqa: E402 - after importorskip

if t.TYPE_CHECKING:
    from libtmux.session import Session


@pytest.mark.parametrize("token", ["{up-of}", "{down-of}", "{left-of}", "{right-of}"])
def test_grep_rejects_relative_special(token: str) -> None:
    """grep_pane with a directional special target raises a targeted hint."""
    with pytest.raises(ToolError, match="control-mode client"):
        grep_pane(ConcreteEngine(capture_lines=("x",)), token, "x")


def test_capture_rejects_relative_special() -> None:
    """capture_pane rejects a directional special target."""
    with pytest.raises(ToolError, match="control-mode client"):
        capture_pane(ConcreteEngine(), "{down-of}")


def test_send_rejects_relative_special() -> None:
    """send_input rejects a directional special target."""
    with pytest.raises(ToolError, match="control-mode client"):
        send_input(ConcreteEngine(), "{left-of}", "ls")


@pytest.mark.parametrize("token", ["{marked}", "{last}"])
def test_anchor_specials_pass_through(token: str) -> None:
    """Anchor special targets are not rejected (real tmux semantics)."""
    engine = ConcreteEngine(capture_lines=("hi",))
    assert capture_pane(engine, token).lines == ("hi",)


@pytest.mark.parametrize(
    "call",
    [
        lambda e: kill_pane(e, "{up-of}"),
        lambda e: resize_pane(e, "{up-of}", width=80),
        lambda e: respawn_pane(e, "{up-of}"),
        lambda e: swap_pane(e, "{up-of}", "%1"),
        lambda e: swap_pane(e, "%1", "{up-of}"),
        lambda e: join_pane(e, "{up-of}", "%1"),
        lambda e: break_pane(e, "{up-of}"),
        lambda e: select_pane(e, "{up-of}"),
    ],
    ids=[
        "kill",
        "resize",
        "respawn",
        "swap_src",
        "swap_dst",
        "join",
        "break",
        "select",
    ],
)
def test_mutating_tools_reject_relative_special(call: t.Any) -> None:
    """Destructive/mutating pane tools reject a relative special target too."""
    with pytest.raises(ToolError, match="control-mode client"):
        call(ConcreteEngine())


def test_grep_pane_invalid_regex_hint() -> None:
    """An invalid search regex is surfaced as a targeted hint, not a raw re.error."""
    with pytest.raises(ToolError, match="invalid search pattern"):
        grep_pane(ConcreteEngine(capture_lines=("x",)), "%1", "[unclosed")


def test_capture_relative_pane_resolves_concrete_live(session: Session) -> None:
    """capture_relative_pane resolves a neighbour to a concrete %N and captures it."""
    engine = SubprocessEngine.for_server(session.server)
    created = create_session(engine, name="relcap")
    try:
        origin = created.first_pane_id
        assert origin is not None
        split_pane(engine, origin, horizontal=True)
        captured = None
        for direction in ("left", "right"):
            try:
                captured = capture_relative_pane(engine, direction, origin)
                break
            except ToolError:
                continue  # no neighbour that way; try the other side
        assert captured is not None  # resolved a concrete pane and captured it
    finally:
        kill_session(engine, created.session_id)
