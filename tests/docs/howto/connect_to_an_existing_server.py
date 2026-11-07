"""Sidecar for ``docs/howto/connect-to-an-existing-server.md``.

The page connects to a server it did not start, so ``setup`` starts one on its
behalf — the reader's equivalent is the tmux they already had open.

Two of the page's claims are the ones worth defending. The listing block claims
a socket file can outlive its daemon, so the last check kills the server and
requires the file to still be there. The connect block claims its ``else``
branch is reachable, which the page can only show one side of, so the same check
re-runs that block against the now-dead socket and reads the other answer back.
"""

from __future__ import annotations

import os
import pathlib
import typing as t

from libtmux.server import Server

if t.TYPE_CHECKING:
    from tests.docs.howto_harness import HowtoContext

SOCKET_NAME = "libtmux-howto"
SESSION_NAME = "editor"


def _socket_dir() -> pathlib.Path:
    """Return the directory tmux keeps ``-L`` sockets in.

    Computed the way the page computes it, from the environment the runner
    already isolated.

    Returns
    -------
    pathlib.Path
        Directory holding this run's named sockets.
    """
    root = pathlib.Path(os.environ.get("TMUX_TMPDIR", "/tmp"))
    return root / f"tmux-{os.geteuid()}"


def setup(ctx: HowtoContext) -> None:
    """Start the server the page expects to find already running.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    Server(socket_name=SOCKET_NAME).new_session(session_name=SESSION_NAME)


def check_1(ctx: HowtoContext) -> None:
    """Block 1 lists this page's socket, under tmux's own directory.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    socket_dir = ctx.namespace["socket_dir"]
    assert isinstance(socket_dir, pathlib.Path)
    assert socket_dir == _socket_dir()

    assert ctx.output[1].strip().splitlines() == [SOCKET_NAME]
    assert [path.name for path in ctx.namespace["sockets"]] == [SOCKET_NAME]


def check_2(ctx: HowtoContext) -> None:
    """Block 2 takes the live branch and reports the real session.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    server = ctx.namespace["server"]
    assert isinstance(server, Server)
    assert server.socket_name == SOCKET_NAME
    assert server.is_alive()

    assert ctx.output[2].strip() == f"{SESSION_NAME} 1 window(s)"


def check_3(ctx: HowtoContext) -> None:
    """Addressing by path reaches the same daemon; the file outlives it.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    by_path = ctx.namespace["by_path"]
    assert isinstance(by_path, Server)
    assert by_path.is_alive()
    assert ctx.output[3].strip().splitlines() == ["True", f"['{SESSION_NAME}']"]

    server = ctx.namespace["server"]

    # The case that separates a liveness check from a truthiness test on the
    # lenient accessor the page warns about: a server that is up and holding
    # nothing. tmux only allows that with exit-empty off, so arrange it.
    server.cmd("set-option", "-s", "exit-empty", "off")
    for session in server.sessions:
        session.kill()
    assert server.is_alive()
    assert not server.sessions
    assert ctx.run_block(2, namespace={}).strip() == "", (
        "block 2 reported no server for a server that is up with no sessions, "
        "so it is testing what the page tells readers not to trust"
    )

    socket = _socket_dir() / SOCKET_NAME
    server.kill()

    # The page tells readers a name in the listing may be a dead end. It is
    # only worth telling them if tmux really does leave the file behind.
    assert socket.is_socket()
    assert not Server(socket_name=SOCKET_NAME).is_alive()

    # The other side of block 2's branch, which the page can only print once.
    assert (
        ctx.run_block(2, namespace={}).strip()
        == "no tmux server is listening on that socket"
    )
