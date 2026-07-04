"""Pure Python process restore policy helpers."""

from __future__ import annotations

import shlex
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
