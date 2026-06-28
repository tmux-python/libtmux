"""Tests for ``analyze`` shell_command normalization."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.workspace import analyze


def _config(shell_command: t.Any) -> dict[str, t.Any]:
    """Build a minimal one-window/one-pane config carrying *shell_command*."""
    return {
        "session_name": "s",
        "windows": [{"panes": [{"shell_command": shell_command}]}],
    }


class BadCase(t.NamedTuple):
    """A shell_command list with an item ``analyze`` must reject."""

    test_id: str
    shell_command: t.Any


BAD_CASES = (
    BadCase("sole_int", [123]),
    BadCase("int_mixed_with_command", ["echo hi", 123]),
    BadCase("float", [1.5]),
    BadCase("nested_list", [["echo"]]),
)


@pytest.mark.parametrize("case", BAD_CASES, ids=[c.test_id for c in BAD_CASES])
def test_unsupported_shell_command_item_raises(case: BadCase) -> None:
    """A non-str/non-Mapping item raises rather than silently vanishing."""
    with pytest.raises(TypeError, match="unsupported shell_command item"):
        analyze(_config(case.shell_command))


class OkCase(t.NamedTuple):
    """A shell_command list ``analyze`` normalizes without raising."""

    test_id: str
    shell_command: t.Any
    expected: tuple[str, ...]


OK_CASES = (
    OkCase("plain_strings", ["a", "b"], ("a", "b")),
    OkCase("none_mixed_is_dropped", ["echo hi", None], ("echo hi",)),
    OkCase("sole_none_is_blank", [None], ()),
)


@pytest.mark.parametrize("case", OK_CASES, ids=[c.test_id for c in OK_CASES])
def test_supported_shell_command_items_normalize(case: OkCase) -> None:
    """Valid items normalize; a None mixed with commands is dropped (tmuxp parity)."""
    ws = analyze(_config(case.shell_command))
    assert ws.windows[0].panes[0].run == case.expected
