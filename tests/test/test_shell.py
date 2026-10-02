"""Tests for libtmux.test.shell."""

from __future__ import annotations

import typing as t

from libtmux.test.retry import retry_until
from libtmux.test.shell import deterministic_shell_command

if t.TYPE_CHECKING:
    import pytest

    from libtmux.server import Server


def test_command_skips_unset_inherit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inherited names that are unset are left out."""
    monkeypatch.setenv("LIBTMUX_SHELL_SET", "x y")
    monkeypatch.delenv("LIBTMUX_SHELL_UNSET", raising=False)

    command = deterministic_shell_command(
        inherit=("LIBTMUX_SHELL_SET", "LIBTMUX_SHELL_UNSET"),
    )

    assert "'LIBTMUX_SHELL_SET=x y'" in command
    assert "LIBTMUX_SHELL_UNSET" not in command


def test_shell_environment_is_clean(server: Server) -> None:
    """The shell sees only the preset variables, with a fixed prompt."""
    session = server.new_session(
        session_name="clean",
        window_command=deterministic_shell_command(),
        environment={"LIBTMUX_LEAK": "1"},
    )
    pane = session.active_pane
    assert pane is not None
    assert retry_until(lambda: pane.capture_pane()[:1] == ["$"], raises=False)

    pane.send_keys("echo names:$(compgen -e | tr '\\n' ' ')end", enter=True)
    assert retry_until(
        lambda: any(ln.startswith("names:") for ln in pane.capture_pane())
    )
    line = next(ln for ln in pane.capture_pane() if ln.startswith("names:"))
    names = set(line.removeprefix("names:").removesuffix("end").split())

    assert {"PS1", "TERM"} <= names
    assert not names & {"HOME", "TMUX", "TMUX_PANE", "LIBTMUX_LEAK"}
