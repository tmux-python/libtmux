"""Tests for the shared agent-state emitter."""

from __future__ import annotations

import pathlib
import typing as t

import pytest

from libtmux.experimental.agents.hooks import emit as emit_mod
from libtmux.experimental.agents.hooks.emit import emit, main


def test_local_uses_set_option() -> None:
    """Local path (TMUX + TMUX_PANE set) calls tmux set-option via runner."""
    calls: list[list[str]] = []
    emit(
        "running",
        runner=lambda argv, **kw: calls.append(argv),
        env={"TMUX": "/tmp/x,1,0", "TMUX_PANE": "%4"},
    )
    assert calls[0][:5] == ["tmux", "set-option", "-p", "-t", "%4"]
    assert calls[0][5:] == ["@agent_state", "running"]


def test_remote_writes_osc_to_tty(tmp_path: pathlib.Path) -> None:
    """Remote path (no TMUX) writes OSC 3008 escape bytes to tty_path."""
    tty = tmp_path / "tty"
    tty.write_bytes(b"")
    emit("idle", tty_path=str(tty), env={})  # no TMUX → remote path
    data = tty.read_bytes()
    assert b"\033]3008;state=idle\033\\" in data


class MainNameCase(t.NamedTuple):
    """A ``main`` argv and the ``name`` that should reach ``emit``."""

    test_id: str
    argv: list[str]
    expected_name: str | None


MAIN_NAME_CASES = (
    MainNameCase("name_with_value", ["running", "--name", "claude"], "claude"),
    MainNameCase("name_flag_last_no_value", ["running", "--name"], None),
    MainNameCase("no_name_flag", ["running"], None),
)


@pytest.mark.parametrize(
    "case",
    MAIN_NAME_CASES,
    ids=[c.test_id for c in MAIN_NAME_CASES],
)
def test_main_parses_name_flag(
    case: MainNameCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--name`` as the final arg yields name=None instead of an IndexError."""
    captured: dict[str, str | None] = {}

    def _fake_emit(state: str, *, name: str | None = None) -> None:
        captured["name"] = name

    monkeypatch.setattr(emit_mod, "emit", _fake_emit)
    assert main(case.argv) == 0
    assert captured["name"] == case.expected_name
