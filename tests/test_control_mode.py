"""Tests for ControlMode context manager."""

from __future__ import annotations

import locale
import os
import select
import sys
import typing as t

import pytest

from libtmux._internal.control_mode import ControlMode
from libtmux.formats import FORMAT_SEPARATOR

if t.TYPE_CHECKING:
    from libtmux.server import Server


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

            for _ in range(20):
                ready, _, _ = select.select([ctl.stdout], [], [], 1)
                assert ready, "timed out waiting for control-mode output"

                line = ctl.stdout.readline()
                if FORMAT_SEPARATOR in line:
                    break
            else:
                pytest.fail("FORMAT_SEPARATOR U+241E not found in control output")
    finally:
        locale.setlocale(locale.LC_CTYPE, old_lc_ctype)
