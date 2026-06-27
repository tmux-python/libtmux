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
class Command:
    """One command sent to a pane, with per-command orchestration.

    Parameters
    ----------
    cmd : str
        The command line sent via ``send-keys``.
    enter : bool
        Submit the command with ``Enter`` (``False`` types it without running --
        e.g. to pre-fill a prompt).
    sleep_before, sleep_after : float or None
        Host-side delays around this individual command (orchestration, not tmux).

    Examples
    --------
    >>> Command("pytest -q").enter
    True
    >>> Command("git commit", enter=False).cmd
    'git commit'
    """

    cmd: str
    enter: bool = True
    sleep_before: float | None = None
    sleep_after: float | None = None


@dataclass(frozen=True)
class Pane:
    """A pane in the declared workspace.

    Parameters
    ----------
    run : str or Command or Sequence[str or Command] or None
        Command(s) to send after the pane is created. A bare string is one
        command (submitted with Enter); a :class:`Command` carries per-command
        ``enter`` and sleep overrides.
    focus : bool
        Select this pane once its window's panes are built. Every pane -- the
        first one included -- has a concrete captured id (the window's creator
        captures its first pane), so focusing any pane is valid.
    start_directory : str or None
        Working directory (inherited from window/session when unset).
    suppress_history : bool
        Keep sent commands out of shell history (leading-space trick).
    sleep_before, sleep_after : float or None
        Host-side delays around this pane's commands (orchestration, not tmux).
    environment : Mapping[str, str]
        Process environment for a *split* pane (``split-window -e``). For the
        window's first pane -- which reuses the window's implicit pane rather than
        splitting -- this env is folded into the window's creator instead, so it
        applies without an extra dispatch.
    shell : str or None
        A shell command to launch in the pane instead of the default shell
        (``split-window`` trailing command); falls back to the window's
        ``window_shell``.
    """

    run: str | Command | Sequence[str | Command] | None = None
    focus: bool = False
    start_directory: str | None = None
    suppress_history: bool = True
    sleep_before: float | None = None
    sleep_after: float | None = None
    environment: Mapping[str, str] = field(default_factory=dict)
    shell: str | None = None

    @property
    def commands(self) -> tuple[Command, ...]:
        """The pane's commands as :class:`Command` values (a bare string -> Command).

        Examples
        --------
        >>> from libtmux.experimental.workspace.ir import Pane, Command
        >>> Pane(run="vim").commands
        (Command(cmd='vim', enter=True, sleep_before=None, sleep_after=None),)
        >>> [c.cmd for c in Pane(run=["a", Command("b", enter=False)]).commands]
        ['a', 'b']
        """
        if self.run is None:
            return ()
        items: Sequence[str | Command]
        items = (self.run,) if isinstance(self.run, (str, Command)) else self.run
        return tuple(c if isinstance(c, Command) else Command(c) for c in items)


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
        ``set-window-option`` key/values applied *before* the panes are built.
    options_after : Mapping[str, str]
        ``set-window-option`` key/values applied *after* the layout and pane
        focus -- for options (e.g. ``main-pane-width``) that only take effect
        once the panes and layout exist.
    environment : Mapping[str, str]
        Process environment for the window (``new-window -e``), inherited by its
        panes. For window 0 (which reuses the session's implicit window) this is
        folded into ``new-session -e`` instead.
    window_shell : str or None
        A shell command to launch in the window's first pane instead of the
        default shell (``new-window`` trailing command); also the fallback
        ``shell`` for the window's split panes.
    panes : Sequence[Pane]
        The window's panes (the first reuses the window's implicit pane).
    """

    name: str | None = None
    layout: str | None = None
    start_directory: str | None = None
    focus: bool = False
    options: Mapping[str, str] = field(default_factory=dict)
    options_after: Mapping[str, str] = field(default_factory=dict)
    environment: Mapping[str, str] = field(default_factory=dict)
    window_shell: str | None = None
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
        ``set-environment`` key/values (session-scoped tmux environment).
    options : Mapping[str, str]
        ``set-option`` (session) key/values.
    global_options : Mapping[str, str]
        ``set-option -g`` key/values (server-global options).
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
    global_options: Mapping[str, str] = field(default_factory=dict)
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
