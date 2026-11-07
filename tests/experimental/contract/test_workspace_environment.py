"""Tests for environment merging when compiling a workspace to operations."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.ops import SplitWindow
from libtmux.experimental.workspace import Pane, Window, Workspace, compile_workspace


class EnvCase(t.NamedTuple):
    """A window/split-pane env pair and the merged env the split op should carry."""

    test_id: str
    window_env: dict[str, str]
    pane_env: dict[str, str]
    expected: dict[str, str] | None


ENV_CASES = (
    EnvCase("window_only", {"TERM": "xterm"}, {}, {"TERM": "xterm"}),
    EnvCase("pane_only", {}, {"DEBUG": "1"}, {"DEBUG": "1"}),
    EnvCase(
        "window_and_pane_merge",
        {"TERM": "xterm"},
        {"DEBUG": "1"},
        {"TERM": "xterm", "DEBUG": "1"},
    ),
    EnvCase("pane_overrides_window", {"K": "win"}, {"K": "pane"}, {"K": "pane"}),
    EnvCase("none_when_both_empty", {}, {}, None),
)


@pytest.mark.parametrize("case", ENV_CASES, ids=[c.test_id for c in ENV_CASES])
def test_split_pane_environment_merges_window_and_pane(case: EnvCase) -> None:
    """A split pane's env merges the window env with its own (the pane wins).

    The window env is "inherited by its panes", so a split pane carrying its own
    env must not discard the window env -- it merges, matching the first pane's
    creator env.
    """
    ws = Workspace(
        name="s",
        windows=[
            Window(
                "w",
                environment=case.window_env,
                panes=[
                    Pane(run="vim"),
                    Pane(run="htop", environment=case.pane_env),
                ],
            ),
        ],
    )
    splits = [
        op for op in compile_workspace(ws).operations if isinstance(op, SplitWindow)
    ]
    assert len(splits) == 1
    assert splits[0].environment == case.expected
