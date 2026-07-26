"""Tests for the classic SubprocessEngine."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.engines import SubprocessEngine
from libtmux.experimental.engines.base import CommandRequest
from libtmux.experimental.ops import SendKeys, run
from libtmux.experimental.ops._types import PaneId

if t.TYPE_CHECKING:
    from libtmux.session import Session


class _FakeProcess:
    """Minimal stand-in for a Popen process."""

    returncode = 0

    def communicate(self) -> tuple[str, str]:
        """Return empty stdout/stderr."""
        return ("", "")


def test_subprocess_engine_decodes_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    """The engine decodes tmux output as UTF-8 (matching common.tmux_cmd)."""
    captured: dict[str, t.Any] = {}

    def fake_popen(_cmd: t.Any, **kwargs: t.Any) -> _FakeProcess:
        captured.update(kwargs)
        return _FakeProcess()

    monkeypatch.setattr(
        "libtmux.experimental.engines.subprocess.subprocess.Popen",
        fake_popen,
    )

    engine = SubprocessEngine(tmux_bin="tmux")
    engine.run(CommandRequest.from_args("display-message", "-p", "x"))

    assert captured["encoding"] == "utf-8"


def test_subprocess_preserves_global_option_semicolon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Global option values stay raw while command arguments are encoded."""
    captured: list[str] = []

    def fake_popen(cmd: list[str], **_kwargs: t.Any) -> _FakeProcess:
        captured.extend(cmd)
        return _FakeProcess()

    monkeypatch.setattr(
        "libtmux.experimental.engines.subprocess.subprocess.Popen",
        fake_popen,
    )
    request = CommandRequest.from_args(
        "-L",
        "socket;",
        "display-message",
        "literal;",
    )

    SubprocessEngine(tmux_bin="tmux").run(request)

    assert captured == [
        "tmux",
        "-L",
        "socket;",
        "display-message",
        "literal\\;",
    ]


def test_subprocess_literal_target_cannot_start_command(session: Session) -> None:
    """A trailing semicolon in a typed target remains literal at tmux argv."""
    pane = session.active_pane
    assert pane is not None
    pane_id = pane.pane_id
    assert pane_id is not None
    operation = SendKeys(
        target=PaneId(f"{pane_id};"),
        keys="kill-server",
    )

    result = run(operation, SubprocessEngine.for_server(session.server))

    assert result.failed
    assert session.server.is_alive()


def test_subprocess_preserves_literal_trailing_semicolon(session: Session) -> None:
    """A semicolon at the end of typed pane input remains part of the input."""
    pane = session.active_pane
    assert pane is not None
    pane_id = pane.pane_id
    assert pane_id is not None
    marker = "LIBTMUX_LITERAL_SEMICOLON"
    operation = SendKeys(
        target=PaneId(pane_id),
        keys=f"{marker};",
        literal=True,
    )

    result = run(operation, SubprocessEngine.for_server(session.server))
    captured = session.server.cmd("capture-pane", "-p", "-t", pane_id)

    assert result.ok
    assert any(f"{marker};" in line for line in captured.stdout)
