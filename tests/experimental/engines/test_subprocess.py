"""Tests for the classic SubprocessEngine."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.engines import SubprocessEngine
from libtmux.experimental.engines.base import CommandRequest


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
