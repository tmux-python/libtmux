"""Tests for the typed ``obj.typed`` view of numeric and flag fields."""

from __future__ import annotations

import inspect
import re
import typing as t

import pytest

from libtmux import exc
from libtmux.fields import ClientFields, ObjFields, _Field
from libtmux.neo import FIELD_VERSION, Obj
from libtmux.pane import Pane

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session


def _descriptors(cls: type) -> dict[str, _Field[t.Any]]:
    return {
        name: value
        for klass in reversed(cls.__mro__)
        for name, value in vars(klass).items()
        if isinstance(value, _Field)
    }


def test_every_typed_field_is_a_dataclass_field() -> None:
    """The view names no field that Obj does not declare."""
    assert set(_descriptors(ClientFields)) <= set(Obj.__dataclass_fields__)


def test_version_gated_fields_are_optional() -> None:
    """A field tmux gained after 3.2a cannot be required on 3.2a."""
    required = {n for n, d in _descriptors(ObjFields).items() if d._required}
    assert required.isdisjoint(FIELD_VERSION)


def test_every_documented_flag_has_a_typed_flag() -> None:
    """A new ``"1"``-when field in the Obj docstring must get a typed flag."""
    doc = inspect.getdoc(Obj) or ""
    flag_doc = re.compile(
        r'^(\w+) : str \| None\n {4}``"1"`` (?:when|while)',
        re.MULTILINE,
    )
    flags = set(flag_doc.findall(doc))
    typed = set(_descriptors(ClientFields))
    assert flags - typed == set(), "document-only flag without a typed accessor"


def test_typed_fields_parse_on_a_live_server(session: Session) -> None:
    """Every typed accessor reads a live pane, window, and session."""
    window = session.new_window(window_shell="cat")
    window.split(shell="cat")
    pane = window.active_pane
    for obj in (pane, window, session):
        for name, desc in _descriptors(ObjFields).items():
            value = getattr(obj.typed, name)
            if desc._required:
                assert value is not None, name
            assert value is None or isinstance(value, (int, bool)), name
    assert type(pane.typed.pane_active) is bool
    assert type(pane.typed.pane_width) is int
    assert pane.typed.pane_width == int(pane.pane_width or "")
    window.refresh()
    assert window.typed.window_panes == 2
    assert pane.typed.pane_dead is False
    assert pane.typed.pane_dead_status is None


def test_typed_view_follows_refresh(session: Session) -> None:
    """The view reads current values, so it follows ``refresh()``."""
    window = session.new_window(window_shell="cat")
    view = window.typed
    assert view.window_panes == 1

    window.split(shell="cat")
    assert view.window_panes == 1
    window.refresh()
    assert view.window_panes == 2


def test_dead_pane_reports_exit_status(server: Server, session: Session) -> None:
    """A dead pane has a flag and an exit status; a live one has no status."""
    server.cmd("set-option", "-g", "remain-on-exit", "on")
    window = session.new_window(window_shell="sh -c 'exit 3'")
    pane = window.active_pane

    from libtmux.test.retry import retry_until

    def is_dead() -> bool:
        pane.refresh()
        return pane.typed.pane_dead

    assert retry_until(is_dead)
    assert pane.typed.pane_dead_status == 3


def test_unlisted_object_raises_field_not_reported(server: Server) -> None:
    """A hand-built object has no fields; required reads raise, optional give None."""
    pane = Pane(server=server, pane_id="%999")

    with pytest.raises(exc.FieldNotReported, match="pane_width") as excinfo:
        _ = pane.typed.pane_width
    assert excinfo.value.field == "pane_width"
    with pytest.raises(exc.FieldNotReported):
        _ = pane.typed.pane_active
    assert pane.typed.pane_dead_status is None
    assert pane.typed.pane_x is None


def test_client_view_reads_client_and_pane_fields(
    control_mode: t.Callable[..., t.Any],
    server: Server,
    session: Session,
) -> None:
    """``Client.typed`` adds the ``client_*`` fields to the pane view."""
    with control_mode() as ctl:
        client = server.clients.get(client_name=ctl.client_name)
        assert isinstance(client.typed, ClientFields)
        assert client.typed.pane_width == session.active_pane.typed.pane_width
        pid = client.typed.client_pid
        assert pid is None or isinstance(pid, int)
        assert isinstance(client.typed.client_control_mode, (bool, type(None)))
