"""Sidecar for ``docs/howto/detect-you-are-inside-tmux.md``.

The page's whole subject is an environment this process does not have, so
``setup`` manufactures it: a real session on the runner's private tmux world,
with ``$TMUX`` and ``$TMUX_PANE`` set exactly as tmux would have set them for
a pane's child. The visible blocks then call
:meth:`~libtmux.Server.from_env` with no arguments, the way a reader would.

Both sides of both branches are exercised. Block 1 is re-run with ``$TMUX``
removed, which is the only honest way to check the "outside tmux" arm, and
block 2 is re-run after the server has been killed, which is the page's real
claim: detection is a read of your own environment and survives the server it
names.
"""

from __future__ import annotations

import typing as t

import pytest

from libtmux.server import Server

if t.TYPE_CHECKING:
    from tests.docs.howto_harness import HowtoContext

SESSION_NAME = "howto-inside"


def setup(ctx: HowtoContext) -> None:
    """Make this process look like a child of a real tmux pane.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    server = Server()
    session = server.new_session(session_name=SESSION_NAME)
    pane = session.active_window.active_pane
    assert pane is not None

    socket_path = server.cmd("display-message", "-p", "#{socket_path}").stdout[0]
    assert session.session_id is not None
    assert pane.pane_id is not None

    # tmux spells $TMUX as "<socket_path>,<server_pid>,<session_id>", with the
    # session id bare rather than sigilled.
    ctx.monkeypatch.setenv(
        "TMUX",
        f"{socket_path},1,{session.session_id.lstrip('$')}",
    )
    ctx.monkeypatch.setenv("TMUX_PANE", pane.pane_id)


def check_1(ctx: HowtoContext) -> None:
    """Confirm detection names the socket in ``$TMUX``, and only there.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    socket_path = Server.from_env().socket_path
    assert socket_path is not None

    server = ctx.namespace["server"]
    assert isinstance(server, Server)
    assert server.socket_path == socket_path
    assert server.is_alive()
    assert ctx.output[1].strip() == f"running inside tmux on {socket_path}"

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.delenv("TMUX")
        assert ctx.run_block(1, namespace={}).strip() == "running outside tmux"


def check_2(ctx: HowtoContext) -> None:
    """Liveness is a second, separate question from detection.

    Killing the server leaves ``$TMUX`` naming it, so the page's claim is
    checked the only way it can be: re-run the block against that corpse and
    require the other message.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    assert ctx.output[2].strip() == "1 session(s) on this server"

    server = ctx.namespace["server"]
    assert isinstance(server, Server)
    socket_path = server.socket_path
    server.kill()

    dead = Server.from_env()
    assert dead.socket_path == socket_path
    assert not dead.is_alive()

    assert ctx.run_block(2, namespace={"server": dead}).strip() == (
        "the server named by $TMUX is gone"
    )
