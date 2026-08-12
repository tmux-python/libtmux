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
import time
import typing as t

import pytest

from libtmux import exc
from libtmux.engines import (
    CommandResult,
    ServerConnection,
    TmuxEngine,
    render_control_line,
    unescape_control_output,
)
from libtmux.server import Server

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.engines import CommandRequest
    from libtmux.session import Session


class ControlModeEngine(TmuxEngine):
    """Execute tmux commands over one persistent ``tmux -C`` connection.

    tmux replies to each command with a ``%begin`` / ``%end`` block, and pushes
    asynchronous notifications between them. Both arrive on the same stream, so
    reading a reply necessarily walks past any notification that landed first --
    which is why collecting them costs nothing extra.

    Delivery is therefore poll-driven: a notification surfaces the next time a
    command runs. Pushing them the instant they arrive needs a reader thread,
    and that is the part a production engine adds.

    It attaches to a session the caller names rather than creating one. Spawning
    with ``new-session -A`` would be simpler, but the session it makes is real:
    it shows up in ``server.sessions`` forever after, so merely connecting an
    engine would change what the caller sees.

    Parameters
    ----------
    connection : ServerConnection
        Which tmux server to reach.
    target : str
        An existing session to attach to. A control client that never attaches
        is pushed no output at all.

    Attributes
    ----------
    notifications : list[str]
        Raw ``%output`` lines seen while reading replies, oldest first.
    reconnects : int
        How many times the connection has been reopened.
    """

    def __init__(self, connection: ServerConnection, target: str) -> None:
        self._connection = connection
        self._target = target
        self.notifications: list[str] = []
        self.reconnects = 0
        self._spawn()

    def _spawn(self) -> None:
        """Open the control connection, consuming tmux's greeting block."""
        connection = self._connection
        argv = [
            connection.resolve_bin(),
            *connection.args,
            "-C",
            "-q",
            "attach-session",
            "-t",
            self._target,
        ]
        self._process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        # tmux greets with a handshake block either way; a failed attach
        # terminates it with %error rather than %end and then exits. Reported
        # as an ordinary result that is indistinguishable from tmux rejecting
        # a command, so it is raised instead.
        lines, returncode = self._read_block()
        if returncode != 0:
            detail = " ".join(lines) or "no reason given"
            msg = f"could not attach to session {self._target!r}: {detail}"
            raise exc.EngineError(msg)

    def _read_block(self) -> tuple[list[str], int]:
        """Read one ``%begin``-delimited reply, returning its lines and status.

        Raises
        ------
        :exc:`~libtmux.exc.EngineError`
            The stream closed before tmux terminated the block.
        """
        assert self._process.stdout is not None
        lines: list[str] = []
        returncode = 0
        while True:
            line = self._process.stdout.readline()
            if not line:
                # The stream ended before tmux terminated the block. Returning
                # here would report the dead connection as a *successful*
                # empty result, which is the worst of the three options.
                msg = "control connection closed"
                raise exc.EngineError(msg)
            line = line.rstrip("\n")
            if line.startswith("%begin"):
                lines = []
            elif line.startswith("%error"):
                returncode = 1
                break
            elif line.startswith("%end"):
                break
            elif line.startswith("%output"):
                # Notifications arrive interleaved with replies. Keeping them
                # rather than discarding them is the whole cost of delivery --
                # each dispatch drains whatever tmux pushed since the last one.
                self.notifications.append(line)
            elif not line.startswith("%"):
                lines.append(line)
        return lines, returncode

    def run(self, request: CommandRequest) -> CommandResult:
        """Write one command line and read back its reply block.

        Reconnects first if the connection died. This is the lazy form: it
        notices on the next command rather than the instant the process exits.

        A reply is not necessarily lost when the client dies. If tmux had
        already written it, the pipe buffer holds it and the next read still
        returns it -- measured, and the opposite of what "in flight" suggests.
        What is lost is a command tmux never answered.

        When the tmux server itself goes away the write fails, and that is
        translated to :exc:`~libtmux.exc.EngineError` so a caller guarding
        against libtmux errors catches it rather than a bare
        :exc:`BrokenPipeError`. Backing off instead of reconnecting in a tight
        loop is what a hardened engine still adds.
        """
        if self._process.poll() is not None:
            self.reconnects += 1
            self._spawn()
        assert self._process.stdin is not None
        try:
            self._process.stdin.write(render_control_line(request.args) + "\n")
            self._process.stdin.flush()
        except OSError as error:
            # The tmux server went away. Translate, so a caller guarding
            # LibTmuxException catches it instead of a bare BrokenPipeError.
            msg = "control connection closed"
            raise exc.EngineError(msg) from error
        stdout, returncode = self._read_block()
        return CommandResult(
            cmd=("tmux", "-C", *request.args),
            stdout=tuple(stdout),
            returncode=returncode,
        )

    def run_batch(
        self,
        requests: Sequence[CommandRequest],
    ) -> list[CommandResult]:
        """Write every command, then read every reply.

        This is the point of a persistent connection: the round trips collapse
        into one. A stateless engine cannot do this -- it has to wait for each
        process to exit before starting the next.
        """
        assert self._process.stdin is not None
        for request in requests:
            self._process.stdin.write(render_control_line(request.args) + "\n")
        self._process.stdin.flush()
        results = []
        for request in requests:
            stdout, returncode = self._read_block()
            results.append(
                CommandResult(
                    cmd=("tmux", "-C", *request.args),
                    stdout=tuple(stdout),
                    returncode=returncode,
                ),
            )
        return results

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
    engine = ControlModeEngine(
        ServerConnection.from_server(session.server),
        str(session.session_name),
    )
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


def test_a_batch_collapses_into_one_round_trip(control_mode_server: Server) -> None:
    """``dispatch_batch`` reaches the engine's pipelining path.

    ``Server.cmd()`` sends one command and waits for it. A batch hands the whole
    sequence to the engine at once, which is the only way a persistent
    connection can write everything before reading anything.
    """
    from libtmux.common import dispatch_batch

    results = dispatch_batch(
        control_mode_server.engine,
        [("display-message", "-p", f"m{index}") for index in range(5)],
    )

    assert [result.stdout for result in results] == [[f"m{i}"] for i in range(5)]


def test_pane_output_arrives_as_notifications(session: Session) -> None:
    """A control client attached to a session is pushed the pane's output.

    :func:`~libtmux.engines.base.unescape_control_output` exists for this: tmux
    writes every non-printable byte in a ``%output`` payload as a backslash and
    three octal digits, so a reader scanning for raw bytes never matches until
    the payload is decoded.

    Two things make this easy to get wrong. The client has to be *attached* --
    a control connection that never attached sees no output at all. And the
    reply to a command bounds the read: polling the stream with
    :func:`select.select` reports "nothing to read" while Python's own buffer
    still holds lines, so a naive reader stops after the first one.
    """
    pane = session.active_window.active_pane
    assert pane is not None
    connection = ServerConnection.from_server(session.server)

    client = subprocess.Popen(
        [
            connection.resolve_bin(),
            *connection.args,
            "-C",
            "attach-session",
            "-t",
            str(session.session_name),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    try:
        assert client.stdin is not None
        assert client.stdout is not None

        # Wait for the client to be attached by asking it something, rather
        # than sleeping a guessed interval: its reply proves it is ready.
        client.stdin.write("display-message -p READY\n")
        client.stdin.flush()
        for _ in range(500):
            if client.stdout.readline().rstrip("\n") == "READY":
                break

        pane.send_keys("printf 'MARKER-OK\\n'")

        # Reading until a command of our own replies bounds the wait without
        # polling, and everything before the reply is what tmux pushed at us.
        client.stdin.write("display-message -p SENTINEL\n")
        client.stdin.flush()

        payloads: list[bytes] = []
        for _ in range(500):
            line = client.stdout.readline()
            if not line or line.rstrip("\n") == "SENTINEL":
                break
            if line.startswith("%output"):
                payloads.append(
                    unescape_control_output(line.rstrip("\n").split(" ", 2)[-1])
                )
    finally:
        client.kill()

    assert payloads, "an attached control client should be pushed pane output"
    assert any(b"MARKER-OK" in payload for payload in payloads)


def test_waiting_for_pane_output_needs_no_reader_thread(
    control_mode_server: Server,
) -> None:
    """Poll for a pane's output by issuing commands, draining pushes as you go.

    Each dispatch reads past whatever tmux pushed since the last one, so a cheap
    command doubles as a drain. That is enough to wait for output without any
    concurrency; a push API that delivers the instant output appears is what
    would need a thread.
    """
    engine = control_mode_server.engine
    assert isinstance(engine, ControlModeEngine)
    session = control_mode_server.sessions[0]
    pane = session.active_window.active_pane
    assert pane is not None

    control_mode_server.cmd(
        "send-keys", "-t", pane.pane_id, "printf 'FOUND-IT\n'", "Enter"
    )

    deadline = time.time() + 5
    found = False
    while time.time() < deadline and not found:
        control_mode_server.cmd("display-message", "-p", "tick")
        found = any(
            b"FOUND-IT" in unescape_control_output(line.split(" ", 2)[-1])
            for line in engine.notifications
        )
        if not found:
            time.sleep(0.05)

    assert found, "pane output should surface through collected notifications"


def test_a_dropped_connection_is_reopened(control_mode_server: Server) -> None:
    """Killing the control client does not end the server object's usefulness.

    Surviving a drop is a liveness check and a respawn. What it does not cover
    is the tmux server itself going away: the next write raises
    :exc:`BrokenPipeError` rather than a
    :exc:`~libtmux.exc.LibTmuxException`. Translating that, and backing off
    instead of reconnecting in a tight loop, belong to a hardened engine.
    """
    engine = control_mode_server.engine
    assert isinstance(engine, ControlModeEngine)
    assert control_mode_server.cmd("display-message", "-p", "one").stdout == ["one"]

    engine._process.kill()
    engine._process.wait()

    assert control_mode_server.cmd("display-message", "-p", "two").stdout == ["two"]
    assert [s.session_name for s in control_mode_server.sessions]
    assert engine.reconnects == 1


def test_connecting_adds_no_session(control_mode_server: Server) -> None:
    """Attaching an engine must not change what the caller sees.

    ``new-session -A`` is the easy way to open a control connection, but the
    session it creates is indistinguishable from one the user made, and it
    outlives the connection.
    """
    names = [s.session_name for s in control_mode_server.sessions]

    assert names, "the fixture session should be visible"
    assert not [name for name in names if str(name).startswith("_")]


def test_a_failed_reconnect_raises_rather_than_looking_like_an_error(
    session: Session,
) -> None:
    """A connection that never established is a transport failure, not a result.

    ``attach-session`` against a dead server makes tmux start a fresh one, which
    has no such session, so the client exits quietly. Reported as a result it
    would carry ``returncode`` 1 and be indistinguishable from tmux rejecting a
    command.
    """
    connection = ServerConnection.from_server(session.server)

    with pytest.raises(exc.EngineError, match="could not attach"):
        ControlModeEngine(connection, "no_such_session_exists")
