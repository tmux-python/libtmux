"""Bounded native capture for the synchronous visible-text predicate."""

from __future__ import annotations

import concurrent.futures
import contextlib
import dataclasses
import logging
import math
import os
import pathlib
import selectors
import shlex
import shutil
import subprocess
import threading
import time
import typing as t

from libtmux import exc

if t.TYPE_CHECKING:
    from libtmux.pane import Pane


logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True, slots=True)
class _PaneObservation:
    pane_id: str
    lines: tuple[str, ...]
    command: tuple[str, ...]
    start: int | t.Literal["-"] | None
    end: int | t.Literal["-"] | None
    join_wrapped: bool
    started_ns: int
    finished_ns: int
    target_lifetime_verified: bool | None = dataclasses.field(default=None, init=False)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


class _WaitTimeout(exc.WaitTimeout):
    last_observation: _PaneObservation | None


class _WaitFailure(exc.LibTmuxException):
    last_observation: _PaneObservation | None


class _WaitCancelled(concurrent.futures.CancelledError):
    last_observation: _PaneObservation | None


class _Environment(dict[str, str]):
    def __repr__(self) -> str:
        """Keep inherited environment values out of exception-local displays."""
        return "<capture environment>"


def _finite_seconds(value: float, name: str) -> float:
    if type(value) not in (int, float):
        msg = f"{name} must be a finite number"
        raise ValueError(msg)
    try:
        result = float(value)
    except (OverflowError, TypeError, ValueError) as error:
        msg = f"{name} must be finite"
        raise ValueError(msg) from error
    if isinstance(value, bool) or not math.isfinite(result):
        msg = f"{name} must be finite"
        raise ValueError(msg)
    return result


def _command(
    pane: Pane,
    start: int | str | None,
    end: int | str | None,
    join: bool,
    environment: _Environment,
) -> tuple[str, ...]:
    from libtmux import pane as pane_module, server as server_module

    server = pane.server
    if (
        type(pane).cmd is not pane_module._STOCK_PANE_CMD
        or "cmd" in vars(pane)
        or type(server).cmd is not server_module._STOCK_SERVER_CMD
        or "cmd" in vars(server)
        or getattr(server, "_engine", None) is not None
    ):
        msg = "visible waits require the stock command dispatcher"
        raise NotImplementedError(msg)
    executable = shutil.which(
        server.tmux_bin or "tmux", path=environment.get("PATH", os.defpath)
    )
    if executable is None:
        raise exc.TmuxCommandNotFound
    pane_id = pane.pane_id
    if not isinstance(pane_id, str) or not pane_id:
        msg = "visible waits require a pane ID"
        raise ValueError(msg)
    arguments = ["capture-pane", "-t", pane_id, "-p"]
    if server.socket_name:
        arguments.insert(0, f"-L{server.socket_name}")
    if server.socket_path:
        arguments.insert(0, f"-S{pathlib.Path(server.socket_path).resolve()}")
    if server.config_file:
        arguments.insert(0, f"-f{pathlib.Path(server.config_file).resolve()}")
    if server.colors:
        if server.colors not in (88, 256):
            raise exc.UnknownColorOption
        arguments.insert(0, "-2" if server.colors == 256 else "-8")
    if start is not None:
        arguments.extend(("-S", str(start)))
    if end is not None:
        arguments.extend(("-E", str(end)))
    if join:
        arguments.append("-J")
    return (str(pathlib.Path(executable).resolve()), *arguments)


def _check(
    command: tuple[str, ...],
    deadline: float,
    timeout: float,
    cancel: threading.Event,
) -> float:
    if cancel.is_set():
        msg = "visible wait cancelled"
        raise concurrent.futures.CancelledError(msg)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired(command, timeout)
    return remaining


def _close_client(process: subprocess.Popen[bytes]) -> None:
    try:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=0.5)
    finally:
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


@contextlib.contextmanager
def _owned_client(
    command: tuple[str, ...], environment: _Environment
) -> t.Iterator[subprocess.Popen[bytes]]:
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("tmux command dispatched", extra={"tmux_cmd": shlex.join(command)})
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment
    )
    try:
        yield process
    except BaseException as error:
        try:
            _close_client(process)
        except BaseException as cleanup_error:  # noqa: BLE001
            # Preserve both failures when cleanup itself is interrupted.
            error.cleanup_error = cleanup_error  # type: ignore[attr-defined]
        raise
    else:
        _close_client(process)


def _capture(
    command: tuple[str, ...],
    deadline: float,
    timeout: float,
    cancel: threading.Event,
    limit: int,
    environment: _Environment,
) -> tuple[tuple[str, ...], int, int]:
    started_ns = time.monotonic_ns()
    stdout = bytearray()
    stderr = bytearray()
    with _owned_client(command, environment) as process:
        assert process.stdout is not None
        assert process.stderr is not None
        with selectors.DefaultSelector() as selector:
            selector.register(
                process.stdout, selectors.EVENT_READ, (stdout, 4 * limit + 65536)
            )
            selector.register(process.stderr, selectors.EVENT_READ, (stderr, 16384))
            while selector.get_map() or process.poll() is None:
                remaining = _check(command, deadline, timeout, cancel)
                for key, _ in selector.select(min(remaining, 0.05)):
                    buffer, maximum = key.data
                    chunk = os.read(key.fd, min(65536, maximum - len(buffer) + 1))
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    buffer.extend(chunk)
                    if len(buffer) > maximum:
                        msg = "capture exceeds its transport byte limit"
                        raise ValueError(msg)
        assert process.returncode is not None
        if process.returncode != 0 or stderr:
            raise subprocess.CalledProcessError(
                process.returncode, command, output=bytes(stdout), stderr=bytes(stderr)
            )
        text = (
            stdout.decode("utf-8", "backslashreplace")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .rstrip("\n")
        )
        if len(text) > limit:
            msg = "capture exceeds max_text_codepoints"
            raise ValueError(msg)
        lines = tuple(text.split("\n")) if text else ()
        finished_ns = time.monotonic_ns()
    return lines, started_ns, finished_ns


def wait_for_text(
    pane: Pane,
    text: str,
    *,
    present: bool,
    timeout: float,
    interval: float,
    cancel_event: threading.Event | None,
    start: int | t.Literal["-"] | None,
    end: int | t.Literal["-"] | None,
    join_wrapped: bool,
    max_text_codepoints: int,
) -> _PaneObservation:
    timeout = _finite_seconds(timeout, "timeout")
    interval = _finite_seconds(interval, "interval")
    if timeout < 0 or not 0 < interval <= 1:
        msg = "timeout must be nonnegative and interval must be in (0, 1]"
        raise ValueError(msg)
    if type(max_text_codepoints) is not int or not 1 <= max_text_codepoints <= 1048576:
        msg = "max_text_codepoints must be an integer in [1, 1048576]"
        raise ValueError(msg)
    if not isinstance(text, str) or not text or len(text) > max_text_codepoints:
        msg = "text must be a nonempty string within max_text_codepoints"
        raise ValueError(msg)
    if type(present) is not bool or type(join_wrapped) is not bool:
        msg = "present and join_wrapped must be booleans"
        raise ValueError(msg)
    for selection in (start, end):
        if selection is not None and selection != "-" and type(selection) is not int:
            msg = "start and end must be integers, '-' or None"
            raise ValueError(msg)
    if cancel_event is not None and not isinstance(cancel_event, threading.Event):
        msg = "cancel_event must be a threading.Event"
        raise ValueError(msg)

    environment = _Environment(os.environ)
    if environment.get("TMUX_TMPDIR"):
        environment["TMUX_TMPDIR"] = str(
            pathlib.Path(environment["TMUX_TMPDIR"]).resolve()
        )
    command = _command(pane, start, end, join_wrapped, environment)
    pane_id = command[command.index("-t") + 1]
    cancel = cancel_event if cancel_event is not None else threading.Event()
    deadline = time.monotonic() + timeout
    last_observation = None
    try:
        while True:
            _check(command, deadline, timeout, cancel)
            lines, started_ns, finished_ns = _capture(
                command, deadline, timeout, cancel, max_text_codepoints, environment
            )
            last_observation = _PaneObservation(
                pane_id,
                lines,
                command,
                start,
                end,
                join_wrapped,
                started_ns,
                finished_ns,
            )
            remaining = _check(command, deadline, timeout, cancel)
            matches = (text in last_observation.text) == present
            _check(command, deadline, timeout, cancel)
            if matches:
                return last_observation
            cancel.wait(min(interval, remaining))
    except Exception as cause:
        error: _WaitTimeout | _WaitCancelled | _WaitFailure
        if isinstance(cause, subprocess.TimeoutExpired):
            error = _WaitTimeout("visible text condition was not met before timeout")
        elif isinstance(cause, concurrent.futures.CancelledError):
            error = _WaitCancelled("visible wait cancelled")
        else:
            error = _WaitFailure(
                "visible text capture failed", subcommand="capture-pane"
            )
        error.last_observation = last_observation
        raise error from cause
    except BaseException as cause:
        cause.last_observation = last_observation  # type: ignore[attr-defined]
        raise
