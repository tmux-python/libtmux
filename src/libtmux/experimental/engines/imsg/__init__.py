"""Experimental native imsg engine -- an opt-in easter egg.

Speaks tmux's binary peer protocol (imsg over the server's ``AF_UNIX`` socket)
directly, with no tmux CLI fork per command. It is the strongest proof that the
operation/result contract is transport-agnostic: it returns the *same*
:class:`~..base.CommandResult` as the subprocess and control-mode engines.

Caveats (why it is opt-in and not the default): it depends on tmux's *internal*
protocol (``PROTOCOL_VERSION`` 8 only; upstream may bump it), it is POSIX-only
(``AF_UNIX`` + ``SCM_RIGHTS`` fd-passing), and it cannot host ``attach-session``
(which falls back to a local spawn). Importing this triggers registration under
the ``imsg`` engine name.
"""

from __future__ import annotations

from libtmux.experimental.engines.imsg.base import ImsgEngine
from libtmux.experimental.engines.imsg.exc import (
    ImsgError,
    ImsgProtocolError,
    UnsupportedProtocolVersion,
)

__all__ = (
    "ImsgEngine",
    "ImsgError",
    "ImsgProtocolError",
    "UnsupportedProtocolVersion",
)
