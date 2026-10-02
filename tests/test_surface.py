"""Tests for :mod:`libtmux._surface`: the supported public surface."""

from __future__ import annotations

import typing as t

import pytest

from libtmux import exc
from libtmux._surface import REMOVED

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session

EXPECTED_REMOVED = {
    "Server": {
        "kill_server",
        "_list_panes",
        "_update_panes",
        "get_by_id",
        "where",
        "find_where",
        "_list_windows",
        "_update_windows",
        "_sessions",
        "_list_sessions",
        "list_sessions",
        "children",
    },
    "Session": {
        "attached_pane",
        "attached_window",
        "attach_session",
        "kill_session",
        "get",
        "get_by_id",
        "where",
        "find_where",
        "_list_windows",
        "_windows",
        "list_windows",
        "children",
    },
    "Window": {
        "split_window",
        "attached_pane",
        "select_window",
        "kill_window",
        "get",
        "get_by_id",
        "where",
        "find_where",
        "_list_panes",
        "_panes",
        "list_panes",
        "children",
    },
    "Pane": {"select_pane", "split_window", "get", "resize_pane"},
}


def test_removed_table_keeps_every_removed_name() -> None:
    """Dropping a table row would turn a removed name into AttributeError."""
    assert {cls: set(names) for cls, names in REMOVED.items()} == EXPECTED_REMOVED


REMOVED_CASES = [
    pytest.param(cls_name, name, id=f"{cls_name}.{name}")
    for cls_name, names in REMOVED.items()
    for name in names
]


def _instance(cls_name: str, server: Server, session: Session) -> t.Any:
    window = session.active_window
    return {
        "Server": server,
        "Session": session,
        "Window": window,
        "Pane": window.active_pane,
    }[cls_name]


@pytest.mark.parametrize(("cls_name", "name"), REMOVED_CASES)
def test_removed_name_raises_and_is_not_listed(
    cls_name: str,
    name: str,
    server: Server,
    session: Session,
) -> None:
    """A removed name raises on access, and neither the class nor dir() has it."""
    obj = _instance(cls_name, server, session)
    assert name not in dir(obj)
    assert name not in vars(type(obj))
    with pytest.raises(exc.DeprecatedError, match="was deprecated"):
        getattr(obj, name)


def test_unknown_name_is_an_attribute_error(session: Session) -> None:
    """A name that was never part of the API stays an AttributeError."""
    with pytest.raises(AttributeError, match="no attribute 'nope'"):
        _ = session.nope  # type: ignore[attr-defined]


def test_property_attribute_error_is_not_masked(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An AttributeError raised inside a property keeps its own message."""

    def boom(self: Session) -> t.NoReturn:
        msg = "inner failure"
        raise AttributeError(msg)

    monkeypatch.setattr(type(session), "active_window", property(boom))
    with pytest.raises(AttributeError, match="inner failure"):
        _ = session.active_window


def test_dir_lists_owned_fields_and_hides_the_rest(
    server: Server,
    session: Session,
) -> None:
    """dir() lists a class's own fields; out-of-scope fields stay readable."""
    window = session.active_window
    pane = window.active_pane
    assert pane is not None
    pane_names, window_names, session_names = dir(pane), dir(window), dir(session)

    assert {"pane_width", "pane_id", "window_id", "session_name"} <= set(pane_names)
    assert "window_width" in window_names
    assert "session_windows" in session_names

    for hidden in ("client_name", "version", "mouse_x", "buffer_name"):
        assert hidden not in pane_names
    assert "pane_width" not in window_names
    assert "pane_width" not in session_names
    assert "window_width" not in session_names
    assert "session_windows" not in window_names

    # Hidden is not removed: the field is still a plain attribute.
    assert pane.client_name is None
    width: str | None = pane.pane_width
    assert width is not None


@pytest.mark.parametrize(
    ("cls_name", "limit"),
    [("Server", 80), ("Session", 70), ("Window", 90), ("Pane", 150)],
)
def test_dir_stays_within_budget(
    cls_name: str,
    limit: int,
    server: Server,
    session: Session,
) -> None:
    """Public names per object stay under a ceiling (was 84, 230, 238, 252)."""
    obj = _instance(cls_name, server, session)
    public = [name for name in dir(obj) if not name.startswith("_")]
    assert len(public) <= limit
