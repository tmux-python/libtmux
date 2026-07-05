"""A fluent, forward-ref builder that folds a session build to a few dispatches.

``plan()`` opens a :class:`PlanBuilder` -- a thin recorder over a Core
:class:`~libtmux.experimental.ops.plan.LazyPlan`. Navigating it
(:meth:`PlanBuilder.new_session` -> :class:`SessionRef` ->
:class:`WindowRef` -> :meth:`WindowRef.pane`) records create operations and
hands back forward handles (:class:`~libtmux.experimental.query.ForwardPaneRef`)
that address objects the plan will create. Nothing runs until
:meth:`PlanBuilder.run` (or its async twin :meth:`PlanBuilder.arun`), which folds
the recorded operations into a handful of ``tmux a ; b`` dispatches by default
(a :class:`~libtmux.experimental.ops.planner.MarkedPlanner`).

Named objects (sessions, windows) are addressed by name so their sub-operations
fold; a pane -- which has no name -- is addressed by a forward
:class:`~libtmux.experimental.ops._types.SlotRef`, resolved from the creating
operation's captured id at execution.

Examples
--------
>>> from libtmux.experimental.engines.concrete import ConcreteEngine
>>> p = plan()
>>> pane = p.new_session("dev").window().pane()
>>> bottom = pane.do(lambda c: c.send_keys("vim")).split()
>>> bottom.do(lambda c: c.send_keys("htop")) is bottom
True
>>> [op.kind for op in p.plan.operations]
['new_session', 'send_keys', 'split_window', 'send_keys']
>>> p.run(ConcreteEngine()).ok
True
"""

from __future__ import annotations

import asyncio
import time
import typing as t
from dataclasses import dataclass, field

from libtmux.experimental.ops import (
    BoundedPlanner,
    DisplayMessage,
    LazyPlan,
    MarkedPlanner,
    NameRef,
    NewSession,
    NewWindow,
    arun,
    run,
)
from libtmux.experimental.ops.plan import _resolve
from libtmux.experimental.query import ForwardPaneRef, _PaneRefBase

if t.TYPE_CHECKING:
    from libtmux.experimental.engines.base import AsyncTmuxEngine, TmuxEngine
    from libtmux.experimental.ops import Planner, PlanResult, StepReport
    from libtmux.experimental.ops._types import SlotRef, Target

_CURSOR_FMT = "#{cursor_x},#{cursor_y}"
_WAIT_PANE_POLLS = 40
_WAIT_PANE_INTERVAL = 0.05
#: The probe format for a session find-or-create -- the ids
#: ``NewSession(capture_panes=True)`` captures, so a found session binds the
#: same self/window/pane slots a created one would.
_SESSION_PROBE = "#{session_id} #{window_id} #{pane_id}"


def _pane_ready(cursor: str) -> bool:
    """Whether a pane's cursor has left the origin (its shell prompt drew)."""
    return bool(cursor) and cursor != "0,0"


@dataclass(frozen=True)
class _HostAction:
    """A host-side pause recorded after an operation (a hard fold boundary)."""

    kind: t.Literal["sleep", "wait"]
    seconds: float = 0.0
    pane: Target | None = None


@dataclass(frozen=True)
class WindowRef:
    """A window in a plan; navigate to its first pane.

    ``first_pane`` is a forward :class:`~..ops._types.SlotRef` to the window's
    first pane (captured by the creating ``new-session`` / ``new-window``).
    """

    plan: LazyPlan
    first_pane: SlotRef

    def pane(self) -> ForwardPaneRef:
        """Return a forward handle to the window's first pane.

        Examples
        --------
        >>> p = plan()
        >>> ref = p.new_session("dev").window().pane()
        >>> isinstance(ref, ForwardPaneRef)
        True
        """
        return ForwardPaneRef(self.plan, self.first_pane)


@dataclass(frozen=True)
class SessionRef:
    """A session in a plan; reach its first window or add another.

    The session is name-addressed (so its window operations fold); ``create`` is
    the ``new-session`` slot, whose captured first pane backs the first window.
    """

    plan: LazyPlan
    name: str
    create: SlotRef

    def window(self) -> WindowRef:
        """Return the session's first window.

        Examples
        --------
        >>> isinstance(plan().new_session("dev").window(), WindowRef)
        True
        """
        return WindowRef(self.plan, self.create.pane)

    def new_window(self, name: str) -> WindowRef:
        """Create another window in this session (name-addressed).

        Examples
        --------
        >>> p = plan()
        >>> _ = p.new_session("dev").new_window("logs")
        >>> [op.kind for op in p.plan.operations]
        ['new_session', 'new_window']
        """
        slot = self.plan.add(
            NewWindow(target=NameRef(self.name), name=name, capture_pane=True),
        )
        return WindowRef(self.plan, slot.pane)


@dataclass(frozen=True)
class PlanBuilder:
    """A fluent recorder over a :class:`LazyPlan`; :meth:`run` folds by default."""

    plan: LazyPlan = field(default_factory=LazyPlan)
    _host_after: dict[int, list[_HostAction]] = field(default_factory=dict)

    def new_session(self, name: str) -> SessionRef:
        """Create a session, capturing its first pane for forward refs.

        Examples
        --------
        >>> p = plan()
        >>> ref = p.new_session("dev")
        >>> isinstance(ref, SessionRef)
        True
        >>> [op.kind for op in p.plan.operations]
        ['new_session']
        """
        slot = self.plan.add(NewSession(session_name=name, capture_panes=True))
        return SessionRef(self.plan, name, slot)

    def find_or_create_session(self, name: str) -> SessionRef:
        """Reach session *name*, creating it only if it does not exist.

        At build time this records the same create as :meth:`new_session`, but
        makes it conditional (see :meth:`~..ops.plan.LazyPlan.ensure`): at
        execution the plan probes for *name* and reuses the live session when it
        is already there, so a re-run is idempotent instead of a duplicate.

        Examples
        --------
        >>> from libtmux.experimental.engines.concrete import ConcreteEngine
        >>> p = plan()
        >>> _ = p.find_or_create_session("dev").window().pane()
        >>> [op.kind for op in p.plan.operations]
        ['new_session']
        >>> p.run(ConcreteEngine()).ok
        True
        """
        create = NewSession(session_name=name, capture_panes=True)
        slot = self.plan.add(create)
        self.plan.ensure(
            slot.slot,
            DisplayMessage(target=NameRef(name), message=_SESSION_PROBE),
        )
        return SessionRef(self.plan, name, slot)

    def sleep(self, seconds: float) -> PlanBuilder:
        """Pause *seconds* after the last recorded op (a hard fold boundary).

        A host step never folds into a ``tmux`` dispatch, so the chain breaks
        before and after it; the pause runs between dispatches at build time.

        Examples
        --------
        >>> from libtmux.experimental.engines.concrete import ConcreteEngine
        >>> p = plan()
        >>> pane = p.new_session("dev").window().pane()
        >>> _ = pane.do(lambda c: c.send_keys("slow-start"))
        >>> p.sleep(0.0).run(ConcreteEngine()).ok
        True
        """
        self._record_host(_HostAction("sleep", seconds=seconds))
        return self

    def wait(self, pane: _PaneRefBase) -> PlanBuilder:
        """Wait for *pane*'s shell prompt before the next dispatch (anti-race).

        Polls the pane's cursor until it leaves the origin, so a follow-up
        command isn't sent before the shell is ready. A hard fold boundary.

        Examples
        --------
        >>> p = plan()
        >>> pane = p.new_session("dev").window().pane()
        >>> p.wait(pane) is p
        True
        """
        self._record_host(_HostAction("wait", pane=pane.target))
        return self

    def _record_host(self, action: _HostAction) -> None:
        """Record *action* after the plan's current last operation."""
        index = len(self.plan.operations) - 1
        if index >= 0:
            self._host_after.setdefault(index, []).append(action)

    def _planner(self, planner: Planner | None) -> Planner:
        """Return the base planner, bounded by host-step boundaries if any."""
        base = planner or MarkedPlanner()
        if self._host_after:
            return BoundedPlanner(base, frozenset(self._host_after))
        return base

    def run(
        self,
        engine: TmuxEngine,
        *,
        version: str | None = None,
        planner: Planner | None = None,
    ) -> PlanResult:
        """Build over *engine*, folding to a few dispatches (``MarkedPlanner``).

        Examples
        --------
        >>> from libtmux.experimental.engines.concrete import ConcreteEngine
        >>> p = plan()
        >>> _ = p.new_session("dev").window().pane().do(lambda c: c.send_keys("vim"))
        >>> p.run(ConcreteEngine()).ok
        True
        """

        def on_step(report: StepReport) -> None:
            for action in self._host_after.get(report.step.indices[-1], ()):
                if action.kind == "sleep":
                    time.sleep(action.seconds)
                elif action.pane is not None:
                    op = _resolve(
                        DisplayMessage(target=action.pane, message=_CURSOR_FMT),
                        report.bindings,
                    )
                    for _ in range(_WAIT_PANE_POLLS):
                        if _pane_ready(run(op, engine, version=version).text):
                            break
                        time.sleep(_WAIT_PANE_INTERVAL)

        return self.plan.execute(
            engine,
            version=version,
            planner=self._planner(planner),
            on_step=on_step,
        )

    async def arun(
        self,
        engine: AsyncTmuxEngine,
        *,
        version: str | None = None,
        planner: Planner | None = None,
    ) -> PlanResult:
        """Async twin of :meth:`run` (same fold and host steps, ``await``ed).

        Examples
        --------
        >>> import asyncio
        >>> from libtmux.experimental.engines.concrete import AsyncConcreteEngine
        >>> p = plan()
        >>> _ = p.new_session("dev").window().pane().do(lambda c: c.send_keys("vim"))
        >>> asyncio.run(p.arun(AsyncConcreteEngine())).ok
        True
        """

        async def on_step(report: StepReport) -> None:
            for action in self._host_after.get(report.step.indices[-1], ()):
                if action.kind == "sleep":
                    await asyncio.sleep(action.seconds)
                elif action.pane is not None:
                    op = _resolve(
                        DisplayMessage(target=action.pane, message=_CURSOR_FMT),
                        report.bindings,
                    )
                    for _ in range(_WAIT_PANE_POLLS):
                        result = await arun(op, engine, version=version)
                        if _pane_ready(result.text):
                            break
                        await asyncio.sleep(_WAIT_PANE_INTERVAL)

        return await self.plan.aexecute(
            engine,
            version=version,
            planner=self._planner(planner),
            on_step=on_step,
        )

    def preview(self, *, version: str | None = None) -> list[tuple[str, ...] | None]:
        """Render a pure argv dry-run of the recorded plan (no engine).

        Examples
        --------
        >>> p = plan()
        >>> _ = p.new_session("dev")
        >>> argv = p.preview()[0]
        >>> argv[:4]
        ('new-session', '-d', '-s', 'dev')
        >>> argv[-1]
        '#{session_id} #{window_id} #{pane_id}'
        """
        return self.plan.preview(version=version)


def plan() -> PlanBuilder:
    """Start a fluent, forward-ref plan build.

    Examples
    --------
    >>> plan().plan.operations
    ()
    """
    return PlanBuilder()
