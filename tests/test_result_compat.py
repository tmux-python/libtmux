"""Tests written before the implementation exists."""

from __future__ import annotations

import pytest

from libtmux.engines import CommandResult


def test_output_is_a_list_so_error_paths_keep_raising() -> None:
    """``isinstance(..., list)`` gates three error paths in src/; keep them live."""
    r = CommandResult(cmd=("tmux",), stderr=("boom",))
    assert isinstance(r.stderr, list)
    assert isinstance(r.stdout, list)
    assert isinstance(r.cmd, list)


def test_output_compares_equal_to_both_list_and_tuple() -> None:
    r = CommandResult(cmd=("tmux",), stdout=("a", "b"))
    assert r.stdout == ["a", "b"]
    assert r.stdout == ("a", "b")  # type: ignore[comparison-overlap]
    assert r.stdout == ["a", "b"]
    assert r.stdout != ["a", "z"]


def test_output_is_read_only() -> None:
    r = CommandResult(cmd=("tmux",), stdout=("a",))
    with pytest.raises(TypeError):
        r.stdout.append("b")  # type: ignore[attr-defined]


def test_result_is_hashable_and_comparable() -> None:
    a = CommandResult(cmd=("tmux",), stdout=("a",))
    b = CommandResult(cmd=("tmux",), stdout=("a",))
    assert a == b
    assert len({a, b}) == 1
