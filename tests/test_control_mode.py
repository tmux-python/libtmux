"""Tests for ControlMode context manager."""

from __future__ import annotations

import io
import locale
import os
import pathlib
import re
import select
import subprocess
import time
import typing as t

import pytest

from libtmux import exc
from libtmux._internal.control_mode import ControlMode
from libtmux.formats import FORMAT_SEPARATOR

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session


def test_ineligible_control_refuses_before_startup(
    server: Server, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refusal stays exercised on old and unqualified development daemons."""
    version = server._get_version()
    stable = re.fullmatch(r"(\d+)\.(\d+)[a-z]?", version)
    if stable is not None and (int(stable[1]), int(stable[2])) >= (3, 7):
        pytest.skip("requires an ineligible control release")
    original = subprocess.Popen
    starts: list[list[str]] = []

    def tracked(
        argv: list[str], *args: t.Any, **kwargs: t.Any
    ) -> subprocess.Popen[str]:
        if "-C" in argv and "run-shell" not in argv:
            starts.append(argv)
        return original(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", tracked)
    with (
        pytest.raises(exc.VersionTooLow, match="ControlMode requires"),
        ControlMode(server, session),
    ):
        pytest.fail("ineligible control client registered")
    assert starts == []
    assert session.session_id in [item.session_id for item in server.sessions]


def test_unavailable_socket_link_refuses_before_control(
    server: Server, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed pin leaves no control client or temporary socket directory."""
    version = server._get_version()
    stable = re.fullmatch(r"(\d+)\.(\d+)[a-z]?", version)
    if stable is None or (int(stable[1]), int(stable[2])) < (3, 7):
        pytest.skip("requires an eligible control release")
    socket = pathlib.Path(
        server.cmd("display-message", "-p", "#{socket_path}").stdout[0]
    )
    before = set(socket.parent.glob(".lt-*"))
    original = subprocess.Popen
    starts: list[list[str]] = []

    def tracked(
        argv: list[str], *args: t.Any, **kwargs: t.Any
    ) -> subprocess.Popen[str]:
        if "-C" in argv and "run-shell" not in argv:
            starts.append(argv)
        return original(argv, *args, **kwargs)

    def unavailable(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        msg = "socket hard links are unavailable"
        raise OSError(msg)

    monkeypatch.setattr(subprocess, "Popen", tracked)
    monkeypatch.setattr(os, "link", unavailable)
    with (
        pytest.raises(exc.LibTmuxException, match=r"cannot retain.*socket"),
        ControlMode(server, session),
    ):
        pytest.fail("control started without an endpoint pin")
    assert starts == []
    assert set(socket.parent.glob(".lt-*")) == before


def test_control_mode_creates_client(
    control_mode: t.Callable[[], ControlMode],
    server: Server,
) -> None:
    """ControlMode creates a client visible in list-clients."""
    with control_mode() as ctl:
        clients = server.list_clients()
        assert len(clients) > 0
        assert ctl.client_name != ""


def test_control_identity_probe_fires_no_user_hooks(
    control_mode: t.Callable[[], ControlMode],
    server: Server,
) -> None:
    """Pinning a control endpoint never runs the user's display-message hooks."""
    from libtmux.test.retry import retry_until

    server.cmd("set-hook", "-g", "after-display-message", "set -ag @probe-after x")
    server.cmd("set-hook", "-g", "command-error", "set -ag @probe-error y")
    with control_mode():
        pass

    # Hooks run in order, so one control firing afterwards proves the pinning
    # left none: each sentinel holds exactly one letter.
    server.cmd("display-message", "-p", "control")
    assert server.cmd("kill-session", "-t", "=missing").returncode != 0

    def settled() -> bool:
        return server.cmd("show-option", "-gqv", "@probe-after").stdout == [
            "x"
        ] and server.cmd("show-option", "-gqv", "@probe-error").stdout == ["y"]

    assert retry_until(settled, seconds=5, raises=False)
    assert server.cmd("show-option", "-gqv", "@probe-after").stdout == ["x"]
    assert server.cmd("show-option", "-gqv", "@probe-error").stdout == ["y"]


def test_control_identity_reports_an_unusual_socket_path(
    control_mode: t.Callable[[], ControlMode],
) -> None:
    """Quotes, separators and commas in a socket path survive the probe."""
    import shutil
    import tempfile

    from libtmux import Server
    from libtmux._internal.control_mode import _identity

    binary, _ = control_mode().server._version_endpoint()
    folder = tempfile.mkdtemp(prefix="lt-")
    path = pathlib.Path(folder) / "q'\"; {a} #~$x,\\b"
    path.mkdir()
    socket = path / "s"
    server = Server(tmux_bin=binary, socket_path=str(socket), config_file="/dev/null")
    try:
        server.new_session("identity", window_command="exec sleep 123")
        report = _identity(binary, ["-S", str(socket)])
        assert report.split(",", 3)[3] == str(socket)
    finally:
        server.cmd("kill-server")
        shutil.rmtree(folder, ignore_errors=True)


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


def test_control_mode_stdout_preserves_non_ascii_output(
    control_mode: t.Callable[[], ControlMode],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control output stays UTF-8 when the client inherits a C locale."""
    old_lc_ctype = locale.setlocale(locale.LC_CTYPE)
    try:
        locale.setlocale(locale.LC_CTYPE, "C")
        for key in ("LC_ALL", "LC_CTYPE", "LANG"):
            monkeypatch.setenv(key, "C")
        with control_mode() as ctl:
            assert isinstance(ctl.stdout, io.TextIOWrapper)
            assert ctl.stdout.encoding == "utf-8"
            os.write(
                ctl._write_fd,
                f"display-message -p '{FORMAT_SEPARATOR}'\n".encode(),
            )
            # Read bytes to avoid waiting on an fd after TextIOWrapper prefetched.
            output = bytearray()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                ready, _, _ = select.select(
                    [ctl.stdout.fileno()], [], [], max(0, deadline - time.monotonic())
                )
                if not ready:
                    break
                chunk = os.read(ctl.stdout.fileno(), 65536)
                if not chunk:
                    break
                output.extend(chunk)
                if FORMAT_SEPARATOR.encode() in output:
                    break
            assert FORMAT_SEPARATOR in output.decode("utf-8"), repr(bytes(output))
    finally:
        locale.setlocale(locale.LC_CTYPE, old_lc_ctype)


def test_control_uses_a_short_private_socket_alias(
    control_mode: t.Callable[[], ControlMode],
) -> None:
    """A valid long native endpoint can still acquire a pinned control client."""
    import tempfile

    from libtmux import Server

    qualified = control_mode()
    binary, _ = qualified.server._version_endpoint()
    with tempfile.TemporaryDirectory(prefix="long-control-") as folder:
        root = pathlib.Path(folder)
        parent = root / ("p" * (96 - len(os.fsencode(root)) - 3))
        parent.mkdir(mode=0o700)
        socket = parent / "s"
        server = Server(
            tmux_bin=binary, socket_path=str(socket), config_file="/dev/null"
        )
        try:
            session = server.new_session(
                "long-control", window_command="exec sleep 123"
            )
            assert server.sessions
            context = ControlMode(server, session)
            with context:
                argv = context._proc.args
                assert isinstance(argv, list)
                alias = pathlib.Path(argv[argv.index("-S") + 1])
                assert len(os.fsencode(alias)) < len(os.fsencode(socket))
                assert alias.stat().st_ino == socket.stat().st_ino
                assert alias.stat().st_dev == socket.stat().st_dev
                assert alias.parent.stat().st_mode & 0o777 == 0o700
                assert context.client_name
            assert context._proc.poll() is not None
            assert not alias.exists() and not alias.parent.exists()
            assert not server.list_clients()
        finally:
            server.kill()


def test_control_carrier_retries_a_cross_device_link(
    control_mode: t.Callable[[], ControlMode], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cross-device temporary root falls back to an owned peer alias."""
    import errno

    context = control_mode()
    original_link = os.link
    attempted: list[pathlib.Path] = []

    def link(source: t.Any, target: t.Any, **kwargs: t.Any) -> None:
        attempted.append(pathlib.Path(target))
        if len(attempted) == 1:
            raise OSError(errno.EXDEV, "cross-device link")
        original_link(source, target, **kwargs)

    monkeypatch.setattr(os, "link", link)
    with context:
        assert len(attempted) == 2
        alias = attempted[-1]
        assert alias.is_socket()
        assert context.client_name
    assert all(not item.exists() and not item.parent.exists() for item in attempted)
    assert context._proc.poll() is not None
