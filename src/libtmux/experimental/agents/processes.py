"""Local process discovery for panes that have not emitted agent state yet."""

from __future__ import annotations

import collections
import pathlib
import typing as t
from dataclasses import dataclass

_AGENT_COMMANDS = {
    "claude": "claude",
    "codex": "codex",
}


@dataclass(frozen=True)
class ProcessInfo:
    """One local process row used for agent discovery.

    Examples
    --------
    >>> ProcessInfo(2, 1, "claude", ("claude", "--help")).command
    'claude'
    """

    pid: int
    ppid: int
    command: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class AgentProcess:
    """A detected coding-agent process.

    Examples
    --------
    >>> AgentProcess("codex", 42).name
    'codex'
    """

    name: str
    pid: int | None


def agent_name_from_command(
    command: str | None,
    argv: t.Sequence[str] = (),
) -> str | None:
    """Return the known agent name represented by *command* or *argv*.

    Examples
    --------
    >>> agent_name_from_command("claude")
    'claude'
    >>> agent_name_from_command("node", ("node", "/mise/bin/codex", "--yolo"))
    'codex'
    >>> agent_name_from_command("zsh") is None
    True
    """
    candidates = [command or "", *argv]
    for raw in candidates:
        name = pathlib.PurePosixPath(raw).name.lower()
        if name in _AGENT_COMMANDS:
            return _AGENT_COMMANDS[name]
    return None


def _ppid_from_stat(text: str) -> int | None:
    """Parse the parent pid from one Linux ``/proc/<pid>/stat`` record.

    Examples
    --------
    >>> _ppid_from_stat("12 (cmd with ) paren) S 7 8 9")
    7
    >>> _ppid_from_stat("not stat") is None
    True
    """
    end = text.rfind(")")
    if end == -1:
        return None
    fields = text[end + 2 :].split()
    if len(fields) < 2:
        return None
    try:
        return int(fields[1])
    except ValueError:
        return None


def _cmdline_args(raw: bytes) -> tuple[str, ...]:
    r"""Decode a Linux ``cmdline`` byte string to argv tokens.

    Examples
    --------
    >>> raw = bytes((99, 111, 100, 101, 120, 0, 45, 45, 121, 111, 108, 111, 0))
    >>> _cmdline_args(raw)
    ('codex', '--yolo')
    """
    return tuple(part.decode(errors="replace") for part in raw.split(b"\0") if part)


def iter_processes(
    proc: pathlib.Path = pathlib.Path("/proc"),
) -> t.Iterator[ProcessInfo]:
    """Yield local processes visible under *proc*.

    Examples
    --------
    >>> import pathlib
    >>> import tempfile
    >>> with tempfile.TemporaryDirectory() as directory:
    ...     root = pathlib.Path(directory)
    ...     process = root / "123"
    ...     process.mkdir()
    ...     _ = (process / "stat").write_text("123 (codex) S 1 2 3")
    ...     _ = (process / "comm").write_text("codex")
    ...     raw = bytes((99, 111, 100, 101, 120, 0, 45, 45, 121, 111, 108, 111, 0))
    ...     _ = (process / "cmdline").write_bytes(raw)
    ...     [row.command for row in iter_processes(root)]
    ['codex']
    """
    try:
        items = tuple(proc.iterdir())
    except OSError:
        return
    for item in items:
        if not item.name.isdigit():
            continue
        try:
            pid = int(item.name)
            stat = (item / "stat").read_text(encoding="utf-8", errors="replace")
            ppid = _ppid_from_stat(stat)
            if ppid is None:
                continue
            command = (item / "comm").read_text(encoding="utf-8", errors="replace")
            argv = _cmdline_args((item / "cmdline").read_bytes())
        except OSError:
            continue
        yield ProcessInfo(pid, ppid, command.strip(), argv)


def _descendants(
    root_pid: int,
    processes: t.Iterable[ProcessInfo],
) -> t.Iterator[ProcessInfo]:
    """Yield descendants of *root_pid* breadth-first.

    Examples
    --------
    >>> rows = (ProcessInfo(2, 1, "sh", ()), ProcessInfo(3, 2, "codex", ()))
    >>> [row.pid for row in _descendants(1, rows)]
    [2, 3]
    """
    children: dict[int, list[ProcessInfo]] = {}
    for process in processes:
        children.setdefault(process.ppid, []).append(process)
    seen: set[int] = set()
    queue: collections.deque[ProcessInfo] = collections.deque(
        children.get(root_pid, ())
    )
    while queue:
        process = queue.popleft()
        if process.pid in seen:
            continue
        seen.add(process.pid)
        yield process
        queue.extend(children.get(process.pid, ()))


def detect_agent_process(
    current_command: str | None,
    root_pid: int | None,
    *,
    processes: t.Iterable[ProcessInfo] | None = None,
) -> AgentProcess | None:
    """Detect a known coding agent for one pane.

    ``current_command`` is the cheap tmux signal.  When it is generic, such as
    ``node`` for Codex, local ``/proc`` descendants below ``root_pid`` are used.

    Examples
    --------
    >>> detect_agent_process("claude", 10)
    AgentProcess(name='claude', pid=10)
    >>> rows = (ProcessInfo(11, 10, "MainThread", ("node", "/bin/codex")),)
    >>> detect_agent_process("node", 10, processes=rows)
    AgentProcess(name='codex', pid=11)
    >>> detect_agent_process("zsh", 10, processes=()) is None
    True
    """
    name = agent_name_from_command(current_command)
    if name is not None:
        return AgentProcess(name, root_pid)
    if root_pid is None:
        return None
    rows = tuple(processes) if processes is not None else tuple(iter_processes())
    for process in _descendants(root_pid, rows):
        name = agent_name_from_command(process.command, process.argv)
        if name is not None:
            return AgentProcess(name, process.pid)
    return None
