"""Prisma-style generated command client experiment."""

from __future__ import annotations

from .shared import CommandCall, new_window_call


class GeneratedSessionCommands:
    """Generated session command namespace."""

    def new_window(self, *, name: str, detach: bool = True) -> CommandCall:
        """Build a typed ``new-window`` command."""
        return new_window_call(window_name=name, detach=detach)


class GeneratedWindowCommands:
    """Generated window command namespace."""

    def rename(self, *, target: str, name: str) -> CommandCall:
        """Build a typed ``rename-window`` command."""
        return CommandCall("rename-window", (name,), target=target)


class GeneratedCommands:
    """Generated root command client."""

    def __init__(self) -> None:
        """Initialize generated namespaces."""
        self.session = GeneratedSessionCommands()
        self.window = GeneratedWindowCommands()
