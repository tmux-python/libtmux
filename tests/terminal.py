"""Terminal clients on isolated tmux servers for integration tests."""

from __future__ import annotations

import contextlib
import fcntl
import os
import struct
import subprocess
import termios
import threading
import typing as t

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session


@contextlib.contextmanager
def attached_terminal(
    server: Server, session: Session, *, drain_output: bool = False
) -> t.Iterator[tuple[str, int]]:
    """Yield the attached client name and the master end of its test PTY."""
    socket_path = server.cmd("display-message", "-p", "#{socket_path}").stdout[0]
    prefix = [server.tmux_bin or "tmux", "-S", socket_path]
    channel = f"terminal-ready-{os.getpid()}"
    server.set_hook("client-attached[0]", f"wait-for -S {channel}", global_=True)
    env = {**os.environ, "TERM": "xterm-256color"}
    env.pop("TMUX", None)
    env.pop("TMUX_PANE", None)
    reader: threading.Thread | None = None

    try:
        with contextlib.ExitStack() as cleanup:
            master, slave = os.openpty()
            cleanup.callback(os.close, master)
            cleanup.callback(os.close, slave)
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
            client = subprocess.Popen(
                [*prefix, "attach-session", "-t", str(session.session_id)],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                env=env,
                start_new_session=True,
            )

            def drain() -> None:
                with contextlib.suppress(OSError):
                    while os.read(master, 65536):
                        pass

            try:
                if drain_output:
                    reader = threading.Thread(target=drain, daemon=True)
                    reader.start()
                subprocess.run(
                    [*prefix, "wait-for", channel],
                    check=True,
                    capture_output=True,
                    timeout=1,
                    env=env,
                )
                name = os.ttyname(slave)
                clients = server.cmd(
                    "list-clients",
                    "-F",
                    "#{client_pid}\t#{client_name}",
                ).stdout
                assert f"{client.pid}\t{name}" in clients
                server.unset_hook("client-attached[0]", global_=True)
                yield name, master
            finally:
                client.terminate()
                try:
                    client.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    client.kill()
                    client.wait(timeout=1)
    finally:
        if reader is not None:
            reader.join(timeout=1)
            assert not reader.is_alive()
