"""Extended retry functionality for libtmux."""

from __future__ import annotations

import logging
import time
import typing as t

from libtmux.exc import WaitTimeout
from libtmux.test.constants import (
    RETRY_INTERVAL_SECONDS,
    RETRY_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)

if t.TYPE_CHECKING:
    from collections.abc import Callable


def retry_until_extended(
    fun: Callable[[], bool],
    seconds: float = RETRY_TIMEOUT_SECONDS,
    *,
    interval: float = RETRY_INTERVAL_SECONDS,
    raises: bool | None = True,
) -> tuple[bool, Exception | None]:
    """
    Retry a function until a condition meets or the specified time passes.

    Extended version that returns both success state and exception.

    Parameters
    ----------
    fun : callable
        A function that will be called repeatedly until it returns ``True`` or
        the specified time passes.
    seconds : float
        Seconds to retry. Defaults to ``8``, which is configurable via
        ``RETRY_TIMEOUT_SECONDS`` environment variables.
    interval : float
        Time in seconds to wait between calls. Defaults to ``0.05`` and is
        configurable via ``RETRY_INTERVAL_SECONDS`` environment variable.
    raises : bool
        Whether or not to raise an exception on timeout. Defaults to ``True``.

    Returns
    -------
    tuple[bool, Exception | None]
        Tuple containing (success, exception). If successful, the exception will
        be None.
    """
    ini = time.time()
    exception = None

    while not fun():
        end = time.time()
        if end - ini >= seconds:
            timeout_msg = f"Timed out after {seconds} seconds"
            exception = WaitTimeout(timeout_msg)
            if raises:
                raise exception
            return False, exception
        time.sleep(interval)
    return True, None
