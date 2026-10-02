"""Run several tmux commands as one command list, with a result for each.

``tmux a ; b ; c`` is one invocation: one fork for a subprocess engine, one
write and one reply wave for a control-mode engine. The cost is attribution.
tmux joins the output of the commands and, when one fails, drops the rest of
the list and reports a single error. :func:`run_group` keeps one result per
request anyway: after every command it adds ``display-message -p`` with a
random marker, so the output between markers belongs to the command before it,
and the first marker that never arrives names the command that failed.

A group is *ordered and stops at the first failure*; requests after the failure
come back as :data:`NOT_RUN` results, never as missing entries. Use
:meth:`~libtmux.engines.base.TmuxEngine.run_batch` when every command should
run regardless of the others.
"""

from __future__ import annotations

import secrets
import typing as t

from libtmux.engines.base import (
    CommandRequest,
    CommandResult,
    CommandSeparator,
    SupportsCommandLine,
)
from libtmux.engines.connection import runs_interactive_client
from libtmux.engines.control.routing import blocks_queue

if t.TYPE_CHECKING:
    from collections.abc import Sequence

    from libtmux.engines.base import TmuxEngine

#: ``returncode`` of a request that never ran because an earlier one failed.
NOT_RUN_RETURNCODE = -1
#: ``stderr`` of a request that never ran.
NOT_RUN = ("not run: earlier command failed",)
#: A group stays well under tmux's 16 KiB command limit; a longer one is split.
_MAX_GROUP_BYTES = 12_000
_MARKER_PREFIX = "libtmux-group-"
#: Bytes the marker command after each request adds, rounded up.
_MARKER_COST = 64


def _size(request: CommandRequest) -> int:
    return sum(len(arg.encode()) + 1 for arg in request.args)


def _check_groupable(request: CommandRequest) -> None:
    """Refuse requests a shared command list cannot carry."""
    if request.input is not None:
        msg = "a request with input cannot join a command group"
        raise ValueError(msg)
    if request.tmux_bin is not None:
        msg = "a request with its own tmux_bin cannot join a command group"
        raise ValueError(msg)
    if not request.args:
        msg = "an empty request cannot join a command group"
        raise ValueError(msg)
    if blocks_queue(request.args) or runs_interactive_client(request.args):
        msg = (
            f"{request.subcommand!r} blocks tmux's command queue or owns a "
            "terminal, so it cannot join a command group"
        )
        raise ValueError(msg)


def group_request(
    requests: Sequence[CommandRequest],
    token: str,
) -> CommandRequest:
    """Join *requests* into one request, a marker after each command.

    Each request's own arguments are untouched, so a ``;`` that is data stays
    data; only :class:`~libtmux.engines.base.CommandSeparator` tokens are
    structural.

    Parameters
    ----------
    requests : sequence of CommandRequest
        The commands, in order.
    token : str
        Distinguishes this group's markers from any command output.

    Returns
    -------
    CommandRequest
        One request whose timeout is the sum of the members', or ``None`` when
        any member is unbounded.

    Examples
    --------
    >>> from libtmux.engines.base import command_count
    >>> group = group_request(
    ...     [
    ...         CommandRequest.from_args("set-option", "-g", "@a", "x;"),
    ...         CommandRequest.from_args("set-option", "-g", "@b", "y"),
    ...     ],
    ...     "t0",
    ... )
    >>> command_count(group.args)
    4
    >>> group.args[:4]
    ('set-option', '-g', '@a', 'x;')
    >>> group.args[5:8]
    ('display-message', '-p', 'libtmux-group-t0:0')
    """
    args: list[str] = []
    for index, request in enumerate(requests):
        _check_groupable(request)
        args += [
            *request.args,
            CommandSeparator(";"),
            "display-message",
            "-p",
            f"{_MARKER_PREFIX}{token}:{index}",
        ]
        if index < len(requests) - 1:
            args.append(CommandSeparator(";"))
    timeouts = [request.timeout for request in requests]
    timeout = None if None in timeouts else sum(t.cast("list[float]", timeouts))
    return CommandRequest(args=tuple(args), timeout=timeout)


def split_group_result(
    requests: Sequence[CommandRequest],
    result: CommandResult,
    token: str,
    *,
    command_lines: Sequence[tuple[str, ...]] | None = None,
) -> list[CommandResult]:
    """Attribute a group's single *result* to each of *requests*.

    Parameters
    ----------
    requests : sequence of CommandRequest
        The requests :func:`group_request` joined.
    result : CommandResult
        What the engine returned for the joined request.
    token : str
        The token passed to :func:`group_request`.
    command_lines : sequence of tuple of str, optional
        The ``cmd`` to report for each request; defaults to ``("tmux", *args)``.

    Returns
    -------
    list of CommandResult
        One per request. Commands before the failure are ``ok`` and carry the
        lines they printed; the failing command carries the group's stderr and
        return code; the rest are :data:`NOT_RUN`.

    Examples
    --------
    >>> requests = [
    ...     CommandRequest.from_args("list-windows"),
    ...     CommandRequest.from_args("kill-window"),
    ... ]
    >>> joined = CommandResult(
    ...     cmd=("tmux",),
    ...     stdout=("0: zsh", "libtmux-group-t0:0"),
    ...     stderr=("no current target",),
    ...     returncode=1,
    ... )
    >>> split = split_group_result(requests, joined, "t0")
    >>> [(r.returncode, r.stdout, r.stderr) for r in split]
    [(0, ('0: zsh',), ()), (1, (), ('no current target',))]
    """
    lines_by_request: list[list[str]] = [[] for _ in requests]
    completed = 0
    current: list[str] = []
    prefix = f"{_MARKER_PREFIX}{token}:"
    for line in result.stdout:
        if line.startswith(prefix) and completed < len(requests):
            lines_by_request[completed] = current
            current = []
            completed += 1
        else:
            current.append(line)
    out: list[CommandResult] = []
    for index, request in enumerate(requests):
        cmd = (
            command_lines[index]
            if command_lines is not None
            else ("tmux", *request.args)
        )
        if index < completed:
            out.append(CommandResult(cmd=cmd, stdout=tuple(lines_by_request[index])))
        elif index == completed:
            out.append(
                CommandResult(
                    cmd=cmd,
                    stdout=tuple(current),
                    stderr=result.stderr,
                    returncode=result.returncode or 1,
                ),
            )
        else:
            out.append(
                CommandResult(cmd=cmd, stderr=NOT_RUN, returncode=NOT_RUN_RETURNCODE),
            )
    return out


def _chunks(requests: Sequence[CommandRequest]) -> list[list[CommandRequest]]:
    chunks: list[list[CommandRequest]] = [[]]
    size = 0
    for request in requests:
        cost = _size(request) + _MARKER_COST
        if chunks[-1] and size + cost > _MAX_GROUP_BYTES:
            chunks.append([])
            size = 0
        chunks[-1].append(request)
        size += cost
    return [chunk for chunk in chunks if chunk]


def run_group(
    engine: TmuxEngine,
    requests: Sequence[CommandRequest],
) -> list[CommandResult]:
    """Run *requests* as one tmux command list and return a result for each.

    A subprocess or exec engine forks once for the whole list; a control-mode
    engine writes one line and reads the replies in one wave. The list stops
    at the first failure, and every later request gets a :data:`NOT_RUN`
    result. A list too long for tmux's 16 KiB command limit is split into the
    fewest lists that fit, and a failure still stops the later ones.

    Parameters
    ----------
    engine : TmuxEngine
        Any engine.
    requests : sequence of CommandRequest
        The commands. None may carry ``input``, name its own ``tmux_bin``,
        wait (``run-shell`` without ``-b``, ``wait-for``) or own a terminal
        (``attach-session``).

    Returns
    -------
    list of CommandResult
        Exactly ``len(requests)`` results, in order.

    Raises
    ------
    ValueError
        A request cannot join a group.

    Examples
    --------
    >>> from libtmux.engines import SubprocessEngine
    >>> engine = SubprocessEngine.for_server(server)
    >>> results = run_group(
    ...     engine,
    ...     [
    ...         CommandRequest.from_args("set-option", "-g", "@a", "1;"),
    ...         CommandRequest.from_args("show-options", "-gqv", "@a"),
    ...     ],
    ... )
    >>> [(r.ok, r.stdout) for r in results]
    [(True, ()), (True, ('1;',))]
    """
    for request in requests:
        _check_groupable(request)
    results: list[CommandResult] = []
    for chunk in _chunks(requests):
        if results and not results[-1].ok:
            results += [
                CommandResult(
                    cmd=("tmux", *request.args),
                    stderr=NOT_RUN,
                    returncode=NOT_RUN_RETURNCODE,
                )
                for request in chunk
            ]
            continue
        token = secrets.token_hex(4)
        joined = engine.run(group_request(chunk, token))
        lines = (
            [engine.command_line(CommandRequest(args=r.args)) for r in chunk]
            if isinstance(engine, SupportsCommandLine)
            else None
        )
        results += split_group_result(chunk, joined, token, command_lines=lines)
    return results
