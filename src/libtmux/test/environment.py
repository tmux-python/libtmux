"""Helper methods for libtmux and downstream libtmux libraries."""

from __future__ import annotations

import os
import typing as t

if t.TYPE_CHECKING:
    import types
    from typing import Self


class EnvironmentVarGuard:
    """Mock environmental variables safely.

    Helps protect the environment variable properly. Can be used as context
    manager.

    Notes
    -----
    Vendorized to fix issue with Anaconda Python 2 not including test module,
    see `tmuxp#121 <https://github.com/tmux-python/tmuxp/issues/121>`_.
    """

    def __init__(self) -> None:
        self._environ = os.environ
        self._original: dict[str, str | None] = {}

    def set(self, envvar: str, value: str) -> None:
        """Set environment variable."""
        self._original.setdefault(envvar, self._environ.get(envvar))
        self._environ[envvar] = value

    def unset(self, envvar: str) -> None:
        """Unset environment variable."""
        self._original.setdefault(envvar, self._environ.get(envvar))
        self._environ.pop(envvar, None)

    def __enter__(self) -> Self:
        """Return context for for context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Cleanup to run after context manager finishes."""
        for envvar, value in self._original.items():
            if value is None:
                self._environ.pop(envvar, None)
            else:
                self._environ[envvar] = value
        self._original.clear()
