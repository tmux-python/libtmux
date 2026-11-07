"""Sidecar for ``docs/howto/create-panes.md``.

The page teaches three things about splitting, and each is checked against the
thing it would be confused with. That ``split()`` hands back the *new* pane is
checked by geometry, not by counting: a page that returned the pane it split
would still leave three panes in the window, but the log pane would not be in
the bottom-right corner. That ``window.panes`` is in layout order is checked by
requiring it to *disagree* with creation order — an order that happened to
match either way would prove nothing. And that a held pane goes stale is checked
by requiring the index it remembers to differ from the one tmux reports.

The error string the page quotes for a split with no room is quoted from tmux,
so it is provoked here rather than trusted.
"""

from __future__ import annotations

import typing as t
from pathlib import Path

import pytest

from libtmux import exc
from libtmux.server import Server

if t.TYPE_CHECKING:
    from libtmux.window import Window
    from tests.docs.howto_harness import HowtoContext

SOCKET_NAME = "libtmux-howto"


def pane_ids(text: str) -> list[str]:
    """Return the pane ids from one of the page's printed lists.

    Parameters
    ----------
    text : str
        A line such as ``created: ['%0', '%1']``.

    Returns
    -------
    list of str
        The ids, in the order printed.
    """
    _, _, listed = text.partition(": ")
    return [item.strip(" '[]") for item in listed.split(",")]


def check_1(ctx: HowtoContext) -> None:
    """Confirm the layout is built out of the panes ``split()`` returned.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    server = ctx.namespace["server"]
    assert isinstance(server, Server)
    assert server.socket_name == SOCKET_NAME

    window: Window = ctx.namespace["window"]
    editor = ctx.namespace["editor"]
    shell = ctx.namespace["shell"]
    logs = ctx.namespace["logs"]

    assert {pane.pane_id for pane in (editor, shell, logs)} == {
        pane.pane_id for pane in window.panes
    }

    assert (editor.at_left, editor.at_top) == (True, True)
    assert (shell.at_right, shell.at_top) == (True, True)
    assert (logs.at_right, logs.at_bottom, logs.at_top) == (True, True, False)

    reported = ctx.output[1].strip().splitlines()
    assert reported[0] == "panes: 3"
    assert reported[1] == "shell is 48 columns wide"

    prefix = "logs is 10 rows tall, in "
    assert reported[2].startswith(prefix)
    # Resolved, because /tmp is a symlink on some platforms and tmux reports
    # the pane's real path.
    assert Path(reported[2][len(prefix) :]).resolve() == Path("/tmp").resolve()

    _refuse_a_split_with_no_room(server)


def _refuse_a_split_with_no_room(server: Server) -> None:
    """Provoke the failure the page quotes tmux's wording for.

    Parameters
    ----------
    server : libtmux.Server
        Server to build the throwaway session on.
    """
    session = server.new_session(session_name="howto-no-room", kill_session=True)
    try:
        pane = session.active_window.active_pane
        assert pane is not None
        with pytest.raises(exc.LibTmuxException) as caught:
            for _ in range(40):
                pane = pane.split()
        # tmux words this differently across releases -- "no space for new
        # pane" through 3.6, "size or position no space for a new pane" from
        # 3.7 -- so pin the part every supported version agrees on.
        assert "no space for" in str(caught.value)
    finally:
        session.kill()


def check_2(ctx: HowtoContext) -> None:
    """Layout order disagrees with creation order, and focus has not moved.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    window: Window = ctx.namespace["window"]
    editor = ctx.namespace["editor"]
    banner = ctx.namespace["banner"]

    created, listed, focus = ctx.output[2].strip().splitlines()
    assert pane_ids(created) != pane_ids(listed), (
        "the page claims window.panes is not creation order, but the two "
        "agree here, so the example demonstrates nothing"
    )
    assert pane_ids(listed) == [pane.pane_id for pane in window.panes]
    assert pane_ids(listed)[0] == banner.pane_id

    assert focus == "focus stayed put: True"
    active = window.active_pane
    assert active is not None
    assert active.pane_id == editor.pane_id


def check_3(ctx: HowtoContext) -> None:
    """Confirm the held pane was stale, ``refresh()`` fixed it, and cleanup ran.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    editor = ctx.namespace["editor"]
    remembered, actual = (
        line.rsplit(" ", 1)[1] for line in ctx.output[3].strip().splitlines()
    )
    assert remembered != actual, (
        f"both blocks reported index {actual}, so nothing on the page went "
        f"stale and refresh() had nothing to fix"
    )
    assert actual == editor.pane_index == "1"

    server = ctx.namespace["server"]
    assert isinstance(server, Server)
    assert "layout" not in [session.session_name for session in server.sessions]
