"""Deliver tmux notifications the instant they arrive.

The sibling control-mode example collects notifications as a side effect of
reading replies, so output surfaces the next time a command runs. That is enough
to wait for a pane, but it is not delivery -- nothing arrives while the caller
is idle.

Pushing them needs one reader thread. It owns the stream, separates a command's
``%begin`` / ``%end`` reply from everything else, hands replies to whoever is
waiting through a queue, and forwards the rest to a callback. Commands still
behave synchronously: :meth:`run` writes and then blocks on the queue.
"""

from __future__ import annotations

import queue
import subprocess
import threading
import time
import typing as t

import pytest

from libtmux.engines import (
    CommandResult,
    ServerConnection,
    TmuxEngine,
    render_control_line,
    unescape_control_output,
)
from libtmux.server import Server

if t.TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from libtmux.engines import CommandRequest
    from libtmux.session import Session


class PushControlModeEngine(TmuxEngine):
    """A control-mode engine that pushes notifications as they arrive.

    Parameters
    ----------
    connection : ServerConnection
        Which tmux server to attach to.
    target : str
        Session name to attach to; a control client sees no output until it
        attaches.
    on_notification : Callable[[str], None]
        Called from the reader thread for every non-reply line.
    """

    def __init__(
        self,
        connection: ServerConnection,
        target: str,
        on_notification: Callable[[str], None],
    ) -> None:
        self._process = subprocess.Popen(
            [
                connection.resolve_bin(),
                *connection.args,
                "-C",
                "attach-session",
                "-t",
                target,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._replies: queue.Queue[tuple[list[str], int]] = queue.Queue()
        self._on_notification = on_notification
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()
        self._replies.get(timeout=10)  # tmux greets with a handshake block

    def _pump(self) -> None:
        """Split the stream into replies and notifications until it closes."""
        assert self._process.stdout is not None
        block: list[str] | None = None
        returncode = 0
        for raw in self._process.stdout:
            line = raw.rstrip("\n")
            if line.startswith("%begin"):
                block, returncode = [], 0
            elif line.startswith("%error"):
                returncode = 1
            elif line.startswith("%end"):
                self._replies.put((block or [], returncode))
                block = None
            elif line.startswith("%"):
                self._on_notification(line)
            elif block is not None:
                block.append(line)
        # Unblock anyone waiting when the connection goes away.
        self._replies.put(([], 1))

    def run(self, request: CommandRequest) -> CommandResult:
        """Write a command, then wait for the reader thread to hand back its reply."""
        assert self._process.stdin is not None
        self._process.stdin.write(render_control_line(request.args) + "\n")
        self._process.stdin.flush()
        stdout, returncode = self._replies.get(timeout=10)
        return CommandResult(
            cmd=("tmux", "-C", *request.args),
            stdout=tuple(stdout),
            returncode=returncode,
        )

    def close(self) -> None:
        """Close stdin, let the reader drain, then join it."""
        try:
            if self._process.stdin is not None:
                self._process.stdin.close()
            self._process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            self._process.kill()
        self._reader.join(timeout=5)


@pytest.fixture
def pushed() -> list[str]:
    """Collect notifications the engine pushes."""
    return []


@pytest.fixture
def push_server(session: Session, pushed: list[str]) -> Iterator[Server]:
    """Yield a server whose engine pushes notifications to *pushed*."""
    engine = PushControlModeEngine(
        ServerConnection.from_server(session.server),
        str(session.session_name),
        pushed.append,
    )
    try:
        yield Server(socket_name=session.server.socket_name, engine=engine)
    finally:
        engine.close()


def test_commands_and_traversal_still_work(push_server: Server) -> None:
    """A reader thread does not change how commands behave."""
    assert push_server.cmd("display-message", "-p", "hi").stdout == ["hi"]
    assert [s.session_name for s in push_server.sessions]


def test_output_arrives_while_the_caller_is_idle(
    push_server: Server,
    pushed: list[str],
) -> None:
    """Notifications land without any command being issued to fetch them.

    This is the difference from draining replies: the loop below runs no tmux
    commands at all, and the output still shows up.
    """
    session = push_server.sessions[0]
    pane = session.active_window.active_pane
    assert pane is not None

    push_server.cmd("send-keys", "-t", pane.pane_id, "printf 'PUSHED\\n'", "Enter")

    deadline = time.time() + 5
    found = False
    while time.time() < deadline and not found:
        found = any(
            b"PUSHED" in unescape_control_output(line.split(" ", 2)[-1])
            for line in list(pushed)
            if line.startswith("%output")
        )
        time.sleep(0.05)

    assert found, "output should be pushed without polling tmux"


def test_close_joins_the_reader_thread(session: Session) -> None:
    """Shutdown is orderly: stdin closes, the stream ends, the thread exits."""
    engine = PushControlModeEngine(
        ServerConnection.from_server(session.server),
        str(session.session_name),
        lambda _line: None,
    )
    engine.close()

    assert not engine._reader.is_alive()
