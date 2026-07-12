"""Tests for the ``from_env()`` family — locating the pane libtmux runs inside.

tmux exports ``$TMUX`` (``socket_path,server_pid,session_id``) and
``$TMUX_PANE`` (``%N``) into every pane's child environment, and never revises
either. libtmux reads the socket path out of ``$TMUX``, then asks tmux — via
``$TMUX_PANE`` — for the window and session, so the frozen session id can never
mislead it.
"""

from __future__ import annotations

import re
import typing as t

import pytest

from libtmux import exc
from libtmux._internal.query_list import ObjectDoesNotExist
from libtmux.pane import Pane
from libtmux.server import Server
from libtmux.session import Session
from libtmux.window import Window

if t.TYPE_CHECKING:
    from collections.abc import Callable, Mapping


def env_for(server: Server, pane_id: str, session_id: str) -> dict[str, str]:
    """Build the ``TMUX``/``TMUX_PANE`` pair tmux exports into *pane_id*.

    The test :func:`~libtmux.pytest_plugin.server` fixture is socket-*name*
    based, so ``Server.socket_path`` is unset; ask tmux for the path the way a
    real pane's ``$TMUX`` would carry it.
    """
    socket_path = server.cmd(
        "display-message",
        "-p",
        "-t",
        pane_id,
        "#{socket_path}",
    ).stdout[0]
    return {
        "TMUX": f"{socket_path},1,{session_id.removeprefix('$')}",
        "TMUX_PANE": pane_id,
    }


class SocketPathFixture(t.NamedTuple):
    """Test fixture for ``$TMUX`` socket path extraction."""

    test_id: str
    tmux: str
    expected_socket_path: str


SOCKET_PATH_FIXTURES: list[SocketPathFixture] = [
    SocketPathFixture(
        test_id="default_socket",
        tmux="/tmp/tmux-1000/default,84215,0",
        expected_socket_path="/tmp/tmux-1000/default",
    ),
    SocketPathFixture(
        test_id="named_socket",
        tmux="/tmp/tmux-1000/libtmux_test0,1,47",
        expected_socket_path="/tmp/tmux-1000/libtmux_test0",
    ),
    SocketPathFixture(
        test_id="comma_inside_socket_path",
        tmux="/tmp/od,d/socket,84215,3",
        expected_socket_path="/tmp/od,d/socket",
    ),
    SocketPathFixture(
        test_id="no_session",
        tmux="/tmp/tmux-1000/default,84215,-1",
        expected_socket_path="/tmp/tmux-1000/default",
    ),
]


@pytest.mark.parametrize(
    list(SocketPathFixture._fields),
    SOCKET_PATH_FIXTURES,
    ids=[test.test_id for test in SOCKET_PATH_FIXTURES],
)
def test_server_from_env_socket_path(
    test_id: str,
    tmux: str,
    expected_socket_path: str,
) -> None:
    """``Server.from_env()`` splits ``$TMUX`` from the right."""
    assert Server.from_env({"TMUX": tmux}).socket_path == expected_socket_path


class NotInsideTmuxFixture(t.NamedTuple):
    """Test fixture for environments that don't describe a tmux pane."""

    test_id: str
    env: dict[str, str]
    message: str


NOT_INSIDE_TMUX_FIXTURES: list[NotInsideTmuxFixture] = [
    NotInsideTmuxFixture(
        test_id="empty_env",
        env={},
        message="$TMUX is unset or empty",
    ),
    NotInsideTmuxFixture(
        test_id="tmux_empty",
        env={"TMUX": "", "TMUX_PANE": "%0"},
        message="$TMUX is unset or empty",
    ),
    NotInsideTmuxFixture(
        test_id="tmux_missing_pid_and_session",
        env={"TMUX": "/tmp/tmux-1000/default", "TMUX_PANE": "%0"},
        message="$TMUX is not '<socket_path>,<server_pid>,<session_id>'",
    ),
    NotInsideTmuxFixture(
        test_id="tmux_missing_socket_path",
        env={"TMUX": ",84215,0", "TMUX_PANE": "%0"},
        message="$TMUX is not '<socket_path>,<server_pid>,<session_id>'",
    ),
]


@pytest.mark.parametrize(
    list(NotInsideTmuxFixture._fields),
    NOT_INSIDE_TMUX_FIXTURES,
    ids=[test.test_id for test in NOT_INSIDE_TMUX_FIXTURES],
)
def test_server_from_env_not_inside_tmux(
    test_id: str,
    env: dict[str, str],
    message: str,
) -> None:
    """A missing or malformed ``$TMUX`` is :exc:`~libtmux.exc.NotInsideTmux`."""
    with pytest.raises(exc.NotInsideTmux, match=re.escape(message)):
        Server.from_env(env)


class PaneEnvFixture(t.NamedTuple):
    """Test fixture for environments whose ``$TMUX_PANE`` is unusable."""

    test_id: str
    tmux_pane: str | None
    message: str


PANE_ENV_FIXTURES: list[PaneEnvFixture] = [
    PaneEnvFixture(
        test_id="unset",
        tmux_pane=None,
        message="$TMUX_PANE is unset or empty",
    ),
    PaneEnvFixture(
        test_id="empty",
        tmux_pane="",
        message="$TMUX_PANE is unset or empty",
    ),
    PaneEnvFixture(
        test_id="sigil_less",
        tmux_pane="0",
        message="$TMUX_PANE is not a pane id",
    ),
    PaneEnvFixture(
        test_id="session_sigil",
        tmux_pane="$1",
        message="$TMUX_PANE is not a pane id",
    ),
]


@pytest.mark.parametrize(
    list(PaneEnvFixture._fields),
    PANE_ENV_FIXTURES,
    ids=[test.test_id for test in PANE_ENV_FIXTURES],
)
def test_pane_from_env_bad_pane_id(
    test_id: str,
    tmux_pane: str | None,
    message: str,
) -> None:
    """``$TMUX_PANE`` must carry the ``%`` sigil tmux routes targets by."""
    env = {"TMUX": "/tmp/tmux-1000/default,84215,0"}
    if tmux_pane is not None:
        env["TMUX_PANE"] = tmux_pane

    with pytest.raises(exc.NotInsideTmux, match=re.escape(message)):
        Pane.from_env(env)


class FromEnvFixture(t.NamedTuple):
    """Test fixture pairing each constructor with its ``from_env``."""

    test_id: str
    from_env: Callable[[Mapping[str, str]], object]


FROM_ENV_FIXTURES: list[FromEnvFixture] = [
    FromEnvFixture(test_id="server", from_env=Server.from_env),
    FromEnvFixture(test_id="session", from_env=Session.from_env),
    FromEnvFixture(test_id="window", from_env=Window.from_env),
    FromEnvFixture(test_id="pane", from_env=Pane.from_env),
]


@pytest.mark.parametrize(
    list(FromEnvFixture._fields),
    FROM_ENV_FIXTURES,
    ids=[test.test_id for test in FROM_ENV_FIXTURES],
)
def test_from_env_outside_tmux(
    test_id: str,
    from_env: Callable[[Mapping[str, str]], object],
) -> None:
    """Every constructor rejects an environment with no tmux in it."""
    with pytest.raises(exc.NotInsideTmux):
        from_env({})


def test_from_env_defaults_to_os_environ(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``env=None`` reads the live process environment, as a real pane would."""
    pane = session.active_pane
    assert pane is not None
    assert pane.pane_id is not None
    assert session.session_id is not None

    for key, value in env_for(session.server, pane.pane_id, session.session_id).items():
        monkeypatch.setenv(key, value)

    assert Pane.from_env().pane_id == pane.pane_id
    assert Window.from_env().window_id == session.active_window.window_id
    assert Session.from_env().session_id == session.session_id
    assert Server.from_env().is_alive()


def test_from_env_resolves_the_calling_pane(session: Session) -> None:
    """The whole family agrees on the pane, window, and session."""
    window = session.active_window
    pane = window.active_pane
    assert pane is not None
    assert pane.pane_id is not None
    assert session.session_id is not None

    env = env_for(session.server, pane.pane_id, session.session_id)

    assert Pane.from_env(env).pane_id == pane.pane_id
    assert Window.from_env(env).window_id == window.window_id
    assert Session.from_env(env).session_id == session.session_id
    assert Pane.from_env(env).window.window_id == window.window_id
    assert Pane.from_env(env).session.session_id == session.session_id


def test_from_env_ignores_stale_session_id(session: Session) -> None:
    """The session id inside ``$TMUX`` is never read, however wrong it is."""
    pane = session.active_pane
    assert pane is not None
    assert pane.pane_id is not None
    assert session.session_id is not None

    env = env_for(session.server, pane.pane_id, "$99999")

    assert Session.from_env(env).session_id == session.session_id


def test_from_env_follows_pane_after_move_window(session: Session) -> None:
    """A moved window resolves to its new session, not the one in ``$TMUX``."""
    server = session.server
    destination = server.new_session(session_name="destination")

    window = session.active_window
    pane = window.active_pane
    assert pane is not None
    assert pane.pane_id is not None
    assert session.session_id is not None
    assert destination.session_id is not None

    session.new_window()  # keep the origin session alive after the move
    env = env_for(server, pane.pane_id, session.session_id)
    window.move_window(destination="99", session=destination.session_id)

    assert Session.from_env(env).session_id == destination.session_id
    assert Window.from_env(env).session.session_id == destination.session_id
    assert Pane.from_env(env).session.session_id == destination.session_id


def test_from_env_agrees_with_tmux_on_a_linked_window(session: Session) -> None:
    """A window linked into two sessions gets tmux's own canonical answer."""
    server = session.server
    guest = server.new_session(session_name="zzz-guest")

    window = session.active_window
    pane = window.active_pane
    assert pane is not None
    assert pane.pane_id is not None
    assert window.window_id is not None
    assert session.session_id is not None
    assert guest.session_name is not None

    server.cmd("link-window", "-s", window.window_id, "-t", guest.session_name)

    env = env_for(server, pane.pane_id, session.session_id)
    tmux_says = server.cmd(
        "display-message",
        "-p",
        "-t",
        pane.pane_id,
        "#{session_id}",
    ).stdout[0]

    resolved = {
        Session.from_env(env).session_id,
        Window.from_env(env).session.session_id,
        Pane.from_env(env).session.session_id,
        Pane.from_env(env).window.session.session_id,
    }

    assert resolved == {tmux_says}


def test_window_from_env_is_the_containing_window(session: Session) -> None:
    """The caller's window is reported, not the session's active window."""
    caller_window = session.active_window
    caller_pane = caller_window.active_pane
    assert caller_pane is not None
    assert caller_pane.pane_id is not None
    assert session.session_id is not None

    env = env_for(session.server, caller_pane.pane_id, session.session_id)

    foreground = session.new_window(window_name="foreground", attach=True)
    assert session.active_window.window_id == foreground.window_id

    assert Window.from_env(env).window_id == caller_window.window_id


class MissingPaneFixture(t.NamedTuple):
    """Test fixture pairing each pane-derived constructor with its ``from_env``."""

    test_id: str
    from_env: Callable[[Mapping[str, str]], object]


MISSING_PANE_FIXTURES: list[MissingPaneFixture] = [
    MissingPaneFixture(test_id="session", from_env=Session.from_env),
    MissingPaneFixture(test_id="window", from_env=Window.from_env),
    MissingPaneFixture(test_id="pane", from_env=Pane.from_env),
]


@pytest.mark.parametrize(
    list(MissingPaneFixture._fields),
    MISSING_PANE_FIXTURES,
    ids=[test.test_id for test in MISSING_PANE_FIXTURES],
)
def test_from_env_missing_pane_on_live_server(
    test_id: str,
    from_env: Callable[[Mapping[str, str]], object],
    session: Session,
) -> None:
    """A vanished pane on a reachable server is an object-lookup failure."""
    pane = session.active_pane
    assert pane is not None
    assert pane.pane_id is not None
    assert session.session_id is not None

    env = env_for(session.server, pane.pane_id, session.session_id)
    env["TMUX_PANE"] = "%99999"

    with pytest.raises(exc.TmuxObjectDoesNotExist):
        from_env(env)


@pytest.mark.parametrize(
    list(MissingPaneFixture._fields),
    MISSING_PANE_FIXTURES,
    ids=[test.test_id for test in MISSING_PANE_FIXTURES],
)
def test_from_env_dead_server(
    test_id: str,
    from_env: Callable[[Mapping[str, str]], object],
    TestServer: Callable[..., Server],
) -> None:
    """An unreachable server is a tmux failure, not a missing object.

    Uses :func:`~libtmux.pytest_plugin.TestServer` rather than the ``session``
    fixture because the server has to be killed inside the test body.
    """
    server = TestServer()
    session = server.new_session(session_name="doomed")

    pane = session.active_pane
    assert pane is not None
    assert pane.pane_id is not None
    assert session.session_id is not None

    env = env_for(server, pane.pane_id, session.session_id)
    server.kill()

    with pytest.raises(exc.LibTmuxException) as excinfo:
        from_env(env)

    assert not isinstance(excinfo.value, ObjectDoesNotExist)


class UnidentifiedPaneFixture(t.NamedTuple):
    """A ``from_env`` that traverses off a pane, and the id it needs."""

    test_id: str
    from_env: Callable[[Mapping[str, str]], object]
    message: str


UNIDENTIFIED_PANE_FIXTURES: list[UnidentifiedPaneFixture] = [
    UnidentifiedPaneFixture(
        test_id="session",
        from_env=Session.from_env,
        message="Pane must have a session_id to resolve its session",
    ),
    UnidentifiedPaneFixture(
        test_id="window",
        from_env=Window.from_env,
        message="Pane must have a window_id to resolve its window",
    ),
]


@pytest.mark.parametrize(
    list(UnidentifiedPaneFixture._fields),
    UNIDENTIFIED_PANE_FIXTURES,
    ids=[test.test_id for test in UNIDENTIFIED_PANE_FIXTURES],
)
def test_from_env_pane_without_parent_id(
    test_id: str,
    from_env: Callable[[Mapping[str, str]], object],
    message: str,
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pane that names no parent is a ``ValueError`` on both constructors.

    :meth:`~libtmux.Session.from_env` and :meth:`~libtmux.Window.from_env` both
    traverse off the pane :meth:`~libtmux.Pane.from_env` returns, and must fail
    the same way when it carries no parent id. Uses ``monkeypatch`` rather than
    the standard fixtures because tmux always stamps a real pane row with both
    ids -- these guards stand in for the ``assert`` a ``python -O`` run strips.
    """

    def unidentified_pane(
        cls: type[Pane],
        env: Mapping[str, str] | None = None,
    ) -> Pane:
        return Pane(server=server, pane_id="%0")

    monkeypatch.setattr(Pane, "from_env", classmethod(unidentified_pane))

    with pytest.raises(ValueError, match=re.escape(message)):
        from_env({})


class SubclassFixture(t.NamedTuple):
    """A ``from_env`` constructor, and the class it is called on."""

    test_id: str
    subclass: type[Server] | type[Session] | type[Window] | type[Pane]


class MyServer(Server):
    """Downstream subclass of :class:`~libtmux.Server`."""


class MySession(Session):
    """Downstream subclass of :class:`~libtmux.Session`."""


class MyWindow(Window):
    """Downstream subclass of :class:`~libtmux.Window`."""


class MyPane(Pane):
    """Downstream subclass of :class:`~libtmux.Pane`."""


SUBCLASS_FIXTURES: list[SubclassFixture] = [
    SubclassFixture(test_id="server", subclass=MyServer),
    SubclassFixture(test_id="session", subclass=MySession),
    SubclassFixture(test_id="window", subclass=MyWindow),
    SubclassFixture(test_id="pane", subclass=MyPane),
]


@pytest.mark.parametrize(
    list(SubclassFixture._fields),
    SUBCLASS_FIXTURES,
    ids=[test.test_id for test in SUBCLASS_FIXTURES],
)
def test_from_env_returns_the_class_it_was_called_on(
    session: Session,
    test_id: str,
    subclass: type[Server] | type[Session] | type[Window] | type[Pane],
) -> None:
    """``from_env`` honours ``cls``, so subclasses get their own type back.

    A constructor that resolves by traversing off another object (rather than
    through ``cls``) silently hands back the base class, and libtmux subclasses
    lose their own behaviour.
    """
    server = session.server
    pane = session.active_pane
    assert pane is not None
    assert pane.pane_id is not None
    assert session.session_id is not None

    env = env_for(server, pane.pane_id, session.session_id)

    assert type(subclass.from_env(env)) is subclass
