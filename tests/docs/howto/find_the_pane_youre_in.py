"""Sidecar for ``docs/howto/find-the-pane-youre-in.md``.

``setup`` arranges the case the page exists for: two panes in a window, the
focus given to the second, and ``$TMUX_PANE`` pointing at the first. A reader
following along at a prompt is the focused pane and would see the two answers
agree; here they must not, so a ``Pane.from_env()`` that resolved to the active
pane fails instead of looking right.

Block 2's other arm — the pane that does hold the focus — is exercised by
re-running the block against the focused pane, because a branch checked on one
side only is half a check.
"""

from __future__ import annotations

import os
import typing as t

from libtmux.pane import Pane
from libtmux.server import Server

if t.TYPE_CHECKING:
    from tests.docs.howto_harness import HowtoContext

SESSION_NAME = "howto-pane"
WINDOW_NAME = "worker"


def setup(ctx: HowtoContext) -> None:
    """Make this process look like a child of a pane that lost the focus.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    server = Server()
    session = server.new_session(session_name=SESSION_NAME)

    window = session.new_window(window_name=WINDOW_NAME, attach=True)
    pane = window.active_pane
    assert pane is not None
    window.split(attach=True)

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
    """Confirm the pane found is the one ``$TMUX_PANE`` names.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    pane = ctx.namespace["pane"]
    assert isinstance(pane, Pane)
    assert pane.pane_id == os.environ["TMUX_PANE"]

    assert ctx.output[1].strip() == (
        f"{pane.pane_id} in {WINDOW_NAME} of {SESSION_NAME}"
    )


def check_2(ctx: HowtoContext) -> None:
    """Focused and located are different questions, and answer differently.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    pane = ctx.namespace["pane"]
    focused = pane.window.active_pane
    assert focused is not None
    assert focused.pane_id != pane.pane_id, (
        "the caller's pane holds the focus, so the distinction this page "
        "teaches is not being tested"
    )

    assert ctx.output[2].strip() == "this pane is running in the background"

    reported = ctx.run_block(2, namespace={"pane": focused})
    assert reported.strip() == "this pane has the focus"
