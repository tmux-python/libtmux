"""Declarative workspace specs -- the structural object language.

The *Declarative* tier (à la SQLAlchemy Declarative on Core): the user declares
the **shape** of a workspace as a tree of :class:`Workspace` / :class:`Window` /
:class:`Pane` values, and the compiler lowers that tree into a Core
:class:`~libtmux.experimental.ops.plan.LazyPlan`. The specs are pure, immutable
data -- no tmux, no engine -- so they round-trip to/from YAML and can be inspected
before anything runs.

Examples
--------
>>> from libtmux.experimental.engines import ConcreteEngine
>>> from libtmux.experimental.workspace.ir import Workspace, Window, Pane
>>> ws = Workspace(
...     name="dev",
...     windows=[
...         Window("editor", layout="main-vertical", panes=[
...             Pane(run="vim"),
...             Pane(run="pytest -q", focus=True),
...         ]),
...         Window("logs", panes=[Pane(run="tail -f app.log")]),
...     ],
... )
>>> ws.compile().operations[0].kind
'new_session'
>>> ws.build(ConcreteEngine(), preflight=False).ok
True
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field

if t.TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from libtmux.experimental.engines.base import AsyncTmuxEngine, TmuxEngine
    from libtmux.experimental.ops.plan import LazyPlan, PlanResult


@dataclass(frozen=True)
class Pane:
    """A pane in the declared workspace.

    Parameters
    ----------
    run : str or Sequence[str] or None
        Command(s) to send after the pane is created (a bare string is one
        command).
    focus : bool
        Select this pane once its window's panes are built. Focusing the *first*
        pane of a multi-pane window is rejected at compile time (the implicit
        first pane has no captured id after the window is split).
    start_directory : str or None
        Working directory (inherited from window/session when unset).
    suppress_history : bool
        Keep sent commands out of shell history (leading-space trick).
    sleep_before, sleep_after : float or None
        Host-side delays around this pane's commands (orchestration, not tmux).
    """

    run: str | Sequence[str] | None = None
    focus: bool = False
    start_directory: str | None = None
    suppress_history: bool = True
    sleep_before: float | None = None
    sleep_after: float | None = None

    @property
    def commands(self) -> tuple[str, ...]:
        """The pane's commands as a tuple (a bare string becomes one command)."""
        if self.run is None:
            return ()
        if isinstance(self.run, str):
            return (self.run,)
        return tuple(self.run)


@dataclass(frozen=True)
class Window:
    """A window in the declared workspace.

    Parameters
    ----------
    name : str or None
        Window name.
    layout : str or None
        A tmux layout applied after the panes exist (e.g. ``main-vertical``).
    start_directory : str or None
        Working directory for the window's panes.
    focus : bool
        Select this window at the end of the build.
    options : Mapping[str, str]
        ``set-window-option`` key/values.
    panes : Sequence[Pane]
        The window's panes (the first reuses the window's implicit pane).
    """

    name: str | None = None
    layout: str | None = None
    start_directory: str | None = None
    focus: bool = False
    options: Mapping[str, str] = field(default_factory=dict)
    panes: Sequence[Pane] = ()


@dataclass(frozen=True)
class Workspace:
    """A declared workspace: a session shape that compiles to Core operations.

    Parameters
    ----------
    name : str
        Session name.
    dimensions : tuple[int, int] or None
        ``(width, height)`` for the session (``-x``/``-y``).
    start_directory : str or None
        Working directory for the session.
    environment : Mapping[str, str]
        ``set-environment`` key/values.
    options : Mapping[str, str]
        ``set-option`` (session) key/values.
    windows : Sequence[Window]
        The session's windows.
    before_script : str or None
        A host shell command run once before building (orchestration).
    on_exists : {"error", "replace", "reuse"}
        What to do if a session of this name already exists.
    """

    name: str
    dimensions: tuple[int, int] | None = None
    start_directory: str | None = None
    environment: Mapping[str, str] = field(default_factory=dict)
    options: Mapping[str, str] = field(default_factory=dict)
    windows: Sequence[Window] = ()
    before_script: str | None = None
    on_exists: t.Literal["error", "replace", "reuse"] = "error"

    def compile(self, *, version: str | None = None) -> LazyPlan:
        """Lower this declared workspace into a Core ``LazyPlan`` (ops only).

        The returned plan is the escape hatch to the Core tier: inspect it,
        serialize it, or execute it directly with any engine. Host steps
        (sleep/before_script) and idempotent replace are applied by
        :meth:`build`/:meth:`abuild`, not recorded in the plan.
        """
        from libtmux.experimental.workspace.compiler import compile_workspace

        return compile_workspace(self, version=version)

    def build(
        self,
        engine: TmuxEngine,
        *,
        version: str | None = None,
        preflight: bool = True,
    ) -> PlanResult:
        """Compile and execute this workspace synchronously over *engine*.

        Set ``preflight=False`` to skip the ``on_exists`` ``has-session`` check
        (e.g. against the stateless ``ConcreteEngine``, which has no real
        sessions to detect).
        """
        from libtmux.experimental.workspace.runner import build_workspace

        return build_workspace(self, engine, version=version, preflight=preflight)

    async def abuild(
        self,
        engine: AsyncTmuxEngine,
        *,
        version: str | None = None,
        preflight: bool = True,
    ) -> PlanResult:
        """Compile and execute this workspace asynchronously over *engine*."""
        from libtmux.experimental.workspace.runner import abuild_workspace

        return await abuild_workspace(
            self,
            engine,
            version=version,
            preflight=preflight,
        )
