"""Test-suite-wide fixtures for libtmux's own tests."""

from __future__ import annotations

import contextlib
import fcntl
import os
import pty
import struct
import subprocess
import termios
import typing as t

import pytest

from libtmux.test.retry import retry_until
from tests.tmux_client import clear_caches

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session


@pytest.fixture(autouse=True)
def _clear_get_version_cache() -> None:
    """Flush the executable's cached tmux release before each test.

    The tests under legacy_api monkey-patch libtmux.common.tmux_cmd then
    call the deprecated get_version() to assert parsed-version behavior.
    With memoization, a prior test's cached result would mask the mock --
    this fixture guarantees a fresh subprocess lookup per test. get_version
    and get_version_str cache independently, so flush both.
    """
    clear_caches()


@pytest.fixture
def pty_client(
    server: Server,
    session: Session,
) -> t.Iterator[t.Callable[[], str]]:
    """Attach a client on a pseudo-terminal and return its name.

    ``display-popup`` draws on a client's terminal. tmux 3.8 turned it into a
    no-op for control-mode clients, so popup tests need a terminal-backed one.
    """
    opened: list[tuple[subprocess.Popen[bytes], int, int]] = []

    def attach() -> str:
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        tmux_bin = server.tmux_bin or "tmux"
        if server.socket_name is not None:
            socket_args = ["-L", str(server.socket_name)]
        elif server.socket_path is not None:
            socket_args = ["-S", str(server.socket_path)]
        else:
            socket_args = []
        proc = subprocess.Popen(
            [tmux_bin, *socket_args, "attach-session", "-t", str(session.session_id)],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env={**os.environ, "TERM": "xterm-256color"},
        )
        opened.append((proc, master, slave))
        found: list[str] = []

        def registered() -> bool:
            result = server.cmd("list-clients", "-F", "#{client_pid}\t#{client_name}")
            for line in result.stdout:
                pid, _, name = line.partition("\t")
                if pid == str(proc.pid) and name:
                    found.append(name.strip())
                    return True
            return False

        retry_until(registered, 3, raises=True)
        return found[0]

    yield attach

    for proc, master, slave in opened:
        proc.kill()
        proc.wait()
        with contextlib.suppress(OSError):
            os.close(master)
        with contextlib.suppress(OSError):
            os.close(slave)
