"""Exact session acquisition and cleanup authorized by a creation receipt."""

from __future__ import annotations

import dataclasses
import os
import pathlib
import re
import secrets
import shlex
import shutil
import subprocess
import typing as t

from libtmux import exc
from libtmux.common import session_check_name
from libtmux.server import Server

if t.TYPE_CHECKING:
    import types

    from libtmux._internal.types import StrPath
    from libtmux.session import Session

_OWNER_ENV = "LIBTMUX_SESSION_OWNER"
_CONFLICT_READ_TIMEOUT = 1.0
_STOCK_SERVER_CMD = Server.cmd
_Resource = t.TypeVar("_Resource")


@dataclasses.dataclass(frozen=True, slots=True)
class SessionIdentity:
    """Retain native identity observations without granting ownership by name.

    Attributes
    ----------
    socket_path : str
        Endpoint reported by the command's connected daemon.
    server_pid, server_start_time : int
        Native daemon PID and start time in whole Unix seconds. These alone
        cannot prove a unique incarnation after replacement.
    session_id : str
        Stable session ID within the observed daemon.
    server_version : str
        Version reported by the connected daemon.
    creation_token : str | None
        Nonce installed by this call's creation command; None for reuse.
    incarnation_verified : bool | None
        True for this call's nonce-backed creation receipt, None for reuse.
        Verification is scoped to that session receipt, not a global daemon ID.
    """

    socket_path: str
    server_pid: int
    server_start_time: int
    session_id: str
    server_version: str
    creation_token: str | None
    incarnation_verified: bool | None = None


@dataclasses.dataclass(frozen=True)
class _Record:
    identity: SessionIdentity
    name: str


@dataclasses.dataclass(frozen=True)
class _Connection:
    prefix: tuple[str, ...]
    environment: dict[str, str] = dataclasses.field(repr=False)
    marker: str
    cwd: str
    timeout: float | None = None

    @classmethod
    def capture(cls, server: Server) -> _Connection:
        """Freeze the stock native route; refuse unknown dispatch before effects."""
        if (
            Server.cmd is not _STOCK_SERVER_CMD
            or getattr(server.cmd, "__func__", None) is not _STOCK_SERVER_CMD
            or getattr(server, "engine", None) is not None
            or getattr(server, "_engine", None) is not None
        ):
            msg = "session acquisition requires the stock native command dispatcher"
            raise NotImplementedError(msg)
        environment = dict(os.environ)
        binary = shutil.which(server.tmux_bin or "tmux", path=environment.get("PATH"))
        if not binary:
            raise exc.TmuxCommandNotFound
        prefix = [str(pathlib.Path(binary).absolute())]
        if server.colors:
            if server.colors not in (88, 256):
                raise exc.UnknownColorOption
            prefix.append("-2" if server.colors == 256 else "-8")
        if server.config_file:
            prefix.extend(("-f", str(pathlib.Path(server.config_file).absolute())))
        if server.socket_path:
            prefix.extend(("-S", str(pathlib.Path(server.socket_path).absolute())))
        elif server.socket_name:
            prefix.extend(("-L", str(server.socket_name)))
        elif environment.get("TMUX"):
            prefix.extend(
                (
                    "-S",
                    str(pathlib.Path(environment["TMUX"].split(",", 1)[0]).absolute()),
                )
            )
        environment.pop("TMUX", None)
        environment.pop("TMUX_PANE", None)
        return cls(
            tuple(prefix),
            environment,
            "libtmux-" + secrets.token_hex(16),
            str(pathlib.Path.cwd()),
        )

    def execute(self, *args: str) -> subprocess.CompletedProcess[bytes]:
        """Run one request without changing the caller's process environment."""
        encoded = [arg[:-1] + r"\;" if arg.endswith(";") else arg for arg in args]
        return subprocess.run(
            [*self.prefix, *encoded],
            env=self.environment,
            cwd=self.cwd,
            capture_output=True,
            check=False,
            timeout=self.timeout,
        )

    @property
    def format(self) -> str:
        """Frame fields independently of names, paths, and their line breaks."""
        fields = (
            "#{socket_path}",
            "#{pid}",
            "#{start_time}",
            "#{session_id}",
            "#{session_name}",
            "#{version}",
            "#{" + _OWNER_ENV + "}",
        )
        return self.marker + self.marker.join(fields) + self.marker

    def records(self, result: subprocess.CompletedProcess[bytes]) -> list[_Record]:
        """Decode only complete native records; absent evidence stays an error."""
        if not result.stdout:
            return []
        parts = result.stdout.decode("utf-8", "backslashreplace").split(self.marker)
        if len(parts) % 8 != 1 or any(
            parts[i].strip() for i in range(0, len(parts), 8)
        ):
            msg = "tmux returned an incomplete session identity receipt"
            raise exc.LibTmuxException(msg)
        records = []
        for offset in range(1, len(parts), 8):
            path, pid, started, session_id, name, version, token = parts[
                offset : offset + 7
            ]
            if not (
                pathlib.Path(path).is_absolute()
                and pid.isascii()
                and pid.isdecimal()
                and int(pid) > 0
                and started.isascii()
                and started.isdecimal()
                and re.fullmatch(r"\$[0-9]+", session_id)
                and version
            ):
                msg = "tmux returned an invalid session identity receipt"
                raise exc.LibTmuxException(msg)
            records.append(
                _Record(
                    SessionIdentity(
                        path,
                        int(pid),
                        int(started),
                        session_id,
                        version,
                        token or None,
                    ),
                    name,
                )
            )
        return records

    def list_sessions(self) -> list[_Record]:
        """Preserve lookup errors except an explicitly absent native daemon."""
        result = self.execute("list-sessions", "-F", self.format)
        detail = result.stderr.decode("utf-8", "backslashreplace").strip()
        if result.returncode != 0 and (
            detail.startswith("no server running on ")
            or (
                detail.startswith("error connecting to ")
                and detail.endswith("(No such file or directory)")
            )
        ):
            return []
        _check(result, "list-sessions")
        return self.records(result)


def _check(result: subprocess.CompletedProcess[bytes], command: str) -> None:
    if result.returncode != 0 or result.stderr:
        detail = result.stderr.decode("utf-8", "backslashreplace").strip()
        error = exc.LibTmuxException(
            detail or f"exit status {result.returncode}", subcommand=command
        )
        raise error from subprocess.CalledProcessError(
            result.returncode,
            result.args,
            result.stdout,
            result.stderr,
        )


def _daemon_condition(identity: SessionIdentity) -> str:
    return (
        f"#{{&&:#{{==:#{{pid}},{identity.server_pid}}},"
        f"#{{==:#{{start_time}},{identity.server_start_time}}}}}"
    )


class FoundOrCreated(t.Generic[_Resource]):
    """Retain an acquisition result and cleanup only its proved creation.

    ``value`` is an ordinary live handle. Its own methods retain their usual
    stale-handle behavior; this result's cleanup uses its independent receipt.
    Reused results never acquire cleanup responsibility. Call :meth:`preserve`
    to release that responsibility for a created resource without destroying it.

    Obtain results through :meth:`~libtmux.Server.create_session`,
    :meth:`~libtmux.Server.reuse_session`, or
    :meth:`~libtmux.Server.find_or_create_session`.

    Attributes
    ----------
    value : Session
        Ordinary session handle returned by acquisition.
    created : bool
        Whether this call received proof that it created the session.
        Preserving or closing the result does not change this history.
    identity : SessionIdentity
        Frozen endpoint and native identity observations.
    cleanup_error : BaseException | None
        Most recent failed cleanup, cleared after successful cleanup.
    """

    def __init__(
        self,
        value: _Resource,
        identity: SessionIdentity,
        connection: _Connection,
        *,
        created: bool,
    ) -> None:
        self._value = value
        self._identity = identity
        self._created = created
        self._connection = connection
        self._closed = False
        self.cleanup_error: BaseException | None = None

    @property
    def value(self) -> _Resource:
        """Return the ordinary live resource handle."""
        return self._value

    @property
    def identity(self) -> SessionIdentity:
        """Return the immutable identity observations from acquisition."""
        return self._identity

    @property
    def created(self) -> bool:
        """Whether this call obtained the resource's creation receipt."""
        return self._created

    def preserve(self) -> _Resource:
        """Release cleanup responsibility and return the ordinary borrowed handle."""
        self._closed = True
        return self.value

    def close(self) -> None:
        """Destroy only the receipt's session, refusing replacement or lost proof.

        Reused, preserved, and already closed results do nothing. For a created
        result, one native command queue verifies the recorded daemon, exact
        session ID, and creation nonce before destruction. A missing session
        on the observed daemon closes successfully; an unreachable or replaced
        daemon does not establish that the owned session is gone.

        Raises
        ------
        LibTmuxException
            Native cleanup failed or the creation identity could not be verified.
        """
        if not self.created or self._closed:
            return
        identity = self.identity
        token = identity.creation_token
        if not token or not re.fullmatch(r"[0-9a-f]{32}", token):
            msg = "session cleanup identity is unverified"
            raise exc.LibTmuxException(msg)
        marker = "libtmux-cleanup-" + secrets.token_hex(16)
        stale = shlex.join(["display-message", "-p", marker + "-stale"])
        missing = shlex.join(["display-message", "-p", marker + "-missing"])
        done = shlex.join(["display-message", "-p", marker + "-done"])
        kill = shlex.join(["kill-session", "-t", identity.session_id]) + "; " + done
        token_check = shlex.join(
            [
                "if-shell",
                "-F",
                "-t",
                identity.session_id,
                f"#{{==:#{{{_OWNER_ENV}}},{token}}}",
                kill,
                stale,
            ]
        )
        session_check = shlex.join(
            [
                "if-shell",
                "-F",
                "-t",
                identity.session_id,
                f"#{{==:#{{session_id}},{identity.session_id}}}",
                token_check,
                missing,
            ]
        )
        daemon_check = _daemon_condition(identity)
        try:
            result = self._connection.execute(
                "if-shell", "-F", daemon_check, session_check, stale
            )
            _check(result, "kill-session")
            if result.stdout.strip() not in (
                (marker + "-done").encode(),
                (marker + "-missing").encode(),
            ):
                msg = "session cleanup identity changed or could not be verified"
                raise exc.LibTmuxException(msg)  # noqa: TRY301 - retain cleanup failure
        except BaseException as error:
            self.cleanup_error = error
            raise
        self.cleanup_error = None
        self._closed = True

    def __enter__(self) -> _Resource:
        """Return the session without acquiring ownership of a reused result."""
        if self._closed:
            msg = "session acquisition is already closed or preserved"
            raise RuntimeError(msg)
        return self.value

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Clean up only a created session when the scope ends.

        If both the body and cleanup fail, :class:`~libtmux.exc.CreationCleanupError`
        retains both exceptions and this result for an explicit cleanup retry.
        """
        _cleanup(self, exc_value)


def _cleanup(owner: FoundOrCreated[t.Any], failure: BaseException | None) -> None:
    try:
        owner.close()
    except BaseException as cleanup_error:
        if failure is not None:
            raise exc.CreationCleanupError(failure, cleanup_error, owner) from failure
        raise


def _materialize(connection: _Connection, record: _Record) -> Session:
    from libtmux.server import Server
    from libtmux.session import Session

    server = Server(
        socket_path=record.identity.socket_path, tmux_bin=connection.prefix[0]
    )
    return Session.from_session_id(server, record.identity.session_id)


def _match(records: list[_Record], name: str) -> _Record | None:
    matches = [record for record in records if record.name == name]
    if len(matches) > 1:
        msg = "ambiguous exact session name"
        raise exc.LibTmuxException(msg)
    return matches[0] if matches else None


def _verify(connection: _Connection, record: _Record) -> None:
    identity = record.identity
    condition = (
        f"#{{&&:{_daemon_condition(identity)},"
        f"#{{==:#{{session_id}},{identity.session_id}}}}}"
    )
    if identity.creation_token:
        condition = (
            f"#{{&&:{condition},#{{==:#{{{_OWNER_ENV}}},{identity.creation_token}}}}}"
        )
    marker = "verified-" + secrets.token_hex(16)
    result = connection.execute(
        "if-shell",
        "-F",
        "-t",
        identity.session_id,
        condition,
        shlex.join(["display-message", "-p", marker]),
    )
    _check(result, "list-sessions")
    if result.stdout.strip() != marker.encode():
        msg = "session identity changed during acquisition"
        raise exc.LibTmuxException(msg)


def _borrow(connection: _Connection, record: _Record) -> FoundOrCreated[Session]:
    identity = dataclasses.replace(record.identity, creation_token=None)
    record = dataclasses.replace(record, identity=identity)
    value = _materialize(connection, record)
    _verify(connection, record)
    return FoundOrCreated(value, identity, connection, created=False)


def _acquire_session(
    server: Server,
    name: str,
    mode: t.Literal["create", "reuse", "find"],
    *,
    start_directory: StrPath | None = None,
    window_name: str | None = None,
    window_command: str | None = None,
    environment: dict[str, str] | None = None,
) -> FoundOrCreated[Session]:
    """Implement the three explicit session acquisition policies."""
    session_check_name(name)
    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        msg = "session names cannot contain control characters"
        raise ValueError(msg)
    connection = _Connection.capture(server)
    observed: SessionIdentity | None = None
    if mode != "create":
        records = connection.list_sessions()
        observed = records[0].identity if records else None
        match = _match(records, name)
        if match is not None:
            return _borrow(connection, match)
        if mode == "reuse":
            msg = f"session named {name!r} does not exist"
            raise exc.ObjectDoesNotExist(msg)
    token = secrets.token_hex(16)
    args = [
        "new-session",
        "-d",
        "-P",
        "-F",
        connection.format,
        "-s",
        name.replace("#", "##"),
    ]
    if start_directory is not None:
        args.extend(("-c", str(pathlib.Path(start_directory).expanduser())))
    if window_name is not None:
        args.extend(("-n", window_name.replace("#", "##")))
    if environment:
        if _OWNER_ENV in environment:
            msg = f"{_OWNER_ENV} is reserved for session ownership"
            raise ValueError(msg)
        for key, env_value in environment.items():
            args.extend(("-e", f"{key}={env_value}"))
    args.extend(("-e", f"{_OWNER_ENV}={token}"))
    if window_command is not None:
        args.append(window_command)
    if observed is not None:
        marker = "stale-" + secrets.token_hex(16)
        result = connection.execute(
            "if-shell",
            "-F",
            _daemon_condition(observed),
            shlex.join(args),
            shlex.join(["display-message", "-p", marker]),
        )
        if result.stdout.strip() == marker.encode():
            msg = "daemon identity changed before session creation"
            raise exc.LibTmuxException(msg)
    else:
        result = connection.execute(*args)
    if (
        result.returncode == 1
        and not result.stdout
        and result.stderr.decode("utf-8", "backslashreplace").strip()
        == f"duplicate session: {name}"
    ):
        conflict = exc.TmuxSessionExists(f"session named {name!r} exists")
        conflict.__cause__ = subprocess.CalledProcessError(
            result.returncode,
            result.args,
            result.stdout,
            result.stderr,
        )
        if mode == "find":
            try:
                reconciliation = dataclasses.replace(
                    connection, timeout=_CONFLICT_READ_TIMEOUT
                )
                match = _match(reconciliation.list_sessions(), name)
                if match is not None:
                    if observed is not None and (
                        match.identity.socket_path,
                        match.identity.server_pid,
                        match.identity.server_start_time,
                    ) != (
                        observed.socket_path,
                        observed.server_pid,
                        observed.server_start_time,
                    ):
                        msg = "daemon identity changed while reconciling creation"
                        raise exc.LibTmuxException(msg)  # noqa: TRY301 - retain conflict
                    return _borrow(connection, match)
            except BaseException as failure:
                raise failure from conflict
        raise conflict
    try:
        records = connection.records(result)
    except exc.LibTmuxException:
        _check(result, "new-session")
        raise
    if len(records) != 1 or records[0].identity.creation_token != token:
        _check(result, "new-session")
        msg = (
            "session creation returned no trustworthy ownership receipt; "
            "outcome unknown"
        )
        raise exc.LibTmuxException(msg)
    record = records[0]
    identity = dataclasses.replace(record.identity, incarnation_verified=True)
    from libtmux.server import Server
    from libtmux.session import Session

    value = Session(
        server=Server(socket_path=identity.socket_path, tmux_bin=connection.prefix[0]),
        session_id=identity.session_id,
        session_name=record.name,
    )
    owner = FoundOrCreated(value, identity, connection, created=True)
    try:
        _check(result, "new-session")
        if record.name != name:
            msg = "tmux normalized the session name; cannot return an exact match"
            raise ValueError(msg)  # noqa: TRY301 - compensate this known creation
        owner._value = _materialize(connection, record)
        _verify(connection, record)
    except BaseException as failure:
        _cleanup(owner, failure)
        raise
    return owner
