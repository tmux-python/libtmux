"""The deprecated wrapper must not sit on the dispatch path."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.common import dispatch, tmux_cmd
from libtmux.engines import CommandResult
from libtmux.server import Server

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.engines import CommandRequest
    from libtmux.session import Session


class CountingEngine:
    """Count dispatches so a test can prove how many objects were built."""

    def __init__(self, stdout: Sequence[str] = ()) -> None:
        self.calls = 0
        self._stdout = tuple(stdout)

    def run(self, request: CommandRequest) -> CommandResult:
        self.calls += 1
        return CommandResult(cmd=("tmux", *request.args), stdout=self._stdout)

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        return [self.run(r) for r in requests]


def test_server_cmd_does_not_build_a_tmux_cmd(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Dispatch goes engine-direct; the back-compat class is never constructed."""
    built = 0
    original = tmux_cmd.__init__

    def counting_init(self: tmux_cmd, *args: t.Any, **kwargs: t.Any) -> None:
        nonlocal built
        built += 1
        original(self, *args, **kwargs)

    monkeypatch.setattr(tmux_cmd, "__init__", counting_init)

    engine = CountingEngine(stdout=("ok",))
    result = Server(socket_name="hotpath", engine=engine).cmd("list-sessions")

    assert result.stdout == ["ok"]
    assert engine.calls == 1
    assert built == 0


def test_dispatch_applies_the_has_session_adaptation() -> None:
    """Tmux answers has-session on stderr; libtmux has always read it on stdout."""
    engine = CountingEngine()

    def run(request: CommandRequest) -> CommandResult:
        return CommandResult(
            cmd=("tmux", *request.args),
            stderr=("can't find session: nope",),
            returncode=1,
        )

    engine.run = run  # type: ignore[method-assign]
    result = dispatch(engine, "has-session", "-t", "nope")

    assert result.stdout == ["can't find session: nope"]


def test_tmux_cmd_still_works_standalone(session: Session) -> None:
    """The back-compat class keeps its own behavior, built on the same helper."""
    proc = tmux_cmd(f"-L{session.server.socket_name}", "display-message", "-p", "hi")

    assert proc.stdout == ["hi"]
    assert proc.returncode == 0


def test_every_command_path_is_logged(session: Session, caplog) -> None:  # type: ignore[no-untyped-def]
    """``raise_if_dead`` logs like any other command.

    It used to call the engine directly, so it was the one tmux command in the
    library that produced no debug record — invisible to anyone reading the log
    to find out what libtmux ran.
    """
    import logging

    with caplog.at_level(logging.DEBUG, logger="libtmux.common"):
        session.server.raise_if_dead()

    dispatched = [
        record
        for record in caplog.records
        if getattr(record, "tmux_subcommand", None) == "list-sessions"
    ]
    assert dispatched, "raise_if_dead should log the command it issues"


def test_raise_if_dead_still_raises_called_process_error() -> None:
    """Routing through dispatch must not change the documented exception."""
    import subprocess

    from libtmux.server import Server

    with pytest.raises(subprocess.CalledProcessError):
        Server(socket_name="definitely_not_running_xyz").raise_if_dead()
