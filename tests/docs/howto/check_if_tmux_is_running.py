"""Sidecar for ``docs/howto/check-if-tmux-is-running.md``.

The page shows one block that branches on
:meth:`~libtmux.Server.is_alive`. Both sides of that branch matter, so the
check runs the block twice: once against a live private server, then once
more in a throwaway namespace with the server killed.
"""

from __future__ import annotations

import subprocess
import typing as t

import pytest

from libtmux.server import Server

if t.TYPE_CHECKING:
    from tests.docs.howto_harness import HowtoContext


def setup(ctx: HowtoContext) -> None:
    """Start one session, so the page's live branch has something to find.

    The private tmux world the session lands in is the runner's doing, not
    this module's.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    Server().new_session(session_name="howto-probe")


def check_1(ctx: HowtoContext) -> None:
    """Both branches of the visible example report correctly.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    assert ctx.output[1].strip() == "tmux is running with 1 session(s)"

    server = ctx.namespace["server"]
    assert isinstance(server, Server)
    assert server.is_alive()
    server.raise_if_dead()

    server.kill()

    assert not server.is_alive()
    with pytest.raises(subprocess.CalledProcessError):
        server.raise_if_dead()

    assert ctx.run_block(1, namespace={}).strip() == "tmux is not running"
