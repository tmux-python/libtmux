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
    """Safely mock environmental variables within a context manager.

    Ensures any changes to environment variables are reverted upon exit.

    Notes
    -----
    This is vendorized to address issues where some Python distributions do
    not include test modules such as test_support.

    References
    ----------
    #. "ImportError: cannot import name test_support" found in certain Python
       distributions, see issue #121 in the tmuxp project.
    """

    def __init__(self) -> None:
        self._environ = os.environ
        self._unset: set[str] = set()
        self._reset: dict[str, str] = {}

    def set(self, envvar: str, value: str) -> None:
        """Set an environment variable, preserving prior state."""
        if envvar not in self._environ:
            self._unset.add(envvar)
        else:
            self._reset[envvar] = self._environ[envvar]
        self._environ[envvar] = value

    def unset(self, envvar: str) -> None:
        """Unset an environment variable, preserving prior state."""
        if envvar in self._environ:
            # If we previously set this variable in this context, remove it from _unset
            if envvar in self._unset:
                self._unset.remove(envvar)
            # If we haven't saved the original value yet, save it
            if envvar not in self._reset:
                self._reset[envvar] = self._environ[envvar]
            del self._environ[envvar]

    def __enter__(self) -> Self:
        """Enter context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Exit context manager, reverting environment changes."""
        for envvar, value in self._reset.items():
            self._environ[envvar] = value
        for unset in self._unset:
            if unset not in self._reset:  # Don't delete variables that were reset
                del self._environ[unset]
