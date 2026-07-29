"""Sidecar for ``docs/howto/run-multiple-servers.md``.

The page's point is that two sockets are two worlds, so the checks read both
daemons after every block: it is not enough that `alpha` gained a window, `beta`
must be shown not to have gained one. The last block's claim — that a handle
built from a socket name and a handle built from that same socket's path are
unequal while addressing one daemon — is verified from both directions, since a
page that taught it backwards would be worse than a page that never mentioned
it.
"""

from __future__ import annotations

import typing as t

from libtmux.server import Server

if t.TYPE_CHECKING:
    from tests.docs.howto_harness import HowtoContext

ALPHA_SOCKET = "libtmux-howto-alpha"
BETA_SOCKET = "libtmux-howto-beta"


def _server_pid(server: Server) -> str:
    """Return the process id of the daemon behind a server handle.

    Parameters
    ----------
    server : libtmux.Server
        Handle to ask.

    Returns
    -------
    str
        tmux's ``#{pid}`` for that socket.
    """
    return server.cmd("display-message", "-p", "#{pid}").stdout[0]


def _socket_path(server: Server) -> str:
    """Return the socket path tmux resolved for a server handle.

    Parameters
    ----------
    server : libtmux.Server
        Handle to ask.

    Returns
    -------
    str
        tmux's ``#{socket_path}`` for that socket.
    """
    return server.cmd("display-message", "-p", "#{socket_path}").stdout[0]


def check_1(ctx: HowtoContext) -> None:
    """Two named sockets carry two independent ``build`` sessions.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    assert ctx.output[1].strip().splitlines() == ["['build']", "['build']"]

    alpha = ctx.namespace["alpha"]
    beta = ctx.namespace["beta"]
    assert isinstance(alpha, Server)
    assert isinstance(beta, Server)
    assert alpha.socket_name == ALPHA_SOCKET
    assert beta.socket_name == BETA_SOCKET

    assert alpha.is_alive()
    assert beta.is_alive()

    assert ctx.namespace["alpha_build"].session_name == "build"
    assert ctx.namespace["beta_build"].session_name == "build"

    # Same session name on both, so the only proof that these are two daemons
    # and not one is that tmux reports two processes on two sockets.
    assert _server_pid(alpha) != _server_pid(beta)
    assert _socket_path(alpha).endswith(ALPHA_SOCKET)
    assert _socket_path(beta).endswith(BETA_SOCKET)


def check_2(ctx: HowtoContext) -> None:
    """Block 2 adds a window to one socket, invisibly to the other.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    assert ctx.output[2].strip().splitlines() == ["2 2", "1 1"]

    alpha = ctx.namespace["alpha"]
    beta = ctx.namespace["beta"]

    alpha_windows = [window.window_name for window in alpha.windows]
    beta_windows = [window.window_name for window in beta.windows]
    assert "tests" in alpha_windows
    assert "tests" not in beta_windows, (
        "the window added to one socket showed up on the other, so these are "
        "not two servers"
    )
    assert len(alpha_windows) == 2
    assert len(beta_windows) == 1
    assert len(alpha.panes) == 2
    assert len(beta.panes) == 1


def check_3(ctx: HowtoContext) -> None:
    """One daemon, two handles, no equality — and both servers torn down.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    alpha = ctx.namespace["alpha"]
    same_daemon = ctx.namespace["same_daemon"]
    assert isinstance(same_daemon, Server)

    assert ctx.output[3].strip().splitlines() == [
        "None",
        "True ['build']",
        "False",
    ]

    # The trap, stated as the page states it: naming a socket never populates
    # the path attribute, and the two are compared together.
    assert alpha.socket_path is None
    assert same_daemon.socket_name is None
    assert str(same_daemon.socket_path).endswith(ALPHA_SOCKET)
    assert same_daemon != alpha
    assert alpha != same_daemon
    # Equality is not simply broken: it does answer for two like-built handles.
    assert Server(socket_name=ALPHA_SOCKET) == alpha

    assert not alpha.is_alive()
    assert not ctx.namespace["beta"].is_alive()
    assert not same_daemon.is_alive()
