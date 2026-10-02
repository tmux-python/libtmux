"""Tests for :mod:`libtmux.engines.control.routing`."""

from __future__ import annotations

import pytest

from libtmux.engines import CommandSeparator
from libtmux.engines.control.routing import blocks_queue

SEP = CommandSeparator(";")


@pytest.mark.parametrize(
    ("args", "blocks"),
    [
        (("display-message", "-p", "x"), False),
        (("list-panes", "-a"), False),
        (("send-keys", "-t", "%1", "run-shell", "Enter"), False),
        (("new-window", "-d"), False),
        (("run-shell", "sleep 1"), True),
        (("run-shell", "-b", "sleep 1"), False),
        (("run-shell", "-bC", "true"), False),
        (("run-shell", "-t", "%1", "-b", "true"), False),
        (("run-shell", "--", "-b"), True),
        (("run", "true"), True),
        (("if-shell", "true", "kill-window"), True),
        (("if-shell", "-b", "true", "kill-window"), False),
        (("wait-for", "chan"), True),
        (("wait-for", "-S", "chan"), True),
        (("wait", "chan"), True),
        (("confirm-before", "kill-window"), True),
        (("command-prompt",), True),
        (("display-popup", "top"), True),
        (("display-panes",), True),
        (("choose-tree",), True),
        (("attach-session", "-t", "x"), True),
        (("new-session", "-s", "x"), True),
        (("new-session", "-d", "-s", "x"), False),
        (("new-session", "-ds", "x"), False),
        (("kill-server",), True),
        (("display-message", "-p", "x", SEP, "wait-for", "chan"), True),
        (("display-message", "-p", "x", SEP, "list-panes"), False),
        ((), False),
    ],
)
def test_blocks_queue(args: tuple[str, ...], blocks: bool) -> None:
    """Commands that wait stay off the control connection."""
    assert blocks_queue(args) is blocks


def test_data_semicolon_is_not_a_boundary() -> None:
    """A ``;`` passed as data does not start a second command."""
    assert not blocks_queue(("display-message", "-p", ";", "wait-for", "x"))
