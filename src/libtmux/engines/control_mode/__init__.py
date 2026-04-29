"""Persistent ``tmux -CC`` control-mode engine for libtmux.

The control-mode engine reuses one long-lived ``tmux`` child for every
command, eliminating the per-call ``fork``/``exec``/socket-handshake cost
that dominates the subprocess and one-shot imsg paths.

This module currently exposes a *registration stub*: the engine is known
to :func:`libtmux.engines.create_engine` and ``LIBTMUX_ENGINE=control_mode``
resolves to it, but :meth:`ControlModeEngine.run` raises
:class:`NotImplementedError` until the parser, reader thread, and
subscription wiring land in subsequent steps.
"""

from __future__ import annotations

from libtmux.engines.control_mode.base import ControlModeEngine

__all__ = ("ControlModeEngine",)
