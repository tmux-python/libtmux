"""Stub for CodexHook — completed in Task 15.

This module exists so that :mod:`libtmux.experimental.agents.hooks.registry`
can import :class:`CodexHook` without error while Task 15 is not yet merged.
The real implementation (config-dir detection, hook-script writing, status
inspection) will replace this body in Task 15.
"""

from __future__ import annotations


class CodexHook:
    """Lifecycle-hook installer for OpenAI Codex CLI.

    .. note::
        This is a **stub** completed in Task 15.  All methods are no-ops;
        :meth:`detect` returns ``False`` and :meth:`status` returns
        ``"absent"`` until the real implementation lands.

    Examples
    --------
    >>> CodexHook().name
    'codex'
    >>> CodexHook().detect()
    False
    >>> CodexHook().status()
    'absent'
    """

    #: Short machine identifier understood by the registry.
    name: str = "codex"

    def detect(self) -> bool:
        """Return ``False`` — stub; real detection added in Task 15.

        Examples
        --------
        >>> CodexHook().detect()
        False
        """
        # TODO(Task 15): detect ~/.codex or `codex` binary presence
        return False

    def install(self) -> None:
        """No-op — stub; real installer added in Task 15.

        Examples
        --------
        >>> CodexHook().install()
        """
        # TODO(Task 15): write hook scripts into ~/.codex/hooks/

    def uninstall(self) -> None:
        """No-op — stub; real uninstaller added in Task 15.

        Examples
        --------
        >>> CodexHook().uninstall()
        """
        # TODO(Task 15): remove hook scripts from ~/.codex/hooks/

    def status(self) -> str:
        """Return ``"absent"`` — stub; real status check added in Task 15.

        Examples
        --------
        >>> CodexHook().status()
        'absent'
        """
        # TODO(Task 15): inspect hook scripts and return installed/outdated/absent
        return "absent"
