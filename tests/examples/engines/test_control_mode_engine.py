"""Drive libtmux over a persistent ``tmux -C`` connection.

The engine seam exists so a transport other than "fork the tmux binary once per
command" can be plugged in. This is the proof: a control-mode engine holds one
long-lived ``tmux -C`` process and writes command lines to it, and the whole
object API -- including the format-heavy listing queries -- works through it
unchanged.

It is deliberately minimal. A production control-mode engine also handles
notifications, reconnection, and pipelining a batch through
:meth:`~libtmux.engines.base.TmuxEngine.run_batch`; none of that is needed to
show that the seam fits.
"""

from __future__ import annotations

import subprocess
import typing as t

import pytest

from libtmux.engines import (
    CommandResult,
    ServerConnection,
    TmuxEngine,
    render_control_line,
)
from libtmux.server import Server

if t.TYPE_CHECKING:
    from libtmux.engines import CommandRequest
    from libtmux.session import Session


class ControlModeEngine(TmuxEngine):
    """Execute tmux commands over one persistent ``tmux -C`` connection.

    tmux replies to each command with a ``%begin`` / ``%end`` block; anything
    else beginning with ``%`` is an asynchronous notification this engine
    ignores.
    """

    def __init__(self, connection: ServerConnection) -> None:
        argv = [
            connection.resolve_bin(),
            *connection.args,
            "-C",
            "-q",
            "new-session",
            "-A",
            "-s",
            "_control",
        ]
        self._process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._read_block()  # tmux greets with a handshake block

    def _read_block(self) -> tuple[list[str], int]:
        """Read one ``%begin``-delimited reply, returning its lines and status."""
        assert self._process.stdout is not None
        lines: list[str] = []
        returncode = 0
        while True:
            line = self._process.stdout.readline()
            if not line:
                break
            line = line.rstrip("\n")
            if line.startswith("%begin"):
                lines = []
            elif line.startswith("%error"):
                returncode = 1
                break
            elif line.startswith("%end"):
                break
            elif not line.startswith("%"):
                lines.append(line)
        return lines, returncode

    def run(self, request: CommandRequest) -> CommandResult:
        """Write one command line and read back its reply block."""
        assert self._process.stdin is not None
        self._process.stdin.write(render_control_line(request.args) + "\n")
        self._process.stdin.flush()
        stdout, returncode = self._read_block()
        return CommandResult(
            cmd=("tmux", "-C", *request.args),
            stdout=tuple(stdout),
            returncode=returncode,
        )

    def close(self) -> None:
        """Shut the connection down."""
        try:
            if self._process.stdin is not None:
                self._process.stdin.close()
            self._process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            self._process.kill()


@pytest.fixture
def control_mode_server(session: Session) -> t.Iterator[Server]:
    """Yield a server dispatching over a persistent control-mode connection."""
    engine = ControlModeEngine(ServerConnection.from_server(session.server))
    try:
        yield Server(socket_name=session.server.socket_name, engine=engine)
    finally:
        engine.close()


def test_commands_run_over_one_persistent_connection(
    control_mode_server: Server,
) -> None:
    """A command dispatches without forking a tmux binary."""
    result = control_mode_server.cmd("display-message", "-p", "hello")

    assert result.stdout == ["hello"]
    assert result.ok


def test_object_api_works_over_control_mode(control_mode_server: Server) -> None:
    """Listing queries hydrate, so traversal works through a non-subprocess engine.

    This is the part that proves the seam: ``sessions`` asks tmux for its whole
    format-field set, parses the reply, and builds objects -- none of which knows
    or cares that no subprocess was involved.
    """
    control_mode_server.new_session("over_control_mode")

    names = [s.session_name for s in control_mode_server.sessions]

    assert "over_control_mode" in names
    session = control_mode_server.sessions.get(session_name="over_control_mode")
    assert session is not None
    assert session.windows
    assert session.windows[0].panes
