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

from libtmux import exc, neo, window as window_module
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


def tmux_resolves_index_to(server: Server, target: str) -> str:
    """Ask tmux which window index it would act on for *target*."""
    result = server.cmd("display-message", "-p", "-t", target, "#{window_index}")
    return result.stdout[0]


def link_window_twice_into_one_session(server: Server) -> tuple[Window, Session]:
    """Link one window into a *single* session at two indexes.

    ``dup`` ends up holding ``@0`` at index 1 and again at index 5, plus an
    unrelated window at index 2 to park the cursor on. Two winlinks, one window,
    one session -- so scoping the listing with ``-t`` does not narrow it to one
    row, and a resolver reading the last row answers 5.
    """
    dup = server.new_session(session_name="dup")

    window = dup.active_window
    assert window.window_id is not None

    dup.new_window(window_name="other", attach=False)
    server.cmd("link-window", "-d", "-s", window.window_id, "-t", "dup:5")

    return window, dup


class WinlinkFixture(t.NamedTuple):
    """A window reachable at more than one winlink."""

    test_id: str
    shape: str
    #: Window index to make current before resolving, if any.
    select: str | None
    #: Sessions the window should be reachable from.
    expected_holders: int


WINLINK_FIXTURES: list[WinlinkFixture] = [
    WinlinkFixture(
        test_id="same_session_low_link_current",
        shape="same-session",
        select="dup:1",
        expected_holders=1,
    ),
    WinlinkFixture(
        test_id="same_session_high_link_current",
        shape="same-session",
        select="dup:5",
        expected_holders=1,
    ),
    WinlinkFixture(
        test_id="same_session_other_window_current",
        shape="same-session",
        select="dup:2",
        expected_holders=1,
    ),
    WinlinkFixture(
        test_id="cross_session",
        shape="cross-session",
        select=None,
        expected_holders=2,
    ),
    WinlinkFixture(
        test_id="grouped_session",
        shape="grouped",
        select=None,
        expected_holders=2,
    ),
]


def build_winlink_shape(server: Server, shape: str) -> Window:
    """Create *shape* and hand back the multiply-linked window."""
    if shape == "same-session":
        window, _dup = link_window_twice_into_one_session(server)
        return window
    if shape == "cross-session":
        window, _old, _recent = link_window_into_second_session(server)
        return window
    if shape == "grouped":
        # ``new-session -t`` is a grouped session: it shares the origin's
        # windows. This is what tmuxp's session groups are built on.
        origin = server.new_session(session_name="origin")
        server.cmd("new-session", "-d", "-t", "origin", "-s", "grouped")
        return origin.active_window
    msg = f"unknown shape: {shape}"
    raise AssertionError(msg)


@pytest.mark.parametrize(
    list(WinlinkFixture._fields),
    WINLINK_FIXTURES,
    ids=[test.test_id for test in WINLINK_FIXTURES],
)
def test_multiply_linked_window_resolves_like_tmux(
    server: Server,
    test_id: str,
    shape: str,
    select: str | None,
    expected_holders: int,
) -> None:
    """A window at several winlinks resolves to the one tmux would act on.

    tmux's rule, from ``cmd_find_best_winlink_with_window`` in ``cmd-find.c``:
    "the current if it contains the window, otherwise the first". Reading the
    last row of the listing instead answers with the highest index, which is
    what libtmux did.
    """
    window = build_winlink_shape(server, shape)
    assert window.window_id is not None

    if select is not None:
        server.cmd("select-window", "-t", select)

    canonical_session = tmux_resolves_to(server, window.window_id)
    canonical_index = tmux_resolves_index_to(server, window.window_id)

    resolved = Window.from_window_id(server=server, window_id=window.window_id)
    assert resolved.window_index == canonical_index
    assert resolved.session_id == canonical_session

    window.refresh()
    assert window.window_index == canonical_index
    assert window.session_id == canonical_session

    assert len(window.linked_sessions) == expected_holders


def test_same_session_double_link_answers_the_low_index(server: Server) -> None:
    """The regression in its narrowest form: tmux says 1, libtmux said 5."""
    window, _dup = link_window_twice_into_one_session(server)
    assert window.window_id is not None

    server.cmd("select-window", "-t", "dup:1")

    assert tmux_resolves_index_to(server, window.window_id) == "1"
    assert Window.from_window_id(server, window.window_id).window_index == "1"


def test_pane_of_multiply_linked_window_agrees_with_its_window(server: Server) -> None:
    """:meth:`Pane.from_pane_id` and :meth:`Window.from_window_id` do not disagree.

    ``list-panes`` emits each pane once, so the pane side was already right. The
    point is that the window side now matches it.
    """
    window, _dup = link_window_twice_into_one_session(server)
    pane = window.active_pane
    assert pane is not None
    assert pane.pane_id is not None
    assert window.window_id is not None

    server.cmd("select-window", "-t", "dup:1")

    resolved_pane = Pane.from_pane_id(server=server, pane_id=pane.pane_id)
    resolved_window = Window.from_window_id(server=server, window_id=window.window_id)

    assert resolved_pane.window_index == resolved_window.window_index
    assert resolved_pane.window_index == tmux_resolves_index_to(server, pane.pane_id)


@pytest.mark.parametrize(
    list(WinlinkFixture._fields),
    WINLINK_FIXTURES,
    ids=[test.test_id for test in WINLINK_FIXTURES],
)
def test_server_collections_enumerate_winlinks(
    server: Server,
    test_id: str,
    shape: str,
    select: str | None,
    expected_holders: int,
) -> None:
    """A server-wide listing yields one row per winlink, and that is the truth.

    :attr:`Server.panes` and :attr:`Server.windows` list with ``-a``, which tmux
    answers with one row per ``(session, index, window)`` edge. A window at two
    winlinks therefore appears twice -- it really is reachable two ways.
    """
    window = build_winlink_shape(server, shape)
    assert window.window_id is not None
    pane = window.active_pane
    assert pane is not None
    assert pane.pane_id is not None

    window_rows = server.windows.filter(window_id=window.window_id)
    pane_rows = server.panes.filter(pane_id=pane.pane_id)

    assert len(window_rows) == 2
    assert len(pane_rows) == 2

    # Every row names the same window, at a different winlink.
    assert {row.window_id for row in window_rows} == {window.window_id}
    winlinks = {(row.session_id, row.window_index) for row in window_rows}
    assert len(winlinks) == 2


@pytest.mark.parametrize(
    list(WinlinkFixture._fields),
    WINLINK_FIXTURES,
    ids=[test.test_id for test in WINLINK_FIXTURES],
)
def test_ambiguous_point_lookup_is_catchable_and_legible(
    server: Server,
    test_id: str,
    shape: str,
    select: str | None,
    expected_holders: int,
) -> None:
    """An ambiguous ``get()`` explains itself, and ``except LibTmuxException`` sees it.

    Two rows for one pane id is a real ambiguity, and a ``default`` does not
    make it go away -- it stands in for an object that is *absent*. So the
    lookup raises, but it raises something the caller can catch and read.
    """
    window = build_winlink_shape(server, shape)
    pane = window.active_pane
    assert pane is not None
    assert pane.pane_id is not None

    with pytest.raises(exc.LibTmuxException) as excinfo:
        server.panes.get(pane_id=pane.pane_id, default=None)

    assert isinstance(excinfo.value, exc.MultipleObjectsReturned)
    assert str(excinfo.value) == (
        f"Multiple objects returned (2): pane_id={pane.pane_id!r}"
    )


def test_point_lookup_by_id_is_the_way_out(server: Server) -> None:
    """The documented escape from an ambiguous scan: name the id with ``-t``.

    :meth:`Pane.from_pane_id` and :meth:`Window.from_window_id` hand the question
    to tmux, which always has exactly one answer.
    """
    window, _old, _recent = link_window_into_second_session(server)
    pane = window.active_pane
    assert pane is not None
    assert pane.pane_id is not None
    assert window.window_id is not None

    assert Pane.from_pane_id(server, pane.pane_id).pane_id == pane.pane_id
    assert Window.from_window_id(server, window.window_id).window_id == window.window_id


def test_linked_sessions_lists_each_holder_once(server: Server) -> None:
    """:attr:`Window.linked_sessions` dedupes winlinks down to sessions.

    A window linked into one session twice is in *one* session, not two -- so
    the two winlinks collapse to one holder.
    """
    window, dup = link_window_twice_into_one_session(server)

    assert [s.session_id for s in window.linked_sessions] == [dup.session_id]

    guest = server.new_session(session_name="guest")
    server.cmd(
        "link-window", "-d", "-s", window.window_id, "-t", f"{guest.session_id}:"
    )

    holders = {s.session_id for s in window.linked_sessions}
    assert holders == {dup.session_id, guest.session_id}


def test_linked_sessions_returns_empty_after_server_kill(
    server: Server,
    session: Session,
) -> None:
    """A retained window has no knowable holders after its server dies."""
    window = session.active_window

    server.kill()

    assert list(window.linked_sessions) == []


def test_linked_sessions_returns_empty_when_session_snapshot_fails(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second listing shares the accessor's lenient error boundary.

    A live server cannot naturally fail only its second back-to-back listing,
    so this exceptional boundary needs a narrow wrapper around the real first
    snapshot.
    """
    window = server.new_session(session_name="holder").active_window
    real_fetch_objs = neo.fetch_objs

    def fail_session_snapshot(**kwargs: t.Any) -> list[dict[str, str]]:
        if kwargs["list_cmd"] == "list-sessions":
            msg = "session snapshot failed"
            raise exc.LibTmuxException(msg)
        return real_fetch_objs(**kwargs)

    monkeypatch.setattr(window_module, "fetch_objs", fail_session_snapshot)

    assert list(window.linked_sessions) == []


def test_linked_sessions_skips_holder_lost_between_snapshots(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A holder disappearing between real snapshots is skipped safely.

    The race cannot be scheduled deterministically without wrapping the first
    listing, so the standard server fixture supplies both live snapshots while
    the wrapper removes one holder between them.
    """
    home = server.new_session(session_name="home")
    window = home.active_window
    guest = server.new_session(session_name="guest")
    server.cmd(
        "link-window",
        "-d",
        "-s",
        window.window_id,
        "-t",
        f"{guest.session_id}:",
    )
    real_fetch_objs = neo.fetch_objs

    def remove_guest_after_window_snapshot(**kwargs: t.Any) -> list[dict[str, str]]:
        rows = real_fetch_objs(**kwargs)
        if kwargs["list_cmd"] == "list-windows":
            guest.kill()
        return rows

    monkeypatch.setattr(
        window_module,
        "fetch_objs",
        remove_guest_after_window_snapshot,
    )

    assert [holder.session_id for holder in window.linked_sessions] == [
        home.session_id,
    ]


def test_linked_sessions_uses_two_list_calls(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolving several holders uses two real tmux listings in total.

    ``fetch_objs`` is wrapped only to record call shape; the real function and
    tmux server still provide every row used by the assertion.
    """
    window, _dup = link_window_twice_into_one_session(server)
    for name in ("guest-one", "guest-two"):
        guest = server.new_session(session_name=name)
        server.cmd(
            "link-window",
            "-d",
            "-s",
            window.window_id,
            "-t",
            f"{guest.session_id}:",
        )

    real_fetch_objs = neo.fetch_objs
    rows = real_fetch_objs(
        server=server,
        list_cmd="list-windows",
        list_extra_args=("-a",),
    )
    expected_session_ids = list(
        dict.fromkeys(
            row["session_id"]
            for row in rows
            if row.get("window_id") == window.window_id and row.get("session_id")
        ),
    )
    list_calls: list[str] = []

    def recording_fetch_objs(**kwargs: t.Any) -> list[dict[str, str]]:
        list_calls.append(kwargs["list_cmd"])
        return real_fetch_objs(**kwargs)

    monkeypatch.setattr(window_module, "fetch_objs", recording_fetch_objs)
    monkeypatch.setattr(neo, "fetch_objs", recording_fetch_objs)

    assert [item.session_id for item in window.linked_sessions] == expected_session_ids
    assert list_calls == ["list-windows", "list-sessions"]
