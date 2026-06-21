"""The ``respawn-window`` operation."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops._types import Effects
from libtmux.experimental.ops.operation import Operation
from libtmux.experimental.ops.registry import register
from libtmux.experimental.ops.results import AckResult

if t.TYPE_CHECKING:
    from collections.abc import Mapping


@register
@dataclass(frozen=True, kw_only=True)
class RespawnWindow(Operation[AckResult]):
    """Restart the command in a (usually dead) window (``respawn-window``).

    Parameters
    ----------
    kill : bool
        Kill the existing process first (``-k``).
    start_directory : str or None
        Working directory for the new process (``-c``).
    environment : Mapping[str, str] or None
        Environment variables (``-e``; tmux 3.0+).
    shell : str or None
        Command to run instead of the default shell.

    Examples
    --------
    >>> from libtmux.experimental.ops._types import WindowId
    >>> RespawnWindow(target=WindowId("@1"), kill=True).render()
    ('respawn-window', '-t', '@1', '-k')
    """

    kind = "respawn_window"
    command = "respawn-window"
    scope = "window"
    result_cls = AckResult
    safety = "mutating"
    effects = Effects()
    flag_version_map: t.ClassVar[Mapping[str, str]] = {"environment": "3.0"}

    kill: bool = False
    start_directory: str | None = None
    environment: Mapping[str, str] | None = None
    shell: str | None = None

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Render the respawn flags."""
        out: list[str] = []
        if self.kill:
            out.append("-k")
        if self.start_directory is not None:
            out.append(f"-c{self.start_directory}")
        if self.environment and self.flag_available("environment", version):
            out.extend(f"-e{key}={value}" for key, value in self.environment.items())
        if self.shell is not None:
            out.append(self.shell)
        return tuple(out)
