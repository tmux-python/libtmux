"""Immutable cursors for counter-aligned, retained tmux history rows."""

from __future__ import annotations

import dataclasses
import pathlib
import re
import stat
import typing as t

from libtmux import exc
from libtmux.common import raise_if_stderr, tmux_cmd
from libtmux.formats import FORMAT_SEPARATOR
from libtmux.pane import Pane
from libtmux.server import Server

_PANE_CMD = Pane.cmd
_SERVER_CMD = Server.cmd
_FIELDS = (
    "version",
    "pid",
    "start_time",
    "socket_path",
    "pane_id",
    "pane_pid",
    "pane_tty",
    "pane_dead",
    "pane_width",
    "pane_height",
    "alternate_on",
    "history_size",
    "history_added",
    "history_collected",
    "history_generation",
)
_FORMAT = FORMAT_SEPARATOR.join(f"#{{{name}}}" for name in _FIELDS)
_Scope = tuple[str | int | None, ...]


@dataclasses.dataclass(frozen=True)
class _Snapshot:
    scope: _Scope | None
    identity: tuple[str, ...]
    width: int
    height: int
    alternate: bool
    size: int
    added: int | None
    collected: int | None
    generation: int | None
    problem: str | None


@dataclasses.dataclass(frozen=True)
class CaptureCursor:
    """Opaque, immutable position returned by :meth:`Pane.capture_since`.

    Pass this value back to ``capture_since``; do not construct or edit it.
    It retains rendered history rows for overlap checks, with memory use
    proportional to retained scrollback. It owns no client or daemon.
    Cursors are process-local values, not a serialization format.

    Attributes
    ----------
    grid : str
        The selection policy: ``"history"`` means the main grid's retained
        physical history rows, excluding the visible screen.
    """

    grid: t.Literal["history"]
    _snapshot: _Snapshot | None = dataclasses.field(repr=False)
    _rows: tuple[str, ...] = dataclasses.field(repr=False)


@dataclasses.dataclass(frozen=True)
class CaptureSince:
    """Rendered history and the evidence for aligning it with an earlier capture.

    Attributes
    ----------
    lines : tuple[str, ...]
        New physical rows for ``continuous``; the full captured history for
        other outcomes. Empty history and unavailable data differ by status.
        Soft wraps stay separate and tmux trims trailing spaces.
    cursor : CaptureCursor
        A fresh immutable cursor. An ``unknown`` result cannot qualify the
        next delta; the next stable capture starts a new anchor.
    status : {"continuous", "reset", "gap", "unknown"}
        ``continuous`` means the sampled counters balance and retained rows
        agree, yielding a suffix of the observed history. ``reset`` starts an
        anchor. ``gap`` means collection passed rows the cursor had read.
        ``unknown`` means the available evidence cannot align the captures.
    reason : str
        Why the status applies. ``initial`` distinguishes a first anchor from
        a detected reset. Reasons describe evidence, not producer outcomes.

    Notes
    -----
    Separate metadata and capture commands are not atomic. ``continuous``
    does not prove that no transient resize, redraw, alternate-screen visit,
    or full 32-bit counter cycle occurred between observations. It promises
    neither every rendered row ever seen nor lossless program output.
    """

    lines: tuple[str, ...]
    cursor: CaptureCursor
    status: t.Literal["continuous", "reset", "gap", "unknown"]
    reason: str

    @property
    def text(self) -> str:
        """Join the captured rows with newlines, without a final newline."""
        return "\n".join(self.lines)


def _check(proc: tmux_cmd, command: str) -> None:
    raise_if_stderr(proc, command)
    returncode = getattr(proc, "returncode", None)
    if type(returncode) is not int or returncode != 0:
        message = f"tmux exited with unqualified status {returncode}"
        raise exc.LibTmuxException(message, subcommand=command)


def _uint(value: str) -> int | None:
    if not value.isascii() or not value.isdecimal():
        return None
    number = int(value)
    return number if number <= 0xFFFFFFFF else None


def _local_scope(pane: Pane, proc: tmux_cmd, socket: str) -> _Scope | None:
    # Custom routing may name a remote socket that aliases an unrelated local
    # path. Never use local filesystem evidence to qualify that dispatcher.
    if (
        getattr(pane.cmd, "__func__", None) is not _PANE_CMD
        or getattr(pane.server.cmd, "__func__", None) is not _SERVER_CMD
        or any(
            getattr(owner, name, None) is not None
            for owner in (pane, pane.server)
            for name in ("_engine", "engine")
        )
    ):
        return None
    if not pathlib.Path(proc.cmd[0]).is_absolute():
        return None
    try:
        endpoint = pathlib.Path(socket).stat()
        executable = pathlib.Path(proc.cmd[0]).resolve()
        binary = executable.stat()
    except OSError:
        return None
    if not stat.S_ISSOCK(endpoint.st_mode) or not endpoint.st_ino:
        return None
    return (
        str(executable),
        binary.st_dev,
        binary.st_ino,
        binary.st_mtime_ns,
        endpoint.st_dev,
        endpoint.st_ino,
        endpoint.st_ctime_ns,
    )


def _read_metadata(pane: Pane) -> _Snapshot | None:
    proc = pane.cmd("display-message", "-p", _FORMAT)
    _check(proc, "display-message")
    if len(proc.stdout) != 1:
        return None
    fields = proc.stdout[0].split(FORMAT_SEPARATOR)
    if len(fields) != len(_FIELDS):
        return None
    data = dict(zip(_FIELDS, fields, strict=True))
    if data["pane_id"] != pane.pane_id:
        message = f"pane {pane.pane_id} is unavailable"
        raise exc.LibTmuxException(message, subcommand="display-message")
    version = re.fullmatch(r"(?:next-)?(\d+)\.(\d+)[a-z]*(?:-.*)?", data["version"])
    if version and tuple(map(int, version.groups())) < (3, 8):
        message = "capture_since requires connected tmux 3.8 or newer"
        raise exc.VersionTooLow(message)
    width, height, size = (
        _uint(data[key]) for key in ("pane_width", "pane_height", "history_size")
    )
    if (
        not width
        or not height
        or size is None
        or data["alternate_on"] not in {"0", "1"}
    ):
        return None
    counters = [
        _uint(data[key])
        for key in ("history_added", "history_collected", "history_generation")
    ]
    scope = _local_scope(pane, proc, data["socket_path"])
    problem = None
    if version is None:
        problem = "unknown-version"
    elif any(counter is None for counter in counters):
        problem = "missing-counters"
    elif not _uint(data["pid"]) or not _uint(data["start_time"]):
        problem = "missing-identity"
    elif scope is None:
        problem = "unverified-endpoint"
    elif data["alternate_on"] == "1":
        problem = "alternate-screen"
    return _Snapshot(
        scope,
        tuple(data[key] for key in _FIELDS[:8]),
        width,
        height,
        data["alternate_on"] == "1",
        size,
        counters[0],
        counters[1],
        counters[2],
        problem,
    )


def _result(
    rows: tuple[str, ...],
    snapshot: _Snapshot | None,
    status: t.Literal["continuous", "reset", "gap", "unknown"],
    reason: str,
    *,
    lines: tuple[str, ...] | None = None,
) -> CaptureSince:
    cursor = CaptureCursor("history", snapshot if status != "unknown" else None, rows)
    return CaptureSince(rows if lines is None else lines, cursor, status, reason)


def _capture_since(
    pane: Pane,
    cursor: CaptureCursor | None,
    *,
    grid: t.Literal["history"],
) -> CaptureSince:
    if grid != "history":
        message = "capture_since supports only grid='history'"
        raise ValueError(message)
    before = _read_metadata(pane)
    if before is None:
        return _result((), None, "unknown", "missing-metadata")

    native = before.scope is not None
    if native:
        # Pin the resolved route, not the mutable caller handle or -L environment.
        # Custom dispatch keeps using the original object and stays unqualified.
        assert before.scope is not None
        pane = Pane(
            server=Server(
                socket_path=before.identity[3],
                tmux_bin=str(before.scope[0]),
            ),
            pane_id=before.identity[4],
        )

    rows: tuple[str, ...] = ()
    route_matches = True
    if before.size:
        # -E -1 selects the last history row only when history is nonempty.
        # -L frames blank rows so tmux_cmd's newline trimming cannot lose them.
        proc = pane.cmd("capture-pane", "-pL", "-S", "-", "-E", "-1")
        _check(proc, "capture-pane")
        if native:
            route_matches = proc.cmd == [
                pane.server.tmux_bin,
                f"-S{pane.server.socket_path}",
                "capture-pane",
                "-t",
                pane.pane_id,
                "-pL",
                "-S",
                "-",
                "-E",
                "-1",
            ]
        captured = []
        for index, row in enumerate(proc.stdout):
            prefix = f"{index - before.size} "
            if not row.startswith(prefix):
                return _result((), None, "unknown", "changed-capture")
            captured.append(row[len(prefix) :])
        rows = tuple(captured)
        if len(rows) != before.size:
            return _result(rows, None, "unknown", "changed-capture")

    after = _read_metadata(pane)
    if not route_matches:
        return _result(rows, None, "unknown", "changed-route")
    if before != after:
        return _result(rows, None, "unknown", "changed-during-capture")
    if before.problem is not None:
        return _result(rows, None, "unknown", before.problem)
    if cursor is None:
        return _result(rows, before, "reset", "initial")
    previous = cursor._snapshot
    if previous is None:
        return _result(rows, before, "reset", "unqualified-cursor")
    if (
        cursor.grid != grid
        or previous.scope != before.scope
        or previous.identity != before.identity
    ):
        return _result(rows, before, "reset", "scope-changed")
    if (previous.width, previous.height) != (before.width, before.height):
        return _result(rows, before, "reset", "geometry-changed")
    if previous.generation != before.generation:
        return _result(rows, before, "reset", "generation-changed")
    if (
        previous.added is None
        or previous.collected is None
        or before.added is None
        or before.collected is None
    ):
        return _result(rows, None, "unknown", "missing-counters")
    added = before.added - previous.added
    collected = before.collected - previous.collected
    if not 0 <= added <= 0x7FFFFFFF or not 0 <= collected <= 0x7FFFFFFF:
        return _result(rows, None, "unknown", "counter-regression")
    if previous.size + added - collected != before.size:
        return _result(rows, None, "unknown", "counter-mismatch")
    if collected > previous.size:
        return _result(rows, before, "gap", "history-collected")
    kept = previous.size - collected
    if cursor._rows[collected:] != rows[:kept]:
        return _result(rows, None, "unknown", "history-changed")
    return _result(rows, before, "continuous", "counter-aligned", lines=rows[kept:])
