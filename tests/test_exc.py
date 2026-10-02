"""Tests for :mod:`libtmux.exc`."""

from __future__ import annotations

import inspect
import typing as t

import pytest

from libtmux import exc

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session
    from libtmux.window import Window

EXC_CLASSES = [
    cls
    for _, cls in inspect.getmembers(exc, inspect.isclass)
    if issubclass(cls, Exception) and cls.__module__ == exc.__name__
]


@pytest.mark.parametrize("cls", EXC_CLASSES, ids=lambda cls: cls.__name__)
def test_every_exception_is_a_tmux_error(cls: type[Exception]) -> None:
    """One ``except TmuxError`` catches everything libtmux defines.

    Enumerates :mod:`libtmux.exc`, so a class added later cannot slip outside
    the root.
    """
    assert issubclass(cls, exc.TmuxError)


class HierarchyFixture(t.NamedTuple):
    """Where a class sits relative to the two halves of the root."""

    test_id: str
    cls: type[Exception]
    is_libtmux_exception: bool
    bases: tuple[type[Exception], ...]


HIERARCHY_FIXTURES = [
    HierarchyFixture(
        "wait_timeout",
        exc.WaitTimeout,
        True,
        (exc.LibTmuxException,),
    ),
    HierarchyFixture(
        "tmux_timeout",
        exc.TmuxTimeout,
        True,
        (exc.LibTmuxException,),
    ),
    HierarchyFixture(
        "pane_run_timeout",
        exc.PaneRunTimeout,
        True,
        (exc.WaitTimeout, exc.TmuxTimeout),
    ),
    HierarchyFixture(
        "server_gone",
        exc.TmuxServerGone,
        True,
        (exc.LibTmuxException,),
    ),
    HierarchyFixture(
        "list_command_failed",
        exc.ListCommandFailed,
        True,
        (exc.TmuxCommandFailed,),
    ),
    HierarchyFixture(
        "deprecated",
        exc.DeprecatedError,
        False,
        (exc.TmuxError, AttributeError),
    ),
]


@pytest.mark.parametrize(
    list(HierarchyFixture._fields),
    HIERARCHY_FIXTURES,
    ids=[f.test_id for f in HIERARCHY_FIXTURES],
)
def test_hierarchy_shape(
    test_id: str,
    cls: type[Exception],
    is_libtmux_exception: bool,
    bases: tuple[type[Exception], ...],
) -> None:
    """Timeouts and waits sit under LibTmuxException; removed APIs do not."""
    assert issubclass(cls, exc.LibTmuxException) is is_libtmux_exception
    assert cls.__bases__ == bases


def test_deprecated_error_is_not_a_tmux_failure() -> None:
    """DeprecatedError is a caller bug, not a tmux failure."""
    assert not issubclass(exc.DeprecatedError, exc.LibTmuxException)


def test_removed_api_escapes_broad_libtmux_handler(server: Server) -> None:
    """A removed API is not swallowed by ``except LibTmuxException``."""
    fell_back = False
    with pytest.raises(exc.DeprecatedError, match=r"Server\.find_where\(\)"):
        try:
            server.find_where({"session_name": "x"})
        except exc.LibTmuxException:
            fell_back = True
    assert not fell_back


def test_removed_api_keeps_feature_detection_working(session: Session) -> None:
    """``hasattr`` and ``getattr`` default see a removed name as absent.

    Reading it directly still raises, naming the replacement, so a
    new-then-old ladder runs while a plain call stays loud.
    """
    assert not hasattr(session, "attached_window")
    assert getattr(session, "attached_window", "fallback") == "fallback"
    with pytest.raises(exc.DeprecatedError, match=r"Session\.active_window"):
        _ = session.attached_window


def test_removed_api_is_still_caught_by_the_root(server: Server) -> None:
    """``except TmuxError`` is the catch-all that does include removed APIs."""
    with pytest.raises(exc.TmuxError):
        server.find_where({"session_name": "x"})


def _timeout() -> exc.LibTmuxException:
    return exc.TmuxTimeout(cmd=["tmux", "list-sessions"], timeout=1.0)


def _wait_timeout() -> exc.LibTmuxException:
    return exc.WaitTimeout("gave up")


def _server_gone() -> exc.LibTmuxException:
    return exc.TmuxServerGone("chan")


@pytest.mark.parametrize(
    "make",
    [_timeout, _wait_timeout, _server_gone],
    ids=["tmux_timeout", "wait_timeout", "server_gone"],
)
def test_lenient_listings_do_not_hide_a_hang(
    server: Server,
    make: t.Callable[[], exc.LibTmuxException],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A timeout is not "nothing to list": the lenient accessors let it out.

    Even though each is a :exc:`LibTmuxException`, the accessors catch only
    command failures, so the hierarchy position of a new error cannot turn a
    hung server into an empty one.
    """
    error = make()

    def _boom(**_: object) -> list[dict[str, str]]:
        raise error

    monkeypatch.setattr("libtmux.server.fetch_objs", _boom)

    with pytest.raises(type(error)):
        _ = server.sessions
    with pytest.raises(type(error)):
        _ = server.clients
    with pytest.raises(type(error)):
        server.fetch_sessions()


def test_window_linked_sessions_does_not_hide_a_hang(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``Window.linked_sessions`` is lenient too, and also lets a timeout out."""
    window: Window = session.active_window

    def _boom(**_: object) -> list[dict[str, str]]:
        raise _timeout()

    monkeypatch.setattr("libtmux.window.fetch_objs", _boom)
    with pytest.raises(exc.TmuxTimeout):
        _ = window.linked_sessions


def test_strict_listing_wraps_only_command_failures(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``fetch_sessions`` still turns a failed list into ListCommandFailed."""
    error = exc.TmuxCommandFailed("no server running")

    def _boom(**_: object) -> list[dict[str, str]]:
        raise error

    monkeypatch.setattr("libtmux.server.fetch_objs", _boom)
    with pytest.raises(exc.ListCommandFailed, match="no server running"):
        server.fetch_sessions()
