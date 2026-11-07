"""Sidecar for ``docs/howto/start-a-server.md``.

The page makes three claims a reader would take on trust, so each is checked
against the daemon the block actually left behind rather than against what the
block printed:

- :meth:`~libtmux.Server.new_session` boots a server on the named socket;
- the daemon is independent of the handle, so a second handle built from
  scratch reaches the same sessions;
- :meth:`~libtmux.Server.start_server` leaves nothing running, which is the
  reason the page steers readers away from it.
"""

from __future__ import annotations

import typing as t

from libtmux.server import Server

if t.TYPE_CHECKING:
    from tests.docs.howto_harness import HowtoContext

SOCKET_NAME = "libtmux-howto"
EMPTY_SOCKET_NAME = "libtmux-howto-empty"


def check_1(ctx: HowtoContext) -> None:
    """Block 1 leaves a live daemon holding one ``worker`` session.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    assert ctx.output[1].strip() == "worker is up: True"

    server = ctx.namespace["server"]
    assert isinstance(server, Server)
    assert server.socket_name == SOCKET_NAME

    assert server.is_alive()
    assert [session.session_name for session in server.sessions] == ["worker"]

    session = ctx.namespace["session"]
    assert session.session_name == "worker"

    # Pasting the page twice has to work, which is what kill_session= buys.
    again = ctx.run_block(1, namespace={})
    assert again.strip() == "worker is up: True"
    assert [session.session_name for session in server.sessions] == ["worker"]


def check_2(ctx: HowtoContext) -> None:
    """Block 2 rebuilds the handle and finds the daemon untouched.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    assert "server" not in ctx.namespace, (
        "block 2 shows that dropping the handle does not touch the daemon; "
        "if the name survives, the page no longer demonstrates that"
    )

    reconnected = ctx.namespace["reconnected"]
    assert isinstance(reconnected, Server)
    assert reconnected.socket_name == SOCKET_NAME

    assert ctx.output[2].strip().splitlines() == ["True", "['worker']"]

    # A third handle, built here and never mentioned on the page, sees the
    # same daemon: what the block prints is a property of the socket, not of
    # the object the block happens to hold.
    assert Server(socket_name=SOCKET_NAME).is_alive()


def check_3(ctx: HowtoContext) -> None:
    """``start_server`` leaves no daemon, and the page cleans up after itself.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    assert ctx.output[3].strip() == "False"

    empty = ctx.namespace["empty"]
    assert isinstance(empty, Server)
    assert empty.socket_name == EMPTY_SOCKET_NAME
    assert not empty.is_alive()
    # Not an artefact of the handle: a fresh one finds nothing either.
    assert not Server(socket_name=EMPTY_SOCKET_NAME).is_alive()

    assert not ctx.namespace["reconnected"].is_alive()
    assert not Server(socket_name=SOCKET_NAME).is_alive()
