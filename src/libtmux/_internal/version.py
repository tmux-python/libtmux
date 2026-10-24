"""Legacy helpers that read the tmux client executable's version.

``libtmux.common`` re-exports every public name here, so existing imports keep
working. The helpers report the executable found on ``PATH`` (or *tmux_bin*),
not the daemon a :class:`~libtmux.Server` is connected to, which can be a
different release. Each one emits a :exc:`DeprecationWarning`; libtmux itself
checks the daemon through :mod:`libtmux._internal.support`.
"""

from __future__ import annotations

import functools
import re
import sys
import typing as t
import warnings

from libtmux import exc
from libtmux._compat import LooseVersion
from libtmux._internal.support import versions

if t.TYPE_CHECKING:
    from collections.abc import Callable

#: Minimum version of tmux required to run libtmux
TMUX_MIN_VERSION = versions.MINIMUM

#: Most recent version of tmux supported
TMUX_MAX_VERSION = "3.7"

_COMPARE_HINT = 'is_at_least(server_version(server), "3.4")'


def _tmux_cmd(*args: str, tmux_bin: str | None = None) -> t.Any:
    """Run ``tmux`` through ``libtmux.common.tmux_cmd``, looked up at call time."""
    from libtmux import common

    return common.tmux_cmd(*args, tmux_bin=tmux_bin)


def _deprecation(name: str, replacement: str) -> str:
    """Return the warning text shared by the deprecated helpers."""
    return (
        f"libtmux.common.{name}() reads the tmux client executable, not the "
        f"daemon a Server is connected to. Use {replacement} from "
        "libtmux._internal.support."
    )


class _TmuxVersionUnavailable(Exception):
    """Internal signal: this tmux predates the ``-V`` flag (pre-1.7)."""


def _no_version_flag_fallback() -> str:
    """Return a synthetic version string when tmux lacks ``-V``.

    OpenBSD ships a ``-V``-less base tmux, so assume the maximum supported
    version; any other platform is genuinely too old.
    """
    if sys.platform.startswith("openbsd"):  # openbsd has no tmux -V
        return f"{TMUX_MAX_VERSION}-openbsd"
    msg = (
        f"libtmux supports tmux {TMUX_MIN_VERSION} and greater. This system"
        " does not meet the minimum tmux version requirement."
    )
    raise exc.LibTmuxException(msg)


def _query_version(tmux_bin: str | None = None) -> str:
    """Return the raw ``tmux -V`` version token, letter suffix intact.

    Not memoized -- :func:`_get_version` and :func:`_get_version_str` each
    cache their own result on top of this query.

    Raises
    ------
    _TmuxVersionUnavailable
        tmux predates the ``-V`` flag; callers apply
        :func:`_no_version_flag_fallback`.
    :exc:`~libtmux.exc.VersionTooLow`
        tmux reported another error on ``-V``.
    """
    proc = _tmux_cmd("-V", tmux_bin=tmux_bin)
    if proc.stderr:
        if proc.stderr[0] == "tmux: unknown option -- V":
            raise _TmuxVersionUnavailable
        raise exc.VersionTooLow(proc.stderr)

    if len(proc.stdout) != 1 or not proc.stdout[0].startswith("tmux "):
        msg = "tmux -V did not report a single version"
        raise exc.VersionTooLow(msg)
    version: str = proc.stdout[0].removeprefix("tmux ")
    return version


@functools.cache
def _get_version_str(tmux_bin: str | None = None) -> str:
    """Return the executable's version token verbatim, letter suffix intact."""
    try:
        return _query_version(tmux_bin=tmux_bin)
    except _TmuxVersionUnavailable:
        return _no_version_flag_fallback()


@functools.cache
def _get_version(tmux_bin: str | None = None) -> LooseVersion:
    """Return the executable's version with letter suffixes stripped."""
    try:
        version = _query_version(tmux_bin=tmux_bin)
    except _TmuxVersionUnavailable:
        # OpenBSD base tmux lacks ``-V``; skip letter-stripping on the synthetic.
        return LooseVersion(_no_version_flag_fallback())

    # Allow latest tmux HEAD
    if version == "master":
        return LooseVersion(f"{TMUX_MAX_VERSION}-master")

    version = re.sub(r"[a-z-]", "", version)

    return LooseVersion(version)


_R = t.TypeVar("_R")
_R_co = t.TypeVar("_R_co", covariant=True)


class _CachedHelper(t.Protocol[_R_co]):
    """A public helper that still offers the old ``cache_clear()`` hook."""

    def __call__(self, tmux_bin: str | None = None) -> _R_co: ...

    def cache_clear(self) -> None: ...


def _clears(
    cached: t.Any,
) -> Callable[[Callable[[str | None], _R]], _CachedHelper[_R]]:
    """Expose *cached*'s ``cache_clear`` on the public helper it backs."""

    def decorate(func: Callable[[str | None], _R]) -> _CachedHelper[_R]:
        func.cache_clear = cached.cache_clear  # type: ignore[attr-defined]
        return t.cast("_CachedHelper[_R]", func)

    return decorate


@_clears(_get_version_str)
def get_version_str(tmux_bin: str | None = None) -> str:
    """Return the tmux executable's version string, preserving letter suffixes.

    .. deprecated:: 0.63.0
        Reads the client executable. Use
        ``libtmux._internal.support.server_version(server)``.

    Parameters
    ----------
    tmux_bin : str, optional
        Path to tmux binary. If *None*, uses the system tmux.

    Returns
    -------
    str
        Raw tmux version, e.g. ``"3.7a"``. Git builds return ``"master"``;
        OpenBSD base tmux returns ``"<max>-openbsd"``.

    Notes
    -----
    Memoized per *tmux_bin*, independently of :func:`get_version`. Call
    ``get_version_str.cache_clear()`` after swapping the tmux binary.
    """
    warnings.warn(
        _deprecation("get_version_str", "server_version(server)"),
        DeprecationWarning,
        stacklevel=2,
    )
    return _get_version_str(tmux_bin)


@_clears(_get_version)
def get_version(tmux_bin: str | None = None) -> LooseVersion:
    """Return the tmux executable's version.

    .. deprecated:: 0.63.0
        Reads the client executable. Use
        ``libtmux._internal.support.server_version(server)``.

    If tmux is built from git master, the version returned will be the latest
    version appended with -master, e.g. ``2.4-master``.

    If using OpenBSD's base system tmux, the version will have ``-openbsd``
    appended to the latest version, e.g. ``2.4-openbsd``.

    Parameters
    ----------
    tmux_bin : str, optional
        Path to tmux binary. If *None*, uses the system tmux from
        :func:`shutil.which`.

    Returns
    -------
    :class:`distutils.version.LooseVersion`
        tmux version according to *tmux_bin* if provided, otherwise the
        system tmux from :func:`shutil.which`

    Notes
    -----
    Memoized per *tmux_bin* (``None`` is a distinct key), independently of
    :func:`get_version_str`. The cache is sticky across ``PATH`` changes and
    on-disk binary swaps; call ``get_version.cache_clear()`` to invalidate.
    """
    warnings.warn(
        _deprecation("get_version", "server_version(server)"),
        DeprecationWarning,
        stacklevel=2,
    )
    return _get_version(tmux_bin)


def has_version(version: str, tmux_bin: str | None = None) -> bool:
    """Return True if the tmux executable is exactly *version*.

    .. deprecated:: 0.63.0
        Reads the client executable, not the daemon.

    Parameters
    ----------
    version : str
        version number, e.g. '3.2a'
    tmux_bin : str, optional
        Path to tmux binary. If *None*, uses the system tmux.

    Returns
    -------
    bool
        True if version matches
    """
    warnings.warn(
        _deprecation("has_version", _COMPARE_HINT),
        DeprecationWarning,
        stacklevel=2,
    )
    return _get_version(tmux_bin) == LooseVersion(version)


def has_gt_version(min_version: str, tmux_bin: str | None = None) -> bool:
    """Return True if the tmux executable is newer than *min_version*.

    .. deprecated:: 0.63.0
        Reads the client executable, not the daemon.

    Parameters
    ----------
    min_version : str
        tmux version, e.g. '3.2a'
    tmux_bin : str, optional
        Path to tmux binary. If *None*, uses the system tmux.

    Returns
    -------
    bool
        True if version above min_version
    """
    warnings.warn(
        _deprecation("has_gt_version", _COMPARE_HINT),
        DeprecationWarning,
        stacklevel=2,
    )
    return _get_version(tmux_bin) > LooseVersion(min_version)


def has_gte_version(min_version: str, tmux_bin: str | None = None) -> bool:
    """Return True if the tmux executable is at least *min_version*.

    .. deprecated:: 0.63.0
        Reads the client executable. Use
        ``is_at_least(server_version(server), min_version)`` from
        ``libtmux._internal.support``.

    Parameters
    ----------
    min_version : str
        tmux version, e.g. '3.2a'
    tmux_bin : str, optional
        Path to tmux binary. If *None*, uses the system tmux.

    Returns
    -------
    bool
        True if version above or equal to min_version
    """
    warnings.warn(
        _deprecation("has_gte_version", _COMPARE_HINT),
        DeprecationWarning,
        stacklevel=2,
    )
    return _get_version(tmux_bin) >= LooseVersion(min_version)


def has_lte_version(max_version: str, tmux_bin: str | None = None) -> bool:
    """Return True if the tmux executable is at most *max_version*.

    .. deprecated:: 0.63.0
        Reads the client executable, not the daemon.

    Parameters
    ----------
    max_version : str
        tmux version, e.g. '3.2a'
    tmux_bin : str, optional
        Path to tmux binary. If *None*, uses the system tmux.

    Returns
    -------
    bool
         True if version below or equal to max_version
    """
    warnings.warn(
        _deprecation("has_lte_version", _COMPARE_HINT),
        DeprecationWarning,
        stacklevel=2,
    )
    return _get_version(tmux_bin) <= LooseVersion(max_version)


def has_lt_version(max_version: str, tmux_bin: str | None = None) -> bool:
    """Return True if the tmux executable is older than *max_version*.

    .. deprecated:: 0.63.0
        Reads the client executable, not the daemon. Use
        ``not is_at_least(server_version(server), max_version)`` from
        ``libtmux._internal.support``.

    Parameters
    ----------
    max_version : str
        tmux version, e.g. '3.2a'
    tmux_bin : str, optional
        Path to tmux binary. If *None*, uses the system tmux.

    Returns
    -------
    bool
        True if version below max_version
    """
    warnings.warn(
        _deprecation("has_lt_version", f"not {_COMPARE_HINT}"),
        DeprecationWarning,
        stacklevel=2,
    )
    return _get_version(tmux_bin) < LooseVersion(max_version)


def has_minimum_version(raises: bool = True, tmux_bin: str | None = None) -> bool:
    """Return True if the executable meets the complete release minimum.

    .. deprecated:: 0.63.0
        Reads the client executable. Commands check their connected daemon's
        version on their own; use
        ``require_version(server_version(server))`` from
        ``libtmux._internal.support`` to check one explicitly.

    This helper preserves patch letters and does not use the legacy
    normalized version cache.

    Parameters
    ----------
    raises : bool
        raise exception if below minimum version requirement
    tmux_bin : str, optional
        Path to tmux binary. If *None*, uses the system tmux.

    Returns
    -------
    bool
        True if tmux meets minimum required version.

    Raises
    ------
    libtmux.exc.VersionTooLow
        tmux version below minimum required for libtmux

    Notes
    -----
    .. versionchanged:: 0.49.0
        Minimum version bumped to 3.2a. For older tmux, use libtmux v0.48.x.

    .. versionchanged:: 0.7.0
        No longer returns version, returns True or False

    .. versionchanged:: 0.1.7
        Versions will now remove trailing letters per
        `Issue 55 <https://github.com/tmux-python/tmuxp/issues/55>`_.
    """
    warnings.warn(
        _deprecation("has_minimum_version", "require_version(server_version(server))"),
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        version = _query_version(tmux_bin=tmux_bin)
        versions.require_version(version, minimum=TMUX_MIN_VERSION)
    except (exc.VersionTooLow, _TmuxVersionUnavailable):
        if raises:
            msg = f"libtmux only supports tmux {TMUX_MIN_VERSION} and greater"
            raise exc.VersionTooLow(msg) from None
        return False
    return True
