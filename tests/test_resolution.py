"""Point lookups resolve through tmux, not through a server-wide scan.

:meth:`~libtmux.Pane.from_pane_id`, :meth:`~libtmux.Window.from_window_id` and
both ``refresh()`` methods name the object with ``-t`` and let tmux's
``cmd_find`` resolve it.

The difference only shows on a *linked* window -- one window that lives in more
than one session at once. ``list-panes -a`` emits such a pane once per holding
session, ordered by session name, and picking a row out of that listing answers
with whichever session happens to sort last. Targeting the id instead hands the
question to tmux, which answers with the session it would itself act on.
"""

from __future__ import annotations

import typing as t

import pytest

from libtmux import exc
from libtmux._internal.query_list import ObjectDoesNotExist
from libtmux.pane import Pane
from libtmux.window import Window

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session


def tmux_resolves_to(server: Server, target: str) -> str:
    """Ask tmux which session it would act on for *target*."""
    return server.cmd("display-message", "-p", "-t", target, "#{session_id}").stdout[0]


def link_window_into_second_session(server: Server) -> tuple[Window, Session, Session]:
    """Link one window into two sessions, name-order fighting activity-order.

    ``zzz-old`` is created first, so it sorts *last* by name but is the *least*
    recently active. ``aaa-recent`` sorts first and is the most recently active.
    A resolver that reads the last row of a ``list-* -a`` listing answers
    ``zzz-old``; tmux answers ``aaa-recent``.
    """
    old = server.new_session(session_name="zzz-old")
    recent = server.new_session(session_name="aaa-recent")

    window = old.active_window
    assert window.window_id is not None
    assert recent.session_name is not None

    server.cmd("link-window", "-s", window.window_id, "-t", recent.session_name)

    return window, old, recent


def test_linked_window_resolves_like_tmux(server: Server) -> None:
    """:meth:`Window.from_window_id` answers with tmux's own session."""
    window, old, recent = link_window_into_second_session(server)
    assert window.window_id is not None

    canonical = tmux_resolves_to(server, window.window_id)
    resolved = Window.from_window_id(server=server, window_id=window.window_id)

    assert resolved.session_id == canonical
    assert resolved.session_id == recent.session_id
    assert resolved.session_id != old.session_id, (
        "'zzz-old' sorts last by name -- resolving from a `list-windows -a` "
        "listing would answer with it"
    )


def test_linked_pane_resolves_like_tmux(server: Server) -> None:
    """:meth:`Pane.from_pane_id` answers with tmux's own session."""
    window, old, recent = link_window_into_second_session(server)
    pane = window.active_pane
    assert pane is not None
    assert pane.pane_id is not None

    canonical = tmux_resolves_to(server, pane.pane_id)
    resolved = Pane.from_pane_id(server=server, pane_id=pane.pane_id)

    assert resolved.session_id == canonical
    assert resolved.session_id == recent.session_id
    assert resolved.session_id != old.session_id


def test_pane_session_follows_move_window(server: Server) -> None:
    """A :class:`Pane` held across a ``move-window`` still finds its session.

    :attr:`Pane.session` resolves through :attr:`Pane.window`, which re-queries
    tmux. Answering from the pane's own cached ``session_id`` would be one
    subprocess cheaper and would break here: tmux destroys a session when its
    last window leaves, so the cached id names a session that no longer exists.
    """
    origin = server.new_session(session_name="origin")
    destination = server.new_session(session_name="destination")

    window = origin.active_window
    pane = window.active_pane  # captured *before* the move
    assert pane is not None

    window.move_window(destination="99", session=destination.session_id)

    assert pane.session.session_id == destination.session_id
    assert pane.window.session_id == destination.session_id


class RefreshAfterKillFixture(t.NamedTuple):
    """A live object, killed out from under a ``refresh()``."""

    test_id: str
    kind: str


REFRESH_AFTER_KILL_FIXTURES: list[RefreshAfterKillFixture] = [
    RefreshAfterKillFixture(test_id="window", kind="window"),
    RefreshAfterKillFixture(test_id="pane", kind="pane"),
]


@pytest.mark.parametrize(
    list(RefreshAfterKillFixture._fields),
    REFRESH_AFTER_KILL_FIXTURES,
    ids=[test.test_id for test in REFRESH_AFTER_KILL_FIXTURES],
)
def test_refresh_after_kill_raises_object_does_not_exist(
    session: Session,
    test_id: str,
    kind: str,
) -> None:
    """A gone object still raises :exc:`~libtmux.exc.TmuxObjectDoesNotExist`.

    tmux reports an unknown ``-t`` target on stderr rather than by returning an
    empty listing, so the raised error has to be translated back.
    """
    window = session.new_window(window_name="doomed")
    target: Window | Pane
    if kind == "window":
        target = window
    else:
        pane = window.split()
        target = pane
        pane.kill()

    if kind == "window":
        window.kill()

    with pytest.raises(ObjectDoesNotExist):
        target.refresh()


def test_missing_pane_on_live_server_raises_object_does_not_exist(
    server: Server,
    session: Session,
) -> None:
    """A pane id that never existed is a missing object, not a broken server."""
    with pytest.raises(exc.TmuxObjectDoesNotExist):
        Pane.from_pane_id(server=server, pane_id="%99999")


def test_dead_server_raises_libtmux_exception(
    server: Server,
    session: Session,
) -> None:
    """A dead server is a different failure from a missing object.

    :exc:`~libtmux.exc.TmuxObjectDoesNotExist` would tell the caller the pane is
    gone, when in fact nothing can be known -- the daemon is not answering.
    """
    pane = session.active_pane
    assert pane is not None
    assert pane.pane_id is not None
    pane_id = pane.pane_id

    server.kill()

    with pytest.raises(exc.LibTmuxException) as excinfo:
        Pane.from_pane_id(server=server, pane_id=pane_id)

    assert not isinstance(excinfo.value, ObjectDoesNotExist)
