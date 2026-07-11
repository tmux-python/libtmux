"""The protocol every agent hook installer satisfies.

Each agent ships its own lifecycle-event vocabulary and its own config format, so
a hook object owns that translation: it knows how to detect its agent, install and
uninstall its hooks, and report their status.
"""

from __future__ import annotations

import typing as t


@t.runtime_checkable
class AgentHook(t.Protocol):
    """Protocol every hook installer must satisfy.

    A hook object represents one agent's lifecycle-hook integration.  It
    knows how to detect whether its hooks are already installed (and at
    what version), install them, uninstall them, and report current status.

    Examples
    --------
    >>> from libtmux.experimental.agents.hooks.claude import ClaudeCodeHook
    >>> hook = ClaudeCodeHook()
    >>> isinstance(hook, AgentHook)
    True
    >>> hook.name
    'claude'
    """

    #: Short machine identifier for this hook (e.g. ``"claude"``).
    name: str

    def detect(self) -> bool:
        """Return ``True`` when the agent binary / config dir is present.

        Examples
        --------
        >>> from libtmux.experimental.agents.hooks.claude import ClaudeCodeHook
        >>> isinstance(ClaudeCodeHook().detect(), bool)
        True
        """
        ...

    def install(self) -> None:
        """Write hook scripts into the agent's config directory.

        Examples
        --------
        >>> import pathlib, tempfile
        >>> from libtmux.experimental.agents.hooks.claude import ClaudeCodeHook
        >>> with tempfile.TemporaryDirectory() as d:
        ...     hook = ClaudeCodeHook(settings_path=pathlib.Path(d) / "settings.json")
        ...     hook.install()
        """
        ...

    def uninstall(self) -> None:
        """Remove hook scripts from the agent's config directory.

        Examples
        --------
        >>> import pathlib, tempfile
        >>> from libtmux.experimental.agents.hooks.claude import ClaudeCodeHook
        >>> with tempfile.TemporaryDirectory() as d:
        ...     hook = ClaudeCodeHook(settings_path=pathlib.Path(d) / "settings.json")
        ...     hook.uninstall()
        """
        ...

    def status(self) -> str:
        """Return ``"installed"``, ``"outdated"``, or ``"absent"``.

        Examples
        --------
        >>> from libtmux.experimental.agents.hooks.claude import ClaudeCodeHook
        >>> ClaudeCodeHook().status() in {"installed", "outdated", "absent"}
        True
        """
        ...
