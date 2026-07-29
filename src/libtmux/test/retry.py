"""Retry helpers for libtmux and downstream libtmux libraries."""

from __future__ import annotations

import time
import typing as t

from libtmux.exc import WaitTimeout
from libtmux.test.constants import (
    RETRY_INTERVAL_SECONDS,
    RETRY_TIMEOUT_SECONDS,
)

if t.TYPE_CHECKING:
    import sys
    from collections.abc import Callable

    if sys.version_info >= (3, 11):
        pass


@t.overload
def retry_until(
    fun: Callable[[], bool],
    seconds: float = ...,
    *,
    interval: float = ...,
    raises: bool | None = ...,
) -> bool: ...


@t.overload
def retry_until(
    fun: Callable[..., bool],
    seconds: float = ...,
    *,
    args: tuple[t.Any, ...],
    interval: float = ...,
    raises: bool | None = ...,
) -> bool: ...


def retry_until(
    fun: Callable[..., bool],
    seconds: float = RETRY_TIMEOUT_SECONDS,
    *,
    args: tuple[t.Any, ...] = (),
    interval: float = RETRY_INTERVAL_SECONDS,
    raises: bool | None = True,
) -> bool:
    """
    Retry a function until a condition meets or the specified time passes.

    Parameters
    ----------
    fun : callable
        A function that will be called repeatedly until it returns ``True``  or
        the specified time passes. Called with ``args`` unpacked, so it accepts
        no arguments unless ``args`` is given.
    seconds : float
        Seconds to retry. Defaults to ``8``, which is configurable via
        ``RETRY_TIMEOUT_SECONDS`` environment variables.
    args : tuple
        Positional arguments passed to ``fun`` on every call. Pass the subject
        being waited on here instead of closing over it, which keeps predicates
        written inside a loop free of a loop-variable binding.
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

    Waiting on something from a loop takes ``args`` rather than a closure:

    >>> window = session.new_window(window_name='retry_until_args')
    >>> panes = [window.active_pane, window.split()]
    >>> for pane in panes:
    ...     pane.send_keys('echo ready')

    Compare whole lines. ``capture_pane`` returns the command tmux echoed onto
    the pane, so ``'ready' in line`` matches that echo and is already true
    before the shell has run anything:

    >>> for pane in panes:
    ...     assert retry_until(
    ...         lambda p: any(line.strip() == 'ready' for line in p.capture_pane()),
    ...         args=(pane,),
    ...     )
    """
    ini = time.time()

    while not fun(*args):
        end = time.time()
        if end - ini >= seconds:
            if raises:
                raise WaitTimeout
            return False
        time.sleep(interval)
    return True
