"""Stub for ClaudeCodeHook — completed in Task 14.

This module exists so that :mod:`libtmux.experimental.agents.hooks.registry`
can import :class:`ClaudeCodeHook` without error while Task 14 is not yet
merged.  The real implementation (config-dir detection, hook-script writing,
status inspection) will replace this body in Task 14.
"""

from __future__ import annotations


class ClaudeCodeHook:
    """Lifecycle-hook installer for Claude Code.

    .. note::
        This is a **stub** completed in Task 14.  All methods are no-ops;
        :meth:`detect` returns ``False`` and :meth:`status` returns
        ``"absent"`` until the real implementation lands.

    Examples
    --------
    >>> ClaudeCodeHook().name
    'claude'
    >>> ClaudeCodeHook().detect()
    False
    >>> ClaudeCodeHook().status()
    'absent'
    """

    #: Short machine identifier understood by the registry.
    name: str = "claude"

    def detect(self) -> bool:
        """Return ``False`` — stub; real detection added in Task 14.

        Examples
        --------
        >>> ClaudeCodeHook().detect()
        False
        """
        # TODO(Task 14): detect ~/.claude or `claude` binary presence
        return False

    def install(self) -> None:
        """No-op — stub; real installer added in Task 14.

        Examples
        --------
        >>> ClaudeCodeHook().install()
        """
        # TODO(Task 14): write hook scripts into ~/.claude/hooks/

    def uninstall(self) -> None:
        """No-op — stub; real uninstaller added in Task 14.

        Examples
        --------
        >>> ClaudeCodeHook().uninstall()
        """
        # TODO(Task 14): remove hook scripts from ~/.claude/hooks/

    def status(self) -> str:
        """Return ``"absent"`` — stub; real status check added in Task 14.

        Examples
        --------
        >>> ClaudeCodeHook().status()
        'absent'
        """
        # TODO(Task 14): inspect hook scripts and return installed/outdated/absent
        return "absent"
