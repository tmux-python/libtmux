r"""Multi-dispatch resolution for independent forward handles (sans-I/O core).

A *linear* forward chain folds into one ``tmux a \; b`` invocation: tmux
addresses the active (or single marked) object with no ``-t``. But it cannot
address two **independent** forward handles in one invocation -- ``-t`` is a
fixed argv token, and a freshly-created id escapes only as ``-P -F`` stdout. So
holding several independent handles needs **multiple dispatches**: each creation
runs on its own with ``-P -F '#{pane_id}'`` to capture its real id, which is
then substituted into the downstream commands.

The resolution is a **sans-I/O generator** -- the same yield-request /
resume-with-result trampoline asyncio itself uses (``Future.__await__`` yields a
request, ``Task.__step`` ``.send()``\\s the result back). One core; two short
drivers (sync ``runner.cmd``, async ``await runner.cmd``). The N-dispatch logic
is never duplicated, and the generator is suspended at a ``yield`` between
dispatches, so it never blocks the event loop.

Note
----
This is an **experimental** prototype, not covered by the versioning policy.
"""

from __future__ import annotations

import dataclasses
import typing as t
from dataclasses import dataclass, field

from libtmux._experimental.chain.ir import (
    CommandCall,
    CommandChain,
    CommandResultLike,
    SlotRef,
)
from libtmux._experimental.chain.plan import (
    AnyTarget,
    BoundPaneCommands,
    BoundSessionCommands,
    BoundWindowCommands,
    PaneQuery,
    PaneRef,
    PaneTarget,
    SessionRef,
    SessionTarget,
    WindowRef,
    WindowTarget,
    _target_arg,
    _to_calls,
)

if t.TYPE_CHECKING:
    import collections.abc as cabc

    from libtmux._experimental.chain._async import AsyncPlanRunner
    from libtmux._experimental.chain.plan import IntoCommands, PlanRunner
    from libtmux.pane import Pane
    from libtmux.server import Server
    from libtmux.session import Session
    from libtmux.window import Window

# A live libtmux object, a chain ref, a typed target, or a bare id string.
PaneSeed: t.TypeAlias = "Pane | PaneRef | PaneTarget | str"
WindowSeed: t.TypeAlias = "Window | WindowRef | WindowTarget | str"
SessionSeed: t.TypeAlias = "Session | SessionRef | SessionTarget | str"

Kind = t.Literal["pane", "window", "session"]
_CAPTURE: dict[Kind, str] = {
    "pane": "#{pane_id}",
    "window": "#{window_id}",
    "session": "#{session_id}",
}
_SEED = -1  # reserved binding key for a query-resolved seed
_MARKED = "{marked}"  # tmux's single server-wide marked-pane target token


class NoSeedResolved(RuntimeError):
    """Raised when a query-seeded forward plan matches no pane."""


class ForwardDispatchError(RuntimeError):
    r"""A forward creation dispatch failed -- nonzero exit or no captured id.

    Raised by the resolver when a ``split``/``new-window``/``new-session`` did
    not print the id it was asked to capture (tmux rejected the target, ran out
    of space, etc.). It turns what was an opaque ``IndexError`` on empty stdout
    into a clear failure carrying the offending ``argv`` and the tmux result.

    Examples
    --------
    >>> class _Result:
    ...     stdout: list[str] = []
    ...     stderr = ["no space for new pane"]
    ...     returncode = 1
    >>> err = ForwardDispatchError(("split-window", "-t", "%1"), _Result())
    >>> err.argv
    ('split-window', '-t', '%1')
    >>> print(str(err))
    forward dispatch failed (exit 1): split-window -t %1: no space for new pane
    """

    def __init__(self, argv: tuple[str, ...], result: CommandResultLike) -> None:
        self.argv = argv
        self.result = result
        stderr = " ".join(result.stderr).strip()
        detail = f": {stderr}" if stderr else ""
        cmd = " ".join(argv)
        msg = f"forward dispatch failed (exit {result.returncode}): {cmd}{detail}"
        super().__init__(msg)


def _capture_id(argv: tuple[str, ...], result: CommandResultLike) -> str:
    """Read the id a creation dispatch printed, or fail loudly."""
    if result.returncode != 0 or not result.stdout:
        raise ForwardDispatchError(argv, result)
    return result.stdout[0].strip()


# --- plan IR ----------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _Create:
    """A creation step; ``call.target`` is concrete, ``None``, or a parent SlotRef."""

    slot: int
    kind: Kind
    call: CommandCall


@dataclass(frozen=True, slots=True)
class _Decorate:
    """A decoration step; ``call.target`` may be a SlotRef into an earlier slot."""

    call: CommandCall


_Step: t.TypeAlias = "_Create | _Decorate"


# --- the sans-I/O protocol --------------------------------------------------
@dataclass(frozen=True, slots=True)
class SnapshotRequest:
    """The driver must supply a tmux snapshot (sync or awaited)."""


@dataclass(frozen=True, slots=True)
class Dispatch:
    """A tmux dispatch the driver runs, handing back its result.

    ``captures`` names the forward slot this dispatch creates an id for
    (``None`` for a decorate- or cleanup-only dispatch); the core binds
    ``stdout[0]`` to that slot once the driver returns the result.
    """

    argv: tuple[str, ...]
    captures: int | None


Request: t.TypeAlias = "SnapshotRequest | Dispatch"


@dataclass(frozen=True, slots=True)
class Resolved:
    """The outcome of a multi-dispatch resolution.

    ``bindings`` maps each forward slot to the concrete id tmux assigned
    (``%N``/``@N``/``$N``); ``results`` holds each resolution dispatch's
    result in order (a recovery ``select-pane -M`` after a failed marked
    fold is not captured).
    """

    bindings: dict[int, str] = field(default_factory=dict)
    results: tuple[CommandResultLike, ...] = ()

    def pane(self, slot: int, server: Server) -> Pane:
        """Look up the live pane a forward slot resolved to (by captured id)."""
        pane = server.panes.get(pane_id=self.bindings[slot])
        assert pane is not None  # get() raises ObjectDoesNotExist rather than None
        return pane

    def window(self, slot: int, server: Server) -> Window:
        """Look up the live window a forward slot resolved to (by captured id)."""
        window = server.windows.get(window_id=self.bindings[slot])
        assert window is not None
        return window

    def session(self, slot: int, server: Server) -> Session:
        """Look up the live session a forward slot resolved to (by captured id)."""
        session = server.sessions.get(session_id=self.bindings[slot])
        assert session is not None
        return session


def _capturing(call: CommandCall, kind: Kind) -> CommandCall:
    """Append ``-P -F '#{<kind>_id}'`` so the creation prints its stable id."""
    return dataclasses.replace(call, args=(*call.args, "-P", "-F", _CAPTURE[kind]))


def _with_capture(call: CommandCall, kind: Kind) -> tuple[str, ...]:
    """Render a capturing creation as argv (the multi-dispatch per-step form)."""
    return _capturing(call, kind).argv()


def _subst(call: CommandCall, bindings: dict[int, str]) -> CommandCall:
    """Replace a SlotRef target with the captured concrete id (plus its suffix)."""
    if isinstance(call.target, SlotRef):
        resolved = bindings[call.target.slot] + call.target.suffix
        return dataclasses.replace(call, target=resolved)
    return call


# --- strategy: a lone pane handle folds into one {marked} dispatch ----------
def _to_marked(call: CommandCall) -> CommandCall:
    """Retarget a SlotRef call to tmux's ``{marked}`` register (single-dispatch)."""
    if isinstance(call.target, SlotRef):
        return dataclasses.replace(call, target=_MARKED)
    return call


def _marked_eligible(steps: tuple[_Step, ...]) -> _Create | None:
    """Return the lone pane creation when the plan folds into one dispatch.

    The marked register is a single server-wide slot, and only a non-detached
    pane creation (``split-window``) leaves its result active to be marked. So
    exactly one pane :class:`_Create` is the one plan shape that resolves in a
    single ``{marked}`` invocation; any other shape (two or more creations, or a
    detached session creation) needs the multi-dispatch path.
    """
    creates = [step for step in steps if isinstance(step, _Create)]
    if len(creates) == 1 and creates[0].kind == "pane":
        return creates[0]
    return None


def _marked_invocation(
    create: _Create,
    decorates: tuple[CommandCall, ...],
    bindings: dict[int, str],
) -> tuple[str, ...]:
    r"""Fold a lone pane creation and its decorates into one ``\;`` invocation.

    Emits ``<split -P -F '#{pane_id}'> \; select-pane -m \; <decorate -t
    {marked}>... \; select-pane -M``: the split's new pane is active, ``-m``
    marks it, every decorate addresses it through tmux's ``{marked}`` register
    (which resolves for window- and session-scoped decorates too), and a trailing
    ``-M`` clears the register. Should the chain fail after the mark is set,
    :func:`drive` issues a recovery ``-M``, so no server-wide mark leaks. With no
    decorates only the capturing creation runs -- the mark would have no reader.
    """
    capture = _capturing(_subst(create.call, bindings), create.kind)
    if not decorates:
        return capture.argv()
    calls = [capture, CommandCall("select-pane", ("-m",))]
    calls.extend(_to_marked(call) for call in decorates)
    calls.append(CommandCall("select-pane", ("-M",)))
    return CommandChain(tuple(calls)).argv()


def drive(
    steps: tuple[_Step, ...],
    *,
    seed_query: PaneQuery | None = None,
) -> t.Generator[Request, t.Any, Resolved]:
    r"""Sans-I/O resolution core: yield a :class:`Request`, resume via ``.send``.

    The plan shape picks the cheapest correct strategy (see :func:`_marked_eligible`):
    a lone pane creation folds into **one** ``{marked}`` invocation; otherwise each
    :class:`_Create` is dispatched alone with ``-P -F`` id capture and a run of
    :class:`_Decorate`\\s folds into one trailing ``\;`` chain with the captured ids
    substituted. No awaits, no runner, no threads -- a pure state machine the
    sync/async drivers feed results into.
    """
    bindings: dict[int, str] = {}
    results: list[CommandResultLike] = []
    tail: list[CommandCall] = []

    if seed_query is not None:
        snapshot = yield SnapshotRequest()
        seed = seed_query.first(snapshot)
        if seed is None:
            msg = "query matched no pane to seed the forward plan"
            raise NoSeedResolved(msg)
        bindings[_SEED] = str(_target_arg(seed.pane_id))

    solo = _marked_eligible(steps)
    if solo is not None:
        decorates = tuple(s.call for s in steps if isinstance(s, _Decorate))
        argv = _marked_invocation(solo, decorates, bindings)
        result = yield Dispatch(argv, solo.slot)
        bindings[solo.slot] = _capture_id(argv, result)
        return Resolved(bindings, (result,))

    for step in steps:
        if isinstance(step, _Create):
            if tail:
                chain = CommandChain(tuple(_subst(c, bindings) for c in tail))
                results.append((yield Dispatch(chain.argv(), None)))
                tail = []
            argv = _with_capture(_subst(step.call, bindings), step.kind)
            result = yield Dispatch(argv, step.slot)
            results.append(result)
            bindings[step.slot] = _capture_id(argv, result)
        else:
            tail.append(step.call)

    if tail:
        chain = CommandChain(tuple(_subst(c, bindings) for c in tail))
        results.append((yield Dispatch(chain.argv(), None)))

    return Resolved(bindings, tuple(results))


# --- the two thin drivers (the only sync/async divergence) ------------------
def run_sync(
    gen: t.Generator[Request, t.Any, Resolved], runner: PlanRunner
) -> Resolved:
    """Drive the resolution core with blocking calls."""
    try:
        request = next(gen)
        while True:
            if isinstance(request, SnapshotRequest):
                request = gen.send(runner.snapshot())
            else:
                request = gen.send(runner.cmd(request.argv[0], *request.argv[1:]))
    except StopIteration as stop:
        return t.cast("Resolved", stop.value)


async def run_async(
    gen: t.Generator[Request, t.Any, Resolved],
    runner: AsyncPlanRunner,
) -> Resolved:
    """Drive the *same* core with ``await`` -- no resolution logic duplicated."""
    try:
        request = next(gen)
        while True:
            if isinstance(request, SnapshotRequest):
                request = gen.send(await runner.snapshot())
            else:
                result = await runner.cmd(request.argv[0], *request.argv[1:])
                request = gen.send(result)
    except StopIteration as stop:
        return t.cast("Resolved", stop.value)


# --- the builder + handles --------------------------------------------------
def _location_args(
    start_directory: str | None, environment: dict[str, str] | None
) -> tuple[str, ...]:
    """Render create-time ``-c<dir>`` / ``-e<k>=<v>`` flags (as libtmux renders them).

    Examples
    --------
    >>> _location_args("/tmp", {"FOO": "bar"})
    ('-c/tmp', '-eFOO=bar')
    >>> _location_args(None, None)
    ()
    """
    args: list[str] = []
    if start_directory is not None:
        args.append(f"-c{start_directory}")
    if environment:
        args.extend(f"-e{key}={value}" for key, value in environment.items())
    return tuple(args)


def _split_args(
    horizontal: bool,
    shell: str | None,
    start_directory: str | None = None,
    environment: dict[str, str] | None = None,
) -> tuple[str, ...]:
    """Render the ``split-window`` flags shared by the plan- and handle-level split."""
    args = ["-h" if horizontal else "-v", *_location_args(start_directory, environment)]
    if shell is not None:
        args.append(shell)
    return tuple(args)


def _id_of(obj: object, attr: str) -> str:
    """Read a tmux id string from a live libtmux object, a chain ref, or a str.

    Examples
    --------
    >>> _id_of("%1", "pane_id")
    '%1'
    >>> _id_of(PaneTarget("%2"), "pane_id")
    '%2'
    >>> _id_of(PaneRef.concrete(pane_id="%3", window_id="@1", session_id="$0",
    ...     pane_index=0, active=True, title=""), "pane_id")
    '%3'
    """
    if isinstance(obj, str):
        return obj
    if isinstance(obj, (PaneTarget, WindowTarget, SessionTarget)):
        return obj.value
    value = getattr(obj, attr)
    if isinstance(value, (PaneTarget, WindowTarget, SessionTarget)):
        return value.value
    return str(value)


def _kind_of(target: AnyTarget) -> Kind:
    """Return the tmux scope a concrete seed target addresses."""
    if isinstance(target, PaneTarget):
        return "pane"
    if isinstance(target, WindowTarget):
        return "window"
    if isinstance(target, SessionTarget):
        return "session"
    msg = f"cannot seed a forward plan from {type(target).__name__}"
    raise TypeError(msg)


class ForwardHandle:
    """A reference to one object inside a :class:`ForwardPlan` -- forward or seed.

    One type spans all three tmux scopes and both lifetimes: a *forward* handle
    is bound to a :class:`~libtmux._experimental.chain.ir.SlotRef` (a not-yet-
    created object whose id the resolver substitutes); a *seed* handle is bound
    to a concrete id string (an object that already exists). The handle knows its
    ``kind`` so creation verbs stay scope-correct -- ``new_window()`` only on a
    session, ``split()`` only on a pane or window -- while the ``.cmd``/
    ``.window``/``.session`` command namespaces are reused unchanged.
    """

    def __init__(self, plan: ForwardPlan, ref: SlotRef | str, kind: Kind) -> None:
        self._plan = plan
        self._ref = ref
        self._kind = kind

    @property
    def cmd(self) -> BoundPaneCommands:
        """Pane-scoped commands bound to this handle."""
        ref = self._ref if isinstance(self._ref, SlotRef) else PaneTarget(self._ref)
        return BoundPaneCommands(ref)

    @property
    def window(self) -> BoundWindowCommands:
        """Window-scoped commands (a pane id resolves up to its window)."""
        ref = self._ref if isinstance(self._ref, SlotRef) else WindowTarget(self._ref)
        return BoundWindowCommands(ref)

    @property
    def session(self) -> BoundSessionCommands:
        """Session-scoped commands bound to this handle's session."""
        ref = self._ref if isinstance(self._ref, SlotRef) else SessionTarget(self._ref)
        return BoundSessionCommands(ref)

    def _parent(self, suffix: str = "") -> str | int | None | SlotRef:
        """Return the ``-t`` parent for a creation off this handle (slot or id)."""
        if isinstance(self._ref, SlotRef):
            return SlotRef(self._ref.slot, suffix)
        return f"{self._ref}{suffix}" if suffix else self._ref

    def split(
        self,
        *,
        horizontal: bool = False,
        shell: str | None = None,
        start_directory: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> ForwardHandle:
        """Split this handle's active pane; return a handle to the new pane."""
        self._require("split", "pane", "window")
        return self._plan._create(
            self._parent(),
            "pane",
            "split-window",
            _split_args(horizontal, shell, start_directory, environment),
        )

    def new_window(
        self,
        *,
        name: str | None = None,
        start_directory: str | None = None,
        environment: dict[str, str] | None = None,
        window_shell: str | None = None,
    ) -> ForwardHandle:
        """Create a window in this session handle; return a window handle.

        Targets the session as ``-t $N:`` -- the (captured or concrete) session
        id with a ``:`` suffix, so it addresses a new window in that session.
        """
        self._require("new_window", "session")
        args: list[str] = []
        if name is not None:
            args += ["-n", name]
        args.extend(_location_args(start_directory, environment))
        if window_shell is not None:
            args.append(window_shell)
        return self._plan._create(
            self._parent(":"), "window", "new-window", tuple(args)
        )

    @property
    def initial_pane(self) -> ForwardHandle:
        """Return a pane handle on this session's initial (default) pane.

        A detached ``new-session`` is born with one window and pane that the
        plan otherwise can't address; this hands back a pane handle bound to the
        session (which resolves to its active pane), so the default window can be
        decorated or split instead of orphaned. Session handles only.
        """
        if self._kind != "session":
            msg = f"initial_pane is only on a session handle, not a {self._kind} handle"
            raise TypeError(msg)
        return ForwardHandle(self._plan, self._ref, "pane")

    @property
    def initial_window(self) -> ForwardHandle:
        """Return a window handle on this session's initial (default) window."""
        if self._kind != "session":
            msg = (
                f"initial_window is only on a session handle, not a {self._kind} handle"
            )
            raise TypeError(msg)
        return ForwardHandle(self._plan, self._ref, "window")

    def do(self, build: cabc.Callable[[ForwardHandle], IntoCommands]) -> ForwardHandle:
        """Decorate this handle via its namespaces (reused, no new vocabulary)."""
        self._plan._steps.extend(_Decorate(call) for call in _to_calls(build(self)))
        return self

    def _require(self, verb: str, *kinds: Kind) -> None:
        """Reject a creation verb used on a handle of the wrong tmux scope."""
        if self._kind not in kinds:
            allowed = " or ".join(kinds)
            msg = f"{verb}() needs a {allowed} handle, not a {self._kind} handle"
            raise TypeError(msg)


class ForwardPlan:
    r"""A builder for a multi-handle forward plan, resolved over N dispatches.

    Hand out independent handles across every tmux scope -- :meth:`new_session`,
    then :meth:`ForwardHandle.new_window`, then :meth:`split` -- decorate each
    through its reused namespaces, then :meth:`run_resolving` (sync) or
    :meth:`run_resolving_async`: one creation per dispatch (``-P -F`` capture),
    the downstream commands folded into one trailing ``\;`` chain with the
    captured ids substituted in.

    Examples
    --------
    Two independent panes, resolved over three dispatches against a fake server
    that hands back fabricated pane ids:

    >>> from libtmux._experimental.chain.plan import PaneTarget
    >>> class _FakeServer:
    ...     count = 6
    ...     def cmd(self, *argv):
    ...         _FakeServer.count += 1
    ...         line = [f"%{_FakeServer.count}"]
    ...         return type("R", (), {"stdout": line, "stderr": [], "returncode": 0})()
    >>> plan = ForwardPlan(PaneTarget("%1"))
    >>> left, right = plan.split(horizontal=True), plan.split()
    >>> _ = left.do(lambda h: h.cmd.send_keys("vim", enter=True))
    >>> _ = right.do(lambda h: h.cmd.send_keys("htop", enter=True))
    >>> plan.run_resolving(_FakeServer()).bindings
    {0: '%7', 1: '%8'}
    """

    def __init__(self, seed: AnyTarget | None = None) -> None:
        self._steps: list[_Step] = []
        self._n = 0
        self._seed = seed
        self._seed_query: PaneQuery | None = None

    @classmethod
    def from_pane(cls, pane: PaneSeed) -> ForwardPlan:
        """Seed from an existing pane (a live ``Pane``, a ref, a target, or an id)."""
        return cls(seed=PaneTarget(_id_of(pane, "pane_id")))

    @classmethod
    def from_window(cls, window: WindowSeed) -> ForwardPlan:
        """Seed from an existing window -- ``split`` splits its active pane."""
        return cls(seed=WindowTarget(_id_of(window, "window_id")))

    @classmethod
    def from_session(cls, session: SessionSeed) -> ForwardPlan:
        """Seed from an existing session -- ``new_window`` adds windows to it."""
        return cls(seed=SessionTarget(_id_of(session, "session_id")))

    @classmethod
    def from_query(cls, query: PaneQuery) -> ForwardPlan:
        """Seed the plan from the first row of a live query (read at run time)."""
        plan = cls(seed=None)
        plan._seed_query = query
        return plan

    @property
    def seed(self) -> ForwardHandle:
        """A handle to the existing seed object -- decorate it or create off it.

        Lets the pre-existing seed take part in the plan like a created handle:
        ``plan.seed.do(...)`` decorates it, and (by scope) ``plan.seed.split()`` /
        ``plan.seed.new_window()`` create children of it.
        """
        if self._seed is None:
            msg = "plan has no concrete seed (use from_pane/from_window/from_session)"
            raise ValueError(msg)
        return ForwardHandle(self, str(_target_arg(self._seed)), _kind_of(self._seed))

    def _seed_target(self) -> str | int | None | SlotRef:
        if self._seed_query is not None:
            return SlotRef(_SEED)
        if self._seed is None:
            return None
        return _target_arg(self._seed)

    def _create(
        self,
        parent: str | int | None | SlotRef,
        kind: Kind,
        name: str,
        args: tuple[str, ...],
    ) -> ForwardHandle:
        slot = self._n
        self._n += 1
        self._steps.append(_Create(slot, kind, CommandCall(name, args, target=parent)))
        return ForwardHandle(self, SlotRef(slot), kind)

    def split(
        self,
        *,
        horizontal: bool = False,
        shell: str | None = None,
        start_directory: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> ForwardHandle:
        """Split the seed (root); return a handle to the new pane."""
        return self._create(
            self._seed_target(),
            "pane",
            "split-window",
            _split_args(horizontal, shell, start_directory, environment),
        )

    def new_session(
        self,
        *,
        name: str | None = None,
        start_directory: str | None = None,
        environment: dict[str, str] | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> ForwardHandle:
        """Create a detached session; return a session handle."""
        args: list[str] = ["-d"]
        if name is not None:
            args += ["-s", name]
        args.extend(_location_args(start_directory, environment))
        if width is not None:
            args += ["-x", str(width)]
        if height is not None:
            args += ["-y", str(height)]
        return self._create(None, "session", "new-session", tuple(args))

    def new_window(
        self,
        *,
        name: str | None = None,
        start_directory: str | None = None,
        environment: dict[str, str] | None = None,
        window_shell: str | None = None,
    ) -> ForwardHandle:
        """Create a window in the seed session (requires :meth:`from_session`)."""
        return self.seed.new_window(
            name=name,
            start_directory=start_directory,
            environment=environment,
            window_shell=window_shell,
        )

    def run_resolving(self, runner: PlanRunner) -> Resolved:
        """Resolve over N dispatches against a live server (sync)."""
        return run_sync(drive(tuple(self._steps), seed_query=self._seed_query), runner)

    async def run_resolving_async(self, runner: AsyncPlanRunner) -> Resolved:
        """Resolve over N dispatches against a live server (async, same core)."""
        return await run_async(
            drive(tuple(self._steps), seed_query=self._seed_query), runner
        )
