"""The connection an engine talks to, re-exported from Core.

:class:`~libtmux.engines.connection.ServerConnection` graduated to Core as part
of the command execution seam, so the experimental engines dispatch over the
same connection value the object API does: one tmux binary resolution, one set
of ``-L``/``-S``/``-f``/``-2`` flags, one ``tmux -V`` probe.

This module is the import path the experimental engines have always used; it
carries no definition of its own.
"""

from __future__ import annotations

from libtmux.engines.connection import ServerConnection

__all__ = ("ServerConnection",)
