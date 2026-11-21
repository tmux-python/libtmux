"""The connection an engine talks to, re-exported from Core.

:class:`~libtmux._internal.connection.ServerConnection` lives in Core's engine
seam so experimental engines and Core's object API share one binary resolution,
one set of ``-L``/``-S``/``-f``/``-2``/``-8`` flags, and one ``tmux -V`` probe.
"""

from __future__ import annotations

from libtmux._internal.connection import ServerConnection

__all__ = ("ServerConnection",)
