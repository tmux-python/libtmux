"""Tests for ControlMode context manager."""

from __future__ import annotations

import locale
import os
import signal
import sys
import time
import typing as t

import pytest

from libtmux._internal import control_mode as control_module
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


@pytest.mark.parametrize("stop_client", [False, True], ids=["normal", "stopped"])
def test_control_mode_cleanup(
    control_mode: t.Callable[[], ControlMode],
    server: Server,
    stop_client: bool,
) -> None:
    """Exiting releases the client and its streams.

    For the stopped client, cleanup must also be *prompt*: SIGCONT wakes a
    SIGSTOP'd process so the pending SIGTERM is seen immediately. Without
    it, ``_stop()`` still cleans up correctly -- ``wait(timeout=5)`` expires
    and the ``kill()`` fallback reaps the process -- but only after 5s,
    which is the production hang this test exists to catch. Bounding
    elapsed time well under that fallback makes a dropped SIGCONT fail the
    test instead of only slowing it down. The clock starts just before the
    ``with`` block exits, so it times only ``__exit__``/``_stop()`` -- not
    spawn or registration, which are unrelated to the SIGCONT path and
    would otherwise eat into the margin under load.
    """
    with control_mode() as ctl:
        assert len(server.list_clients()) > 0
        if stop_client:
            os.kill(ctl._proc.pid, signal.SIGSTOP)
            _, state = os.waitpid(ctl._proc.pid, os.WUNTRACED)
            assert os.WIFSTOPPED(state)
        started = time.monotonic()
    elapsed = time.monotonic() - started

    assert ctl.stdout.closed
    assert ctl._proc.stderr is not None and ctl._proc.stderr.closed
    assert ctl._proc.poll() is not None
    clients = server.list_clients()
    assert len(clients) == 0
    assert elapsed < 2, (
        f"cleanup took {elapsed:.2f}s; a stopped client should be woken by "
        "SIGCONT and not fall through to the 5s wait() timeout"
    )


@pytest.mark.parametrize("problem", [RuntimeError, KeyboardInterrupt])
def test_control_mode_failed_registration_closes_streams(
    control_mode: t.Callable[[], ControlMode],
    monkeypatch: pytest.MonkeyPatch,
    problem: type[BaseException],
) -> None:
    """A failed handshake must release the real subprocess and its pipes."""

    def reject_registration(*args: object, **kwargs: object) -> None:
        message = "registration failed"
        raise problem(message)

    monkeypatch.setattr(control_module, "retry_until", reject_registration)
    ctl = control_mode()
    try:
        with pytest.raises(problem, match="registration failed"), ctl:
            pytest.fail("Registration must fail before entering the body")
        assert ctl.stdout.closed
        assert ctl._proc.stderr is not None and ctl._proc.stderr.closed
        assert ctl._proc.poll() is not None
    finally:
        if ctl._proc.poll() is None:
            os.close(ctl._write_fd)
            ctl._proc.kill()
            ctl._proc.wait(timeout=5)
        ctl.stdout.close()
        if ctl._proc.stderr is not None:
            ctl._proc.stderr.close()


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
                f"display-message -p '{FORMAT_SEPARATOR}'\ndetach-client\n".encode(),
            )
            stdout, stderr = ctl._proc.communicate(timeout=5)
            assert ctl._proc.returncode == 0, stderr
            assert FORMAT_SEPARATOR in stdout
    finally:
        locale.setlocale(locale.LC_CTYPE, old_lc_ctype)
