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

import typing as t
from dataclasses import dataclass, field

from libtmux.experimental.ops import (
    LazyPlan,
    MarkedPlanner,
    NameRef,
    NewSession,
    NewWindow,
)
from libtmux.experimental.query import ForwardPaneRef

if t.TYPE_CHECKING:
    from libtmux.experimental.engines.base import AsyncTmuxEngine, TmuxEngine
    from libtmux.experimental.ops import Planner, PlanResult
    from libtmux.experimental.ops._types import SlotRef


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
        return self.plan.execute(
            engine,
            version=version,
            planner=planner or MarkedPlanner(),
        )

    async def arun(
        self,
        engine: AsyncTmuxEngine,
        *,
        version: str | None = None,
        planner: Planner | None = None,
    ) -> PlanResult:
        """Async twin of :meth:`run` (same fold, ``await``ed)."""
        return await self.plan.aexecute(
            engine,
            version=version,
            planner=planner or MarkedPlanner(),
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
