"""Sidecar for ``docs/howto/connect-to-an-existing-window.md``.

``setup`` builds the collision the page opens with: two sessions whose windows
carry the same names at the same indexes. If a future change made window names
or indexes unique server-wide, block 1's output would stop demonstrating
anything and ``check_1`` would say so.

``check_2`` owns the page's sharpest claim — that a window index is a string,
so an integer lookup silently returns the default instead of the window — and
``check_3`` owns the linked-window claim the closing paragraph makes.
"""

from __future__ import annotations

import typing as t

import pytest

from libtmux import exc
from libtmux.server import Server
from libtmux.window import Window

if t.TYPE_CHECKING:
    from tests.docs.howto_harness import HowtoContext

#: A socket no server listens on, for exercising the page's "not found" branch.
ABSENT_SOCKET = "howto-no-such-server"


def setup(ctx: HowtoContext) -> None:
    """Leave two sessions whose windows share names and indexes.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    server = Server()
    for name in ("editor", "notes"):
        session = server.new_session(session_name=name, window_name="code")
        session.new_window(window_name="logs", attach=False)


def check_1(ctx: HowtoContext) -> None:
    """Verify the server-wide listing shows a name and index used twice.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    server = ctx.namespace["server"]
    assert isinstance(server, Server)

    rows = [line.split("\t") for line in ctx.output[1].strip().splitlines()]
    expected = [
        [f"{s.session_name}:{w.window_index}", w.window_name]
        for s in server.sessions
        for w in s.windows
    ]
    assert rows == expected

    names = [name for _position, name in rows]
    indexes = [position.split(":")[1] for position, _name in rows]
    assert names.count("logs") == 2, (
        "the page opens by showing one window name reused across sessions"
    )
    assert len(set(indexes)) < len(indexes), (
        "the page opens by showing one window index reused across sessions"
    )


def check_2(ctx: HowtoContext) -> None:
    """Name and index lookups find the right windows, and ``1`` finds nothing.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    session = ctx.namespace["session"]
    by_name = ctx.namespace["by_name"]
    by_index = ctx.namespace["by_index"]

    assert by_name.window_name == "logs"
    assert by_name.session.session_name == "editor"
    assert by_index.window_id == session.active_window.window_id

    assert ctx.output[2].strip().splitlines() == [
        f"by name:  {by_name}",
        f"by index: {by_index}",
    ]

    index = session.active_window.window_index
    assert isinstance(index, str)
    assert session.windows.get(window_index=index, default=None) is not None
    assert session.windows.get(window_index=int(index), default=None) is None, (
        "the page warns that an integer index quietly matches nothing"
    )

    absent = Server(socket_name=ABSENT_SOCKET)
    assert ctx.run_block(2, namespace={"server": absent}).strip() == (
        "no session named 'editor' — pick one from the listing above"
    )


def check_3(ctx: HowtoContext) -> None:
    """Verify an id resolves to one window even when two sessions hold it.

    Linking the window into a second session is the state the closing
    paragraph describes, so it is built here rather than asserted from memory.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    server = ctx.namespace["server"]
    window = ctx.namespace["window"]

    assert ctx.output[3].strip() == f"{window.window_name} True"

    with pytest.raises(exc.TmuxObjectDoesNotExist):
        Window.from_window_id(server, "@999")

    guest = server.new_session(session_name="guest")
    server.cmd(
        "link-window",
        "-d",
        "-s",
        window.window_id,
        "-t",
        f"{guest.session_id}:",
    )

    assert len(server.windows.filter(window_id=window.window_id)) == 2
    with pytest.raises(exc.MultipleObjectsReturned):
        server.windows.get(window_id=window.window_id)

    assert Window.from_window_id(server, window.window_id).window_id == (
        window.window_id
    )
    assert sorted(s.session_name for s in window.linked_sessions) == ["editor", "guest"]
