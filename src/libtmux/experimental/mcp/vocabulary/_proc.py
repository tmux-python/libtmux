"""Linux ``/proc`` readers for the caller-discovery parent walk (pure, fail-closed).

Recovering the launching pane when the MCP's own environment is stripped means
walking the process tree: a launcher (e.g. an agent harness) may hold ``TMUX`` /
``TMUX_PANE`` while the ``uv run`` child that became this server does not. Each
reader returns ``None`` on any failure (missing ``/proc``, permission, a dead
pid) so discovery degrades to "not in tmux" rather than raising -- matching the
lenient list-accessor contract. Only ``TMUX`` / ``TMUX_PANE`` are ever read from
another process's environment (env-minimisation -- never materialise secrets).
"""

from __future__ import annotations

import pathlib
import typing as t

if t.TYPE_CHECKING:
    from collections.abc import Mapping

#: The only environment keys ever read from another process.
_WANTED = ("TMUX", "TMUX_PANE")


def read_proc_environ(pid: int) -> Mapping[str, str] | None:
    """Return a process's ``TMUX``/``TMUX_PANE`` env only, or ``None`` on failure.

    ``/proc/<pid>/environ`` is ``KEY=VAL`` pairs joined by NUL bytes. Any read
    error (missing, permission, dead pid -- all ``OSError`` subclasses) yields
    ``None``.
    """
    try:
        raw = pathlib.Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return None
    out: dict[str, str] = {}
    for item in raw.split(b"\x00"):
        if b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        name = key.decode(errors="replace")
        if name in _WANTED:
            out[name] = value.decode(errors="replace")
    return out


def _ppid_from_stat(data: bytes) -> int | None:
    """Parse the parent pid out of ``/proc/<pid>/stat`` bytes.

    The ``comm`` field (2nd) is paren-wrapped and may itself contain spaces or
    parens, so the parse anchors on the *last* ``)``; the fields after it are
    space-separated, with state at index 0 and ppid at index 1.

    Examples
    --------
    >>> _ppid_from_stat(b"1234 (we ird (name)) S 99 1234 1234 0 -1")
    99
    >>> _ppid_from_stat(b"garbage") is None
    True
    """
    try:
        return int(data[data.rindex(b")") + 1 :].split()[1])
    except (ValueError, IndexError):
        return None


def read_proc_ppid(pid: int) -> int | None:
    """Return a process's parent pid from ``/proc/<pid>/stat``, or ``None``."""
    try:
        data = pathlib.Path(f"/proc/{pid}/stat").read_bytes()
    except OSError:
        return None
    return _ppid_from_stat(data)


def read_proc_uid(pid: int) -> int | None:
    """Return a process's real uid from ``/proc/<pid>/status``, or ``None``.

    The ``Uid:`` line is ``real effective saved-set filesystem``; the first
    field (the real uid) is what :func:`os.getuid` returns.
    """
    try:
        for line in pathlib.Path(f"/proc/{pid}/status").read_bytes().splitlines():
            if line.startswith(b"Uid:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None
