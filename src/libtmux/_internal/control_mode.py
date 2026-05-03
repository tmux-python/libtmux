"""Control-mode client context manager for tmux testing.

Provides a context manager that spawns a ``tmux -C attach-session``
subprocess, creating a real tmux client that satisfies commands
requiring an attached client (e.g. ``display-popup``, ``detach-client``).
"""

from __future__ import annotations

import os
import subprocess
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
    _write_fd: int

    def __init__(self, server: Server, session: Session) -> None:
        self.server = server
        self.session = session

    def __enter__(self) -> ControlMode:
        """Spawn control-mode client and wait for registration."""
        read_fd, self._write_fd = os.pipe()

        tmux_bin = self.server.tmux_bin or "tmux"

        # Build socket arguments matching Server's own logic
        if self.server.socket_name is not None:
            socket_args = ["-L", str(self.server.socket_name)]
        elif self.server.socket_path is not None:
            socket_args = ["-S", str(self.server.socket_path)]
        else:
            socket_args = []

        cmd = [
            tmux_bin,
            *socket_args,
            "-C",
            "attach-session",
            "-t",
            str(self.session.session_id),
        ]

        try:
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stdin=read_fd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            finally:
                # Close read end in parent regardless — subprocess owns it now
                os.close(read_fd)
        except BaseException:
            # Popen failed before we could spawn the subprocess; close the
            # write end too so the pipe doesn't leak. __exit__ won't run
            # because __enter__ never returned.
            os.close(self._write_fd)
            raise

        self.stdout = self._proc.stdout  # type: ignore[assignment]
        client_pid = str(self._proc.pid)

        # Wait for client to register
        def client_registered() -> bool:
            result = self.server.cmd(
                "list-clients",
                "-F",
                "#{client_pid}\t#{client_name}",
            )
            for line in result.stdout:
                pid, _, client_name = line.partition("\t")
                if pid == client_pid and client_name:
                    self.client_name = client_name.strip()
                    return True
            return False

        try:
            retry_until(client_registered, 3, raises=True)
        except Exception:
            # Clean up subprocess and write end if registration fails
            os.close(self._write_fd)
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
            raise

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Terminate control-mode client."""
        # Close write end — causes the control-mode client to exit (EOF on stdin)
        os.close(self._write_fd)

        # Terminate and wait for subprocess
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
