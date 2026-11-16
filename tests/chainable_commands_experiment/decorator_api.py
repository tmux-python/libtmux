"""Django-style decorator experiment for command metadata."""

from __future__ import annotations

import typing as t
from collections.abc import Callable

from .shared import (
    CommandCall,
    CommandScope,
    CommandSpec,
    new_window_call,
    split_window_call,
)

P = t.ParamSpec("P")


def tmux_command(
    name: str,
    *,
    scope: CommandScope,
    chainable: bool = True,
) -> Callable[[Callable[P, CommandCall]], Callable[P, CommandCall]]:
    """Attach command metadata while preserving the callable signature."""
    spec = CommandSpec(name=name, scope=scope, chainable=chainable)

    def decorator(
        function: Callable[P, CommandCall],
    ) -> Callable[P, CommandCall]:
        vars(function)["__tmux_command_spec__"] = spec
        return function

    return decorator


def get_command_spec(function: object) -> CommandSpec:
    """Return metadata attached by :func:`tmux_command`."""
    spec = getattr(function, "__tmux_command_spec__", None)
    if isinstance(spec, CommandSpec):
        return spec
    msg = "callable does not have tmux command metadata"
    raise TypeError(msg)


@tmux_command("new-window", scope="session")
def new_window(
    *,
    window_name: str | None = None,
    detach: bool = True,
) -> CommandCall:
    """Build a ``new-window`` call."""
    return new_window_call(window_name=window_name, detach=detach)


@tmux_command("split-window", scope="window")
def split_window(
    *,
    horizontal: bool = False,
    percentage: int | None = None,
) -> CommandCall:
    """Build a ``split-window`` call."""
    return split_window_call(horizontal=horizontal, percentage=percentage)
