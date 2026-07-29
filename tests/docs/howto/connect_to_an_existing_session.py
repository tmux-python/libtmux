"""Sidecar for ``docs/howto/connect-to-an-existing-session.md``.

The page reads a server it did not build, so ``setup`` builds one: two detached
sessions on the default socket of this page's private tmux world. Two, not one,
because the page claims a name lookup is unambiguous while a lookup on another
attribute is not — and that claim needs a second session to be false.

The checks pin the page's three factual claims rather than its wording: a dead
server yields an empty listing instead of an error, ``get()`` raises on absence
only when it has no ``default`` and raises on ambiguity regardless, and
``has_session`` matches exactly unless told otherwise.
"""

from __future__ import annotations

import typing as t

import pytest

from libtmux import exc
from libtmux.server import Server
from libtmux.session import Session

if t.TYPE_CHECKING:
    from tests.docs.howto_harness import HowtoContext

#: A socket no server listens on, for exercising the page's "not found" branch.
ABSENT_SOCKET = "howto-no-such-server"


def setup(ctx: HowtoContext) -> None:
    """Leave two detached sessions for the page to find.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    server = Server()
    server.new_session(session_name="editor", window_name="code")
    server.new_session(session_name="notes", window_name="code")


def check_1(ctx: HowtoContext) -> None:
    """Verify the listing reports every session on the server, id first.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    server = ctx.namespace["server"]
    assert isinstance(server, Server)

    lines = ctx.output[1].strip().splitlines()
    assert lines == [f"{s.session_id}\t{s.session_name}" for s in server.sessions]
    assert {line.split("\t")[1] for line in lines} == {"editor", "notes"}


def check_2(ctx: HowtoContext) -> None:
    """Both branches of the guarded lookup behave as the page says.

    The "not found" branch runs against a socket nothing listens on, which
    exercises the page's other claim at the same time: an unreachable server
    hands back an empty listing rather than raising, so ``get()`` sees absence.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    assert ctx.output[2].strip() == "editor holds 1 window(s)"

    session = ctx.namespace["session"]
    assert isinstance(session, Session)
    assert session.session_name == "editor"

    absent = Server(socket_name=ABSENT_SOCKET)
    assert not absent.is_alive()
    assert list(absent.sessions) == []
    assert (
        ctx.run_block(2, namespace={"server": absent}).strip()
        == "no session named 'editor'"
    )

    server = ctx.namespace["server"]
    with pytest.raises(exc.ObjectDoesNotExist):
        server.sessions.get(session_name="no-such-session")
    assert server.sessions.get(session_name="no-such-session", default=None) is None

    with pytest.raises(exc.MultipleObjectsReturned):
        server.sessions.get(session_attached="0", default=None)


def check_3(ctx: HowtoContext) -> None:
    """Verify an id round-trips and ``has_session`` is exact by default.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    server = ctx.namespace["server"]
    session = ctx.namespace["session"]

    assert ctx.output[3].strip().splitlines() == ["editor True", "True False"]

    found = ctx.namespace["found"]
    assert found.session_id == session.session_id

    with pytest.raises(exc.TmuxObjectDoesNotExist):
        Session.from_session_id(server, "$999")

    assert server.has_session("edit", exact=False)
