"""Sidecar for ``docs/howto/send-keys-to-every-pane.md``.

The page's three blocks build on each other, so the checks mirror that:
block 1's window has to exist before block 2 can type into it, and block 2's
keystrokes have to have reached a shell before block 3 photographs the screen.

Block 3 does its own waiting, in front of the reader — that is the technique
the page teaches. These checks therefore verify the *result* of that wait
rather than repeating it, and they verify it the strict way: a line equal to
the answer, never a line containing it. A containment test would also match
the command tmux echoed onto the pane, and would pass in a world where no
shell ever ran.
"""

from __future__ import annotations

import typing as t

from libtmux.server import Server
from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    from libtmux.pane import Pane
    from tests.docs.howto_harness import HowtoContext

SOCKET_NAME = "libtmux-howto"


def answer(pane: Pane) -> str:
    """Return the line the page expects this pane to print.

    Parameters
    ----------
    pane : libtmux.Pane
        Pane the command was sent to.

    Returns
    -------
    str
        Expected output line, e.g. ``%2 is ready``.
    """
    return f"{pane.pane_id} is ready"


def answered(pane: Pane) -> bool:
    """Report whether the pane's own shell printed the answer.

    Whole-line equality on purpose: ``capture_pane`` includes the echoed
    command, so a containment test is true before the shell has run.

    Parameters
    ----------
    pane : libtmux.Pane
        Pane to read.

    Returns
    -------
    bool
        True when a captured line is exactly this pane's answer.
    """
    return any(line.strip() == answer(pane) for line in pane.capture_pane())


def check_1(ctx: HowtoContext) -> None:
    """Block 1 leaves a three-pane window on its own named server.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    server = ctx.namespace["server"]
    assert isinstance(server, Server)
    assert server.socket_name == SOCKET_NAME

    window = ctx.namespace["window"]
    panes = window.panes
    assert len(panes) == 3
    assert ctx.output[1].strip() == f"3 panes in {window.window_id}"

    for pane in panes:
        retry_until(lambda pane=pane: any(pane.capture_pane()))  # type: ignore[misc]


def check_2(ctx: HowtoContext) -> None:
    """Every pane runs the command and answers with its own id.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    window = ctx.namespace["window"]
    for pane in window.panes:
        retry_until(lambda pane=pane: answered(pane))  # type: ignore[misc]


def check_3(ctx: HowtoContext) -> None:
    """Block 3's own wait succeeds for every pane, and the session is gone.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    reported = ctx.output[3].strip().splitlines()
    assert len(reported) == 3
    for line in reported:
        pane_id, _, verdict = line.partition(" ")
        assert pane_id.startswith("%")
        assert verdict == "True", (
            f"block 3 reported {line!r}: its wait gave up before the pane "
            f"answered, so the page teaches a wait that does not work"
        )

    server = ctx.namespace["server"]
    assert isinstance(server, Server)
    assert "fanout" not in [session.session_name for session in server.sessions]
