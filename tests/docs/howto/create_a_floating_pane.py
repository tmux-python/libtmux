"""Sidecar for ``docs/howto/create-a-floating-pane.md``.

Two of the page's claims would otherwise go untested on this machine. The
version guard never fires when the page runs — ``MIN_TMUX_VERSION`` keeps the
page off any tmux that would trip it — so it is re-run against a
:func:`~libtmux.common.has_gte_version` that reports an older tmux, and required
to stop the reader before a session exists. And "a float is an ordinary pane" is
only worth printing if the float's own shell really answered, so the second
block's verdict is checked strictly: a containment test on ``capture_pane``
output would match the command tmux echoed onto the pane and pass in a world
where nothing ran.
"""

from __future__ import annotations

import typing as t

import pytest

from libtmux.server import Server

if t.TYPE_CHECKING:
    from libtmux.window import Window
    from tests.docs.howto_harness import HowtoContext

SOCKET_NAME = "libtmux-howto"

#: Floating panes are a tmux 3.7 feature, so the page's first block refuses to
#: go on without one. The harness reads this and skips the page below it,
#: rather than letting the guide's own guard fail the suite.
MIN_TMUX_VERSION = "3.7"


def check_1(ctx: HowtoContext) -> None:
    """Confirm the overlay floats where asked, and that the guard works.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    server = ctx.namespace["server"]
    assert isinstance(server, Server)
    assert server.socket_name == SOCKET_NAME

    window: Window = ctx.namespace["window"]
    overlay = ctx.namespace["overlay"]
    assert overlay.pane_floating_flag == "1"
    assert overlay.pane_id in [pane.pane_id for pane in window.panes]

    assert ctx.output[1].strip().splitlines() == [
        "floating: True",
        "size: 60 x 12",
        "origin: 4 2",
    ]

    _guard_stops_an_older_tmux(ctx)


def _guard_stops_an_older_tmux(ctx: HowtoContext) -> None:
    """Re-run block 1 against a tmux the page should refuse to use.

    The block is run in a namespace of its own, so the page's own session is
    left alone. Reaching :meth:`~libtmux.Server.new_session` at all would mean
    the guard let a script proceed to build state it would then have to clean
    up — the failure the page's prose promises to prevent.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "libtmux.common.has_gte_version",
            lambda _version, tmux_bin=None: False,
        )
        with pytest.raises(RuntimeError, match=r"3\.7"):
            ctx.run_block(1, namespace={})


def check_2(ctx: HowtoContext) -> None:
    """Confirm the float ran the command and printed the answer.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    overlay = ctx.namespace["overlay"]
    assert ctx.output[2].strip() == "True", (
        f"block 2 printed {ctx.output[2]!r}: the float's own shell never "
        f"answered, so the page's claim that a float is an ordinary pane is "
        f"untested"
    )
    assert any(
        row.strip() == f"floating {overlay.pane_id}" for row in overlay.capture_pane()
    )


def check_3(ctx: HowtoContext) -> None:
    """Both floats were found by their flag, and closing them spared the tiling.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    tiled = ctx.namespace["tiled"]
    extra = ctx.namespace["extra"]
    assert extra.pane_floating_flag == "1"
    assert tiled.pane_floating_flag == "0"

    counted, left = ctx.output[3].strip().splitlines()
    assert counted == "floating: 2 of 3 panes"
    assert left == f"left: ['{tiled.pane_id}']"

    server = ctx.namespace["server"]
    assert isinstance(server, Server)
    assert "floating" not in [session.session_name for session in server.sessions]
