"""Declarative workspace specs -- the structural object language.

The *Declarative* tier (à la SQLAlchemy Declarative on Core): the user declares
the **shape** of a workspace as a tree of :class:`Workspace` / :class:`Window` /
:class:`Pane` values, and the compiler lowers that tree into a Core
:class:`~libtmux.experimental.ops.plan.LazyPlan`. The specs are pure, immutable
data -- no tmux, no engine -- so they round-trip to/from YAML and can be inspected
before anything runs.

Examples
--------
>>> from libtmux.experimental.engines import MockEngine
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
>>> ws.build(MockEngine(), preflight=False).ok
True
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field

if t.TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from libtmux.experimental.engines.base import AsyncTmuxEngine, TmuxEngine
    from libtmux.experimental.ops.plan import LazyPlan, PlanResult
    from libtmux.experimental.ops.planner import Planner
    from libtmux.experimental.workspace.events import BuildEvent


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

    def to_config(self) -> str | dict[str, t.Any]:
        """Serialize to a tmuxp ``shell_command`` item.

        A plain command (``enter=True``, no sleeps) collapses back to a bare
        string; otherwise a ``{cmd, ...}`` mapping carrying only the overrides.
        """
        if self.enter and self.sleep_before is None and self.sleep_after is None:
            return self.cmd
        out: dict[str, t.Any] = {"cmd": self.cmd}
        if not self.enter:
            out["enter"] = False
        if self.sleep_before is not None:
            out["sleep_before"] = self.sleep_before
        if self.sleep_after is not None:
            out["sleep_after"] = self.sleep_after
        return out


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

    def to_dict(self) -> dict[str, t.Any]:
        """Serialize to a canonical tmuxp pane config (inverse of the analyzer)."""
        out: dict[str, t.Any] = {}
        if self.run is not None:
            out["shell_command"] = [c.to_config() for c in self.commands]
        if self.focus:
            out["focus"] = True
        if self.start_directory is not None:
            out["start_directory"] = self.start_directory
        if not self.suppress_history:
            out["suppress_history"] = False
        if self.sleep_before is not None:
            out["sleep_before"] = self.sleep_before
        if self.sleep_after is not None:
            out["sleep_after"] = self.sleep_after
        if self.environment:
            out["environment"] = dict(self.environment)
        if self.shell is not None:
            out["shell"] = self.shell
        return out


@dataclass(frozen=True)
class Float:
    """Absolute geometry for a floating pane (tmux 3.7 ``new-pane``).

    Floating panes are popup-style overlays, not tiled cells, so their geometry
    is absolute rather than split-relative. :attr:`width`/:attr:`height` set the
    size (``-x``/``-y``) and :attr:`x`/:attr:`y` set the top-left offset
    (``-X``/``-Y``); each is cells (``int``) or a percentage (``str`` like
    ``"50%"``). The remaining fields mirror the ``new-pane`` flag vocabulary.

    Parameters
    ----------
    width, height : int or str or None
        Size in cells or ``N%`` (``-x`` / ``-y``).
    x, y : int or str or None
        Absolute position in cells or ``N%`` (``-X`` / ``-Y``).
    zoom : bool
        Zoom the pane (``-Z``).
    empty : bool
        Create an empty pane with no command (``-E``).
    style, active_border_style, inactive_border_style : str or None
        Content / active-border / inactive-border styles (``-s`` / ``-S`` /
        ``-R``).
    message : str or None
        Remain-on-exit message (``-m``).

    Examples
    --------
    >>> from libtmux.experimental.workspace.ir import Float
    >>> Float(width=120, height=40, x="C", y="C").to_dict()
    {'width': 120, 'height': 40, 'x': 'C', 'y': 'C'}
    >>> Float().to_dict()
    {}
    """

    width: int | str | None = None
    height: int | str | None = None
    x: int | str | None = None
    y: int | str | None = None
    zoom: bool = False
    empty: bool = False
    style: str | None = None
    active_border_style: str | None = None
    inactive_border_style: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, t.Any]:
        """Serialize to a canonical float-geometry config (omitting defaults)."""
        out: dict[str, t.Any] = {}
        if self.width is not None:
            out["width"] = self.width
        if self.height is not None:
            out["height"] = self.height
        if self.x is not None:
            out["x"] = self.x
        if self.y is not None:
            out["y"] = self.y
        if self.zoom:
            out["zoom"] = True
        if self.empty:
            out["empty"] = True
        if self.style is not None:
            out["style"] = self.style
        if self.active_border_style is not None:
            out["active_border_style"] = self.active_border_style
        if self.inactive_border_style is not None:
            out["inactive_border_style"] = self.inactive_border_style
        if self.message is not None:
            out["message"] = self.message
        return out


@dataclass(frozen=True)
class FloatingPane:
    """A floating-pane overlay: a :class:`Pane` plus its :class:`Float` geometry.

    Overlays are *not* tiled cells -- the compiler emits them as ``new-pane`` and
    keeps them out of the tiled split chain, the ``select-layout`` call, and the
    pane-count check. :attr:`attach_to` names a :class:`Window` (by name) to float
    over; ``None`` floats over the window the overlay is declared on.

    Parameters
    ----------
    pane : Pane
        The pane's command(s), focus, env, shell, etc.
    geometry : Float
        The floating geometry; defaults to tmux's own (half-width, quarter-height,
        cascading position).
    attach_to : str or None
        Name of the window to float over; ``None`` for the host window.

    Examples
    --------
    >>> from libtmux.experimental.workspace.ir import Float, FloatingPane, Pane
    >>> fp = FloatingPane(pane=Pane(run="lazygit"), geometry=Float(width="60%"))
    >>> fp.to_dict()["shell_command"]
    ['lazygit']
    >>> fp.to_dict()["float"]
    {'width': '60%'}
    """

    pane: Pane = field(default_factory=Pane)
    geometry: Float = field(default_factory=Float)
    attach_to: str | None = None

    def to_dict(self) -> dict[str, t.Any]:
        """Serialize to a pane config plus a ``float`` geometry (and ``attach_to``)."""
        out = self.pane.to_dict()
        out["float"] = self.geometry.to_dict()
        if self.attach_to is not None:
            out["attach_to"] = self.attach_to
        return out


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
    window_index : int or None
        Place this window at an explicit session index (``new-window -t
        session:N``). Honored only for created windows (2..N); window 0 reuses
        the session's implicit window and keeps the session base index.
    panes : Sequence[Pane]
        The window's panes (the first reuses the window's implicit pane).
    floats : Sequence[FloatingPane]
        Floating-pane overlays for this window (tmux 3.7+). Overlays are not
        tiled cells: they are created with ``new-pane`` after the layout and are
        excluded from the split chain and the tiled pane count.
    """

    name: str | None = None
    layout: str | None = None
    start_directory: str | None = None
    focus: bool = False
    options: Mapping[str, str] = field(default_factory=dict)
    options_after: Mapping[str, str] = field(default_factory=dict)
    environment: Mapping[str, str] = field(default_factory=dict)
    window_shell: str | None = None
    window_index: int | None = None
    panes: Sequence[Pane] = ()
    floats: Sequence[FloatingPane] = ()

    def to_dict(self) -> dict[str, t.Any]:
        """Serialize to a canonical tmuxp window config (inverse of the analyzer)."""
        out: dict[str, t.Any] = {}
        if self.name is not None:
            out["window_name"] = self.name
        if self.layout is not None:
            out["layout"] = self.layout
        if self.start_directory is not None:
            out["start_directory"] = self.start_directory
        if self.focus:
            out["focus"] = True
        if self.options:
            out["options"] = dict(self.options)
        if self.options_after:
            out["options_after"] = dict(self.options_after)
        if self.environment:
            out["environment"] = dict(self.environment)
        if self.window_shell is not None:
            out["window_shell"] = self.window_shell
        if self.window_index is not None:
            out["window_index"] = self.window_index
        out["panes"] = [pane.to_dict() for pane in self.panes]
        if self.floats:
            out["floats"] = [fp.to_dict() for fp in self.floats]
        return out


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
    wait_pane : bool
        When ``True``, wait for each command-bearing pane's shell to be ready
        (its cursor to leave the origin) before sending keys -- the tmuxp
        anti-race. Off by default (the fast path); panes with a custom ``shell``
        skip the wait. See :mod:`~.events` and the runner.
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
    wait_pane: bool = False

    def to_dict(self) -> dict[str, t.Any]:
        """Serialize to a canonical tmuxp workspace dict (the inverse of analyze).

        ``analyze(ws.to_dict())`` reconstructs an equivalent workspace; the output
        uses canonical (non-shorthand) keys and omits fields left at their default.

        Examples
        --------
        >>> from libtmux.experimental.workspace.ir import Workspace, Window, Pane
        >>> ws = Workspace(
        ...     name="dev",
        ...     windows=[Window("editor", panes=[Pane(run="vim")])],
        ... )
        >>> ws.to_dict()["session_name"]
        'dev'
        >>> ws.to_dict()["windows"][0]["window_name"]
        'editor'
        """
        out: dict[str, t.Any] = {"session_name": self.name}
        if self.dimensions is not None:
            out["dimensions"] = list(self.dimensions)
        if self.start_directory is not None:
            out["start_directory"] = self.start_directory
        if self.environment:
            out["environment"] = dict(self.environment)
        if self.options:
            out["options"] = dict(self.options)
        if self.global_options:
            out["global_options"] = dict(self.global_options)
        if self.before_script is not None:
            out["before_script"] = self.before_script
        if self.on_exists != "error":
            out["on_exists"] = self.on_exists
        if self.wait_pane:
            out["wait_pane"] = True
        out["windows"] = [window.to_dict() for window in self.windows]
        return out

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
        on_event: Callable[[BuildEvent], None] | None = None,
        planner: Planner | None = None,
    ) -> PlanResult:
        """Compile and execute this workspace synchronously over *engine*.

        Set ``preflight=False`` to skip the ``on_exists`` ``has-session`` check
        (e.g. against the stateless ``MockEngine``, which has no real
        sessions to detect). Pass *on_event* to observe the structural build
        stream (see :mod:`~.events`). The build folds dispatches by default; pass
        *planner* (e.g. :class:`~..ops.planner.SequentialPlanner`) to override.
        """
        from libtmux.experimental.workspace.runner import build_workspace

        return build_workspace(
            self,
            engine,
            version=version,
            preflight=preflight,
            on_event=on_event,
            planner=planner,
        )

    async def abuild(
        self,
        engine: AsyncTmuxEngine,
        *,
        version: str | None = None,
        preflight: bool = True,
        on_event: Callable[[BuildEvent], Awaitable[None]] | None = None,
        planner: Planner | None = None,
    ) -> PlanResult:
        """Compile and execute this workspace asynchronously over *engine*.

        *on_event* is awaited for each build event (see :mod:`~.events`). Folds by
        default; pass *planner* to override.
        """
        from libtmux.experimental.workspace.runner import abuild_workspace

        return await abuild_workspace(
            self,
            engine,
            version=version,
            preflight=preflight,
            on_event=on_event,
            planner=planner,
        )
