"""Confirm a built workspace matches its declarative spec (live introspection).

Reads the live server through the classic libtmux objects and diffs the observed
session/window/pane structure against the declared :class:`~.ir.Workspace`. Used by
the live test track; the offline (``ConcreteEngine``) track asserts on the
compiled plan instead, since a stateless engine has no structure to read back.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    from libtmux.experimental.workspace.ir import Workspace
    from libtmux.server import Server


@dataclass
class ConfirmReport:
    """The outcome of confirming a built workspace against its spec."""

    ok: bool
    problems: tuple[str, ...]


def confirm(ws: Workspace, server: Server, *, timeout: float = 5.0) -> ConfirmReport:
    """Diff the live server against the declared workspace; report mismatches."""
    problems: list[str] = []
    sessions = server.sessions.filter(session_name=ws.name)
    if not sessions:
        return ConfirmReport(ok=False, problems=(f"session {ws.name!r} not found",))
    session = sessions[0]

    windows = list(session.windows)
    if len(windows) != len(ws.windows):
        problems.append(f"window count {len(windows)} != declared {len(ws.windows)}")

    for spec, live in zip(ws.windows, windows, strict=False):
        if spec.name is not None and live.window_name != spec.name:
            problems.append(
                f"window name {live.window_name!r} != declared {spec.name!r}"
            )
        live_panes = list(live.panes)
        expected_panes = max(1, len(spec.panes))
        if len(live_panes) != expected_panes:
            problems.append(
                f"window {spec.name!r} pane count "
                f"{len(live_panes)} != declared {expected_panes}",
            )
        focused_panes = [i for i, p in enumerate(spec.panes) if p.focus]
        if focused_panes and focused_panes[-1] < len(live_panes):
            want_idx = focused_panes[-1]
            active_pane = live.active_pane
            if active_pane is None or (
                active_pane.pane_id != live_panes[want_idx].pane_id
            ):
                problems.append(
                    f"window {spec.name!r} active pane != declared focus "
                    f"(pane index {want_idx})",
                )

    focused = [w for w in ws.windows if w.focus]
    if focused and focused[-1].name is not None:
        want = focused[-1].name
        active_name = session.active_window.window_name
        if active_name != want:
            problems.append(
                f"active window {active_name!r} != declared focus {want!r}",
            )

    if ws.start_directory and windows:
        want_cwd = ws.start_directory
        session_id = session.session_id

        def _cwd_ok() -> bool:
            fresh = server.sessions.filter(session_id=session_id)
            if not fresh:
                return False
            pane = next(iter(fresh[0].windows)).active_pane
            return pane is not None and pane.pane_current_path == want_cwd

        if not retry_until(_cwd_ok, timeout, raises=False):
            problems.append(f"first pane cwd != declared {want_cwd!r}")

    return ConfirmReport(ok=not problems, problems=tuple(problems))
