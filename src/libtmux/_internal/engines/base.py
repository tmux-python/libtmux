"""Base engine for libtmux."""

from __future__ import annotations

import typing as t
from abc import ABC, abstractmethod

if t.TYPE_CHECKING:
    from libtmux.common import tmux_cmd


class Engine(ABC):
    """Abstract base class for tmux execution engines."""

    @abstractmethod
    def run(self, *args: t.Any) -> tmux_cmd:
        """Run a tmux command and return the result."""
        ...
