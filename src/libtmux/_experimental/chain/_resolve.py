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
    _target_arg,
    _to_calls,
)

if t.TYPE_CHECKING:
    import collections.abc as cabc

    from libtmux._experimental.chain._async import AsyncPlanRunner
    from libtmux._experimental.chain.plan import IntoCommands, PlanRunner

Kind = t.Literal["pane", "window", "session"]
_CAPTURE: dict[Kind, str] = {
    "pane": "#{pane_id}",
    "window": "#{window_id}",
    "session": "#{session_id}",
}
_SEED = -1  # reserved binding key for a query-resolved seed


class NoSeedResolved(RuntimeError):
    """Raised when a query-seeded forward plan matches no pane."""


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


def _with_capture(call: CommandCall, kind: Kind) -> tuple[str, ...]:
    """Append ``-P -F '#{<kind>_id}'`` so the creation prints its stable id."""
    return (*call.argv(), "-P", "-F", _CAPTURE[kind])


def _subst(call: CommandCall, bindings: dict[int, str]) -> CommandCall:
    """Replace a SlotRef target with the captured concrete id (plus its suffix)."""
    if isinstance(call.target, SlotRef):
        resolved = bindings[call.target.slot] + call.target.suffix
        return dataclasses.replace(call, target=resolved)
    return call


def drive(
    steps: tuple[_Step, ...],
    *,
    seed_query: PaneQuery | None = None,
) -> t.Generator[Request, t.Any, Resolved]:
    r"""Sans-I/O resolution core: yield a :class:`Request`, resume via ``.send``.

    Each :class:`_Create` is dispatched alone with ``-P -F`` id capture; a run of
    :class:`_Decorate`\\s folds into one trailing ``\;`` chain with the captured
    ids substituted. No awaits, no runner, no threads -- a pure state machine the
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

    for step in steps:
        if isinstance(step, _Create):
            if tail:
                chain = CommandChain(tuple(_subst(c, bindings) for c in tail))
                results.append((yield Dispatch(chain.argv(), None)))
                tail = []
            argv = _with_capture(_subst(step.call, bindings), step.kind)
            result = yield Dispatch(argv, step.slot)
            results.append(result)
            bindings[step.slot] = result.stdout[0].strip()
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
def _split_args(horizontal: bool, shell: str | None) -> tuple[str, ...]:
    """Render the ``split-window`` flags shared by the plan- and handle-level split."""
    args = ["-h" if horizontal else "-v"]
    if shell is not None:
        args.append(shell)
    return tuple(args)


class ForwardHandle:
    """A reference to a forward object (a slot) inside a :class:`ForwardPlan`.

    One type spans all three tmux scopes: the handle knows its ``kind``
    (``pane``/``window``/``session``), so its creation verbs stay scope-correct
    -- ``new_window()`` only on a session, ``split()`` only on a pane or window
    -- while the ``.cmd``/``.window``/``.session`` command namespaces are reused
    unchanged, each bound to this handle's
    :class:`~libtmux._experimental.chain.ir.SlotRef` so the resolver substitutes
    the captured id.
    """

    def __init__(self, plan: ForwardPlan, slot: int, kind: Kind) -> None:
        self._plan = plan
        self._slot = slot
        self._kind = kind

    @property
    def cmd(self) -> BoundPaneCommands:
        """Pane-scoped commands bound to this handle."""
        return BoundPaneCommands(SlotRef(self._slot))

    @property
    def window(self) -> BoundWindowCommands:
        """Window-scoped commands (a pane id resolves up to its window)."""
        return BoundWindowCommands(SlotRef(self._slot))

    @property
    def session(self) -> BoundSessionCommands:
        """Session-scoped commands bound to this handle's session."""
        return BoundSessionCommands(SlotRef(self._slot))

    def split(
        self, *, horizontal: bool = False, shell: str | None = None
    ) -> ForwardHandle:
        """Split this handle's active pane; return a handle to the new pane."""
        self._require("split", "pane", "window")
        return self._plan._create(
            SlotRef(self._slot), "pane", "split-window", _split_args(horizontal, shell)
        )

    def new_window(self, *, name: str | None = None) -> ForwardHandle:
        """Create a window in this session handle; return a window handle.

        Targets the session as ``-t $N:`` -- the captured session id with a
        ``:`` suffix, so a plain ``$N`` capture addresses a new window in it.
        """
        self._require("new_window", "session")
        args = ("-n", name) if name is not None else ()
        return self._plan._create(
            SlotRef(self._slot, ":"), "window", "new-window", args
        )

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
    def from_pane(cls, pane: PaneRef) -> ForwardPlan:
        """Seed the plan from a concrete pane row."""
        return cls(seed=pane.pane_id)

    @classmethod
    def from_query(cls, query: PaneQuery) -> ForwardPlan:
        """Seed the plan from the first row of a live query (read at run time)."""
        plan = cls(seed=None)
        plan._seed_query = query
        return plan

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
        return ForwardHandle(self, slot, kind)

    def split(
        self, *, horizontal: bool = False, shell: str | None = None
    ) -> ForwardHandle:
        """Split the seed (root); return a handle to the new pane."""
        return self._create(
            self._seed_target(), "pane", "split-window", _split_args(horizontal, shell)
        )

    def new_session(self, *, name: str | None = None) -> ForwardHandle:
        """Create a detached session; return a session handle."""
        args = ("-d", "-s", name) if name is not None else ("-d",)
        return self._create(None, "session", "new-session", args)

    def run_resolving(self, runner: PlanRunner) -> Resolved:
        """Resolve over N dispatches against a live server (sync)."""
        return run_sync(drive(tuple(self._steps), seed_query=self._seed_query), runner)

    async def run_resolving_async(self, runner: AsyncPlanRunner) -> Resolved:
        """Resolve over N dispatches against a live server (async, same core)."""
        return await run_async(
            drive(tuple(self._steps), seed_query=self._seed_query), runner
        )
