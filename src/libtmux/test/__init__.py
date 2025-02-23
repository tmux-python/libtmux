"""Helper methods for libtmux and downstream libtmux libraries."""

from __future__ import annotations

import contextlib
import logging
import os
import pathlib
import random
import time
import typing as t

from libtmux.exc import WaitTimeout
from libtmux.test.constants import (
    RETRY_INTERVAL_SECONDS,
    RETRY_TIMEOUT_SECONDS,
    TEST_SESSION_PREFIX,
)

from .random import namer

logger = logging.getLogger(__name__)

if t.TYPE_CHECKING:
    import sys
    import types
    from collections.abc import Callable, Generator

    from libtmux.server import Server
    from libtmux.session import Session
    from libtmux.window import Window

    if sys.version_info >= (3, 11):
        from typing import Self
    else:
        from typing_extensions import Self


current_dir = pathlib.Path(__file__)
example_dir = current_dir.parent / "examples"
fixtures_dir = current_dir / "fixtures"


def retry_until(
    fun: Callable[[], bool],
    seconds: float = RETRY_TIMEOUT_SECONDS,
    *,
    interval: float = RETRY_INTERVAL_SECONDS,
    raises: bool | None = True,
) -> bool:
    """
    Retry a function until a condition meets or the specified time passes.

    Parameters
    ----------
    fun : callable
        A function that will be called repeatedly until it returns ``True``  or
        the specified time passes.
    seconds : float
        Seconds to retry. Defaults to ``8``, which is configurable via
        ``RETRY_TIMEOUT_SECONDS`` environment variables.
    interval : float
        Time in seconds to wait between calls. Defaults to ``0.05`` and is
        configurable via ``RETRY_INTERVAL_SECONDS`` environment variable.
    raises : bool
        Whether or not to raise an exception on timeout. Defaults to ``True``.

    Examples
    --------
    >>> def fn():
    ...     p = session.active_window.active_pane
    ...     return p.pane_current_path is not None

    >>> retry_until(fn)
    True

    In pytest:

    >>> assert retry_until(fn, raises=False)
    """
    ini = time.time()

    while not fun():
        end = time.time()
        if end - ini >= seconds:
            if raises:
                raise WaitTimeout
            return False
        time.sleep(interval)
    return True
