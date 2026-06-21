"""Tests for engine base helpers."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.engines.base import render_control_line


class WireCase(t.NamedTuple):
    """An argv and the control-mode wire line it should render to."""

    test_id: str
    argv: tuple[str, ...]
    expected: str


WIRE_CASES = (
    WireCase(
        test_id="plain",
        argv=("rename-window", "-t", "@1", "edit"),
        expected="rename-window -t @1 edit",
    ),
    WireCase(
        test_id="quotes_spaces",
        argv=("set-option", "@x", "a b"),
        expected="set-option @x 'a b'",
    ),
    WireCase(
        test_id="chain_keeps_bare_semicolon",
        argv=("rename-window", "a", ";", "kill-window", "@2"),
        expected="rename-window a ; kill-window @2",
    ),
)


@pytest.mark.parametrize(
    list(WireCase._fields),
    WIRE_CASES,
    ids=[c.test_id for c in WIRE_CASES],
)
def test_render_control_line(
    test_id: str,
    argv: tuple[str, ...],
    expected: str,
) -> None:
    """A standalone ``;`` stays a separator; other tokens are shell-quoted."""
    assert render_control_line(argv) == expected
