"""Gate tests on the tmux client executable's release.

These read the executable the suite launches (``LIBTMUX_TMUX`` or ``PATH``),
with letter suffixes stripped, which is what the daemons the fixtures start
run. libtmux itself checks the connected daemon through
:mod:`libtmux._internal.support`; the deprecated ``libtmux.common`` helpers
are only exercised under ``tests/legacy_api``.
"""

from __future__ import annotations

from libtmux._compat import LooseVersion
from libtmux._internal import version as _legacy


def client_gte(minimum: str) -> bool:
    """Return True if the client executable is at least *minimum*."""
    return _legacy._get_version() >= LooseVersion(minimum)


def client_lte(maximum: str) -> bool:
    """Return True if the client executable is at most *maximum*."""
    return _legacy._get_version() <= LooseVersion(maximum)


def clear_caches() -> None:
    """Forget the executable's cached release, for tests that fake ``tmux -V``."""
    _legacy._get_version.cache_clear()
    _legacy._get_version_str.cache_clear()
