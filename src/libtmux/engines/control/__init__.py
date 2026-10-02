"""Control-mode machinery for tmux engines.

:mod:`libtmux.engines.control.protocol` is the I/O-free core: a parser for what
``tmux -C`` writes and an encoder for what it reads. Drivers that own a pipe
build on it.
"""

from __future__ import annotations
