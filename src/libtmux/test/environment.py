"""Helper methods for libtmux and downstream libtmux libraries."""

from __future__ import annotations

import logging
import os
import typing as t

logger = logging.getLogger(__name__)

if t.TYPE_CHECKING:
    import sys
    import types

    if sys.version_info >= (3, 11):
        from typing import Self
    else:
        from typing_extensions import Self


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
        self._unset: set[str] = set()
        self._reset: dict[str, str] = {}

    def set(self, envvar: str, value: str) -> None:
        """Set environment variable."""
        if envvar not in self._environ:
            self._unset.add(envvar)
        else:
            self._reset[envvar] = self._environ[envvar]
        self._environ[envvar] = value

    def unset(self, envvar: str) -> None:
        """Unset environment variable."""
        if envvar in self._environ:
            # If we previously set this variable in this context, remove it from _unset
            if envvar in self._unset:
                self._unset.remove(envvar)
            # If we haven't saved the original value yet, save it
            if envvar not in self._reset:
                self._reset[envvar] = self._environ[envvar]
            del self._environ[envvar]

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
        for envvar, value in self._reset.items():
            self._environ[envvar] = value
        for unset in self._unset:
            if unset not in self._reset:  # Don't delete variables that were reset
                del self._environ[unset]
