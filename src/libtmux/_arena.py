"""Contract values for the opt-in arena doctest adapter."""

from __future__ import annotations

import dataclasses
import pathlib
import typing as t

ARENA_ARTIFACT_TARGETS = {
    "python-exact-binary": ("docs/topics/workspace_setup.md",),
    "python-workspace-setup": ("docs/topics/workspace_setup.md",),
    # The first artifact to actually exercise several sources against one
    # lent server. Both pages only ever touch the `server`/`session` the
    # arena fixture hands them -- neither constructs its own `Server()`, so
    # neither can reach the lent daemon's own kill-server (see
    # ARENA_EXCLUDED_SOURCES below for the page that does).
    "python-workspace-and-location": (
        "docs/topics/workspace_setup.md",
        "docs/topics/self_location.md",
    ),
}

# A source that must never run under the arena: its examples stop the lent
# server rather than a private one. Named here so the refusal is a specific,
# visible reason rather than an absence from ARENA_ARTIFACT_TARGETS -- the
# two would otherwise look identical from the outside (a source rejected for
# not matching the requested artifact's tuple looks like a typo, not a
# safety rule).
ARENA_EXCLUDED_SOURCES: dict[str, str] = {
    "docs/topics/context_managers.md": (
        "every example opens `with Server()`; in arena mode the doctest "
        "namespace's `Server` name is bound to a factory pinned to the "
        "lent socket path, so leaving the block runs Server.__exit__ -> "
        "Server.kill() -> `kill-server` against the borrowed daemon "
        "itself, not a private one"
    ),
}


def _assert_no_excluded_targets(
    artifact_targets: t.Mapping[str, tuple[str, ...]],
) -> None:
    """Refuse at import time if any artifact ever names an excluded source.

    A mapping edit that adds an excluded page back in would otherwise only
    surface the first time someone ran that artifact against a real lent
    server -- by which point it may already have stopped it.
    """
    conflicts = {
        artifact: sorted(overlap)
        for artifact, sources in artifact_targets.items()
        if (overlap := frozenset(sources) & ARENA_EXCLUDED_SOURCES.keys())
    }
    if conflicts:
        msg = f"artifact(s) name an excluded arena source: {conflicts!r}"
        raise AssertionError(msg)


_assert_no_excluded_targets(ARENA_ARTIFACT_TARGETS)


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

    def targets_for(self, root: pathlib.Path) -> tuple[pathlib.Path, ...]:
        """Resolve every source bound to this artifact inside ``root``."""
        return tuple(root / rel for rel in ARENA_ARTIFACT_TARGETS[self.artifact])
