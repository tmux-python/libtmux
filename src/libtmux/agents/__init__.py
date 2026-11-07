"""Top-level agent console entry point for ``python -m libtmux.agents``.

The public import is intentionally small: this package exposes the command-line
entry point while the underlying monitor and synchronization primitives remain
in :mod:`libtmux.experimental.agents`.

Examples
--------
>>> callable(main)
True
"""

from __future__ import annotations

from libtmux.agents.cli import main

__all__ = ("main",)
