"""Typed, target-safe deferred query-command plans.

A plan starts from a lazy :class:`PaneQuery`, resolves it against a pure
:class:`TmuxSnapshot`, maps each typed :class:`PaneRef` row to one or more
commands, and compiles the result into a single
:class:`~libtmux._experimental.chain.ir.CommandChain` -- which
dispatches once. Targets are typed (:class:`PaneTarget`, :class:`WindowTarget`,
:class:`SessionTarget`), so a row-bound command namespace cannot mis-target a
command.

Compilation (:meth:`CommandPlan.to_chain`) is a pure function of the
snapshot, so a plan can be inspected in memory -- no tmux required -- and only
:meth:`CommandPlan.run` and :meth:`CommandPlan.run_deferred` touch a live
server.

Note
----
This is an **experimental** API, not covered by the project's versioning policy.
It may change or be removed between any releases without notice.
"""

from __future__ import annotations

import collections.abc as cabc
import dataclasses
import typing as t
from dataclasses import dataclass

from libtmux._experimental.chain.chain import (
    DeferredCommandResult,
    ensure_chainable,
    validate_command_scope,
)
from libtmux._experimental.chain.ir import (
    Arg,
    CommandCall,
    CommandChain,
    CommandResultLike,
    CommandRunner,
    SlotRef,
)

if t.TYPE_CHECKING:
    from typing_extensions import Self

OrderField: t.TypeAlias = t.Literal["pane_id", "pane_index", "title"]
"""A :class:`PaneRef` field a query may order by."""

MappedT = t.TypeVar("MappedT")


class NoCommandsResolved(RuntimeError):
    """Raised when a deferred plan resolves to no concrete commands."""


@dataclass(frozen=True, slots=True)
class PaneTarget:
    """A typed tmux pane target (e.g. ``%1``).

    Examples
    --------
    >>> PaneTarget("%1")
    PaneTarget(value='%1')
    >>> str(PaneTarget("%1"))
    '%1'
    """

    value: str

    @classmethod
    def coerce(cls, target: str | PaneTarget) -> PaneTarget:
        """Normalize raw pane-target text into a typed target.

        Examples
        --------
        >>> PaneTarget.coerce("%2")
        PaneTarget(value='%2')
        >>> PaneTarget.coerce(PaneTarget("%2"))
        PaneTarget(value='%2')
        """
        if isinstance(target, str):
            return cls(target)
        return target

    def __str__(self) -> str:
        """Render as the tmux target value."""
        return self.value


@dataclass(frozen=True, slots=True)
class WindowTarget:
    """A typed tmux window target (e.g. ``@1``).

    Examples
    --------
    >>> str(WindowTarget("@1"))
    '@1'
    """

    value: str

    @classmethod
    def coerce(cls, target: str | WindowTarget) -> WindowTarget:
        """Normalize raw window-target text into a typed target.

        Examples
        --------
        >>> WindowTarget.coerce("@1")
        WindowTarget(value='@1')
        """
        if isinstance(target, str):
            return cls(target)
        return target

    def __str__(self) -> str:
        """Render as the tmux target value."""
        return self.value


@dataclass(frozen=True, slots=True)
class SessionTarget:
    """A typed tmux session target (e.g. ``$0``).

    Examples
    --------
    >>> str(SessionTarget("$0"))
    '$0'
    """

    value: str

    @classmethod
    def coerce(cls, target: str | SessionTarget) -> SessionTarget:
        """Normalize raw session-target text into a typed target.

        Examples
        --------
        >>> SessionTarget.coerce("$0")
        SessionTarget(value='$0')
        """
        if isinstance(target, str):
            return cls(target)
        return target

    def __str__(self) -> str:
        """Render as the tmux target value."""
        return self.value


@dataclass(frozen=True, slots=True)
class PendingTarget:
    """A tmux runtime token for an object that does not exist yet.

    A *forward* ref -- the pane/window/session a creation verb will make -- has
    no id until tmux runs, so it is addressed at dispatch via a runtime token:
    ``"active"`` renders to ``None`` (no ``-t``), since a non-detached
    split/new-window/new-session activates what it creates and the next commands
    hit it; ``"marked"`` renders to ``"{marked}"`` (the ``select-pane -m`` pane).

    Examples
    --------
    >>> PendingTarget().render() is None
    True
    >>> PendingTarget("marked").render()
    '{marked}'
    """

    slot: t.Literal["active", "marked"] = "active"

    def render(self) -> str | None:
        """Render as the tmux runtime token (``None`` for active, else marked)."""
        return None if self.slot == "active" else "{marked}"

    @property
    def value(self) -> str:
        """Display form (``""`` for active) so a ``*TargetT`` union is uniform."""
        return self.render() or ""


PaneTargetT: t.TypeAlias = "PaneTarget | PendingTarget"
WindowTargetT: t.TypeAlias = "WindowTarget | PendingTarget"
SessionTargetT: t.TypeAlias = "SessionTarget | PendingTarget"
AnyTarget: t.TypeAlias = (
    "PaneTarget | WindowTarget | SessionTarget | PendingTarget | SlotRef"
)


def _target_arg(target: AnyTarget) -> str | int | None | SlotRef:
    """Render a target as a concrete id or a pending token (the single seam).

    Examples
    --------
    >>> _target_arg(PaneTarget("%1"))
    '%1'
    >>> _target_arg(PendingTarget()) is None
    True
    """
    if isinstance(target, PendingTarget):
        return target.render()
    if isinstance(target, SlotRef):
        return target  # deferred; the multi-dispatch resolver substitutes it
    return target.value


class ForwardDataUnavailable(RuntimeError):
    """Raised when forward-ref metadata is read before tmux creates the object."""


def _forward_data(field: str) -> t.NoReturn:
    """Raise: a forward ref has no metadata until tmux creates the object."""
    msg = f"{field} is unavailable on a forward ref until tmux creates the object"
    raise ForwardDataUnavailable(msg)


class _ForwardRef:
    """Shared forward-chaining surface for the typed refs.

    A ref accumulates a one-dispatch ``_lineage`` of creation/decoration calls;
    this mixin compiles and dispatches it. Defining it once keeps
    :class:`PaneRef`/:class:`WindowRef`/:class:`SessionRef` free of repetition.
    """

    __slots__ = ()

    if t.TYPE_CHECKING:
        _lineage: tuple[CommandCall, ...]

    def do(self, build: cabc.Callable[[Self], IntoCommands]) -> Self:
        """Append commands built from this ref via its own namespaces.

        The fluent way to act on a forward ref with no new vocabulary: ``build``
        uses the existing ``.cmd``/``.window``/``.session`` namespaces; the
        cursor (this ref) is unchanged.

        Examples
        --------
        >>> ref = PaneRef.concrete(
        ...     pane_id="%1", window_id="@1", session_id="$0",
        ...     pane_index=0, active=True, title="editor",
        ... )
        >>> ref.do(lambda p: p.cmd.send_keys("vim", enter=True)).to_chain().argvs()
        (('send-keys', '-t', '%1', 'vim', 'Enter'),)
        """
        extra = _to_calls(build(self))
        return dataclasses.replace(self, _lineage=(*self._lineage, *extra))  # type: ignore[type-var]

    def to_chain(self) -> CommandChain:
        """Fold the accumulated lineage into one chain (chainability-checked).

        Examples
        --------
        >>> ref = PaneRef.concrete(
        ...     pane_id="%1", window_id="@1", session_id="$0",
        ...     pane_index=0, active=True, title="editor",
        ... )
        >>> ref.split().to_chain().argvs()
        (('split-window', '-t', '%1', '-v'),)
        """
        return _compile_lineage(self._lineage)

    def run(self, runner: CommandRunner) -> CommandResultLike:
        """Dispatch the accumulated lineage in one tmux invocation.

        Examples
        --------
        Dispatch the lineage against a live server in one invocation:

        >>> ref = PaneRef.concrete(
        ...     pane_id=pane.pane_id, window_id=pane.window_id,
        ...     session_id=pane.session_id, pane_index=0, active=True, title="",
        ... )
        >>> built = ref.do(lambda p: p.cmd.send_keys("echo hi", enter=True))
        >>> built.run(pane.server).returncode
        0
        """
        return self.to_chain().run(runner)


def _compile_lineage(calls: tuple[CommandCall, ...]) -> CommandChain:
    """Chainability-check an accumulated lineage and fold it into one chain."""
    for call in calls:
        ensure_chainable(call.name)
    return CommandChain(calls)


class CommandValue:
    """Base for typed command values produced by a deferred plan.

    Subclasses carry their own typed target and compile to an
    :class:`~libtmux._experimental.chain.ir.CommandCall`.
    """

    def to_call(self) -> CommandCall:
        """Compile this command value into a shared command call."""
        raise NotImplementedError

    def argv(self) -> tuple[str, ...]:
        """Render this command value as tmux argv tokens.

        Examples
        --------
        >>> SendKeys(PaneTarget("%1"), "clear", enter=True).argv()
        ('send-keys', '-t', '%1', 'clear', 'Enter')
        """
        return self.to_call().argv()


CommandLike: t.TypeAlias = "CommandValue | CommandCall"
IntoCommands: t.TypeAlias = "CommandLike | cabc.Iterable[CommandLike]"


@dataclass(frozen=True, slots=True)
class SendKeys(CommandValue):
    """A typed ``send-keys`` command bound to a pane.

    Examples
    --------
    >>> SendKeys(PaneTarget("%1"), "clear", enter=True).argv()
    ('send-keys', '-t', '%1', 'clear', 'Enter')
    """

    target: PaneTargetT | SlotRef
    command: str
    enter: bool = False

    def to_call(self) -> CommandCall:
        """Compile to a shared command call.

        Examples
        --------
        >>> SendKeys(PaneTarget("%1"), "clear", enter=True).to_call().argv()
        ('send-keys', '-t', '%1', 'clear', 'Enter')
        """
        args: list[Arg] = [self.command]
        if self.enter:
            args.append("Enter")
        return CommandCall("send-keys", tuple(args), target=_target_arg(self.target))


@dataclass(frozen=True, slots=True)
class ResizePane(CommandValue):
    """A typed ``resize-pane`` command bound to a pane.

    Examples
    --------
    >>> ResizePane(PaneTarget("%1"), height=20).argv()
    ('resize-pane', '-t', '%1', '-y', '20')
    """

    target: PaneTargetT | SlotRef
    height: int

    def to_call(self) -> CommandCall:
        """Compile to a shared command call.

        Examples
        --------
        >>> ResizePane(PaneTarget("%1"), height=20).to_call().argv()
        ('resize-pane', '-t', '%1', '-y', '20')
        """
        return CommandCall(
            "resize-pane",
            ("-y", self.height),
            target=_target_arg(self.target),
        )


@dataclass(frozen=True, slots=True)
class SelectLayout(CommandValue):
    """A typed ``select-layout`` command bound to a window.

    Examples
    --------
    >>> SelectLayout(WindowTarget("@1"), "even-horizontal").argv()
    ('select-layout', '-t', '@1', 'even-horizontal')
    """

    target: WindowTargetT | SlotRef
    layout: str

    def to_call(self) -> CommandCall:
        """Compile to a shared command call.

        Examples
        --------
        >>> SelectLayout(WindowTarget("@1"), "tiled").to_call().argv()
        ('select-layout', '-t', '@1', 'tiled')
        """
        return CommandCall(
            "select-layout", (self.layout,), target=_target_arg(self.target)
        )


class BoundPaneCommands:
    """Pane command namespace bound to one typed pane target.

    Examples
    --------
    >>> BoundPaneCommands(PaneTarget("%1")).send_keys("clear", enter=True).argv()
    ('send-keys', '-t', '%1', 'clear', 'Enter')
    """

    def __init__(self, target: PaneTargetT | SlotRef) -> None:
        self.target = target

    def send_keys(self, command: str, *, enter: bool = False) -> SendKeys:
        """Build a target-bound ``send-keys`` command.

        Examples
        --------
        >>> BoundPaneCommands(PaneTarget("%1")).send_keys("clear").argv()
        ('send-keys', '-t', '%1', 'clear')
        """
        return SendKeys(target=self.target, command=command, enter=enter)

    def resize_pane(self, *, height: int) -> ResizePane:
        """Build a target-bound ``resize-pane`` command.

        Examples
        --------
        >>> BoundPaneCommands(PaneTarget("%1")).resize_pane(height=20).argv()
        ('resize-pane', '-t', '%1', '-y', '20')
        """
        return ResizePane(target=self.target, height=height)

    def set_option(self, name: str, value: Arg) -> CommandCall:
        """Build a pane-scoped ``set-option -p`` bound to this pane.

        Examples
        --------
        >>> BoundPaneCommands(PaneTarget("%1")).set_option("@x", "1").argv()
        ('set-option', '-t', '%1', '-p', '@x', '1')
        """
        return self.raw("set-option", "-p", name, value)

    def select(self) -> CommandCall:
        """Build a ``select-pane`` bound to this pane.

        Examples
        --------
        >>> BoundPaneCommands(PaneTarget("%1")).select().argv()
        ('select-pane', '-t', '%1')
        """
        return self.raw("select-pane")

    def raw(self, name: str, *args: Arg) -> CommandCall:
        """Build an arbitrary pane-scoped command bound to this pane.

        The typed escape hatch: any tmux command, with the pane target
        pre-bound, for commands without a first-class builder. Still subject to
        the chainability check when compiled in a plan.

        Examples
        --------
        >>> BoundPaneCommands(PaneTarget("%1")).raw("pipe-pane", "-o").argv()
        ('pipe-pane', '-t', '%1', '-o')
        """
        validate_command_scope(name, "pane")
        return CommandCall(name, args, target=_target_arg(self.target))


class BoundWindowCommands:
    """Window command namespace bound to one typed window target.

    Examples
    --------
    >>> BoundWindowCommands(WindowTarget("@1")).select_layout("tiled").argv()
    ('select-layout', '-t', '@1', 'tiled')
    """

    def __init__(self, target: WindowTargetT | SlotRef) -> None:
        self.target = target

    def select_layout(self, layout: str) -> SelectLayout:
        """Build a target-bound ``select-layout`` command.

        Examples
        --------
        >>> BoundWindowCommands(WindowTarget("@1")).select_layout("tiled").argv()
        ('select-layout', '-t', '@1', 'tiled')
        """
        return SelectLayout(target=self.target, layout=layout)

    def set_option(self, name: str, value: Arg) -> CommandCall:
        """Build a window-scoped ``set-option -w`` bound to this window.

        Examples
        --------
        >>> BoundWindowCommands(WindowTarget("@1")).set_option("mode-keys", "vi").argv()
        ('set-option', '-t', '@1', '-w', 'mode-keys', 'vi')
        """
        return self.raw("set-option", "-w", name, value)

    def rename(self, name: str) -> CommandCall:
        """Build a ``rename-window`` bound to this window.

        Examples
        --------
        >>> BoundWindowCommands(WindowTarget("@1")).rename("editor").argv()
        ('rename-window', '-t', '@1', 'editor')
        """
        return self.raw("rename-window", name)

    def select(self) -> CommandCall:
        """Build a ``select-window`` bound to this window.

        Examples
        --------
        >>> BoundWindowCommands(WindowTarget("@1")).select().argv()
        ('select-window', '-t', '@1')
        """
        return self.raw("select-window")

    def raw(self, name: str, *args: Arg) -> CommandCall:
        """Build an arbitrary window-scoped command bound to this window.

        Examples
        --------
        >>> BoundWindowCommands(WindowTarget("@1")).raw("set-option", "@x", "1").argv()
        ('set-option', '-t', '@1', '@x', '1')
        """
        validate_command_scope(name, "window")
        return CommandCall(name, args, target=_target_arg(self.target))


class BoundSessionCommands:
    """Session command namespace bound to one typed session target.

    The session scope exists mainly for the ``raw`` escape hatch -- e.g. the
    per-session ``set-option`` loops that workspace builders issue.

    Examples
    --------
    >>> BoundSessionCommands(SessionTarget("$0")).raw("set-option", "@x", "1").argv()
    ('set-option', '-t', '$0', '@x', '1')
    """

    def __init__(self, target: SessionTargetT | SlotRef) -> None:
        self.target = target

    def set_option(self, name: str, value: Arg) -> CommandCall:
        """Build a session-scoped ``set-option`` bound to this session.

        Examples
        --------
        >>> BoundSessionCommands(SessionTarget("$0")).set_option("status", "on").argv()
        ('set-option', '-t', '$0', 'status', 'on')
        """
        return self.raw("set-option", name, value)

    def set_environment(self, name: str, value: str) -> CommandCall:
        """Build a session-scoped ``set-environment`` bound to this session.

        Examples
        --------
        >>> cmds = BoundSessionCommands(SessionTarget("$0"))
        >>> cmds.set_environment("EDITOR", "vim").argv()
        ('set-environment', '-t', '$0', 'EDITOR', 'vim')
        """
        return self.raw("set-environment", name, value)

    def rename(self, name: str) -> CommandCall:
        """Build a ``rename-session`` bound to this session.

        Examples
        --------
        >>> BoundSessionCommands(SessionTarget("$0")).rename("work").argv()
        ('rename-session', '-t', '$0', 'work')
        """
        return self.raw("rename-session", name)

    def raw(self, name: str, *args: Arg) -> CommandCall:
        """Build an arbitrary session-scoped command bound to this session."""
        validate_command_scope(name, "session")
        return CommandCall(name, args, target=_target_arg(self.target))


@dataclass(frozen=True, slots=True)
class PaneRef(_ForwardRef):
    r"""A typed pane handle -- concrete (a snapshot row) or forward, one type.

    A *concrete* ref comes from a query/snapshot: a real ``%id`` and metadata
    (``pane_index``/``active``/``title``). A *forward* ref is declared before the
    pane exists (``pane.split()``); its id is a :class:`PendingTarget` resolved
    at dispatch and reading its metadata raises until tmux creates it. The
    ``.cmd``/``.window``/``.session`` namespaces work identically on both.

    Examples
    --------
    Concrete (from a snapshot): build a command bound to this pane's real ids.

    >>> pane = PaneRef.concrete(
    ...     pane_id="%1", window_id="@1", session_id="$0",
    ...     pane_index=0, active=True, title="editor",
    ... )
    >>> pane.cmd.send_keys("clear", enter=True).argv()
    ('send-keys', '-t', '%1', 'clear', 'Enter')
    >>> pane.title
    'editor'
    >>> pane.is_forward
    False

    Forward: split it, then split the pane that split just created -- one chain.

    >>> pane.split(horizontal=True).split().to_chain().argvs()
    (('split-window', '-t', '%1', '-h'), ('split-window', '-v'))
    """

    pane_id: PaneTargetT
    window_id: WindowTargetT
    session_id: SessionTargetT
    _pane_index: int | None = None
    _active: bool | None = None
    _title: str | None = None
    _lineage: tuple[CommandCall, ...] = ()

    @classmethod
    def concrete(
        cls,
        *,
        pane_id: str | PaneTarget,
        window_id: str | WindowTarget,
        session_id: str | SessionTarget,
        pane_index: int,
        active: bool,
        title: str,
    ) -> PaneRef:
        """Build a concrete pane row (real ids and metadata).

        Examples
        --------
        >>> ref = PaneRef.concrete(
        ...     pane_id="%1", window_id="@1", session_id="$0",
        ...     pane_index=0, active=True, title="editor",
        ... )
        >>> (ref.is_forward, ref.title)
        (False, 'editor')
        """
        return cls(
            pane_id=PaneTarget.coerce(pane_id),
            window_id=WindowTarget.coerce(window_id),
            session_id=SessionTarget.coerce(session_id),
            _pane_index=pane_index,
            _active=active,
            _title=title,
        )

    @property
    def is_forward(self) -> bool:
        """Whether this ref's id resolves at dispatch (vs. a known ``%id``)."""
        return isinstance(self.pane_id, PendingTarget)

    @property
    def pane_index(self) -> int:
        """Pane index (raises on a forward ref -- the pane does not exist yet)."""
        if self._pane_index is None:
            _forward_data("pane_index")
        return self._pane_index

    @property
    def active(self) -> bool:
        """Whether the pane is active (raises on a forward ref)."""
        if self._active is None:
            _forward_data("active")
        return self._active

    @property
    def title(self) -> str:
        """Pane title (raises on a forward ref)."""
        if self._title is None:
            _forward_data("title")
        return self._title

    @property
    def cmd(self) -> BoundPaneCommands:
        """Pane-scoped commands bound to this pane (concrete id or pending token)."""
        return BoundPaneCommands(self.pane_id)

    @property
    def window(self) -> BoundWindowCommands:
        """Window-scoped commands bound to this pane's window."""
        return BoundWindowCommands(self.window_id)

    @property
    def session(self) -> BoundSessionCommands:
        """Session-scoped commands bound to this pane's session."""
        return BoundSessionCommands(self.session_id)

    def split(self, *, horizontal: bool = False, shell: str | None = None) -> PaneRef:
        r"""Split this pane; return a FORWARD ref to the new (active) pane.

        The new pane stays in this pane's window/session; its own id is pending
        until dispatch -- a non-detached split activates it, so later commands
        hit it with no ``-t``.
        """
        args: list[Arg] = ["-h" if horizontal else "-v"]
        if shell is not None:
            args.append(shell)
        call = CommandCall(
            "split-window", tuple(args), target=_target_arg(self.pane_id)
        )
        return PaneRef(
            pane_id=PendingTarget("active"),
            window_id=self.window_id,
            session_id=self.session_id,
            _lineage=(*self._lineage, call),
        )

    def break_pane(self, *, name: str | None = None) -> WindowRef:
        r"""Break this pane into a new window; return a FORWARD :class:`WindowRef`."""
        args: list[Arg] = ["-s", _require_id(self.pane_id)]
        args += ["-t", f"{_require_id(self.session_id)}:"]  # scope to owning session
        if name is not None:
            args += ["-n", name]
        call = CommandCall("break-pane", tuple(args))
        return WindowRef(
            window_id=PendingTarget("active"),
            session_id=self.session_id,
            _lineage=(*self._lineage, call),
        )


CommandMapper: t.TypeAlias = cabc.Callable[[PaneRef], IntoCommands]


def _require_id(target: AnyTarget) -> str:
    """Return a concrete id, or raise -- creation verbs need a real source id."""
    if isinstance(target, (PendingTarget, SlotRef)):
        msg = "a creation verb needs a concrete source id, not a forward ref"
        raise ForwardDataUnavailable(msg)
    return target.value


@dataclass(frozen=True, slots=True)
class WindowRef(_ForwardRef):
    r"""A typed window handle -- concrete or forward, mirroring :class:`PaneRef`.

    Created by ``session.new_window()`` or ``pane.break_pane()``. Reuses the
    ``.window``/``.session`` namespaces; ``.split()`` descends into a forward
    :class:`PaneRef`.

    Examples
    --------
    >>> win = WindowRef.concrete(
    ...     window_id="@1", session_id="$0", window_index=1, window_name="editor"
    ... )
    >>> win.window.select_layout("tiled").argv()
    ('select-layout', '-t', '@1', 'tiled')
    >>> win.split().is_forward
    True
    """

    window_id: WindowTargetT
    session_id: SessionTargetT
    _window_index: int | None = None
    _window_name: str | None = None
    _lineage: tuple[CommandCall, ...] = ()

    @classmethod
    def concrete(
        cls,
        *,
        window_id: str | WindowTarget,
        session_id: str | SessionTarget,
        window_index: int,
        window_name: str,
    ) -> WindowRef:
        """Build a concrete window row (real ids and metadata).

        Examples
        --------
        >>> ref = WindowRef.concrete(
        ...     window_id="@1", session_id="$0", window_index=1, window_name="editor"
        ... )
        >>> (ref.is_forward, ref.window_name)
        (False, 'editor')
        """
        return cls(
            window_id=WindowTarget.coerce(window_id),
            session_id=SessionTarget.coerce(session_id),
            _window_index=window_index,
            _window_name=window_name,
        )

    @property
    def is_forward(self) -> bool:
        """Whether this window resolves at dispatch."""
        return isinstance(self.window_id, PendingTarget)

    @property
    def window_index(self) -> int:
        """Window index (raises on a forward ref)."""
        if self._window_index is None:
            _forward_data("window_index")
        return self._window_index

    @property
    def window_name(self) -> str:
        """Window name (raises on a forward ref)."""
        if self._window_name is None:
            _forward_data("window_name")
        return self._window_name

    @property
    def window(self) -> BoundWindowCommands:
        """Window-scoped commands bound to this window."""
        return BoundWindowCommands(self.window_id)

    @property
    def session(self) -> BoundSessionCommands:
        """Session-scoped commands bound to this window's session."""
        return BoundSessionCommands(self.session_id)

    def split(self, *, horizontal: bool = False, shell: str | None = None) -> PaneRef:
        r"""Split this window's active pane; return a forward :class:`PaneRef`."""
        args: list[Arg] = ["-h" if horizontal else "-v"]
        if shell is not None:
            args.append(shell)
        call = CommandCall(
            "split-window", tuple(args), target=_target_arg(self.window_id)
        )
        return PaneRef(
            pane_id=PendingTarget("active"),
            window_id=self.window_id,
            session_id=self.session_id,
            _lineage=(*self._lineage, call),
        )


@dataclass(frozen=True, slots=True)
class SessionRef(_ForwardRef):
    r"""A typed session handle -- concrete or forward, mirroring :class:`PaneRef`.

    Created by :func:`new_session`. Reuses the ``.session`` namespace;
    ``.new_window()`` descends into a forward :class:`WindowRef`.

    Examples
    --------
    >>> SessionRef.concrete(session_id="$0", session_name="ci").new_window(
    ...     name="build"
    ... ).is_forward
    True
    """

    session_id: SessionTargetT
    _session_name: str | None = None
    _lineage: tuple[CommandCall, ...] = ()

    @classmethod
    def concrete(
        cls, *, session_id: str | SessionTarget, session_name: str
    ) -> SessionRef:
        """Build a concrete session row (real id and name).

        Examples
        --------
        >>> ref = SessionRef.concrete(session_id="$0", session_name="ci")
        >>> (ref.is_forward, ref.session_name)
        (False, 'ci')
        """
        return cls(
            session_id=SessionTarget.coerce(session_id),
            _session_name=session_name,
        )

    @property
    def is_forward(self) -> bool:
        """Whether this session resolves at dispatch."""
        return isinstance(self.session_id, PendingTarget)

    @property
    def session_name(self) -> str:
        """Session name (raises on a forward ref)."""
        if self._session_name is None:
            _forward_data("session_name")
        return self._session_name

    @property
    def session(self) -> BoundSessionCommands:
        """Session-scoped commands bound to this session."""
        return BoundSessionCommands(self.session_id)

    def new_window(self, *, name: str | None = None) -> WindowRef:
        r"""Create a window in this session; return a forward :class:`WindowRef`."""
        args: list[Arg] = []
        target = _target_arg(self.session_id)
        if target is not None:
            args += ["-t", f"{target}:"]
        if name is not None:
            args += ["-n", name]
        call = CommandCall("new-window", tuple(args))
        return WindowRef(
            window_id=PendingTarget("active"),
            session_id=self.session_id,
            _lineage=(*self._lineage, call),
        )


def new_session(*, name: str | None = None) -> SessionRef:
    r"""Create a detached session; return a forward :class:`SessionRef`.

    Examples
    --------
    >>> new_session(name="ci").new_window(name="build").to_chain().argvs()
    (('new-session', '-d', '-s', 'ci'), ('new-window', '-n', 'build'))
    """
    args: list[Arg] = ["-d"]
    if name is not None:
        args += ["-s", name]
    call = CommandCall("new-session", tuple(args))
    return SessionRef(session_id=PendingTarget("active"), _lineage=(call,))


@dataclass(frozen=True, slots=True)
class TmuxSnapshot:
    """A pure snapshot of tmux pane state used to resolve plans.

    Examples
    --------
    >>> snapshot = TmuxSnapshot(panes=())
    >>> snapshot.panes
    ()
    """

    panes: tuple[PaneRef, ...]


class SnapshotProvider(t.Protocol):
    """Object that can provide a pure tmux snapshot."""

    def snapshot(self) -> TmuxSnapshot:
        """Return a tmux snapshot."""
        ...


class PlanRunner(CommandRunner, SnapshotProvider, t.Protocol):
    """A runner that can both resolve snapshots and dispatch commands."""


SnapshotSource: t.TypeAlias = "TmuxSnapshot | SnapshotProvider"


@dataclass(frozen=True, slots=True)
class PaneQuery:
    """A lazy pane query that can become a deferred command plan.

    Examples
    --------
    >>> snapshot = TmuxSnapshot(
    ...     panes=(
    ...         PaneRef.concrete(pane_id="%1", window_id="@1", session_id="$0",
    ...                 pane_index=0, active=True, title="editor"),
    ...         PaneRef.concrete(pane_id="%2", window_id="@1", session_id="$0",
    ...                 pane_index=1, active=False, title="logs"),
    ...     ),
    ... )
    >>> [p.pane_id.value for p in panes().filter(active=True).all(snapshot)]
    ['%1']
    """

    active_filter: bool | None = None
    ordering: OrderField | None = None
    limit_count: int | None = None

    def filter(self, *, active: bool) -> PaneQuery:
        """Return a query filtered by active state.

        Examples
        --------
        >>> panes().filter(active=True)
        PaneQuery(active_filter=True, ordering=None, limit_count=None)
        """
        return dataclasses.replace(self, active_filter=active)

    def order_by(self, field: OrderField) -> PaneQuery:
        """Return a query ordered by a known pane field.

        Examples
        --------
        >>> panes().order_by("pane_index")
        PaneQuery(active_filter=None, ordering='pane_index', limit_count=None)
        """
        return dataclasses.replace(self, ordering=field)

    def limit(self, count: int) -> PaneQuery:
        """Return a query capped to ``count`` rows.

        Examples
        --------
        >>> panes().limit(2)
        PaneQuery(active_filter=None, ordering=None, limit_count=2)
        """
        return dataclasses.replace(self, limit_count=count)

    def all(self, source: SnapshotSource) -> list[PaneRef]:
        """Evaluate the query against a snapshot source.

        Examples
        --------
        >>> snapshot = TmuxSnapshot(
        ...     panes=(
        ...         PaneRef.concrete(pane_id="%2", window_id="@1", session_id="$0",
        ...                 pane_index=1, active=True, title="logs"),
        ...         PaneRef.concrete(pane_id="%1", window_id="@1", session_id="$0",
        ...                 pane_index=0, active=True, title="editor"),
        ...     ),
        ... )
        >>> [p.pane_id.value for p in panes().order_by("pane_index").all(snapshot)]
        ['%1', '%2']
        """
        rows = list(_resolve_snapshot(source).panes)
        if self.active_filter is not None:
            rows = [row for row in rows if row.active == self.active_filter]
        if self.ordering is not None:
            ordering = self.ordering
            rows.sort(key=lambda row: _order_value(row, ordering))
        if self.limit_count is not None:
            rows = rows[: self.limit_count]
        return rows

    def first(self, source: SnapshotSource) -> PaneRef | None:
        """Evaluate the query and return its first row, or ``None``."""
        rows = self.limit(1).all(source)
        if not rows:
            return None
        return rows[0]

    def map(
        self,
        mapper: cabc.Callable[[PaneRef], MappedT],
    ) -> MappedPaneQuery[MappedT]:
        """Return a data-only transformation query (no commands)."""
        return MappedPaneQuery(query=self, mapper=mapper)

    def commands(self, mapper: CommandMapper) -> CommandPlan:
        """Return a deferred plan where each row maps to one or more commands.

        Examples
        --------
        >>> snapshot = TmuxSnapshot(
        ...     panes=(
        ...         PaneRef.concrete(pane_id="%1", window_id="@1", session_id="$0",
        ...                 pane_index=0, active=True, title="editor"),
        ...     ),
        ... )
        >>> plan = panes().commands(
        ...     lambda pane: (
        ...         pane.cmd.resize_pane(height=10),
        ...         pane.window.select_layout("tiled"),
        ...     ),
        ... )
        >>> compiled = plan.to_chain(snapshot).argvs()
        >>> compiled[0]
        ('resize-pane', '-t', '%1', '-y', '10')
        >>> compiled[1]
        ('select-layout', '-t', '@1', 'tiled')
        """
        return CommandPlan(_CommandPlanNode(query=self, mapper=mapper))


@dataclass(frozen=True, slots=True)
class MappedPaneQuery(t.Generic[MappedT]):
    """A data-only query transformation over pane rows.

    Examples
    --------
    >>> snapshot = TmuxSnapshot(
    ...     panes=(
    ...         PaneRef.concrete(pane_id="%1", window_id="@1", session_id="$0",
    ...                 pane_index=0, active=True, title="editor"),
    ...     ),
    ... )
    >>> panes().map(lambda pane: pane.title).all(snapshot)
    ['editor']
    """

    query: PaneQuery
    mapper: cabc.Callable[[PaneRef], MappedT]

    def all(self, source: SnapshotSource) -> list[MappedT]:
        """Evaluate the query and transform every row.

        Examples
        --------
        >>> snapshot = TmuxSnapshot(
        ...     panes=(
        ...         PaneRef.concrete(pane_id="%1", window_id="@1", session_id="$0",
        ...                 pane_index=0, active=True, title="editor"),
        ...         PaneRef.concrete(pane_id="%2", window_id="@1", session_id="$0",
        ...                 pane_index=1, active=True, title="logs"),
        ...     ),
        ... )
        >>> panes().map(lambda pane: pane.title).all(snapshot)
        ['editor', 'logs']
        """
        return [self.mapper(row) for row in self.query.all(source)]

    def first(self, source: SnapshotSource) -> MappedT | None:
        """Evaluate the query and transform the first row, or ``None``.

        Examples
        --------
        >>> snapshot = TmuxSnapshot(
        ...     panes=(
        ...         PaneRef.concrete(pane_id="%1", window_id="@1", session_id="$0",
        ...                 pane_index=0, active=True, title="editor"),
        ...     ),
        ... )
        >>> panes().map(lambda pane: pane.title).first(snapshot)
        'editor'
        >>> panes().filter(active=False).map(lambda p: p.title).first(snapshot) is None
        True
        """
        row = self.query.first(source)
        if row is None:
            return None
        return self.mapper(row)


@dataclass(frozen=True, slots=True)
class _CommandPlanNode:
    """A deferred query plus a command mapper (an unresolved plan node)."""

    query: PaneQuery
    mapper: CommandMapper


@dataclass(frozen=True, slots=True)
class CommandPlan:
    """A lazy command plan that resolves a query into a command sequence.

    Examples
    --------
    >>> snapshot = TmuxSnapshot(
    ...     panes=(
    ...         PaneRef.concrete(pane_id="%2", window_id="@1", session_id="$0",
    ...                 pane_index=1, active=True, title="logs"),
    ...         PaneRef.concrete(pane_id="%1", window_id="@1", session_id="$0",
    ...                 pane_index=0, active=True, title="editor"),
    ...     ),
    ... )
    >>> plan = (
    ...     panes()
    ...     .filter(active=True)
    ...     .order_by("pane_index")
    ...     .commands(lambda pane: pane.cmd.resize_pane(height=20))
    ... )
    >>> plan.to_chain(snapshot).argvs()
    (('resize-pane', '-t', '%1', '-y', '20'), ('resize-pane', '-t', '%2', '-y', '20'))
    """

    node: _CommandPlanNode

    def to_chain(self, source: SnapshotSource) -> CommandChain:
        """Resolve the query and compile mapped commands (pure).

        Parameters
        ----------
        source : SnapshotSource
            A :class:`TmuxSnapshot` or a :class:`SnapshotProvider`.

        Returns
        -------
        CommandChain

        Raises
        ------
        NoCommandsResolved
            If the resolved query produced no commands.
        ChainabilityError
            If a mapped command is non-chainable -- its output would be
            consumed mid-chain (e.g. ``show-option``). Raw ``CommandCall``
            composition via ``>>`` is the explicit escape hatch and is not
            checked.

        Examples
        --------
        >>> snapshot = TmuxSnapshot(
        ...     panes=(
        ...         PaneRef.concrete(pane_id="%1", window_id="@1", session_id="$0",
        ...                 pane_index=0, active=True, title="editor"),
        ...     ),
        ... )
        >>> panes().commands(
        ...     lambda p: p.cmd.resize_pane(height=10)
        ... ).to_chain(snapshot).argvs()
        (('resize-pane', '-t', '%1', '-y', '10'),)
        """
        calls: list[CommandCall] = []
        for row in self.node.query.all(source):
            calls.extend(_to_calls(self.node.mapper(row)))
        if not calls:
            msg = "command plan resolved to no commands"
            raise NoCommandsResolved(msg)
        for call in calls:
            ensure_chainable(call.name)
        return CommandChain(tuple(calls))

    def run(self, runner: PlanRunner) -> None:
        """Resolve, compile, and dispatch the plan in one tmux invocation.

        An empty plan is a no-op (it does not raise), mirroring libtmux's
        lenient list-accessor contract.

        Examples
        --------
        Dispatch ``send-keys`` to every active pane in one invocation, against
        a live tmux server:

        >>> from libtmux._experimental.chain import SessionPlanExecutor
        >>> plan = panes().filter(active=True).commands(
        ...     lambda pane: pane.cmd.send_keys("echo libtmux", enter=True),
        ... )
        >>> plan.run(SessionPlanExecutor(session))
        """
        try:
            sequence = self.to_chain(runner)
        except NoCommandsResolved:
            return None
        sequence.run(runner)
        return None

    def run_deferred(self, runner: PlanRunner) -> tuple[DeferredCommandResult, ...]:
        r"""Dispatch once and return a resolved deferred result per command.

        The chain dispatches a single time; each returned
        :class:`~libtmux._experimental.chain.chain.DeferredCommandResult` is
        resolved with the chain's merged result (a ``\\;`` dispatch is not
        separable per command, so every handle reflects the same result). An
        empty plan returns an empty tuple.

        Examples
        --------
        >>> from libtmux._experimental.chain import SessionPlanExecutor
        >>> plan = panes().filter(active=True).commands(
        ...     lambda pane: pane.cmd.send_keys("echo libtmux", enter=True),
        ... )
        >>> results = plan.run_deferred(SessionPlanExecutor(session))
        >>> all(r.returncode == 0 for r in results)
        True
        """
        try:
            sequence = self.to_chain(runner)
        except NoCommandsResolved:
            return ()
        result = sequence.run(runner)
        return tuple(
            DeferredCommandResult(call).resolve(result) for call in sequence.calls
        )


def panes() -> PaneQuery:
    """Start a lazy pane query.

    Examples
    --------
    >>> panes()
    PaneQuery(active_filter=None, ordering=None, limit_count=None)
    """
    return PaneQuery()


def _resolve_snapshot(source: SnapshotSource) -> TmuxSnapshot:
    if isinstance(source, TmuxSnapshot):
        return source
    return source.snapshot()


def _order_value(row: PaneRef, field: OrderField) -> str | int:
    if field == "pane_id":
        return row.pane_id.value
    if field == "pane_index":
        return row.pane_index
    return row.title


def _to_calls(value: IntoCommands) -> tuple[CommandCall, ...]:
    if isinstance(value, CommandCall):
        return (value,)
    if isinstance(value, CommandValue):
        return (value.to_call(),)
    if isinstance(value, str | bytes):
        msg = "command mapper must return a command or iterable of commands"
        raise TypeError(msg)

    calls: list[CommandCall] = []
    try:
        iterator = iter(value)
    except TypeError as exc:
        msg = "command mapper must return a command or iterable of commands"
        raise TypeError(msg) from exc
    for item in iterator:
        calls.extend(_to_calls(item))
    return tuple(calls)
