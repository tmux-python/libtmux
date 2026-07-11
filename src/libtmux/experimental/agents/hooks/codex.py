"""Codex CLI lifecycle-hook installer.

Installs agent-state-emitting command hooks into Codex's ``config.toml``
under the ``[hooks]`` section.  Writes hooks between paired marker comments
so that :meth:`CodexHook.install`, :meth:`CodexHook.status`, and
:meth:`CodexHook.uninstall` operate only on our bounded block and preserve
the rest of ``config.toml`` verbatim.

The modern ``[hooks]`` TOML format (array-of-tables ``[[hooks.<event>]]``) is
the primary mechanism.  Codex's older single-program ``notify`` hook (fires
on turn-complete only, emitting ``done``) is a fallback for old Codex
versions — it is **not** implemented in v1; modern ``[hooks]`` is primary.

Codex event → state mapping::

    user_prompt_submit  → running
    permission_request  → awaiting_input
    stop                → done
    session_start       → idle

Each hook fires on a named Codex lifecycle event.  Codex passes event JSON
on stdin, but each event registers a separate hook so the command hard-codes
its state.

Marker-bounded write strategy
------------------------------
Our TOML is appended (or replaced in-place) between two TOML comment
markers::

    # >>> libtmux-agent-state >>>
    ... our hook entries ...
    # <<< libtmux-agent-state <<<

All content outside the block is preserved byte-for-byte; the file is never
round-tripped through a TOML serialiser.  ``status()`` and ``uninstall()``
operate exclusively on the marker-bounded block.
"""

from __future__ import annotations

import pathlib
import re
import shutil

from libtmux.experimental.agents._atomic import atomic_write_text

#: Codex event name → agent-state string.
#:
#: Maps each Codex lifecycle event to the agent-state value that
#: ``libtmux-agent-emit`` should broadcast when that event fires.
#:
#: Examples
#: --------
#: >>> _CODEX_EVENT_STATE["user_prompt_submit"]
#: 'running'
#: >>> _CODEX_EVENT_STATE["session_start"]
#: 'idle'
_CODEX_EVENT_STATE: dict[str, str] = {
    "user_prompt_submit": "running",
    "permission_request": "awaiting_input",
    "stop": "done",
    "session_start": "idle",
}

_MARKER_START: str = "# >>> libtmux-agent-state >>>"
_MARKER_END: str = "# <<< libtmux-agent-state <<<"

#: Matches the marker-bounded block body (no preceding separator newline).
_BLOCK_RE: re.Pattern[str] = re.compile(
    re.escape(_MARKER_START) + r".*?" + re.escape(_MARKER_END) + r"\n?",
    re.DOTALL,
)

#: Matches the block body together with its preceding separator newline.
_BLOCK_WITH_SEP_RE: re.Pattern[str] = re.compile(
    r"\n" + re.escape(_MARKER_START) + r".*?" + re.escape(_MARKER_END) + r"\n?",
    re.DOTALL,
)


class CodexHook:
    """Lifecycle-hook installer for the Codex CLI (OpenAI).

    Merges ``libtmux-agent-emit`` hook entries into Codex's
    ``~/.codex/config.toml`` using a marker-bounded text block.
    Content outside the block is preserved byte-for-byte.

    The TOML shape used for each event is an array-of-tables entry::

        [[hooks.<event>]]
        type = "command"
        command = "libtmux-agent-emit <state>"

    This produces syntactically valid TOML (the whole file parses cleanly
    with :mod:`tomllib` after install).

    Parameters
    ----------
    config_path : pathlib.Path or None
        Path to Codex's ``config.toml``.  Defaults to
        ``~/.codex/config.toml`` when ``None``.

    Notes
    -----
    **Legacy notify fallback (not implemented in v1).**
    Old Codex versions support a single-program ``notify`` hook that fires
    on turn-complete only (equivalent to ``done``).  Modern ``[hooks]`` is the
    primary mechanism; the ``notify`` path is documented here for future
    reference but is not implemented.

    Examples
    --------
    >>> import pathlib, tempfile
    >>> with tempfile.TemporaryDirectory() as d:
    ...     hook = CodexHook(config_path=pathlib.Path(d) / "config.toml")
    ...     before = hook.status()
    ...     hook.install()
    ...     after = hook.status()
    ...     hook.uninstall()
    ...     gone = hook.status()
    >>> (before, after, gone)
    ('absent', 'installed', 'absent')
    """

    #: Short machine identifier understood by the registry.
    name: str = "codex"

    def __init__(self, config_path: pathlib.Path | None = None) -> None:
        self._config_path: pathlib.Path = (
            config_path
            if config_path is not None
            else pathlib.Path.home() / ".codex" / "config.toml"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read(self) -> str:
        """Return the current file text, or ``""`` if the file is absent.

        Returns
        -------
        str
            File content decoded as UTF-8, or an empty string when the file
            does not exist.

        Examples
        --------
        >>> import pathlib, tempfile
        >>> with tempfile.TemporaryDirectory() as d:
        ...     hook = CodexHook(config_path=pathlib.Path(d) / "config.toml")
        ...     text = hook._read()
        >>> text
        ''
        """
        try:
            return self._config_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def _write(self, content: str) -> None:
        r"""Write *content* atomically to :attr:`_config_path`.

        Creates parent directories as needed.  Uses a sibling temp file plus
        ``os.fsync`` + ``os.replace`` so no partial write survives a crash.

        Parameters
        ----------
        content : str
            Full file text to write.

        Examples
        --------
        >>> import pathlib, tempfile
        >>> with tempfile.TemporaryDirectory() as d:
        ...     hook = CodexHook(config_path=pathlib.Path(d) / "config.toml")
        ...     hook._write('model = "o4"\n')
        ...     text = hook._read()
        >>> text
        'model = "o4"\n'
        """
        atomic_write_text(self._config_path, content)

    def _build_block(self) -> str:
        r"""Build the marker-bounded TOML block string.

        Returns the block from start marker to end marker (inclusive) with a
        trailing newline.  The block does **not** include the leading separator
        newline added by :meth:`install` when appending to a non-empty file.

        Returns
        -------
        str
            Ready-to-write block text ending with ``\n``.

        Examples
        --------
        >>> import pathlib, tempfile
        >>> with tempfile.TemporaryDirectory() as d:
        ...     hook = CodexHook(config_path=pathlib.Path(d) / "config.toml")
        ...     block = hook._build_block()
        >>> block.startswith("# >>> libtmux-agent-state >>>")
        True
        >>> "libtmux-agent-emit running" in block
        True
        >>> block.endswith("# <<< libtmux-agent-state <<<\n")
        True
        """
        lines = [_MARKER_START]
        for event, state in _CODEX_EVENT_STATE.items():
            lines.append("")
            lines.append(f"[[hooks.{event}]]")
            lines.append('type = "command"')
            lines.append(f'command = "libtmux-agent-emit {state}"')
        lines.append(_MARKER_END)
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Public interface (AgentHook protocol)
    # ------------------------------------------------------------------

    def detect(self) -> bool:
        """Return ``True`` when the Codex config dir and binary are present.

        Returns
        -------
        bool
            ``True`` when both the parent directory of *config_path* exists
            **and** a ``codex`` binary is on ``$PATH``; ``False`` otherwise.

        Examples
        --------
        >>> import pathlib, tempfile
        >>> with tempfile.TemporaryDirectory() as d:
        ...     hook = CodexHook(config_path=pathlib.Path(d) / "config.toml")
        ...     result = hook.detect()
        >>> isinstance(result, bool)
        True
        """
        return self._config_path.parent.exists() and shutil.which("codex") is not None

    def install(self) -> None:
        """Write our hook block into ``config.toml`` (idempotent).

        If our marker block is already present it is replaced in-place;
        otherwise the block is appended with a blank-line separator.
        Content outside the marker block is preserved verbatim.

        Examples
        --------
        >>> import pathlib, tempfile
        >>> with tempfile.TemporaryDirectory() as d:
        ...     hook = CodexHook(config_path=pathlib.Path(d) / "config.toml")
        ...     hook.install()
        ...     status = hook.status()
        >>> status
        'installed'
        """
        content = self._read()
        new_block = self._build_block()
        if _MARKER_START in content:
            # Strip ALL existing marker blocks (handles duplicates from a
            # manually-malformed config) then append exactly one fresh block.
            content = _BLOCK_WITH_SEP_RE.sub("", content)
            if _MARKER_START in content:
                # Any block at the very start of file has no preceding newline.
                content = _BLOCK_RE.sub("", content)
            if content:
                if not content.endswith("\n"):
                    content += "\n"
                content = content + "\n" + new_block
            else:
                content = new_block
        elif content:
            if not content.endswith("\n"):
                content += "\n"
            content = content + "\n" + new_block
        else:
            content = new_block
        self._write(content)

    def uninstall(self) -> None:
        """Remove our marker-bounded block; leave everything else intact.

        Handles a missing file or absent block gracefully (no-op).  The
        separator newline added by :meth:`install` is also removed so that
        the original file content is restored exactly.

        Examples
        --------
        >>> import pathlib, tempfile
        >>> with tempfile.TemporaryDirectory() as d:
        ...     hook = CodexHook(config_path=pathlib.Path(d) / "config.toml")
        ...     hook.install()
        ...     hook.uninstall()
        ...     status = hook.status()
        >>> status
        'absent'
        """
        content = self._read()
        if _MARKER_START not in content:
            return
        new_content = _BLOCK_WITH_SEP_RE.sub("", content)
        if new_content == content:
            # Block was at the start of the file — no preceding newline.
            new_content = _BLOCK_RE.sub("", content)
        self._write(new_content)

    def status(self) -> str:
        """Return the installation status of our hook block.

        Reads ``config.toml`` and checks whether our marker-bounded block is
        present and matches what :meth:`install` would write today.

        Returns
        -------
        str
            ``"installed"`` — block present and content matches current
            expected output.
            ``"absent"`` — our start marker not found in the file.
            ``"outdated"`` — start marker found but block content differs.

        Examples
        --------
        >>> import pathlib, tempfile
        >>> with tempfile.TemporaryDirectory() as d:
        ...     hook = CodexHook(config_path=pathlib.Path(d) / "config.toml")
        ...     before = hook.status()
        ...     hook.install()
        ...     after = hook.status()
        >>> (before, after)
        ('absent', 'installed')
        """
        content = self._read()
        if _MARKER_START not in content:
            return "absent"
        match = _BLOCK_RE.search(content)
        if match is None:
            return "absent"
        if match.group(0) == self._build_block():
            return "installed"
        return "outdated"
