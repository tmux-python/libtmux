"""Sidecar for ``docs/howto/find-the-session-youre-in.md``.

``setup`` builds two sessions on the runner's private tmux world and points
``$TMUX`` / ``$TMUX_PANE`` at a pane of one of them, so the page's bare
``Session.from_env()`` has a real pane to resolve through and block 2's roster
has a sibling to distinguish it from.

The session id inside ``$TMUX`` is deliberately a lie. tmux freezes that field
at pane spawn and libtmux never reads it, so a wrong value here is what proves
the page's answer comes from tmux rather than from the environment: if
``from_env`` ever started trusting ``$TMUX``, these checks go red.
"""

from __future__ import annotations

import typing as t

from libtmux.server import Server
from libtmux.session import Session

if t.TYPE_CHECKING:
    from tests.docs.howto_harness import HowtoContext

SESSION_NAME = "howto-here"
OTHER_SESSION_NAME = "howto-elsewhere"


def setup(ctx: HowtoContext) -> None:
    """Make this process look like a child of a pane in ``howto-here``.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    server = Server()
    session = server.new_session(session_name=SESSION_NAME)
    server.new_session(session_name=OTHER_SESSION_NAME)

    pane = session.active_window.active_pane
    assert pane is not None

    socket_path = server.cmd("display-message", "-p", "#{socket_path}").stdout[0]
    assert pane.pane_id is not None

    # A session id no session has. tmux freezes this field at pane spawn and
    # libtmux never reads it, so a wrong one here must not change the answer.
    ctx.monkeypatch.setenv("TMUX", f"{socket_path},1,999")
    ctx.monkeypatch.setenv("TMUX_PANE", pane.pane_id)


def check_1(ctx: HowtoContext) -> None:
    """Confirm the session found holds the pane, not the id in ``$TMUX``.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    session = ctx.namespace["session"]
    assert isinstance(session, Session)
    assert session.session_name == SESSION_NAME
    assert session.session_id != "$999"
    assert ctx.output[1].strip() == f"{SESSION_NAME} ({session.session_id})"


def check_2(ctx: HowtoContext) -> None:
    """Confirm the roster covers every session and marks only the caller.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    session = ctx.namespace["session"]
    # Splitting without stripping first: an unmarked row opens with the two
    # spaces the page prints, and stripping the block would eat them.
    lines = [line for line in ctx.output[2].splitlines() if line]

    assert {line[2:] for line in lines} == {SESSION_NAME, OTHER_SESSION_NAME}
    assert [line[2:] for line in lines if line.startswith("*")] == [
        session.session_name,
    ]
