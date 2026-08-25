"""Contract values for the opt-in arena doctest adapter."""

from __future__ import annotations

import dataclasses
import pathlib
import typing as t

ARENA_ARTIFACT_TARGETS = {
    "python-exact-binary": "docs/topics/workspace_setup.md",
    "python-workspace-setup": "docs/topics/workspace_setup.md",
}


@dataclasses.dataclass(frozen=True)
class ArenaSpec:
    """Describe one explicitly selected external tmux endpoint."""

    artifact: str
    socket_path: str
    tmux_bin: str

    @classmethod
    def from_environ(cls, environ: t.Mapping[str, str]) -> ArenaSpec | None:
        """Return an active specification only for a complete descriptor contract."""
        if not environ.get("LIBTMUX_ARENA_DESCRIPTOR"):
            return None

        artifact = environ.get("LIBTMUX_ARENA_ARTIFACT")
        socket_path = environ.get("LIBTMUX_SOCKET_PATH")
        tmux_bin = environ.get("LIBTMUX_TMUX_BIN")
        if not artifact or not socket_path or not tmux_bin:
            msg = "arena descriptor, artifact, socket, and tmux executable are required"
            raise ValueError(msg)
        if artifact not in ARENA_ARTIFACT_TARGETS:
            msg = f"arena artifact {artifact!r} has no audited source mapping"
            raise ValueError(msg)
        return cls(artifact=artifact, socket_path=socket_path, tmux_bin=tmux_bin)

    def target_for(self, root: pathlib.Path) -> pathlib.Path:
        """Resolve the source bound to this artifact inside ``root``."""
        return root / ARENA_ARTIFACT_TARGETS[self.artifact]
