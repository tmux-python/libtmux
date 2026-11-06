"""Owned fresh pane programs using native event waiters."""

from __future__ import annotations

import concurrent.futures
import contextlib
import dataclasses
import logging
import math
import os
import pathlib
import re
import selectors
import shlex
import shutil
import subprocess
import threading
import time
import typing as t
import uuid

from libtmux import exc

if t.TYPE_CHECKING:
    from libtmux.session import Session

logger = logging.getLogger(__name__)
_FIELDS = "#{pid}|#{start_time}|#{window_id}|#{pane_id}|#{window_name}"
_STATE = _FIELDS + "|#{pane_dead}|#{pane_dead_status}|#{pane_dead_signal}"


@dataclasses.dataclass(frozen=True, slots=True)
class _ProgramExit:
    pane_id: str
    exit_status: int | None
    exit_signal: str | None


@dataclasses.dataclass(frozen=True, slots=True)
class _ProgramTermination:
    pane_id: str
    pane_removed: bool
    exit_status: int | None
    exit_signal: str | None


@dataclasses.dataclass(frozen=True, slots=True)
class _PaneObservation:
    pane_id: str
    lines: tuple[str, ...]
    command: tuple[str, ...]
    start: int
    end: int | t.Literal["-"]
    join_wrapped: bool
    started_ns: int
    finished_ns: int
    target_lifetime_verified: bool | None = dataclasses.field(default=None, init=False)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


class _FailureEvidence:
    last_observation: _ProgramExit | None
    last_capture: _PaneObservation | None
    operation_error: BaseException
    cleanup_errors: tuple[BaseException, ...]
    owner: _Program


class _ProgramFailure(_FailureEvidence, exc.LibTmuxException):
    """Keep existing exception catches while attaching the owned handle."""


class _ProgramTimeout(_FailureEvidence, exc.WaitTimeout):
    """A bounded program operation expired."""


class _ProgramCancelled(_FailureEvidence, concurrent.futures.CancelledError):
    """A wait was cancelled without terminating its program."""


class _Environment(dict[str, str]):
    def __repr__(self) -> str:
        return "<program client environment>"


def _budget(
    timeout: float, cancel: threading.Event | None
) -> tuple[float, threading.Event]:
    if type(timeout) not in (int, float):
        msg = "timeout must be finite and nonnegative"
        raise ValueError(msg)
    try:
        seconds = float(timeout)
    except OverflowError as error:
        msg = "timeout must be finite and nonnegative"
        raise ValueError(msg) from error
    if not math.isfinite(seconds) or seconds < 0:
        msg = "timeout must be finite and nonnegative"
        raise ValueError(msg)
    if cancel is not None and not isinstance(cancel, threading.Event):
        msg = "cancel_event must be a threading.Event"
        raise ValueError(msg)
    return (
        time.monotonic() + seconds,
        cancel if cancel is not None else threading.Event(),
    )


def _check(deadline: float, cancel: threading.Event) -> float:
    if cancel.is_set():
        msg = "program operation cancelled"
        raise concurrent.futures.CancelledError(msg)
    left = deadline - time.monotonic()
    if left <= 0:
        msg = "program operation"
        raise subprocess.TimeoutExpired(msg, 0)
    return left


class _Client:
    """Own one bounded native pipe transport, including an event waiter."""

    def __init__(
        self, command: tuple[str, ...], env: _Environment, limit: int = 16384
    ) -> None:
        self.command = command
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "tmux command dispatched", extra={"tmux_cmd": shlex.join(command)}
            )
        self.selector = selectors.DefaultSelector()
        try:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
        except BaseException:
            self.selector.close()
            raise
        self.output = bytearray()
        self.errors = bytearray()
        assert self.process.stdout is not None
        assert self.process.stderr is not None
        self.closed = False
        try:
            self.selector.register(
                self.process.stdout, selectors.EVENT_READ, (self.output, limit)
            )
            self.selector.register(
                self.process.stderr, selectors.EVENT_READ, (self.errors, 16384)
            )
        except BaseException as error:
            try:
                self.close()
            except BaseException as cleanup_error:  # noqa: BLE001
                error.cleanup_error = cleanup_error  # type: ignore[attr-defined]
            raise

    def pump(self, seconds: float = 0) -> None:
        for key, _ in self.selector.select(seconds):
            buffer, limit = key.data
            chunk = os.read(key.fd, min(65536, limit - len(buffer) + 1))
            if not chunk:
                self.selector.unregister(key.fileobj)
            else:
                buffer.extend(chunk)
                if len(buffer) > limit:
                    msg = "program client exceeds its transport byte limit"
                    raise ValueError(msg)
        if self.errors:
            raise subprocess.CalledProcessError(
                self.process.poll() or 1,
                self.command,
                output=bytes(self.output),
                stderr=bytes(self.errors),
            )

    def frames(self) -> list[list[bytes]]:
        frames: list[list[bytes]] = []
        key: tuple[bytes, ...] | None = None
        body: list[bytes] = []
        for line in self.output.splitlines():
            match = re.fullmatch(rb"%(begin|end|error) (\d+) (\d+) (\d+)", line)
            if match is None:
                if key is not None:
                    body.append(bytes(line))
                continue
            kind, *parts = match.groups()
            if kind == b"begin":
                key, body = tuple(parts), []
            elif tuple(parts) == key:
                if kind == b"error":
                    raise subprocess.CalledProcessError(
                        1, self.command, output=bytes(self.output)
                    )
                frames.append(body)
                key = None
        return frames

    def until(
        self, predicate: t.Callable[[], bool], deadline: float, cancel: threading.Event
    ) -> None:
        while not predicate():
            left = _check(deadline, cancel)
            self.pump(min(left, 0.05))
            if (
                not self.selector.get_map()
                and self.process.poll() is not None
                and not predicate()
            ):
                msg = "program observer ended before its evidence arrived"
                raise EOFError(msg)

    def close(self) -> None:
        if self.closed:
            return
        try:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=0.5)
        finally:
            self.selector.close()
            for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
                if pipe is not None:
                    pipe.close()
        self.closed = True


class _Program:
    """Own a created pane and two observers; methods never follow mutable facades."""

    def __init__(self, prefix: tuple[str, ...], environment: _Environment) -> None:
        self._prefix = prefix
        self._environment = environment
        self._receipt: tuple[str, ...] = ()
        self._exit: _Client | None = None
        self._generation: _Client | None = None
        self._result: _ProgramExit | None = None
        self._capture: _PaneObservation | None = None
        self._launched = False
        self._launch_submitted = False
        self._removed = False
        self._cleaned = False
        self._invalid = False

    @property
    def pane_id(self) -> str:
        return self._receipt[3]

    def _run(
        self,
        args: tuple[str, ...],
        deadline: float,
        cancel: threading.Event,
        limit: int = 16384,
    ) -> bytes:
        _check(deadline, cancel)
        client = _Client((*self._prefix, *args), self._environment, limit)
        try:
            client.until(
                lambda: (
                    not client.selector.get_map() and client.process.poll() is not None
                ),
                deadline,
                cancel,
            )
            if client.process.returncode != 0:
                raise subprocess.CalledProcessError(  # noqa: TRY301
                    client.process.returncode or 1,
                    client.command,
                    output=bytes(client.output),
                    stderr=bytes(client.errors),
                )
            output = bytes(client.output)
        except BaseException as error:
            try:
                client.close()
            except BaseException as cleanup_error:  # noqa: BLE001
                error.cleanup_error = cleanup_error  # type: ignore[attr-defined]
            raise
        else:
            client.close()
            return output

    def _condition(self) -> str:
        comparisons = [
            "#{==:#{" + key + "}," + value + "}"
            for key, value in zip(
                ("pid", "start_time", "window_id", "pane_id", "window_name"),
                self._receipt,
                strict=True,
            )
        ]
        result = comparisons.pop()
        for comparison in comparisons:
            result = "#{&&:" + comparison + "," + result + "}"
        if not self._launch_submitted:
            result = (
                "#{&&:" + result + ",#{&&:#{==:#{pane_pid},},#{==:#{pane_dead},0}}}"
            )
        return result

    def _guard(self, commands: str, *, completed_only: bool = False) -> tuple[str, ...]:
        condition = self._condition()
        if completed_only:
            condition = "#{&&:" + condition + ",#{==:#{pane_dead},1}}"
        return (
            "if-shell",
            "-F",
            "-t",
            self.pane_id,
            condition,
            "display-message -p LIBTMUX_PROGRAM_ADMITTED ; " + commands,
            "display-message -p LIBTMUX_PROGRAM_REFUSED",
        )

    def _guarded(
        self,
        commands: str,
        deadline: float,
        cancel: threading.Event,
        limit: int = 16384,
        *,
        completed_only: bool = False,
    ) -> bytes:
        output = self._run(
            self._guard(commands, completed_only=completed_only),
            deadline,
            cancel,
            limit,
        )
        prefix = b"LIBTMUX_PROGRAM_ADMITTED\n"
        if not output.startswith(prefix):
            msg = "program ownership or lifetime could not be verified"
            raise ValueError(msg)
        return output[len(prefix) :]

    def _state(
        self, deadline: float, cancel: threading.Event
    ) -> tuple[str, ...] | None:
        row = self._run(
            ("display-message", "-p", "-t", self.pane_id, _STATE), deadline, cancel
        )
        fields = tuple(row.decode().strip().split("|"))
        if fields[:2] != self._receipt[:2]:
            msg = "program server lifetime changed"
            raise ValueError(msg)
        if len(fields) != 8 or fields[:5] != self._receipt:
            msg = "program ownership or lifetime changed"
            raise ValueError(msg)
        return fields

    def _generation_alive(self, deadline: float, cancel: threading.Event) -> None:
        generation = self._generation
        if generation is None or generation.closed:
            msg = "program lifetime observation is unavailable"
            raise ValueError(msg)
        generation.pump()
        if self._invalid or b"LIBTMUX_LIFETIME_INVALID" in generation.output:
            self._invalid = True
            msg = "program lifetime changed after a pane respawn"
            raise ValueError(msg)
        waiters = (
            self._run(("wait-for", "-E", "-l", "pane-created"), deadline, cancel)
            .decode()
            .splitlines()
        )
        if f"client-{generation.process.pid}" not in waiters:
            self._invalid = True
            msg = "program lifetime observer was lost or invalidated"
            raise ValueError(msg)

    def _raise(
        self, error: BaseException, cleanup_errors: tuple[BaseException, ...] = ()
    ) -> t.NoReturn:
        if isinstance(error, (_ProgramFailure, _ProgramTimeout, _ProgramCancelled)):
            raise error
        cleanup_errors = (*cleanup_errors, *getattr(error, "cleanup_errors", ()))
        transport_cleanup = getattr(error, "cleanup_error", None)
        if transport_cleanup is not None:
            cleanup_errors = (*cleanup_errors, transport_cleanup)
        if isinstance(error, KeyboardInterrupt):
            failure: BaseException = error
        elif isinstance(error, subprocess.TimeoutExpired):
            failure = _ProgramTimeout("program operation deadline expired")
        elif isinstance(error, concurrent.futures.CancelledError):
            failure = _ProgramCancelled(str(error))
        else:
            failure = _ProgramFailure(str(error))
        for name, value in {
            "last_observation": self._result,
            "last_capture": self._capture,
            "operation_error": error,
            "cleanup_errors": cleanup_errors,
            "owner": self,
        }.items():
            setattr(failure, name, value)
        if failure is error:
            raise failure
        raise failure from error

    @contextlib.contextmanager
    def _errors(self) -> t.Iterator[None]:
        try:
            yield
        except BaseException as error:  # noqa: BLE001
            # Keep interruption identity and original operation causes.
            self._raise(error)

    def wait(
        self, *, timeout: float = 5, cancel_event: threading.Event | None = None
    ) -> _ProgramExit:
        """Return recorded exit status or signal; cancellation preserves the program."""
        deadline, cancel = _budget(timeout, cancel_event)
        with self._errors():
            _check(deadline, cancel)
            if self._removed:
                msg = "program pane was removed; unobserved exit status is unknown"
                raise ValueError(msg)
            self._generation_alive(deadline, cancel)
            if self._result is not None:
                return self._result
            observer = self._exit
            assert observer is not None
            while not any(
                line.startswith(b"LIBTMUX_EXIT|")
                for frame in observer.frames()
                for line in frame
            ):
                self._generation_alive(deadline, cancel)
                self._state(deadline, cancel)
                observer.pump(min(_check(deadline, cancel), 0.05))
                if (
                    not observer.selector.get_map()
                    and observer.process.poll() is not None
                    and not any(
                        line.startswith(b"LIBTMUX_EXIT|")
                        for frame in observer.frames()
                        for line in frame
                    )
                ):
                    msg = "program exit observer was lost; exit status is unknown"
                    raise EOFError(msg)
            self._generation_alive(deadline, cancel)
            rows = [
                line.decode()
                for frame in observer.frames()
                for line in frame
                if line.startswith(b"LIBTMUX_EXIT|")
            ]
            fields = tuple(rows[-1].split("|")[1:])
            if len(fields) != 8 or fields[:5] != self._receipt or fields[5] != "1":
                msg = "program exit evidence is missing or belongs to another lifetime"
                raise ValueError(msg)
            status = int(fields[6]) if fields[6] else None
            signal = fields[7] or None
            if (status is None) == (signal is None):
                msg = "program exit status and signal are unknown"
                raise ValueError(msg)
            self._result = _ProgramExit(self.pane_id, status, signal)
            observer.close()
            return self._result

    def collect(
        self,
        *,
        start: int = -1000,
        end: int | t.Literal["-"] = "-",
        max_text_codepoints: int = 1048576,
        timeout: float = 5,
    ) -> _PaneObservation:
        """Capture a bounded rendered range; this is not a program byte stream."""
        deadline, cancel = _budget(timeout, None)
        if type(start) is not int or not -10000 <= start <= 10000:
            msg = "start must be an integer in [-10000, 10000]"
            raise ValueError(msg)
        if end != "-" and (type(end) is not int or not -10000 <= end <= 10000):
            msg = "end must be '-' or an integer in [-10000, 10000]"
            raise ValueError(msg)
        if (
            type(max_text_codepoints) is not int
            or not 1 <= max_text_codepoints <= 1048576
        ):
            msg = "max_text_codepoints must be an integer in [1, 1048576]"
            raise ValueError(msg)
        with self._errors():
            self._generation_alive(deadline, cancel)
            args = (
                "capture-pane",
                "-p",
                "-J",
                "-t",
                self.pane_id,
                "-S",
                str(start),
                "-E",
                str(end),
            )
            started_ns = time.monotonic_ns()
            output = self._guarded(
                shlex.join(args), deadline, cancel, 4 * max_text_codepoints + 65536
            )
            finished_ns = time.monotonic_ns()
            self._generation_alive(deadline, cancel)
            text = (
                output.decode("utf-8", "backslashreplace")
                .replace("\r\n", "\n")
                .replace("\r", "\n")
                .rstrip("\n")
            )
            if len(text) > max_text_codepoints:
                msg = "capture exceeds max_text_codepoints"
                raise ValueError(msg)
            self._capture = _PaneObservation(
                self.pane_id,
                tuple(text.split("\n")) if text else (),
                (*self._prefix, *self._guard(shlex.join(args))),
                start,
                end,
                True,
                started_ns,
                finished_ns,
            )
            return self._capture

    def _close_observers(self) -> tuple[BaseException, ...]:
        errors: list[BaseException] = []
        for client in (self._exit, self._generation):
            if client is not None:
                try:
                    client.close()
                except BaseException as error:  # noqa: BLE001
                    errors.append(error)
        return tuple(errors)

    def _remove(
        self, deadline: float, cancel: threading.Event, *, completed_only: bool = False
    ) -> None:
        try:
            commands = f"kill-pane -t {self.pane_id}"
            if self._launch_submitted:
                generation = self._generation
                if (
                    generation is None
                    or generation.closed
                    or generation.process.poll() is not None
                    or self._invalid
                ):
                    msg = "submitted program lifetime is unknown; cleanup is refused"
                    raise ValueError(msg)  # noqa: TRY301
                # Consume the still-pending registration and delete in one native queue.
                # A respawn or lost client removes the waiter, whose error cancels kill.
                commands = (
                    f"wait-for -E -w client-{generation.process.pid} pane-created ; "
                    + commands
                )
            self._guarded(commands, deadline, cancel, completed_only=completed_only)
        except BaseException as error:
            failures = self._close_observers()
            if failures:
                error.cleanup_errors = failures  # type: ignore[attr-defined]
            raise
        self._removed = True

    def terminate(self, *, timeout: float = 5) -> _ProgramTermination:
        """Close the owned pane and PTY; descendant process exit is not established."""
        deadline, cancel = _budget(timeout, None)
        with self._errors():
            if not self._removed:
                self._remove(deadline, cancel)
            errors = self._close_observers()
            if errors:
                self._raise(errors[0], errors)
            return _ProgramTermination(
                self.pane_id,
                True,
                self._result.exit_status if self._result else None,
                self._result.exit_signal if self._result else None,
            )

    def cleanup(self, *, timeout: float = 5) -> None:
        """Remove a completed owned pane and reap observers; refuse a live program."""
        deadline, cancel = _budget(timeout, None)
        if self._cleaned:
            return
        with self._errors():
            if not self._removed:
                # An absent pane is already removed; never follow a fallback target.
                try:
                    row = self._run(
                        ("display-message", "-p", "-t", self.pane_id, _STATE),
                        deadline,
                        cancel,
                    )
                    fields = tuple(row.decode().strip().split("|"))
                    if fields[:2] != self._receipt[:2]:
                        msg = "program server lifetime changed"
                        raise ValueError(msg)  # noqa: TRY301
                    if len(fields) == 8 and fields[3] != self.pane_id:
                        self._removed = True
                    else:
                        if fields[:5] != self._receipt:
                            msg = "program ownership changed"
                            raise ValueError(msg)  # noqa: TRY301
                        if self._launch_submitted:
                            self._generation_alive(deadline, cancel)
                except BaseException as error:
                    failures = self._close_observers()
                    if failures:
                        error.cleanup_errors = failures  # type: ignore[attr-defined]
                    raise
                if not self._removed:
                    if self._launched and fields[5] != "1":
                        msg = "program is still running; call terminate explicitly"
                        raise ValueError(msg)
                    self._remove(
                        deadline, cancel, completed_only=self._launch_submitted
                    )
            errors = self._close_observers()
            if errors:
                self._raise(errors[0], errors)
            self._cleaned = True


def start_program(
    session: Session,
    argv: t.Sequence[str],
    timeout: float,
    cancel_event: threading.Event | None,
) -> _Program:
    """Freeze the selected native route, then retain and observe a fresh program."""
    from libtmux import server as server_module, session as session_module

    deadline, cancel = _budget(timeout, cancel_event)
    if isinstance(argv, (str, bytes)) or not isinstance(argv, t.Sequence):
        msg = "argv must be a sequence of strings"
        raise TypeError(msg)
    arguments = tuple(argv)
    if (
        len(arguments) < 2
        or any(not isinstance(arg, str) or "\0" in arg for arg in arguments)
        or not arguments[0]
    ):
        msg = "argv requires a program and at least one string argument without NUL"
        raise ValueError(msg)
    server = session.server
    if (
        type(session).cmd is not session_module._STOCK_SESSION_CMD
        or "cmd" in vars(session)
        or type(server).cmd is not server_module._STOCK_SERVER_CMD
        or "cmd" in vars(server)
        or getattr(server, "_engine", None) is not None
        or getattr(server, "engine", None) is not None
    ):
        msg = "program handles require the stock command dispatcher"
        raise NotImplementedError(msg)
    session_id = session.session_id
    if not isinstance(session_id, str) or re.fullmatch(r"\$\d+", session_id) is None:
        msg = "program handles require a stable session ID"
        raise ValueError(msg)
    environment = _Environment(os.environ)
    if environment.get("TMUX_TMPDIR"):
        environment["TMUX_TMPDIR"] = str(
            pathlib.Path(environment["TMUX_TMPDIR"]).resolve()
        )
    binary = shutil.which(
        server.tmux_bin or "tmux", path=environment.get("PATH", os.defpath)
    )
    if binary is None:
        raise exc.TmuxCommandNotFound
    prefix = [str(pathlib.Path(binary).resolve())]
    if server.colors:
        if server.colors not in (88, 256):
            raise exc.UnknownColorOption
        prefix.append("-2" if server.colors == 256 else "-8")
    if server.config_file:
        prefix.extend(("-f", str(pathlib.Path(server.config_file).resolve())))
    if server.socket_path:
        prefix.extend(("-S", str(pathlib.Path(server.socket_path).resolve())))
    if server.socket_name:
        prefix.extend(("-L", server.socket_name))
    job = _Program(tuple(prefix), environment)
    try:
        parent = (
            job._run(
                (
                    "display-message",
                    "-p",
                    "-t",
                    session_id,
                    "#{pid}|#{start_time}|#{session_id}|#{version}",
                ),
                deadline,
                cancel,
            )
            .decode()
            .strip()
            .split("|")
        )
        if (
            len(parent) != 4
            or parent[2] != session_id
            or not parent[0].isdigit()
            or not parent[1].isdigit()
        ):
            msg = "borrowed parent session could not be identified"
            raise ValueError(msg)  # noqa: TRY301
        version = parent[3]
        parsed = re.match(r"(\d+)\.(\d+)", version.removeprefix("next-"))
        if parsed is None or tuple(map(int, parsed.groups())) < (3, 8):
            msg = "program handles require a connected tmux 3.8+ server"
            raise NotImplementedError(msg)  # noqa: TRY301
        name = "libtmux-program-" + uuid.uuid4().hex
        parent_guard = (
            "#{&&:#{&&:#{==:#{pid},"
            + parent[0]
            + "},#{==:#{start_time},"
            + parent[1]
            + "}},#{==:#{session_id},"
            + session_id
            + "}}"
        )
        creation = shlex.join(
            (
                "new-window",
                "-d",
                "-E",
                "-n",
                name,
                "-t",
                session_id + ":",
                "-P",
                "-F",
                _FIELDS,
            )
        )
        receipt = job._run(
            (
                "if-shell",
                "-F",
                "-t",
                session_id,
                parent_guard,
                creation,
                "display-message -p LIBTMUX_PROGRAM_REFUSED",
            ),
            deadline,
            cancel,
        )
        fields = tuple(receipt.decode().strip().split("|"))
        if (
            len(fields) != 5
            or fields[4] != name
            or not fields[0].isdigit()
            or not fields[1].isdigit()
            or re.fullmatch(r"@\d+", fields[2]) is None
            or re.fullmatch(r"%\d+", fields[3]) is None
        ):
            msg = "creation receipt is missing; submitted outcome is unknown"
            raise ValueError(msg)  # noqa: TRY301
        job._receipt = fields
        job._guarded(
            f"set-option -p -t {job.pane_id} remain-on-exit on ; "
            f"set-option -p -t {job.pane_id} remain-on-exit-format ''",
            deadline,
            cancel,
        )
        predicate = "#{==:#{pane}," + job.pane_id + "}"
        exit_args = (
            "wait-for",
            "-E",
            "-F",
            predicate,
            "pane-died",
            ";",
            "display-message",
            "-p",
            "-t",
            job.pane_id,
            "LIBTMUX_EXIT|" + _STATE,
        )
        _check(deadline, cancel)
        observer = _Client((*job._prefix, "-C", *exit_args), environment)
        job._exit = observer
        observer.until(lambda: bool(observer.frames()), deadline, cancel)
        _check(deadline, cancel)
        launch = shlex.join(("respawn-pane", "-t", job.pane_id, "--", *arguments))
        launch += " ; " + shlex.join(
            ("display-message", "-p", "-t", job.pane_id, "LIBTMUX_SPAWN|#{pane_pid}")
        )
        launch += " ; " + shlex.join(
            ("wait-for", "-E", "-F", predicate, "pane-created")
        )
        launch += " ; display-message -p LIBTMUX_LIFETIME_INVALID"
        launch_arguments = job._guard(launch)
        job._launch_submitted = True
        generation = _Client((*job._prefix, "-C", *launch_arguments), environment)
        job._generation = generation
        # Admission, respawn, PID receipt and registration follow the if-shell frame.
        generation.until(lambda: len(generation.frames()) >= 5, deadline, cancel)
        if (
            b"LIBTMUX_PROGRAM_REFUSED" in job._generation.output
            or b"LIBTMUX_SPAWN|" not in job._generation.output
        ):
            msg = "program launch ownership was refused"
            raise ValueError(msg)  # noqa: TRY301
        job._launched = True
        job._generation_alive(deadline, cancel)
    except BaseException as error:  # noqa: BLE001
        cleanup_errors: list[BaseException] = []
        if job._receipt:
            try:
                cleanup_deadline, cleanup_cancel = _budget(0.5, None)
                job._remove(cleanup_deadline, cleanup_cancel)
            except BaseException as cleanup_error:  # noqa: BLE001
                cleanup_errors.append(cleanup_error)
        cleanup_errors.extend(job._close_observers())
        job._raise(error, tuple(cleanup_errors))
    return job
