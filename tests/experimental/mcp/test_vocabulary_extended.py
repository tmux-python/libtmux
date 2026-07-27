"""Extended vocabulary -- new verbs, conveniences, the async surface, the bridge.

Pure tests run against the in-memory ``MockEngine`` and the pure geometry
helpers (no tmux); live tests drive a real tmux server for the geometry-resolved
conveniences (``resolve_relative_pane`` / ``find_pane_by_position`` / directional
``select_pane``) that only mean something against a real layout.
"""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux.experimental.engines import MockEngine, SubprocessEngine
from libtmux.experimental.mcp.vocabulary import (
    PaneRef,
    acreate_session,
    agrep_pane,
    capture_active_pane,
    create_session,
    grep_pane,
    has_session,
    resize_pane,
    resolve_relative_pane,
    run_tmux,
    select_pane,
)
from libtmux.experimental.mcp.vocabulary._bridge import (
    SyncToAsyncEngine,
    drive_sync,
    synced,
)
from libtmux.experimental.mcp.vocabulary._geometry import (
    PaneBox,
    corner_pane,
    neighbor,
    parse_boxes,
)

if t.TYPE_CHECKING:
    from libtmux.session import Session


# --------------------------------------------------------------------------- #
# Geometry helpers (pure)
# --------------------------------------------------------------------------- #
def _two_columns() -> list[PaneBox]:
    """Build a left|right two-pane layout."""
    return parse_boxes(
        [
            {
                "pane_id": "%1",
                "pane_left": "0",
                "pane_top": "0",
                "pane_right": "39",
                "pane_bottom": "23",
                "pane_at_left": "1",
                "pane_at_top": "1",
                "pane_at_bottom": "1",
                "pane_at_right": "0",
            },
            {
                "pane_id": "%2",
                "pane_left": "41",
                "pane_top": "0",
                "pane_right": "80",
                "pane_bottom": "23",
                "pane_at_left": "0",
                "pane_at_top": "1",
                "pane_at_bottom": "1",
                "pane_at_right": "1",
            },
        ],
    )


def test_neighbor_resolves_horizontal() -> None:
    """The right neighbour of the left pane is the right pane, and vice versa."""
    boxes = _two_columns()
    assert neighbor(boxes, "%1", "right") == "%2"
    assert neighbor(boxes, "%2", "left") == "%1"


def test_neighbor_none_when_no_pane_that_way() -> None:
    """A pane with no neighbour in a direction resolves to None."""
    boxes = _two_columns()
    assert neighbor(boxes, "%1", "left") is None
    assert neighbor(boxes, "%1", "up") is None
    assert neighbor(boxes, "%9", "right") is None  # unknown origin


def test_corner_pane_uses_edge_predicates() -> None:
    """The corner finder composes the pane_at_* predicates."""
    boxes = _two_columns()
    assert corner_pane(boxes, "top-left") == "%1"
    assert corner_pane(boxes, "bottom-right") == "%2"


# --------------------------------------------------------------------------- #
# The sync bridge
# --------------------------------------------------------------------------- #
def test_synced_twin_runs_over_sync_engine() -> None:
    """A synced twin drives its async source over a plain sync engine."""
    result = create_session(MockEngine(), name="dev")  # create_session is a twin
    assert result.session_id == "$1"


def test_drive_sync_rejects_real_io() -> None:
    """drive_sync refuses a coroutine that suspends on a real await."""

    async def suspends() -> int:
        await asyncio.sleep(0)  # yields to the loop -- no loop here
        return 1

    with pytest.raises(RuntimeError, match="real I/O"):
        drive_sync(suspends())


def test_synced_preserves_callable() -> None:
    """synced() yields a callable with the engine param retyped to sync."""

    async def tool(engine: t.Any, value: int) -> int:
        return value

    twin = synced(tool)
    hints = t.get_type_hints(twin)
    assert hints["engine"].__name__ == "TmuxEngine"


# --------------------------------------------------------------------------- #
# New verbs / conveniences (offline)
# --------------------------------------------------------------------------- #
def test_grep_pane_filters_lines() -> None:
    """grep_pane returns only the captured lines matching the pattern."""
    engine = MockEngine(capture_lines=("foo", "bar baz", "foobar"))
    assert grep_pane(engine, "%1", "foo").lines == ("foo", "foobar")


def test_grep_pane_ignore_case() -> None:
    """grep_pane honours the ignore_case flag."""
    engine = MockEngine(capture_lines=("FOO", "bar"))
    assert grep_pane(engine, "%1", "foo", ignore_case=True).lines == ("FOO",)


def test_capture_active_pane_needs_no_target() -> None:
    """capture_active_pane captures with no explicit target."""
    engine = MockEngine(capture_lines=("hello",))
    assert capture_active_pane(engine).lines == ("hello",)


def test_resize_and_run_tmux_offline() -> None:
    """resize_pane is fire-and-forget; run_tmux returns a raw outcome."""
    engine = MockEngine()
    assert resize_pane(engine, "%1", width=80) is None
    raw = run_tmux(engine, ["list-sessions"])
    assert raw.ok and raw.returncode == 0


def test_has_session_returns_bool() -> None:
    """has_session answers an existence query as a bool."""
    assert has_session(MockEngine(), "$1") is True


def test_geometry_tools_return_paneref_offline() -> None:
    """Geometry-resolved tools return a PaneRef even with nothing to resolve."""
    engine = MockEngine()
    assert isinstance(resolve_relative_pane(engine, "right", "%1"), PaneRef)
    assert isinstance(select_pane(engine, "%1", direction="left"), PaneRef)


# --------------------------------------------------------------------------- #
# The async surface
# --------------------------------------------------------------------------- #
def test_async_surface_over_wrapped_engine() -> None:
    """The a-prefixed tools run over an async engine (sync engine wrapped)."""

    async def main() -> tuple[str, tuple[str, ...]]:
        engine = SyncToAsyncEngine(MockEngine(capture_lines=("x", "y")))
        session = await acreate_session(engine, name="dev")
        grep = await agrep_pane(engine, "%1", "x")
        return session.session_id, grep.lines

    session_id, lines = asyncio.run(main())
    assert session_id == "$1"
    assert lines == ("x",)


# --------------------------------------------------------------------------- #
# Live geometry conveniences
# --------------------------------------------------------------------------- #
def test_resolve_relative_pane_live(session: Session) -> None:
    """resolve_relative_pane finds the adjacent pane in a real split layout."""
    engine = SubprocessEngine.for_server(session.server)
    created = create_session(engine, name="reltest")
    try:
        origin = created.first_pane_id
        assert origin is not None
        other = split_pane_id(engine, origin)
        # Exactly one of left/right of the origin is the new pane.
        found = {
            resolve_relative_pane(engine, "left", origin).pane_id,
            resolve_relative_pane(engine, "right", origin).pane_id,
        }
        assert other in found
    finally:
        kill(engine, created.session_id)


def test_find_pane_by_position_live(session: Session) -> None:
    """find_pane_by_position returns a real pane occupying the corner."""
    from libtmux.experimental.mcp.vocabulary import find_pane_by_position, list_panes

    engine = SubprocessEngine.for_server(session.server)
    created = create_session(engine, name="corner")
    try:
        origin = created.first_pane_id
        assert origin is not None
        split_pane_id(engine, origin)
        ids = {
            row["pane_id"]
            for row in list_panes(engine).rows
            if row.get("session_id") == created.session_id
        }
        corner = find_pane_by_position(engine, "top-left", origin).pane_id
        assert corner in ids
    finally:
        kill(engine, created.session_id)


def split_pane_id(engine: SubprocessEngine, target: str) -> str:
    """Split *target* horizontally and return the new pane id (test helper)."""
    from libtmux.experimental.mcp.vocabulary import split_pane

    return split_pane(engine, target, horizontal=True).pane_id


def kill(engine: SubprocessEngine, session_id: str) -> None:
    """Kill a test session (helper)."""
    from libtmux.experimental.mcp.vocabulary import kill_session

    kill_session(engine, session_id)
