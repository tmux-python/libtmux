"""Claude Code lifecycle-hook installer.

Installs and uninstalls agent-state-emitting hooks into Claude Code's
``~/.claude/settings.json``.  Each installed hook runs
``libtmux-agent-emit <state>`` on the relevant Claude lifecycle event.

The ``"hooks"`` section of ``settings.json`` is keyed by Claude event name;
each event value is a list of *groups*, where each group is a dict::

    {"hooks": [{"type": "command", "command": "<shell-command>"}]}

Only groups whose command contains ``libtmux-agent-emit`` are ever touched;
all other user groups are preserved verbatim.
"""

from __future__ import annotations

import contextlib
import json
import os
import pathlib
import shutil
import tempfile
import typing as t

#: Claude Code event name → agent-state string.
#:
#: Maps each Claude lifecycle event to the agent-state value that
#: ``libtmux-agent-emit`` should broadcast when that event fires.
#:
#: Examples
#: --------
#: >>> _CLAUDE_EVENT_STATE["UserPromptSubmit"]
#: 'running'
#: >>> _CLAUDE_EVENT_STATE["Stop"]
#: 'awaiting_input'
_CLAUDE_EVENT_STATE: dict[str, str] = {
    "UserPromptSubmit": "running",
    "Notification": "awaiting_input",
    "Stop": "awaiting_input",
    "SessionStart": "idle",
}

#: Substring present in every hook command we own; used to identify our entries.
_OUR_MARKER: str = "libtmux-agent-emit"


def _is_our_group(group: dict[str, t.Any]) -> bool:
    """Return ``True`` when *group* contains at least one of our hook commands.

    Parameters
    ----------
    group : dict[str, Any]
        A hook group dict (``{"hooks": [{...}]}``) from ``settings.json``.

    Returns
    -------
    bool
        ``True`` iff any ``"command"`` value inside the group's ``"hooks"``
        list contains :data:`_OUR_MARKER`.

    Notes
    -----
    The substring match here is intentionally *wider* than the exact-command
    match :meth:`ClaudeCodeHook.status` uses: it claims any group emitted by
    any version of this installer (e.g. with extra flags) so uninstall and
    idempotent install always sweep them. The false-positive risk -- a user
    command that literally contains ``libtmux-agent-emit`` -- is negligible.

    Examples
    --------
    >>> _is_our_group({"hooks": [{"type": "command",
    ...                           "command": "libtmux-agent-emit running"}]})
    True
    >>> _is_our_group({"hooks": [{"type": "command",
    ...                           "command": "echo user-owned"}]})
    False
    >>> _is_our_group({"hooks": []})
    False
    """
    return any(_OUR_MARKER in h.get("command", "") for h in group.get("hooks", []))


def _our_group(state: str) -> dict[str, t.Any]:
    """Return a fresh hook group that emits *state*.

    Parameters
    ----------
    state : str
        Agent-state string (e.g. ``"running"``).

    Returns
    -------
    dict[str, Any]
        A hook group dict ready to be inserted into a Claude event list.

    Examples
    --------
    >>> g = _our_group("running")
    >>> g["hooks"][0]["command"]
    'libtmux-agent-emit running'
    >>> g["hooks"][0]["type"]
    'command'
    """
    return {"hooks": [{"type": "command", "command": f"{_OUR_MARKER} {state}"}]}


class ClaudeCodeHook:
    """Lifecycle-hook installer for Claude Code.

    Merges ``libtmux-agent-emit`` hook entries into Claude Code's
    ``settings.json`` without touching any existing user hooks.  All
    mutations are written atomically (temp file + ``os.replace``).

    Parameters
    ----------
    settings_path : pathlib.Path or None
        Path to ``settings.json``.  Defaults to
        ``~/.claude/settings.json`` when ``None``.

    Examples
    --------
    >>> import pathlib, tempfile
    >>> with tempfile.TemporaryDirectory() as d:
    ...     hook = ClaudeCodeHook(settings_path=pathlib.Path(d) / "settings.json")
    ...     before = hook.status()
    ...     hook.install()
    ...     after = hook.status()
    ...     hook.uninstall()
    ...     gone = hook.status()
    >>> hook.name
    'claude'
    >>> (before, after, gone)
    ('absent', 'installed', 'absent')
    """

    #: Short machine identifier understood by the registry.
    name: str = "claude"

    def __init__(self, settings_path: pathlib.Path | None = None) -> None:
        self._settings_path: pathlib.Path = (
            settings_path
            if settings_path is not None
            else pathlib.Path.home() / ".claude" / "settings.json"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, t.Any]:
        """Load and return the settings dict, or an empty dict if absent.

        Returns
        -------
        dict[str, Any]
            Parsed JSON content of the settings file, or ``{}`` when the
            file does not exist.

        Notes
        -----
        Only a missing file is treated as empty.  A present-but-malformed
        settings file surfaces :exc:`json.JSONDecodeError` unchanged: we fail
        loud rather than silently overwrite a user's corrupt config.

        Examples
        --------
        >>> import pathlib, tempfile
        >>> with tempfile.TemporaryDirectory() as d:
        ...     sink = ClaudeCodeHook(settings_path=pathlib.Path(d) / "s.json")
        ...     loaded = sink._load()
        >>> loaded
        {}
        """
        try:
            with self._settings_path.open(encoding="utf-8") as fh:
                return t.cast(dict[str, t.Any], json.load(fh))
        except FileNotFoundError:
            return {}

    def _save(self, data: dict[str, t.Any]) -> None:
        """Write *data* atomically to :attr:`_settings_path`.

        Parameters
        ----------
        data : dict[str, Any]
            JSON-serialisable settings dict.

        Notes
        -----
        Uses a sibling temp file + ``os.fsync`` + ``os.replace`` so that
        no partial write ever survives a crash.

        Examples
        --------
        >>> import json, pathlib, tempfile
        >>> with tempfile.TemporaryDirectory() as d:
        ...     hook = ClaudeCodeHook(settings_path=pathlib.Path(d) / "s.json")
        ...     hook._save({"hooks": {}})
        ...     result = json.loads((pathlib.Path(d) / "s.json").read_text())
        >>> result
        {'hooks': {}}
        """
        directory = self._settings_path.parent
        directory.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(directory), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            pathlib.Path(tmp).replace(self._settings_path)
        except BaseException:
            with contextlib.suppress(OSError):
                pathlib.Path(tmp).unlink()
            raise

    # ------------------------------------------------------------------
    # Public interface (AgentHook protocol)
    # ------------------------------------------------------------------

    def detect(self) -> bool:
        """Return ``True`` when the Claude Code config dir and binary are present.

        Returns
        -------
        bool
            ``True`` when both ``~/.claude/`` (or the parent of
            *settings_path*) exists **and** a ``claude`` binary is on
            ``$PATH``; ``False`` otherwise.

        Examples
        --------
        >>> import pathlib, tempfile
        >>> with tempfile.TemporaryDirectory() as d:
        ...     hook = ClaudeCodeHook(settings_path=pathlib.Path(d) / "settings.json")
        ...     ok = isinstance(hook.detect(), bool)
        >>> ok
        True
        """
        return (
            self._settings_path.parent.exists() and shutil.which("claude") is not None
        )

    def install(self) -> None:
        """Merge our hook entries into the settings file (idempotent).

        For each Claude lifecycle event in :data:`_CLAUDE_EVENT_STATE`:

        1. Load the current settings (or start from ``{}`` if absent).
        2. Strip any existing groups that contain ``libtmux-agent-emit``
           (idempotency — removes a previous install before re-adding).
        3. Append a fresh group with the correct ``libtmux-agent-emit``
           command.
        4. Write the result atomically.

        User-owned groups (those whose commands do **not** contain
        ``libtmux-agent-emit``) are never modified.

        Examples
        --------
        >>> import pathlib, tempfile
        >>> with tempfile.TemporaryDirectory() as d:
        ...     hook = ClaudeCodeHook(settings_path=pathlib.Path(d) / "settings.json")
        ...     hook.install()
        ...     status = hook.status()
        >>> status
        'installed'
        """
        data = self._load()
        hooks_section: dict[str, list[dict[str, t.Any]]] = data.get("hooks", {})
        for event, state in _CLAUDE_EVENT_STATE.items():
            groups: list[dict[str, t.Any]] = list(hooks_section.get(event, []))
            # Remove any previous our-entries (idempotency).
            groups = [g for g in groups if not _is_our_group(g)]
            # Append a fresh our-entry.
            groups.append(_our_group(state))
            hooks_section[event] = groups
        data["hooks"] = hooks_section
        self._save(data)

    def uninstall(self) -> None:
        """Remove only our hook entries; leave all user entries intact.

        For each event key in the settings ``"hooks"`` section, groups
        whose command contains ``libtmux-agent-emit`` are removed.  Any
        event whose group list becomes empty is pruned from the section, so
        an install-then-uninstall on a fresh file leaves ``"hooks"`` empty
        rather than littered with empty arrays.  Events that still hold
        user-owned groups are preserved.  The file is written atomically.

        Examples
        --------
        >>> import pathlib, tempfile
        >>> with tempfile.TemporaryDirectory() as d:
        ...     hook = ClaudeCodeHook(settings_path=pathlib.Path(d) / "s.json")
        ...     hook.install()
        ...     hook.uninstall()
        ...     status = hook.status()
        >>> status
        'absent'
        """
        data = self._load()
        hooks_section: dict[str, list[dict[str, t.Any]]] = data.get("hooks", {})
        for event in list(hooks_section):
            hooks_section[event] = [
                g for g in hooks_section[event] if not _is_our_group(g)
            ]
        # Prune now-empty event keys; events with surviving user groups stay.
        hooks_section = {k: v for k, v in hooks_section.items() if v}
        data["hooks"] = hooks_section
        self._save(data)

    def status(self) -> str:
        """Return the installation status of our hooks.

        Reads the settings file and counts how many of the expected
        ``libtmux-agent-emit`` commands are present.

        Returns
        -------
        str
            ``"installed"`` — all expected hooks present and matching.
            ``"absent"`` — none of our hooks found.
            ``"outdated"`` — some but not all hooks found.

        Examples
        --------
        >>> import pathlib, tempfile
        >>> with tempfile.TemporaryDirectory() as d:
        ...     hook = ClaudeCodeHook(settings_path=pathlib.Path(d) / "settings.json")
        ...     before = hook.status()
        ...     hook.install()
        ...     after = hook.status()
        >>> (before, after)
        ('absent', 'installed')
        """
        data = self._load()
        hooks_section: dict[str, list[dict[str, t.Any]]] = data.get("hooks", {})

        present = 0
        for event, state in _CLAUDE_EVENT_STATE.items():
            expected_cmd = f"{_OUR_MARKER} {state}"
            groups = hooks_section.get(event, [])
            found = any(
                any(h.get("command") == expected_cmd for h in g.get("hooks", []))
                for g in groups
            )
            if found:
                present += 1

        total = len(_CLAUDE_EVENT_STATE)
        if present == total:
            return "installed"
        if present == 0:
            return "absent"
        return "outdated"
