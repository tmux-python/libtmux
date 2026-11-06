"""Retained capture values preserve text, routing and failure distinctions."""

from __future__ import annotations

import dataclasses
import os
import pathlib
import shlex
import subprocess
import sys
import typing as t

import pytest

from libtmux import Pane, PaneObservation, Server, exc
from libtmux.common import tmux_cmd


def test_observation_owns_text_and_actual_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A controlled backend permits alias mutation after the capture returns."""
    result = object.__new__(tmux_cmd)
    result.stdout = ["界 e\u0301 😀", "second"]
    result.stderr = []
    result.returncode = 0
    result.cmd = ["backend", "capture-pane", "-p", "-S", "0", "-E", "-", "-J"]
    pane = object.__new__(Pane)
    pane.pane_id = "%23"
    calls = []

    def capture(cmd: str, *args: object, target: str | int | None = None) -> tmux_cmd:
        calls.append((cmd, args, target))
        return result

    monkeypatch.setattr(pane, "cmd", capture)
    value = PaneObservation.capture(pane, start=0, end="-", join_wrapped=True)
    result.stdout[0] = "changed"
    result.cmd[0] = "changed"
    assert value.lines == ("界 e\u0301 😀", "second")
    assert value.command[0] == "backend"
    assert value.text == "界 e\u0301 😀\nsecond"
    assert (value.start, value.end, value.join_wrapped) == (0, "-", True)
    assert value.pane_id == "%23"
    assert calls == [("capture-pane", ("-p", "-S", "0", "-E", "-", "-J"), "%23")]
    assert 0 < value.started_ns <= value.finished_ns
    assert value.target_lifetime_verified is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(value, "pane_id", "%24")  # noqa: B010 - test runtime freezing
    assert not isinstance(value, Pane)
    assert not hasattr(value, "server") and not hasattr(value, "cmd")


def test_observation_bounds_and_backend_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A controlled backend distinguishes empty text, refusal, and native errors."""
    pane = object.__new__(Pane)
    pane.pane_id = "%23"
    calls = []
    result = object.__new__(tmux_cmd)
    result.stdout, result.stderr, result.cmd, result.returncode = [], [], [], 0
    failure = RuntimeError("remote backend failed")

    def capture(*args: object, **kwargs: object) -> tmux_cmd:
        calls.append(args)
        return result

    monkeypatch.setattr(pane, "cmd", capture)
    for limit in (0, -1, True, 1.5):
        with pytest.raises(ValueError, match="positive integer"):
            PaneObservation.capture(pane, max_text_codepoints=t.cast("int", limit))
    with pytest.raises(ValueError, match="start"):
        PaneObservation.capture(pane, start=t.cast("int", "invalid"))
    assert not calls
    assert PaneObservation.capture(pane).lines == ()

    class MutableLines(list[str]):
        """Simulate a backend replacing its buffer after a reader traverses it."""

        def __iter__(self) -> t.Iterator[str]:
            yield from super().__iter__()
            self[:] = ["oversized"]

    result.stdout = MutableLines(["x"])
    assert PaneObservation.capture(pane, max_text_codepoints=1).text == "x"
    result.stdout = ["😀", "e\u0301"]
    assert PaneObservation.capture(pane, max_text_codepoints=4).text == "😀\ne\u0301"
    with pytest.raises(ValueError, match="exceeds"):
        PaneObservation.capture(pane, max_text_codepoints=3)
    result.stderr = ["no such pane"]
    with pytest.raises(exc.LibTmuxException, match="no such pane"):
        PaneObservation.capture(pane)
    result.stdout, result.stderr = [], []
    for status in (1, None):
        result.returncode = status
        with pytest.raises(exc.LibTmuxException, match=f"status {status}"):
            PaneObservation.capture(pane)

    def failed(*args: object, **kwargs: object) -> tmux_cmd:
        raise failure

    monkeypatch.setattr(pane, "cmd", failed)
    with pytest.raises(RuntimeError) as raised:
        PaneObservation.capture(pane)
    assert raised.value is failure
    pane.pane_id = None
    with pytest.raises(ValueError, match="pane_id"):
        PaneObservation.capture(pane)


def test_observation_retains_cooperative_producer_after_removal(
    server: Server,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain an actual routed capture through redraw and native teardown."""
    server.config_file = os.devnull
    server.new_session(session_name="keeper", window_command="cat")
    producer = tmp_path / "observation.py"
    producer.write_text(
        "import subprocess, sys\n"
        "sys.stdout.write('界 e\\u0301 😀\\nretained\\n')\n"
        "sys.stdout.flush()\n"
        "subprocess.run(['tmux', '-L' + sys.argv[1], 'wait-for', '-S', "
        "'observation-ready'], check=True, timeout=0.5)\n"
        "sys.stdin.readline()\n"
        "sys.stdout.write('\\x1b[2J\\x1b[Hreplacement\\n')\n"
        "sys.stdout.flush()\n"
        "subprocess.run(['tmux', '-L' + sys.argv[1], 'wait-for', '-S', "
        "'observation-redrawn'], check=True, timeout=0.5)\n"
        "sys.stdin.readline()\n",
    )
    observed = server.new_session(
        session_name="observed",
        window_command=shlex.join(
            [sys.executable, str(producer), str(server.socket_name)]
        ),
    )
    pane = observed.active_pane
    assert pane is not None
    subprocess.run(
        ["tmux", f"-L{server.socket_name}", "wait-for", "observation-ready"],
        check=True,
        capture_output=True,
        timeout=0.5,
    )
    facade = Pane(
        server=Server(socket_path=str(tmp_path / "unused-socket")),
        pane_id=pane.pane_id,
    )
    monkeypatch.setattr(facade, "cmd", pane.cmd)
    assert not facade.server.is_alive()
    value = PaneObservation.capture(facade, start=-20)
    assert "界 e\u0301 😀" in value.lines
    assert "retained" in value.lines
    with pytest.raises(ValueError, match="exceeds"):
        PaneObservation.capture(facade, max_text_codepoints=1)
    before = dataclasses.astuple(value)
    assert f"-L{server.socket_name}" in value.command
    assert str(tmp_path / "unused-socket") not in value.command
    pane.send_keys("", enter=True)
    subprocess.run(
        ["tmux", f"-L{server.socket_name}", "wait-for", "observation-redrawn"],
        check=True,
        capture_output=True,
        timeout=0.5,
    )
    later = PaneObservation.capture(facade, start=-20)
    assert "replacement" in later.lines
    assert "replacement" not in value.lines
    assert later.started_ns >= value.finished_ns
    assert dataclasses.astuple(value) == before
    pane.kill()
    assert dataclasses.astuple(value) == before and "retained" in value.text
    with pytest.raises(exc.LibTmuxException):
        PaneObservation.capture(facade)
    assert server.is_alive()
    server.kill()
    assert not server.is_alive()
    assert dataclasses.astuple(value) == before and "retained" in value.text
    with pytest.raises(exc.LibTmuxException):
        PaneObservation.capture(facade)
