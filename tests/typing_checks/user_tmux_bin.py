"""How adopter code passes ``tmux_bin`` under ``mypy --strict``."""

from __future__ import annotations

import os
import pathlib

from libtmux import Server


def tmux_bin_takes_a_path(
    path: pathlib.Path, text: str, env_path: os.PathLike[str]
) -> None:
    """Pass the tmux binary as ``str`` or any path-like."""
    Server(tmux_bin=text)
    Server(tmux_bin=path)
    Server(tmux_bin=env_path)
    Server(tmux_bin=None)
    with Server.owned(tmux_bin=path):
        pass


def tmux_bin_is_not_a_command_line() -> None:
    """Reject an argv list that the old annotation also rejected."""
    Server(tmux_bin=["docker", "exec", "c", "tmux"])  # type: ignore[arg-type]
