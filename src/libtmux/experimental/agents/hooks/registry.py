"""AgentHook installer registry.

All known :class:`~libtmux.experimental.agents.hooks.base.AgentHook`
installers are listed via :func:`registry` or fetched by name via
:func:`get`.  Imports inside those functions stay lazy to avoid cycles.
"""

from __future__ import annotations

from libtmux.experimental.agents.hooks.base import AgentHook


def registry() -> list[AgentHook]:
    """Return one instance of every known hook installer.

    Imports are performed lazily here to break any potential import cycles
    between this registry module and individual hook modules.

    Returns
    -------
    list[AgentHook]
        Ordered list of hook installer instances; currently
        ``[ClaudeCodeHook(), CodexHook()]``.

    Examples
    --------
    >>> hooks = registry()
    >>> {h.name for h in hooks} >= {"claude", "codex"}
    True
    """
    # Lazy imports — keep here to avoid import cycles when hook modules
    # grow richer dependencies (Tasks 14/15).
    from libtmux.experimental.agents.hooks.claude import ClaudeCodeHook
    from libtmux.experimental.agents.hooks.codex import CodexHook

    return [ClaudeCodeHook(), CodexHook()]


def get(name: str) -> AgentHook:
    """Return the hook installer for *name*, or raise :exc:`KeyError`.

    Parameters
    ----------
    name : str
        The hook's :attr:`~libtmux.experimental.agents.hooks.base.AgentHook.name`
        (e.g. ``"claude"`` or ``"codex"``).

    Returns
    -------
    AgentHook
        The matching hook installer instance.

    Raises
    ------
    KeyError
        When no hook with *name* is registered.

    Examples
    --------
    >>> get("claude").name
    'claude'
    >>> get("codex").name
    'codex'
    >>> try:
    ...     get("unknown")
    ... except KeyError:
    ...     print("KeyError raised")
    KeyError raised
    """
    for hook in registry():
        if hook.name == name:
            return hook
    raise KeyError(name)
