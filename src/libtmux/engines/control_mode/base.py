"""Stub for the persistent ``tmux -CC`` control-mode engine."""

from __future__ import annotations

import logging
import pathlib

from libtmux.engines.base import CommandRequest, CommandResult
from libtmux.engines.registry import register_engine

logger = logging.getLogger(__name__)


class ControlModeEngine:
    """Persistent ``tmux -CC`` engine — registration stub.

    Instantiation succeeds so the engine appears in
    :func:`libtmux.engines.available_engines` and can be selected via
    ``LIBTMUX_ENGINE=control_mode`` or ``Server(engine="control_mode")``.
    Calling :meth:`run` raises :class:`NotImplementedError` until the
    parser, reader thread, and lifecycle wiring land.
    """

    def __init__(self, tmux_bin: str | pathlib.Path | None = None) -> None:
        self.tmux_bin = str(tmux_bin) if tmux_bin is not None else None

    def run(self, request: CommandRequest) -> CommandResult:
        """Execute a tmux command via the persistent control-mode client."""
        msg = (
            "ControlModeEngine.run is not implemented yet; "
            "the persistent tmux -CC backend is under development."
        )
        raise NotImplementedError(msg)


register_engine("control_mode", ControlModeEngine)
