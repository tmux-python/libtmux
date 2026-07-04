"""Pure Python process restore policy helpers."""

from __future__ import annotations

import pathlib
import shlex
import subprocess
import typing as t
from dataclasses import dataclass

DEFAULT_RESTORE_PROGRAMS = (
    "vi",
    "vim",
    "view",
    "nvim",
    "emacs",
    "man",
    "less",
    "more",
    "tail",
    "top",
    "htop",
    "irssi",
    "weechat",
    "mutt",
)
"""Conservative default process allow-list from tmux-resurrect."""


@dataclass(frozen=True, slots=True)
class ProcessRestoreRule:
    """A single process restore allow-list entry."""

    match: str
    relaxed: bool = False
    command_template: str | None = None

    @classmethod
    def parse(cls, value: str) -> ProcessRestoreRule:
        """Parse a tmux-resurrect-style process rule.

        Examples
        --------
        >>> ProcessRestoreRule.parse('vim')
        ProcessRestoreRule(match='vim', relaxed=False, command_template=None)

        >>> rule = ProcessRestoreRule.parse('python->uv run python *')
        >>> rule.match
        'python'
        >>> rule.command_template
        'uv run python *'
        """
        relaxed = value.startswith("~")
        raw = value[1:] if relaxed else value
        if "->" in raw:
            match, command_template = raw.split("->", 1)
        else:
            match, command_template = raw, None
        return cls(
            match=match,
            relaxed=relaxed,
            command_template=command_template or None,
        )

    def matches(self, full_command: str) -> bool:
        """Return True when this rule matches a saved command.

        Examples
        --------
        >>> ProcessRestoreRule('vim').matches('vim pyproject.toml')
        True

        >>> ProcessRestoreRule('server', relaxed=True).matches('node server.js')
        True

        >>> ProcessRestoreRule('git log').matches('git log --oneline')
        True
        """
        if self.relaxed:
            return self.match in full_command
        return _command_matches(full_command, self.match)

    def resolve(self, full_command: str) -> str:
        """Return the replay command for this rule.

        Examples
        --------
        >>> ProcessRestoreRule('vim').resolve('vim pyproject.toml')
        'vim pyproject.toml'

        >>> ProcessRestoreRule('python', command_template='uv run python *').resolve(
        ...     'python -m http.server 8000',
        ... )
        'uv run python -m http.server 8000'

        >>> ProcessRestoreRule(
        ...     'rails server',
        ...     relaxed=True,
        ...     command_template='rails server *',
        ... ).resolve('/rubies/bin/ruby script/rails server -p 3000')
        'rails server -p 3000'
        """
        if self.command_template is None:
            return full_command
        arguments = _arguments_after_match(
            full_command,
            self.match,
            relaxed=self.relaxed,
        )
        return self.command_template.replace("*", arguments).strip()


@dataclass(frozen=True, slots=True)
class ProcessRestorePolicy:
    """Process replay policy independent from tmux plugin options."""

    enabled: bool = True
    restore_all: bool = False
    rules: tuple[ProcessRestoreRule, ...] = tuple(
        ProcessRestoreRule(program) for program in DEFAULT_RESTORE_PROGRAMS
    )

    @classmethod
    def from_options(
        cls,
        user_processes: str | None,
        *,
        default_processes: tuple[str, ...] = DEFAULT_RESTORE_PROGRAMS,
    ) -> ProcessRestorePolicy:
        """Build a policy from tmux-resurrect-style process options.

        Examples
        --------
        >>> policy = ProcessRestorePolicy.from_options("'python->uv run python *'")
        >>> policy.resolve_command('python -m http.server 8000')
        'uv run python -m http.server 8000'

        >>> ProcessRestorePolicy.from_options('false').resolve_command('vim')
        """
        if user_processes == "false":
            return cls(enabled=False, rules=())
        if user_processes == ":all:":
            return cls(restore_all=True, rules=())

        rules = [ProcessRestoreRule.parse(program) for program in default_processes]
        if user_processes:
            rules.extend(
                ProcessRestoreRule.parse(program)
                for program in shlex.split(user_processes)
            )
        return cls(rules=tuple(rules))

    def resolve_command(self, full_command: str) -> str | None:
        """Return a replay command, or None when policy skips this process.

        Examples
        --------
        >>> ProcessRestorePolicy.from_options(None).resolve_command('vim README.md')
        'vim README.md'

        >>> ProcessRestorePolicy.from_options(None).resolve_command('node server.js')

        >>> policy = ProcessRestorePolicy.from_options('"git log"')
        >>> policy.resolve_command('git log --oneline')
        'git log --oneline'
        """
        if not self.enabled or not full_command:
            return None
        if self.restore_all:
            return full_command

        for rule in self.rules:
            if rule.matches(full_command):
                return rule.resolve(full_command)
        return None


DEFAULT_PROCESS_RESTORE_POLICY = ProcessRestorePolicy()
"""Default conservative process replay policy."""


class ProcessCommandProvider(t.Protocol):
    """Provider that resolves a pane process id to a full command line."""

    def capture(self, pid: int) -> str | None:
        """Return a shell command for a process id.

        Examples
        --------
        >>> class MissingProvider:
        ...     def capture(self, pid: int) -> str | None:
        ...         return None
        >>> MissingProvider().capture(1234) is None
        True
        """
        ...


@dataclass(frozen=True, slots=True)
class _ProcfsProcess:
    """Parsed procfs process metadata."""

    pid: int
    ppid: int
    pgrp: int
    tpgid: int
    command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProcfsProcessCommandProvider:
    """Capture full process commands from Linux procfs."""

    proc_root: pathlib.Path = pathlib.Path("/proc")

    def capture(self, pid: int) -> str | None:
        """Return the foreground command for a tmux pane process id.

        Examples
        --------
        >>> import pathlib
        >>> provider = ProcfsProcessCommandProvider(pathlib.Path('/missing-proc'))
        >>> provider.capture(1234) is None
        True
        """
        if pid <= 0:
            return None

        try:
            proc_dirs = tuple(self.proc_root.iterdir())
        except OSError:
            proc_dirs = ()

        processes = {
            process.pid: process
            for process in (_read_procfs_process(proc_dir) for proc_dir in proc_dirs)
            if process is not None
        }
        root = processes.get(pid) or _read_procfs_process(self.proc_root / str(pid))
        if root is None:
            return None
        processes[root.pid] = root

        process = _select_foreground_process(root, processes)
        if process is None:
            return None
        return shlex.join(process.command)


def _read_procfs_process(proc_dir: pathlib.Path) -> _ProcfsProcess | None:
    """Return parsed process metadata from a procfs PID directory.

    Examples
    --------
    >>> _read_procfs_process(pathlib.Path('/missing-proc/1234')) is None
    True
    """
    if not proc_dir.name.isdecimal():
        return None

    pid = int(proc_dir.name)
    command = _read_procfs_cmdline(proc_dir / "cmdline")
    stat = _read_procfs_stat(proc_dir / "stat")
    if stat is None and not command:
        return None

    ppid, pgrp, tpgid = stat or (0, 0, 0)
    return _ProcfsProcess(
        pid=pid,
        ppid=ppid,
        pgrp=pgrp,
        tpgid=tpgid,
        command=command,
    )


def _read_procfs_cmdline(path: pathlib.Path) -> tuple[str, ...]:
    """Return decoded argv from a procfs ``cmdline`` file.

    Examples
    --------
    >>> _read_procfs_cmdline(pathlib.Path('/missing-proc/cmdline'))
    ()
    """
    try:
        raw_cmdline = path.read_bytes()
    except OSError:
        return ()

    return tuple(
        part.decode("utf-8", "backslashreplace")
        for part in raw_cmdline.split(b"\0")
        if part
    )


def _read_procfs_stat(path: pathlib.Path) -> tuple[int, int, int] | None:
    r"""Return ``(ppid, pgrp, tpgid)`` from a procfs ``stat`` file.

    Examples
    --------
    >>> tmp_path = pathlib.Path(request.getfixturevalue("tmp_path"))
    >>> stat_path = tmp_path / "stat"
    >>> _ = stat_path.write_text("123 (vim) S 1 200 0 34816 200 0\\n")
    >>> _read_procfs_stat(stat_path)
    (1, 200, 200)
    """
    try:
        stat = path.read_text(encoding="utf-8")
    except OSError:
        return None

    try:
        suffix = stat.rsplit(")", 1)[1].split()
        return int(suffix[1]), int(suffix[2]), int(suffix[5])
    except (IndexError, ValueError):
        return None


def _select_foreground_process(
    root: _ProcfsProcess,
    processes: t.Mapping[int, _ProcfsProcess],
) -> _ProcfsProcess | None:
    """Return the foreground descendant process, falling back to ``root``.

    Examples
    --------
    >>> shell = _ProcfsProcess(100, 1, 100, 200, ("-zsh",))
    >>> vim = _ProcfsProcess(200, 100, 200, 200, ("vim", "README.md"))
    >>> _select_foreground_process(shell, {100: shell, 200: vim}) == vim
    True
    """
    children_by_parent: dict[int, list[_ProcfsProcess]] = {}
    for process in processes.values():
        children_by_parent.setdefault(process.ppid, []).append(process)

    descendants: list[tuple[int, _ProcfsProcess]] = []
    seen = {root.pid}
    stack = [(1, child) for child in children_by_parent.get(root.pid, [])]
    while stack:
        depth, process = stack.pop()
        if process.pid in seen:
            continue
        seen.add(process.pid)
        descendants.append((depth, process))
        stack.extend(
            (depth + 1, child) for child in children_by_parent.get(process.pid, [])
        )

    foreground = [
        (depth, process)
        for depth, process in descendants
        if root.tpgid > 0 and process.pgrp == root.tpgid and process.command
    ]
    if foreground:
        return max(foreground, key=lambda item: (item[0], item[1].pid))[1]

    with_command = [
        (depth, process) for depth, process in descendants if process.command
    ]
    if with_command:
        return max(with_command, key=lambda item: (item[0], item[1].pid))[1]

    return root if root.command else None


@dataclass(frozen=True, slots=True)
class PsProcessCommandProvider:
    """Capture full process commands with ``ps``."""

    ps_bin: str = "ps"

    def capture(self, pid: int) -> str | None:
        """Return a command from ``ps -p <pid> -o command=``.

        Examples
        --------
        >>> PsProcessCommandProvider(ps_bin='/missing-ps').capture(1234) is None
        True
        """
        if pid <= 0:
            return None
        try:
            proc = subprocess.run(
                (self.ps_bin, "-p", str(pid), "-o", "command="),
                capture_output=True,
                check=False,
                text=True,
            )
        except OSError:
            return None
        if proc.returncode != 0:
            return None
        command = proc.stdout.strip()
        return command or None


@dataclass(frozen=True, slots=True)
class CompositeProcessCommandProvider:
    """Try multiple process command providers in order."""

    providers: tuple[ProcessCommandProvider, ...]

    def capture(self, pid: int) -> str | None:
        """Return the first command captured by a child provider.

        Examples
        --------
        >>> class Provider:
        ...     def capture(self, pid: int) -> str | None:
        ...         return 'vim README.md'
        >>> CompositeProcessCommandProvider((Provider(),)).capture(1234)
        'vim README.md'
        """
        for provider in self.providers:
            command = provider.capture(pid)
            if command:
                return command
        return None


def default_process_command_provider() -> ProcessCommandProvider:
    """Return the default full-command provider chain.

    Examples
    --------
    >>> provider = default_process_command_provider()
    >>> hasattr(provider, 'capture')
    True
    """
    return CompositeProcessCommandProvider(
        (ProcfsProcessCommandProvider(),),
    )


def _command_matches(full_command: str, match: str) -> bool:
    """Return True when a full command matches an exact restore rule.

    Examples
    --------
    >>> _command_matches('vim pyproject.toml', 'vim')
    True

    >>> _command_matches('git log --oneline', 'git log')
    True

    >>> _command_matches('vimdiff file.py', 'vim')
    False
    """
    return full_command == match or full_command.startswith(f"{match} ")


def _arguments_after_match(
    full_command: str,
    match: str,
    *,
    relaxed: bool = False,
) -> str:
    """Return shell-quoted arguments after an exact command match.

    Examples
    --------
    >>> _arguments_after_match('python -m http.server 8000', 'python')
    '-m http.server 8000'

    >>> _arguments_after_match('node server.js', 'python')
    ''

    >>> _arguments_after_match(
    ...     '/rubies/bin/ruby script/rails server -p 3000',
    ...     'rails server',
    ...     relaxed=True,
    ... )
    '-p 3000'
    """
    if relaxed:
        match_index = full_command.find(match)
        if match_index == -1:
            return ""
        argument_index = match_index + len(match)
        while (
            argument_index < len(full_command)
            and not full_command[argument_index].isspace()
        ):
            argument_index += 1
        return full_command[argument_index:].lstrip()

    try:
        parts = shlex.split(full_command)
    except ValueError:
        return ""
    try:
        match_parts = shlex.split(match)
    except ValueError:
        return ""
    if parts[: len(match_parts)] != match_parts:
        return ""
    return shlex.join(parts[len(match_parts) :])
