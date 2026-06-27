"""Tests for the shared agent-state emitter."""

from __future__ import annotations

import pathlib

from libtmux.experimental.agents.hooks.emit import emit


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
