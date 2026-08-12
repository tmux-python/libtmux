"""Drive libtmux with no tmux server, using a custom engine.

The engine seam's payoff is that :class:`~libtmux.Server` will dispatch through
any object satisfying :class:`~libtmux.engines.base.TmuxEngine`. That makes it
possible to assert on the tmux commands a piece of code *would* run, and to
answer them from a script, without a tmux server anywhere.
"""

from __future__ import annotations

import typing as t

from libtmux.engines import CommandResult
from libtmux.server import Server

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.engines import CommandRequest


class RecordingEngine:
    """Record every dispatch and answer from a canned script.

    Attributes
    ----------
    requests : list[tuple[str, ...]]
        The argv of every request, in dispatch order.
    """

    def __init__(self, stdout: Sequence[str] = ()) -> None:
        self.requests: list[tuple[str, ...]] = []
        self._stdout = tuple(stdout)

    def run(self, request: CommandRequest) -> CommandResult:
        """Record *request* and return the canned result."""
        self.requests.append(request.args)
        return CommandResult(cmd=("tmux", *request.args), stdout=self._stdout)

    def run_batch(self, requests: Sequence[CommandRequest]) -> list[CommandResult]:
        """Run each request in order."""
        return [self.run(request) for request in requests]


def test_engine_records_dispatch_without_tmux() -> None:
    """A custom engine sees the tmux argv and supplies the answer."""
    engine = RecordingEngine(stdout=("my_session",))
    server = Server(engine=engine)

    result = server.cmd("display-message", "-p", "#{session_name}")

    assert result.stdout == ["my_session"]
    assert engine.requests == [("display-message", "-p", "#{session_name}")]


def test_engine_sees_no_connection_flags() -> None:
    """Connection flags live on the engine, so a request carries only the command.

    An engine implementing its own transport never has to parse ``-L``/``-S``
    back out of the argv it is handed.
    """
    engine = RecordingEngine()
    Server(socket_name="example_recording", engine=engine).cmd("list-sessions")

    assert engine.requests == [("list-sessions",)]


def test_target_is_rendered_into_the_request() -> None:
    """``target=`` reaches the engine as the ``-t`` flag tmux expects."""
    engine = RecordingEngine()
    Server(engine=engine).cmd("kill-window", target="@3")

    assert engine.requests == [("kill-window", "-t", "@3")]
