"""Tests for the read-seam list operations."""

from __future__ import annotations

import typing as t

from libtmux.experimental.engines import ConcreteEngine
from libtmux.experimental.ops import (
    ListPanes,
    ListSessions,
    ListWindows,
    result_from_dict,
    result_to_dict,
    run,
)
from libtmux.experimental.ops._read import (
    DEFAULT_LIST_VERSION,
    FORMAT_SEPARATOR,
    get_output_format,
)
from libtmux.experimental.ops.results import ListPanesResult

if t.TYPE_CHECKING:
    from libtmux.session import Session


def test_list_panes_template_matches_neo() -> None:
    """The op renders the identical -F template neo would build (no drift)."""
    _fields, fmt = get_output_format("list-panes", "3.6a")
    argv = ListPanes().render(version="3.6a")
    assert "-a" in argv
    assert fmt in argv  # same template, byte for byte


def test_list_panes_parses_rows_into_snapshot_tree() -> None:
    """A synthesized list-panes output parses into a ServerSnapshot tree."""
    fields, _ = get_output_format("list-panes", DEFAULT_LIST_VERSION)

    def row(**values: str) -> str:
        cells = [values.get(name, "") for name in fields]
        return FORMAT_SEPARATOR.join(cells) + FORMAT_SEPARATOR

    stdout = (
        row(session_id="$0", session_name="a", window_id="@1", pane_id="%1"),
        row(session_id="$0", session_name="a", window_id="@1", pane_id="%2"),
    )
    op = ListPanes()
    result = op.build_result(returncode=0, stdout=stdout, version=DEFAULT_LIST_VERSION)

    assert isinstance(result, ListPanesResult)
    assert [p.pane_id for p in result.panes] == ["%1", "%2"]
    assert [s.session_id for s in result.server.sessions] == ["$0"]
    assert [p.pane_id for p in result.server.sessions[0].windows[0].panes] == [
        "%1",
        "%2",
    ]


def test_list_result_serialization_round_trip() -> None:
    """A list result round-trips via its JSON-friendly rows."""
    fields, _ = get_output_format("list-panes", DEFAULT_LIST_VERSION)
    cells = [""] * len(fields)
    cells[fields.index("pane_id")] = "%1"
    line = FORMAT_SEPARATOR.join(cells) + FORMAT_SEPARATOR
    result = ListPanes().build_result(
        returncode=0,
        stdout=(line,),
        version=DEFAULT_LIST_VERSION,
    )
    assert result_from_dict(result_to_dict(result)) == result


def test_empty_output_yields_empty_views() -> None:
    """No panes -> empty rows, empty snapshot, no error."""
    result = run(ListPanes(), ConcreteEngine(), version="3.6a")
    assert result.rows == ()
    assert result.server.sessions == ()
    assert result.ok


def test_list_panes_live(session: Session) -> None:
    """Against real tmux, ListPanes builds a tree containing the fixture pane."""
    from libtmux.experimental.engines import SubprocessEngine

    server = session.server
    engine = SubprocessEngine.for_server(server)

    # No version -> the safe 3.2a-floor template (a field subset valid on any
    # supported tmux); core ids (pane_id/session_id) are always present.
    result = run(ListPanes(), engine)

    assert result.ok
    pane_ids = {p.pane_id for p in result.panes}
    active_pane = session.active_pane
    assert active_pane is not None
    assert active_pane.pane_id in pane_ids
    # the snapshot tree includes the fixture session
    session_ids = {s.session_id for s in result.server.sessions}
    assert session.session_id in session_ids


def test_list_sessions_live(session: Session) -> None:
    """Against real tmux, ListSessions returns the fixture session."""
    from libtmux.experimental.engines import SubprocessEngine

    server = session.server
    engine = SubprocessEngine.for_server(server)
    result = run(ListSessions(), engine)
    assert result.ok
    assert session.session_id in {s.session_id for s in result.sessions}


def test_list_windows_live(session: Session) -> None:
    """Against real tmux, ListWindows returns typed window snapshots."""
    from libtmux.experimental.engines import SubprocessEngine

    server = session.server
    engine = SubprocessEngine.for_server(server)
    result = run(ListWindows(), engine)
    assert result.ok
    assert all(w.window_id.startswith("@") for w in result.windows)
