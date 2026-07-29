"""Sidecar for ``docs/howto/find-the-window-youre-in.md``.

``setup`` builds a two-pane window on the runner's private tmux world, focuses
the *other* pane, and points ``$TMUX_PANE`` at the first one. That is the
arrangement the page is about: a process whose window is not the window anyone
is looking at, so a ``Window.from_env()`` that quietly returned the active
window would be caught here rather than admired.

Block 2 lists the sessions holding that window, which in the ordinary case is
one. The multi-holder case is the point of the section, so the check links the
window into a second session and re-runs the block — an example that only ever
printed one line would be teaching an accessor the reader has no reason to
call.
"""

from __future__ import annotations

import typing as t

from libtmux.server import Server
from libtmux.window import Window

if t.TYPE_CHECKING:
    from tests.docs.howto_harness import HowtoContext

SESSION_NAME = "howto-window"
GUEST_SESSION_NAME = "howto-guest"
WINDOW_NAME = "worker"


def setup(ctx: HowtoContext) -> None:
    """Make this process look like a child of a pane in a background window.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    server = Server()
    session = server.new_session(session_name=SESSION_NAME)

    window = session.new_window(window_name=WINDOW_NAME, attach=False)
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
    """Confirm the window found contains the caller, not the focus.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    window = ctx.namespace["window"]
    assert isinstance(window, Window)
    assert window.window_name == WINDOW_NAME
    assert len(window.panes) == 2

    session = window.session
    active = session.active_window
    assert active is not None
    assert active.window_id != window.window_id, (
        "the caller's window is the focused one, so this page's central "
        "claim is not being tested"
    )

    assert ctx.output[1].strip() == (f"{WINDOW_NAME} ({window.window_id}), 2 pane(s)")


def check_2(ctx: HowtoContext) -> None:
    """One holder normally, every holder once the window is shared.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    window = ctx.namespace["window"]
    assert ctx.output[2].split() == [SESSION_NAME]

    server = window.server
    guest = server.new_session(session_name=GUEST_SESSION_NAME)
    server.cmd(
        "link-window",
        "-d",
        "-s",
        window.window_id,
        "-t",
        f"{guest.session_id}:",
    )

    assert sorted(ctx.run_block(2).split()) == sorted(
        [SESSION_NAME, GUEST_SESSION_NAME],
    )
