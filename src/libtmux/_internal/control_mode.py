"""Control-mode client context manager for tmux testing.

Provides a context manager that spawns a ``tmux -C attach-session``
subprocess, creating a real tmux client that satisfies commands
requiring an attached client (e.g. ``display-popup``, ``detach-client``).
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile
import typing as t

from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    import types

    from libtmux.server import Server
    from libtmux.session import Session


class ControlMode:
    """Context manager that spawns a tmux control-mode client.

    Creates a real client attached to the session, visible in
    ``Server.list_clients()``. The client communicates via the tmux
    control protocol on stdout.

    While active, ``Server.list_clients()`` will include this client.

    Parameters
    ----------
    server : Server
        The tmux server instance.
    session : Session
        The session to attach to.

    Examples
    --------
    >>> with ControlMode(server=server, session=session) as ctl:
    ...     clients = server.list_clients()
    ...     assert len(clients) > 0
    ...     assert ctl.client_name != ''
    """

    server: Server
    session: Session
    client_name: str
    stdout: t.IO[str]

    _proc: subprocess.Popen[str]
    _fifo_path: str
    _write_fd: int

    def __init__(self, server: Server, session: Session) -> None:
        self.server = server
        self.session = session

    def __enter__(self) -> ControlMode:
        """Spawn control-mode client and wait for registration."""
        self._fifo_path = tempfile.mktemp(prefix="libtmux_ctl_")
        os.mkfifo(self._fifo_path)

        tmux_bin = self.server.tmux_bin or "tmux"
        cmd = [
            tmux_bin,
            "-L",
            str(self.server.socket_name),
            "-C",
            "attach-session",
            "-t",
            str(self.session.session_id),
        ]

        # Open read end for subprocess stdin
        read_fd = os.open(self._fifo_path, os.O_RDONLY | os.O_NONBLOCK)

        self._proc = subprocess.Popen(
            cmd,
            stdin=read_fd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        os.close(read_fd)

        # Open write end to keep FIFO alive
        self._write_fd = os.open(self._fifo_path, os.O_WRONLY)

        self.stdout = self._proc.stdout  # type: ignore[assignment]

        # Wait for client to register
        def client_registered() -> bool:
            clients = self.server.list_clients()
            return len(clients) > 0

        retry_until(client_registered, 3, raises=True)

        # Capture client name
        result = self.server.cmd(
            "list-clients",
            "-F",
            "#{client_name}",
        )
        self.client_name = result.stdout[0].strip() if result.stdout else ""

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Terminate control-mode client and clean up FIFO."""
        # Close write end — causes the control-mode client to exit
        os.close(self._write_fd)

        # Terminate and wait for subprocess
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()

        # Remove FIFO
        fifo = pathlib.Path(self._fifo_path)
        if fifo.exists():
            fifo.unlink()
