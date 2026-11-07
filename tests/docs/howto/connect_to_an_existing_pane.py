"""Sidecar for ``docs/howto/connect-to-an-existing-pane.md``.

The page's warning rests on a fact about tmux that a reader cannot see from the
page's own output: splitting one pane twice does not leave the newest pane last.
``setup`` therefore records the order the panes were *created* in, and
``check_2`` compares it against the order ``Window.panes`` reports. The day
those two agree, the warning is wrong and this module fails.
"""

from __future__ import annotations

import typing as t

import pytest

from libtmux import exc
from libtmux.pane import Pane
from libtmux.server import Server

if t.TYPE_CHECKING:
    from tests.docs.howto_harness import HowtoContext

#: Pane ids in the order ``setup`` created them, oldest first.
CREATED: list[str] = []


def setup(ctx: HowtoContext) -> None:
    """Leave a session whose active window was split twice.

    Both splits act on the window's active pane, which never moves because
    :meth:`~libtmux.Window.split` does not attach — the same sequence the
    page's warning describes.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    session = Server().new_session(session_name="editor", window_name="code")
    window = session.active_window

    original = window.active_pane
    assert original is not None

    CREATED.clear()
    for pane in (original, window.split(), window.split()):
        assert pane.pane_id is not None
        CREATED.append(pane.pane_id)


def check_1(ctx: HowtoContext) -> None:
    """Verify the listing reports three panes, in index order.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    window = ctx.namespace["window"]
    panes = window.panes
    assert len(panes) == 3

    assert ctx.output[1].strip().splitlines() == [
        f"{p.pane_index}\t{p.pane_id}\t{p.pane_width}x{p.pane_height}" for p in panes
    ]


def check_2(ctx: HowtoContext) -> None:
    """Layout order is not creation order, which is what the page warns about.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    window = ctx.namespace["window"]
    pane = ctx.namespace["pane"]
    panes = window.panes

    assert pane.pane_id == window.active_pane.pane_id
    assert ctx.output[2].strip().splitlines() == [
        f"active: {pane.pane_id}",
        f"first:  {panes[0].pane_id}",
        f"last:   {panes[-1].pane_id}",
    ]

    ordered = [p.pane_id for p in panes]
    assert ordered == [CREATED[0], CREATED[2], CREATED[1]], (
        f"panes created {CREATED} came back as {ordered}; the page's warning "
        f"describes the newest pane landing at index 1"
    )
    assert ordered[-1] != CREATED[-1], "`panes[-1]` is not the newest pane"


def check_3(ctx: HowtoContext) -> None:
    """Verify a stored id resolves back to the same pane and window.

    Block 1's guarded branch is exercised last, once nothing else needs the
    session: that block builds its own :class:`~libtmux.Server`, so the only
    way to reach the branch is to take the session away.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    server = ctx.namespace["server"]
    session = ctx.namespace["session"]
    window = ctx.namespace["window"]
    found = ctx.namespace["found"]

    assert ctx.output[3].strip() == "True True"
    assert found.pane_id == ctx.namespace["pane_id"]
    assert found.window.window_id == window.window_id

    with pytest.raises(exc.TmuxObjectDoesNotExist):
        Pane.from_pane_id(server, "%999")

    session.kill()
    assert ctx.run_block(1, namespace={}).strip() == (
        "no session named 'editor' — use a session name of your own"
    )
