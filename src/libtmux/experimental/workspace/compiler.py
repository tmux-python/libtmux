"""Compile a declarative :class:`~.ir.Workspace` into a Core ``LazyPlan``.

This is the *unit-of-work* of the Declarative tier: it walks the structural spec
tree and emits Core operations in tmuxp-faithful order (create session -> per
window: create/rename, window options, reuse the first pane, split the rest, send
keys, apply layout, focus panes; then focus the window last), wiring
:class:`~libtmux.experimental.ops._types.SlotRef` forward references so the caller
never handles a tmux id.

Implicit-object strategy: creators opt into capturing their implicit children's
ids (``NewSession(capture_panes=True)`` -> session/first-window/first-pane;
``NewWindow(capture_pane=True)`` -> window/first-pane), so every window's first
pane has a real captured id reachable as ``slot.pane`` / ``session.pane``. The
session's first window is reused as window 1 (addressed via ``session.window`` /
``session.pane``); windows 2..N are created detached. Because the first pane has a
concrete id, first-pane focus and any-order sends work, and the
``compile() -> LazyPlan`` stays executable by Core (the sub-ids bind in
``_drive``).

Host-side steps (sleep / before_script) are returned alongside the plan in a
:class:`Compiled` schedule -- they are *not* recorded as operations, keeping the
Core op spine pure.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field, replace

from libtmux.experimental.ops import (
    LazyPlan,
    NewPane,
    NewSession,
    NewWindow,
    RenameWindow,
    SelectLayout,
    SelectPane,
    SelectWindow,
    SendKeys,
    SetEnvironment,
    SetOption,
    SetWindowOption,
    SplitWindow,
)
from libtmux.experimental.workspace.ir import Pane

if t.TYPE_CHECKING:
    from collections.abc import Mapping

    from libtmux.experimental.ops._types import SlotRef
    from libtmux.experimental.workspace.ir import Window, Workspace


class WorkspaceCompileError(ValueError):
    """A declared workspace cannot be lowered to Core operations."""


@dataclass(frozen=True)
class HostStep:
    """A host-side step interleaved by the runner (not a tmux operation).

    ``"sleep"`` waits *seconds*; ``"script"`` runs *command* in *cwd*;
    ``"wait_pane"`` polls *pane* (a :class:`~..ops._types.SlotRef`) until its
    shell is ready (the runner resolves the ref and queries the live cursor).
    """

    kind: t.Literal["sleep", "script", "wait_pane"]
    seconds: float | None = None
    command: str | None = None
    cwd: str | None = None
    pane: SlotRef | None = None


@dataclass(frozen=True)
class Compiled:
    """A compiled workspace: the Core plan plus its host-step schedule.

    Parameters
    ----------
    plan : LazyPlan
        The pure Core operations (executable by any engine via ``execute``).
    host_after : Mapping[int, tuple[HostStep, ...]]
        Host steps to run *after* the operation at the given index.
    pre : tuple[HostStep, ...]
        Host steps to run before any operation (e.g. ``before_script``).
    """

    plan: LazyPlan
    host_after: Mapping[int, tuple[HostStep, ...]] = field(default_factory=dict)
    pre: tuple[HostStep, ...] = ()


def compile_workspace(ws: Workspace, *, version: str | None = None) -> LazyPlan:
    """Lower a declarative workspace into a Core ``LazyPlan`` (ops only).

    Examples
    --------
    >>> from libtmux.experimental.workspace.ir import Workspace, Window, Pane
    >>> ws = Workspace(name="dev", windows=[Window("editor", panes=[Pane(run="vim")])])
    >>> [op.kind for op in compile_workspace(ws).operations]
    ['new_session', 'rename_window', 'send_keys']
    """
    return compile_full(ws, version=version).plan


def _schedule_before(
    host_after: dict[int, list[HostStep]],
    pre: list[HostStep],
    next_index: int,
    step: HostStep,
) -> None:
    """Schedule *step* to run just before the op that will land at *next_index*."""
    after = next_index - 1
    if after < 0:
        pre.append(step)
    else:
        host_after.setdefault(after, []).append(step)


def _emit_pane_commands(
    plan: LazyPlan,
    host_after: dict[int, list[HostStep]],
    pre: list[HostStep],
    ws: Workspace,
    window: Window,
    pane: Pane,
    target: SlotRef,
) -> None:
    """Emit a pane's command sends with their host-side sleep / wait scheduling.

    Shared by tiled panes and floating-pane overlays so both honor ``wait_pane``,
    ``suppress_history``, and the per-pane / per-command sleeps identically.
    """
    commands = pane.commands
    if not commands:
        return
    if ws.wait_pane and (pane.shell or window.window_shell) is None:
        # Wait for the pane's shell prompt before sending keys (anti-race); a pane
        # launching a custom shell/command does not get this wait, mirroring
        # tmuxp's `if pane_shell is None`.
        _schedule_before(host_after, pre, len(plan), HostStep("wait_pane", pane=target))
    if pane.sleep_before is not None:
        _schedule_before(
            host_after,
            pre,
            len(plan),
            HostStep("sleep", seconds=pane.sleep_before),
        )
    for command in commands:
        if command.sleep_before is not None:
            _schedule_before(
                host_after,
                pre,
                len(plan),
                HostStep("sleep", seconds=command.sleep_before),
            )
        plan.add(
            SendKeys(
                target=target,
                keys=command.cmd,
                enter=command.enter,
                suppress_history=pane.suppress_history,
            ),
        )
        if command.sleep_after is not None:
            host_after.setdefault(len(plan) - 1, []).append(
                HostStep("sleep", seconds=command.sleep_after),
            )
    if pane.sleep_after is not None:
        host_after.setdefault(len(plan) - 1, []).append(
            HostStep("sleep", seconds=pane.sleep_after),
        )


def _emit_floats(
    plan: LazyPlan,
    host_after: dict[int, list[HostStep]],
    pre: list[HostStep],
    ws: Workspace,
    window: Window,
    first_pane_ref: SlotRef,
) -> None:
    """Emit the window's floating-pane overlays (tmux 3.7 ``new-pane``).

    Overlays are created *after* the tiled panes and layout, target the window's
    first pane, and are deliberately kept out of the split chain and the layout so
    they never perturb the tiled topology. Cross-window ``attach_to`` (floating
    over a *different* window) is not yet supported.
    """
    for fp in window.floats:
        if fp.attach_to is not None and fp.attach_to != window.name:
            msg = (
                f"floating pane attach_to={fp.attach_to!r} targets another window; "
                "cross-window floats are not yet supported"
            )
            raise WorkspaceCompileError(msg)
        geo = fp.geometry
        float_ref = plan.add(
            NewPane(
                target=first_pane_ref,
                width=geo.width,
                height=geo.height,
                x=geo.x,
                y=geo.y,
                zoom=geo.zoom,
                empty=geo.empty,
                style=geo.style,
                active_border_style=geo.active_border_style,
                inactive_border_style=geo.inactive_border_style,
                message=geo.message,
                start_directory=(
                    fp.pane.start_directory
                    or window.start_directory
                    or ws.start_directory
                ),
                environment=dict(fp.pane.environment) or None,
                shell_command=fp.pane.shell,
            ),
        )
        _emit_pane_commands(plan, host_after, pre, ws, window, fp.pane, float_ref)
        if fp.pane.focus:
            plan.add(SelectPane(target=float_ref))


def _emit_window(
    plan: LazyPlan,
    host_after: dict[int, list[HostStep]],
    pre: list[HostStep],
    ws: Workspace,
    window: Window,
    window_ref: SlotRef,
    first_pane_ref: SlotRef,
) -> None:
    """Emit a window's options, panes, sends, layout, pane focus, and floats.

    *window_ref* addresses the window (rename/options/layout); *first_pane_ref* is
    the captured id of the window's first pane.
    """
    for key, value in window.options.items():
        plan.add(SetWindowOption(target=window_ref, option=key, value=value))

    panes = list(window.panes) or [Pane()]
    prev: SlotRef = first_pane_ref
    focus_targets: list[SlotRef] = []
    for pane_index, pane in enumerate(panes):
        if pane_index == 0:
            target: SlotRef = first_pane_ref
        else:
            target = plan.add(
                SplitWindow(
                    target=prev,
                    start_directory=(
                        pane.start_directory
                        or window.start_directory
                        or ws.start_directory
                    ),
                    environment=(
                        dict(pane.environment) or dict(window.environment) or None
                    ),
                    shell=pane.shell or window.window_shell,
                ),
            )
        _emit_pane_commands(plan, host_after, pre, ws, window, pane, target)
        if pane.focus:
            focus_targets.append(target)
        prev = target

    if window.layout is not None:
        plan.add(SelectLayout(target=window_ref, layout=window.layout))
    for target in focus_targets:
        plan.add(SelectPane(target=target))
    for key, value in window.options_after.items():
        plan.add(SetWindowOption(target=window_ref, option=key, value=value))

    # Floating overlays come last: after the tiled layout, excluded from it.
    _emit_floats(plan, host_after, pre, ws, window, first_pane_ref)


def _creator_environment(window: Window) -> dict[str, str]:
    """Env for a window's *first* (implicit) pane, applied via its creator's ``-e``.

    The first pane reuses the window's implicit pane rather than splitting, so its
    process environment cannot ride a ``split-window -e``. Instead the window's
    ``environment`` (and its first pane's own ``environment``) fold into the
    creator -- ``new-session -e`` for window 0, ``new-window -e`` for the rest --
    applying it without an extra dispatch.
    """
    env = dict(window.environment)
    if window.panes:
        env.update(window.panes[0].environment)
    return env


def _creator_start_directory(window: Window, ws: Workspace) -> str | None:
    """Working directory for a window's *first* (implicit) pane.

    The first pane is created by the window's creator (``new-session`` for
    window 0, ``new-window`` for the rest), not a split, so its directory must
    ride the creator's ``-c`` with the full pane -> window -> session precedence.
    Without this, window 0's first pane would inherit the *session*
    ``start_directory`` instead of the window's.
    """
    if window.panes and window.panes[0].start_directory:
        return window.panes[0].start_directory
    return window.start_directory or ws.start_directory


def compile_full(ws: Workspace, *, version: str | None = None) -> Compiled:
    """Lower a workspace into a Core plan plus its host-step schedule."""
    if not ws.windows:
        msg = f"workspace {ws.name!r} declares no windows"
        raise WorkspaceCompileError(msg)

    plan = LazyPlan()
    host_after: dict[int, list[HostStep]] = {}
    pre: list[HostStep] = []
    if ws.before_script:
        pre.append(HostStep("script", command=ws.before_script, cwd=ws.start_directory))

    width = ws.dimensions[0] if ws.dimensions else None
    height = ws.dimensions[1] if ws.dimensions else None
    session = plan.add(
        NewSession(
            session_name=ws.name,
            start_directory=_creator_start_directory(ws.windows[0], ws),
            width=width,
            height=height,
            environment=_creator_environment(ws.windows[0]) or None,
            capture_panes=True,
        ),
    )
    for key, value in ws.environment.items():
        plan.add(SetEnvironment(target=session, name=key, value=value))
    for key, value in ws.options.items():
        plan.add(SetOption(target=session, option=key, value=value))
    for key, value in ws.global_options.items():
        plan.add(SetOption(option=key, value=value, global_=True))

    window_refs: list[SlotRef] = []
    for index, window in enumerate(ws.windows):
        if index == 0:
            # Reuse the session's implicit first window via its captured ids.
            window_ref: SlotRef = session.window
            first_pane_ref = session.pane
            if window.name is not None:
                plan.add(RenameWindow(target=window_ref, name=window.name))
        else:
            # An explicit window_index targets new-window at `session:N`; the
            # SlotRef suffix appends ":N" to the captured session id at run time.
            create_target = (
                replace(session, suffix=f":{window.window_index}")
                if window.window_index is not None
                else session
            )
            slot = plan.add(
                NewWindow(
                    target=create_target,
                    name=window.name,
                    start_directory=_creator_start_directory(window, ws),
                    environment=_creator_environment(window) or None,
                    window_shell=window.window_shell,
                    capture_pane=True,
                ),
            )
            window_ref = slot
            first_pane_ref = slot.pane
        window_refs.append(window_ref)
        _emit_window(plan, host_after, pre, ws, window, window_ref, first_pane_ref)

    for index, window in enumerate(ws.windows):
        if window.focus:
            plan.add(SelectWindow(target=window_refs[index]))

    return Compiled(
        plan,
        {key: tuple(value) for key, value in host_after.items()},
        tuple(pre),
    )
