"""Control-mode client context manager for a qualified local tmux daemon."""

from __future__ import annotations

import contextlib
import os
import pathlib
import stat
import subprocess
import tempfile
import typing as t
import uuid

from libtmux import exc
from libtmux._internal.support import versions
from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    import types
    from collections.abc import Iterator

    from typing_extensions import Self

    from libtmux.server import Server
    from libtmux.session import Session

# run-shell -C parses the expanded text, so the fields avoid whitespace and the
# socket path, which may hold anything, is single-quoted with quotes re-opened.
_IDENTITY = r"#{version},#{pid},#{start_time},'#{s/'/'\\''/:socket_path}'"


def _identity(binary: str, selectors: list[str]) -> str:
    # run-shell -C fires no after-* or command-error hook; the expanded
    # identity comes back in the error text of its failed parse.
    marker = "libtmux-identity-" + uuid.uuid4().hex + "-"
    result = versions._run(
        [binary, "-u", *selectors, "-N", "run-shell", "-C", marker + _IDENTITY]
    )
    prefix = f"unknown command: {marker}"
    # A single line: a newline inside the socket path must not truncate it.
    lines = result.stderr.rstrip("\n").split("\n")
    report = (
        lines[0][len(prefix) :]
        if result.returncode == 1 and len(lines) == 1 and lines[0].startswith(prefix)
        else ""
    )
    fields = report.split(",", 3)
    if (
        not report
        or len(fields) != 4
        or not fields[1].isdigit()
        or not fields[2].isdigit()
        or not pathlib.Path(fields[3]).is_absolute()
    ):
        detail = result.stderr.strip() or "tmux did not report its daemon identity"
        msg = f"ControlMode cannot identify its daemon: {detail}"
        raise exc.LibTmuxException(msg)
    return report


def _require_release(version: str) -> None:
    # Strict ranking: 3.8-rc2 and next-3.8 qualify, next-3.7 and 3.7-rc* do not.
    try:
        versions.require_version(version, minimum="3.7")
    except exc.VersionTooLow:
        msg = f"ControlMode requires tmux 3.7 or newer; daemon reports {version!r}"
        raise exc.VersionTooLow(msg) from None


@contextlib.contextmanager
def _pinned_endpoint(server: Server) -> Iterator[list[str]]:
    binary, selectors = server._version_endpoint()
    identity = _identity(binary, selectors)
    version, _, _, socket = identity.split(",", 3)
    _require_release(version)

    original = pathlib.Path(socket)
    with contextlib.ExitStack() as resources:
        try:
            original_stat = original.lstat()
            if not stat.S_ISSOCK(original_stat.st_mode):
                msg = "ControlMode requires a local Unix socket"
                raise exc.LibTmuxException(msg)
            parents = sorted(
                dict.fromkeys((pathlib.Path(tempfile.gettempdir()), original.parent)),
                key=lambda path: len(os.fsencode(path)),
            )
            for parent in parents:
                with contextlib.ExitStack() as attempt:
                    try:
                        folder = attempt.enter_context(
                            tempfile.TemporaryDirectory(prefix=".lt-", dir=parent)
                        )
                        alias = pathlib.Path(folder) / "s"
                        os.link(original, alias, follow_symlinks=False)
                    except OSError:
                        if parent == parents[-1]:
                            raise
                        continue
                    resources.enter_context(attempt.pop_all())
                    break
            pinned = alias.lstat()
            if (original_stat.st_dev, original_stat.st_ino) != (
                pinned.st_dev,
                pinned.st_ino,
            ) or _identity(binary, ["-S", str(alias)]) != identity:
                msg = "ControlMode daemon changed before acquisition"
                raise exc.LibTmuxException(msg)
        except OSError as error:
            msg = f"ControlMode cannot retain the selected tmux socket: {error}"
            raise exc.LibTmuxException(msg) from error
        # Keep the inode reachable until the owned control client exits.
        yield [binary, "-u", "-N", "-S", str(alias)]


class ControlMode:
    """Attach a control client to a local tmux 3.7 or newer release.

    The socket filesystem must permit a private hard link. An endpoint that
    disappears or changes before acquisition is refused. Ordinary subprocess
    operations remain available on tmux 3.3a and newer.

    Parameters
    ----------
    server : Server
        Server whose local daemon to attach to.
    session : Session
        Session on that server.

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
    _resources: contextlib.ExitStack | None

    def __init__(self, server: Server, session: Session) -> None:
        self.server = server
        self.session = session
        self._resources = None

    def __enter__(self) -> Self:
        """Check the daemon's version, acquire control and wait for registration."""
        if self._resources is not None:
            msg = "ControlMode is already active"
            raise exc.LibTmuxException(msg)
        with contextlib.ExitStack() as resources:
            endpoint = resources.enter_context(_pinned_endpoint(self.server))
            read_fd, self._write_fd = os.pipe()
            try:
                try:
                    self._proc = subprocess.Popen(
                        [
                            *endpoint,
                            "-C",
                            "attach-session",
                            "-t",
                            str(self.session.session_id),
                        ],
                        stdin=read_fd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding="utf-8",
                    )
                finally:
                    os.close(read_fd)
            except BaseException:
                os.close(self._write_fd)
                raise
            resources.callback(self._close_client)
            assert self._proc.stdout is not None
            self.stdout = self._proc.stdout
            client_pid = str(self._proc.pid)

            # tmux names a client with no tty "client-<pid>"; ask for the live
            # client pids with run-shell -C, which fires no hook.
            self.client_name = f"client-{client_pid}"

            def client_registered() -> bool:
                if self._proc.poll() is not None:
                    assert self._proc.stderr is not None
                    detail = self._proc.stderr.read().strip()
                    msg = f"ControlMode client exited before registration: {detail}"
                    raise exc.LibTmuxException(msg)
                marker = "libtmux-clients-" + uuid.uuid4().hex + "-"
                result = versions._run(
                    [*endpoint, "run-shell", "-C", marker + "#{L:#{client_pid},}"]
                )
                prefix = f"unknown command: {marker}"
                return any(
                    client_pid in line[len(prefix) :].split(",")
                    for line in result.stderr.splitlines()
                    if line.startswith(prefix)
                )

            retry_until(client_registered, 3, raises=True)
            self._resources = resources.pop_all()
        return self

    def _close_client(self) -> None:
        os.close(self._write_fd)
        try:
            if self._proc.poll() is None:
                self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=5)
        finally:
            if self._proc.stdout is not None:
                self._proc.stdout.close()
            if self._proc.stderr is not None:
                self._proc.stderr.close()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Close the owned client and its private socket alias."""
        if self._resources is not None:
            resources, self._resources = self._resources, None
            resources.close()
