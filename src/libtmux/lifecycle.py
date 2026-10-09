"""Explicit destruction responsibility for tmux resources.

Borrowed handles remain useful after client scope exit. An ``Owned`` context
accepts destruction responsibility and retains the remote identity independently
of later edits to the borrowed handle.
"""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import math
import os
import re
import secrets
import select
import shlex
import sys
import threading
import time
import typing as t
import weakref

from libtmux import exc
from libtmux._compat import BaseExceptionGroup
from libtmux.common import _run_cleanup

if t.TYPE_CHECKING:
    import types
    from collections.abc import Generator

    from libtmux.common import tmux_cmd
    from libtmux.server import Server

Resource = t.TypeVar("Resource")
ObjectKind = t.Literal["server", "session", "window", "pane"]
_GENERATION_OPTION = "@libtmux_owner_generation"
_TOKEN = re.compile(r"[0-9a-fA-F]{32}\Z")


class UnknownCreation(exc.LibTmuxException):
    """Creation returned no trustworthy receipt; inspect before retrying it."""


class CreationCleanupError(exc.LibTmuxException):
    """A failed creation rollback retains its exact owner for inspection or retry.

    Raised alongside the original operation error in a ``BaseExceptionGroup``.
    ``__cause__`` retains the cleanup failure. ``owner.identity`` identifies the
    accepted resource; ``owner.close()`` retries against that same generation.

    Parameters
    ----------
    owner : Owned
        Cleanup responsibility retained from the original creation receipt.
    """

    def __init__(self, owner: Owned[None]) -> None:
        self.owner = owner
        super().__init__("creation rollback failed; inspect or retry error.owner")


@dataclasses.dataclass(frozen=True)
class OwnedIdentity:
    """The immutable endpoint, daemon generation and object accepted for cleanup.

    Attributes
    ----------
    socket_path : str
        Captured absolute endpoint.
    server_pid : int
        PID reported by the accepted tmux daemon.
    start_time : int
        Daemon start time reported by tmux, in whole seconds.
    generation_token : str
        Random daemon metadata that also distinguishes PID/start-time reuse.
    kind : str
        ``server``, ``session``, ``window`` or ``pane``.
    object_id : str or None
        Stable tmux ID; a whole-server owner has no object ID.
    """

    socket_path: str
    server_pid: int
    start_time: int
    generation_token: str
    kind: ObjectKind
    object_id: str | None

    @property
    def _condition(self) -> str:
        """Test this generation within the daemon's destructive command dispatch."""
        return (
            "#{&&:"
            f"#{{&&:#{{==:#{{pid}},{self.server_pid}}},"
            f"#{{==:#{{start_time}},{self.start_time}}}}},"
            f"#{{==:#{{{_GENERATION_OPTION}}},{self.generation_token}}}}}"
        )


@dataclasses.dataclass(frozen=True)
class _CreationReceipt:
    client: Server
    identity: OwnedIdentity


def _identity_from_fields(
    client: Server, kind: ObjectKind, fields: list[str]
) -> OwnedIdentity:
    """Decode daemon and object identity returned on one creation connection."""
    prefix = {"session": "$", "window": "@", "pane": "%"}.get(kind)
    if (
        len(fields) != 4
        or not fields[0].isascii()
        or not fields[0].isdecimal()
        or int(fields[0]) <= 0
        or not fields[1].isascii()
        or not fields[1].isdecimal()
        or not _TOKEN.fullmatch(fields[2])
        or (
            not re.fullmatch(re.escape(prefix) + r"[0-9]+", fields[3])
            if prefix is not None
            else bool(fields[3])
        )
    ):
        message = (
            "tmux returned invalid ownership identity or reserved generation token"
        )
        raise exc.LibTmuxException(message)
    return OwnedIdentity(
        client.socket_path,
        int(fields[0]),
        int(fields[1]),
        fields[2],
        kind,
        fields[3] or None,
    )


def _creation_format(kind: ObjectKind, payload: str) -> str:
    """Prefix object output with its same-connection creation receipt."""
    return (
        f"#{{pid}}\t#{{start_time}}\t#{{{_GENERATION_OPTION}}}\t"
        f"#{{{kind}_id}}\t{payload}"
    )


def _rollback_creation(receipt: _CreationReceipt, failure: BaseException) -> None:
    """Recover the recorded creation without accepting a later daemon token."""

    def recover() -> None:
        owner = Owned._from_receipt(None, receipt)
        if not owner._process_exited():
            try:
                owner.close()
            except BaseException as cleanup_error:
                if not isinstance(cleanup_error, Exception):
                    retry = CreationCleanupError(owner)
                    retry.__cause__ = cleanup_error
                    message = "creation rollback was interrupted"
                    raise BaseExceptionGroup(message, [cleanup_error, retry]) from None
                raise CreationCleanupError(owner) from cleanup_error

    _run_cleanup(recover, failure)


def _require_creation_success(result: tmux_cmd) -> None:
    """Surface the original client failure after retaining a creation receipt."""
    if result.returncode or result.stderr:
        detail = "\n".join(result.stderr)
        raise exc.LibTmuxException(detail or f"exit status {result.returncode}")


def _check_creation_guards(result: tmux_cmd, stale: str, invalid: str) -> None:
    """Distinguish refusal before dispatch from a missing creation receipt."""
    detail = "\n".join(result.stderr)
    if stale in detail:
        message = "the creation endpoint now names a different tmux daemon"
        raise exc.StaleTmuxOwner(message)
    if invalid in detail:
        message = "tmux returned an invalid reserved generation token before creation"
        raise exc.LibTmuxException(message)


def _verify_identity(client: Server, identity: OwnedIdentity, timeout: float) -> None:
    """Refuse handoff when a later connection identifies another generation."""
    accepted = _capture_identity(client, identity.kind, identity.object_id, timeout)
    if accepted != identity:
        message = "the daemon generation changed after creation"
        raise exc.StaleTmuxOwner(message)


def _creation_receipt(
    client: Server, kind: ObjectKind, command: str, result: tmux_cmd
) -> tuple[_CreationReceipt, str]:
    """Accept a receipt before classifying the command's exit status."""
    fields = result.stdout[0].split("\t", 4) if result.stdout else []
    if len(fields) != 5:
        detail = "\n".join(result.stderr) or f"exit status {result.returncode}"
        message = (
            f"{command} returned no trustworthy creation receipt ({detail}); "
            "inspect the endpoint before retry"
        )
        raise UnknownCreation(message)
    try:
        identity = _identity_from_fields(client, kind, fields[:4])
    except Exception as failure:
        message = (
            f"{command} returned no trustworthy creation receipt; "
            "inspect the endpoint before retry"
        )
        raise UnknownCreation(message) from failure
    return _CreationReceipt(client, identity), fields[4]


@contextlib.contextmanager
def _creation(
    server: Server,
    kind: ObjectKind,
    command: str,
    arguments: tuple[str | int, ...],
    *,
    parent: object | None = None,
) -> Generator[tuple[tmux_cmd, _CreationReceipt], None, None]:
    """Keep a creation receipt across materialization and its possible failure."""
    client = copy.copy(server)
    operation = shlex.join([command, *(str(arg) for arg in arguments)])
    stale = "libtmux-creation-stale-" + secrets.token_hex(16)
    invalid = "libtmux-creation-invalid-generation-" + secrets.token_hex(16)
    if parent is not None:
        _, parent_kind, parent_id = _kind_and_id(parent)
        prior = getattr(parent, "_creation_receipt", None)
        parent_identity = (
            prior.identity
            if isinstance(prior, _CreationReceipt)
            else _capture_identity(client, parent_kind, parent_id, 5.0)
        )
        operation = shlex.join(
            ["if-shell", "-F", parent_identity._condition, operation, stale]
        )
    valid = "#{m/r:^" + "[0-9a-fA-F]" * 32 + "$,#{" + _GENERATION_OPTION + "}}"
    arguments = (
        *(("start-server", ";") if kind == "session" else ()),
        *_generation_setup(),
        "if-shell",
        "-F",
        valid,
        operation,
        invalid,
    )
    observed: list[tmux_cmd] = []
    result: tmux_cmd | None = None
    receipt: _CreationReceipt | None = None
    try:
        result = client.cmd(
            str(arguments[0]),
            *arguments[1:],
            timeout=5.0,
            _on_completion=observed.append,
        )
        _check_creation_guards(result, stale, invalid)
        receipt, result.stdout[0] = _creation_receipt(client, kind, command, result)
        _require_creation_success(result)
        yield result, receipt
        _verify_identity(client, receipt.identity, 5.0)
    except BaseException as failure:
        if receipt is None and observed:
            with contextlib.suppress(UnknownCreation):
                receipt, _ = _creation_receipt(client, kind, command, observed[0])
        if receipt is not None:
            _rollback_creation(receipt, failure)
        elif result is None:
            message = (
                f"{command} returned no creation receipt; "
                "inspect the endpoint before retry"
            )
            if isinstance(failure, Exception):
                raise UnknownCreation(message) from failure
            if sys.version_info >= (3, 11):
                failure.add_note(message)
            else:
                failure.__dict__.setdefault("__notes__", []).append(message)
        raise


def _kind_and_id(resource: object) -> tuple[Server, ObjectKind, str | None]:
    """Validate an accepted public resource and its exact tmux ID."""
    from libtmux.pane import Pane
    from libtmux.server import Server
    from libtmux.session import Session
    from libtmux.window import Window

    if isinstance(resource, Server):
        return resource, "server", None
    if isinstance(resource, Session):
        kind: ObjectKind = "session"
        object_id = resource.session_id
    elif isinstance(resource, Window):
        kind = "window"
        object_id = resource.window_id
    elif isinstance(resource, Pane):
        kind = "pane"
        object_id = resource.pane_id
    else:
        message = "ownership requires a Server, Session, Window or Pane"
        raise TypeError(message)
    prefix = {"session": "$", "window": "@", "pane": "%"}[kind]
    if object_id is None or not re.fullmatch(re.escape(prefix) + r"[0-9]+", object_id):
        message = f"invalid {kind} ID: {object_id!r}"
        raise ValueError(message)
    return resource.server, kind, object_id


def _generation_setup() -> tuple[str, ...]:
    """Initialize reserved server metadata on the accepting tmux connection."""
    token = secrets.token_hex(16)
    return (
        "set-option",
        "-soq",
        _GENERATION_OPTION,
        token,
        ";",
    )


def _capture_identity(
    client: Server, kind: ObjectKind, object_id: str | None, timeout: float
) -> OwnedIdentity:
    """Accept token and numeric identity in the same connected command list."""
    setup = _generation_setup()
    target = ("-t", object_id) if object_id is not None else ()
    identity_format = f"#{{pid}}\t#{{start_time}}\t#{{{_GENERATION_OPTION}}}\t" + (
        f"#{{{kind}_id}}" if object_id is not None else ""
    )
    result = client.cmd(
        setup[0],
        *setup[1:],
        "display-message",
        "-p",
        *target,
        identity_format,
        timeout=timeout,
    )
    if result.returncode or result.stderr:
        raise exc.LibTmuxException(
            "\n".join(result.stderr) or f"exit status {result.returncode}",
            subcommand="accept-ownership",
        )
    fields = result.stdout[0].split("\t") if len(result.stdout) == 1 else []
    if (
        len(fields) != 4
        or not fields[0].isascii()
        or not fields[0].isdecimal()
        or int(fields[0]) <= 0
        or not fields[1].isascii()
        or not fields[1].isdecimal()
        or not _TOKEN.fullmatch(fields[2])
        or fields[3] != (object_id or "")
    ):
        message = (
            "tmux returned invalid ownership identity or reserved generation token"
        )
        raise exc.LibTmuxException(message)
    return OwnedIdentity(
        client.socket_path, int(fields[0]), int(fields[1]), fields[2], kind, object_id
    )


class Owned(t.Generic[Resource]):
    """Destroy an accepted remote resource at context exit or on ``close()``.

    Acceptance initializes the reserved server option
    ``@libtmux_owner_generation`` if absent, then captures it with the daemon
    and object IDs in one tmux connection. An existing malformed token fails
    acceptance. Keep that reserved option unchanged during the daemon's life.

    Each close attempt is bounded by ``timeout``. A failed attempt preserves
    ``cleanup_error`` and can be retried. Both body and cleanup failures survive
    in a ``BaseExceptionGroup``. Garbage collection releases local process
    observation handles only; explicit close or context exit destroys tmux state.

    Parameters
    ----------
    value : Server, Session, Window or Pane
        Existing resource whose destruction the caller accepts.
    timeout : float
        Positive finite seconds for acceptance and each cleanup attempt.
    """

    def __init__(self, value: Resource, *, timeout: float = 5.0) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            message = "ownership timeout must be positive and finite"
            raise ValueError(message)
        server, kind, object_id = _kind_and_id(value)
        receipt = getattr(value, "_creation_receipt", None)
        if isinstance(receipt, _CreationReceipt):
            identity = _capture_identity(receipt.client, kind, object_id, timeout)
            if identity != receipt.identity:
                message = "the endpoint no longer identifies the created tmux resource"
                raise exc.StaleTmuxOwner(message)
            self._initialize(value, receipt.client, receipt.identity, timeout)
            return
        client = copy.copy(server)
        identity = _capture_identity(client, kind, object_id, timeout)
        self._initialize(value, client, identity, timeout)

    @classmethod
    def _from_receipt(
        cls, value: Resource, receipt: _CreationReceipt, timeout: float = 5.0
    ) -> Owned[Resource]:
        """Use the original creation identity without another acceptance query."""
        owner = cls.__new__(cls)
        owner._initialize(value, receipt.client, receipt.identity, timeout)
        return owner

    def _initialize(
        self,
        value: Resource,
        client: Server,
        identity: OwnedIdentity,
        timeout: float,
    ) -> None:
        """Retain local state after an adoption or a same-connection receipt."""
        self._value = value
        self._client = copy.copy(client)
        self._timeout = timeout
        self._identity = identity
        self._closed = False
        self._cleanup_error: BaseException | None = None
        self._lock = threading.RLock()
        self._pidfd: int | None = None
        self._release_pidfd: weakref.finalize[[int], Owned[Resource]] | None = None
        if hasattr(os, "pidfd_open"):
            try:
                self._pidfd = os.pidfd_open(self.identity.server_pid)
            except ProcessLookupError:
                # A completed process makes cleanup unnecessary if no replacement
                # is listening. The guarded dispatch still checks that endpoint.
                pass
            else:
                self._release_pidfd = weakref.finalize(self, os.close, self._pidfd)

    @property
    def value(self) -> Resource:
        """Return the borrowed object; editing it does not change cleanup identity."""
        return self._value

    @property
    def identity(self) -> OwnedIdentity:
        """Return the immutable remote identity accepted by this owner."""
        return self._identity

    @property
    def closed(self) -> bool:
        """Whether cleanup completed, rather than merely being attempted."""
        return self._closed

    @property
    def cleanup_error(self) -> BaseException | None:
        """Return the latest failed cleanup attempt, cleared after success."""
        return self._cleanup_error

    def _process_exited(self, timeout: float = 0) -> bool:
        """Observe the accepted process independently of the socket pathname."""
        if self._pidfd is not None:
            poller = select.poll()
            poller.register(self._pidfd, select.POLLIN)
            return bool(poller.poll(math.ceil(max(timeout, 0) * 1000)))
        deadline = time.monotonic() + timeout
        while True:
            try:
                os.kill(self.identity.server_pid, 0)
            except ProcessLookupError:
                return True
            except PermissionError:
                return False
            if time.monotonic() >= deadline:
                return False
            time.sleep(min(0.01, max(0, deadline - time.monotonic())))

    def _destroy(self, deadline: float) -> None:
        """Dispatch destruction only if the connected daemon matches acceptance."""
        identity = self.identity
        command = f"kill-{identity.kind}"
        argv = [command]
        if identity.object_id is not None:
            argv += ["-t", identity.object_id]
        stale = f"libtmux-stale-owner-{identity.generation_token}"
        result = self._client.cmd(
            "if-shell",
            "-F",
            identity._condition,
            shlex.join(argv),
            stale,
            timeout=max(0.001, deadline - time.monotonic()),
        )
        detail = "\n".join(result.stderr)
        if result.returncode or result.stderr:
            if stale in detail:
                message = "the endpoint now names a different tmux daemon"
                raise exc.StaleTmuxOwner(message)
            if identity.object_id is not None and detail == (
                f"can't find {identity.kind}: {identity.object_id}"
            ):
                return
            unreachable = (
                "no server running" in detail
                or "error connecting to" in detail
                or "server exited unexpectedly" in detail
            )
            if unreachable and self._process_exited():
                return
            if unreachable:
                message = "accepted tmux daemon is unreachable and may still be alive"
                raise exc.LibTmuxException(message, subcommand=command)
            raise exc.LibTmuxException(
                detail or f"exit status {result.returncode}", subcommand=command
            )
        if identity.kind == "server" and not self._process_exited(
            max(0, deadline - time.monotonic())
        ):
            message = "accepted tmux daemon has not exited before the cleanup deadline"
            raise exc.LibTmuxException(message, subcommand=command)

    def close(self) -> None:
        """Destroy the accepted resource, retaining failure for inspection and retry."""
        deadline = time.monotonic() + self._timeout
        if not self._lock.acquire(timeout=self._timeout):
            message = "timed out waiting for another cleanup attempt"
            error = TimeoutError(message)
            self._cleanup_error = error
            raise error
        try:
            if self._closed:
                return
            try:
                self._destroy(deadline)
            except BaseException as error:
                self._cleanup_error = error
                raise
            self._closed = True
            self._cleanup_error = None
            if self._release_pidfd is not None:
                self._release_pidfd()
                self._pidfd = None
        finally:
            self._lock.release()

    def __enter__(self) -> Resource:
        """Enter the owned scope and return its borrowed resource."""
        if self.closed:
            message = "cannot enter a closed tmux owner"
            raise RuntimeError(message)
        return self.value

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Close the owner while preserving a body failure if teardown also fails."""
        _run_cleanup(self.close, exc_value)
