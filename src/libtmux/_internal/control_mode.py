"""Control-mode client context manager for a qualified local tmux daemon."""

from __future__ import annotations

import contextlib
import os
import pathlib
import re
import stat
import subprocess
import tempfile
import typing as t

from libtmux import exc
from libtmux._internal import support
from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    import types
    from collections.abc import Iterator

    from typing_extensions import Self

    from libtmux.server import Server
    from libtmux.session import Session

_IDENTITY = "#{version}\t#{pid}\t#{start_time}\t#{socket_path}"


def _identity(binary: str, selectors: list[str]) -> str:
    result = support._run(
        [binary, "-u", *selectors, "-N", "display-message", "-p", _IDENTITY]
    )
    report = result.stdout.rstrip("\n")
    fields = report.split("\t", 3)
    if (
        result.returncode
        or "\n" in report
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
    try:
        support.require_version(version, minimum="3.7")
    except exc.VersionTooLow:
        msg = f"ControlMode requires tmux 3.7 or newer; daemon reports {version!r}"
        raise exc.VersionTooLow(msg) from None
    if re.fullmatch(r"\d+\.\d+[a-z]?", version) is None:
        msg = f"ControlMode requires a qualified release; daemon reports {version!r}"
        raise exc.VersionTooLow(msg)


@contextlib.contextmanager
def _pinned_endpoint(server: Server) -> Iterator[list[str]]:
    binary, selectors = server._version_endpoint()
    identity = _identity(binary, selectors)
    version, _, _, socket = identity.split("\t", 3)
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
        """Admit the daemon before control acquisition and wait for registration."""
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

            def client_registered() -> bool:
                if self._proc.poll() is not None:
                    assert self._proc.stderr is not None
                    detail = self._proc.stderr.read().strip()
                    msg = f"ControlMode client exited before registration: {detail}"
                    raise exc.LibTmuxException(msg)
                result = self.server.cmd(
                    "-u", "list-clients", "-F", "#{client_pid}\t#{client_name}"
                )
                for line in result.stdout:
                    pid, _, client_name = line.partition("\t")
                    if pid == client_pid and client_name:
                        self.client_name = client_name.strip()
                        return True
                return False

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
