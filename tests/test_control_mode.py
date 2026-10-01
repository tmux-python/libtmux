"""Tests for ControlMode context manager."""

from __future__ import annotations

import locale
import os
import queue
import sys
import threading
import time
import typing as t

import pytest

from libtmux._internal.control_mode import ControlMode
from libtmux.formats import FORMAT_SEPARATOR

if t.TYPE_CHECKING:
    from collections.abc import Iterator

    from libtmux.server import Server


def _read_lines(
    stream: t.IO[str],
    *,
    limit: int,
    timeout: float,
) -> Iterator[str]:
    """Yield up to *limit* lines from *stream*, giving up after *timeout*.

    A reader thread owns the stream and the caller polls a queue, so the wait
    is bounded without anything having to ask the file descriptor whether a
    line is available.

    That question has no useful answer here. ``ControlMode`` builds its
    subprocess with ``text=True``, so ``stream`` is a ``TextIOWrapper`` over a
    ``BufferedReader``: ``select`` would report readiness on the raw
    descriptor while ``readline`` serves from the userspace buffer above it.
    tmux writes a whole ``%begin``/``%end`` block in one burst, so the first
    ``readline`` routinely drains every remaining line off the descriptor --
    leaving ``select`` with nothing to report and the answer already in hand.
    """
    lines: queue.Queue[str | BaseException | None] = queue.Queue()

    def pump() -> None:
        try:
            for line in stream:
                lines.put(line)
        except BaseException as e:  # noqa: BLE001
            # Carry it across the thread boundary. Collapsing it into the
            # ``None`` sentinel would report the reader as having reached EOF,
            # naming the wrong cause for a decode error this test exists to
            # catch.
            lines.put(e)
        finally:
            lines.put(None)

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()

    deadline = time.monotonic() + timeout
    for _ in range(limit):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            pytest.fail("timed out waiting for control-mode output")
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:
            pytest.fail("timed out waiting for control-mode output")
        if isinstance(line, BaseException):
            raise line
        if line is None:
            pytest.fail("control-mode stream closed before the expected output")
        yield line


def test_control_mode_creates_client(
    control_mode: t.Callable[[], ControlMode],
    server: Server,
) -> None:
    """ControlMode creates a client visible in list-clients."""
    with control_mode() as ctl:
        clients = server.list_clients()
        assert len(clients) > 0
        assert ctl.client_name != ""


def test_control_mode_cleanup(
    control_mode: t.Callable[[], ControlMode],
    server: Server,
) -> None:
    """Client is removed after ControlMode context exits."""
    with control_mode():
        assert len(server.list_clients()) > 0

    # After context exit, client should be gone
    clients = server.list_clients()
    assert len(clients) == 0


def test_control_mode_client_name(
    control_mode: t.Callable[[], ControlMode],
) -> None:
    """ControlMode.client_name contains the tmux client identifier."""
    with control_mode() as ctl:
        assert "client-" in ctl.client_name


def test_control_mode_client_name_matches_spawned_client(
    control_mode: t.Callable[[], ControlMode],
    server: Server,
) -> None:
    """ControlMode records the client name for its own subprocess."""
    with control_mode() as first, control_mode() as second:
        clients = {
            tuple(line.split("\t", 1))
            for line in server.cmd(
                "list-clients",
                "-F",
                "#{client_pid}\t#{client_name}",
            ).stdout
        }

        assert first.client_name != second.client_name
        assert (str(first._proc.pid), first.client_name) in clients
        assert (str(second._proc.pid), second.client_name) in clients


@pytest.mark.skipif(
    sys.flags.utf8_mode != 0,
    reason="PYTHONUTF8 mode forces UTF-8, masking the locale bug",
)
def test_control_mode_stdout_preserves_non_ascii_output(
    control_mode: t.Callable[[], ControlMode],
) -> None:
    """Control-mode stdout must preserve non-ASCII tmux output."""
    old_lc_ctype = locale.setlocale(locale.LC_CTYPE)
    try:
        locale.setlocale(locale.LC_CTYPE, "C")
        with control_mode() as ctl:
            os.write(
                ctl._write_fd,
                f"display-message -p '{FORMAT_SEPARATOR}'\n".encode(),
            )

            for line in _read_lines(ctl.stdout, limit=20, timeout=5):
                if FORMAT_SEPARATOR in line:
                    break
            else:
                pytest.fail("FORMAT_SEPARATOR U+241E not found in control output")
    finally:
        locale.setlocale(locale.LC_CTYPE, old_lc_ctype)
