"""AgentHook protocol and canonical lifecycle-event → state map.

The ``EVENT_STATE`` map translates neutral event names emitted by agent
lifecycle hooks into the :data:`AgentState` string vocabulary understood
by the monitor.  ``AgentHook`` is the protocol every hook installer must
satisfy.
"""

from __future__ import annotations

import typing as t

#: Canonical map from a neutral lifecycle event name to an agent-state string.
#:
#: Keys are the event names that agent hooks fire (e.g. as hook script names);
#: values are the :class:`~libtmux.experimental.agents.state.AgentState`
#: string representations the monitor stores.
#:
#: Examples
#: --------
#: >>> EVENT_STATE["turn_start"]
#: 'running'
#: >>> EVENT_STATE["needs_approval"]
#: 'awaiting_input'
#: >>> EVENT_STATE["turn_end"]
#: 'done'
#: >>> EVENT_STATE["session_start"]
#: 'idle'
EVENT_STATE: dict[str, str] = {
    "turn_start": "running",
    "needs_approval": "awaiting_input",
    "turn_end": "done",
    "session_start": "idle",
}


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
