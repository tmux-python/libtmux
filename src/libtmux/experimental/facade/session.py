"""Session-scope facades (eager / lazy / async) over the operation spine."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.facade.window import AsyncWindow, EagerWindow, LazyWindow
from libtmux.experimental.ops import (
    KillSession,
    NewWindow,
    RenameSession,
    arun,
    run,
)
from libtmux.experimental.ops._types import SessionId

if t.TYPE_CHECKING:
    from libtmux.experimental.engines.base import AsyncTmuxEngine, TmuxEngine
    from libtmux.experimental.ops._types import Target
    from libtmux.experimental.ops.plan import LazyPlan
    from libtmux.experimental.ops.results import Result


@dataclass(frozen=True)
class EagerSession:
    """A live session handle; methods execute immediately.

    Examples
    --------
    >>> from libtmux.experimental.engines import ConcreteEngine
    >>> session = EagerSession(ConcreteEngine(), "$0")
    >>> window = session.new_window(name="build")
    >>> window.window_id
    '@1'
    >>> session.rename("work").ok
    True
    """

    engine: TmuxEngine
    session_id: str
    version: str | None = None

    def new_window(
        self,
        *,
        name: str | None = None,
        start_directory: str | None = None,
    ) -> EagerWindow:
        """Create a window in this session; return a live window handle."""
        result = run(
            NewWindow(
                target=SessionId(self.session_id),
                name=name,
                start_directory=start_directory,
            ),
            self.engine,
            version=self.version,
        )
        result.raise_for_status()
        assert result.new_id is not None
        return EagerWindow(self.engine, result.new_id, self.version)

    def rename(self, name: str) -> Result:
        """Rename this session."""
        return run(
            RenameSession(target=SessionId(self.session_id), name=name),
            self.engine,
            version=self.version,
        )

    def kill(self) -> Result:
        """Kill this session."""
        return run(
            KillSession(target=SessionId(self.session_id)),
            self.engine,
            version=self.version,
        )


@dataclass(frozen=True)
class LazySession:
    """A deferred session handle; methods record into a plan.

    Examples
    --------
    >>> from libtmux.experimental.engines import ConcreteEngine
    >>> from libtmux.experimental.ops import LazyPlan
    >>> from libtmux.experimental.ops._types import SessionId
    >>> plan = LazyPlan()
    >>> session = LazySession(plan, SessionId("$0"))
    >>> window = session.new_window(name="build")
    >>> _ = session.rename("work")
    >>> plan.execute(ConcreteEngine()).ok
    True
    """

    plan: LazyPlan
    ref: Target

    def new_window(
        self,
        *,
        name: str | None = None,
        start_directory: str | None = None,
    ) -> LazyWindow:
        """Record a new window; return a deferred window handle."""
        slot = self.plan.add(
            NewWindow(target=self.ref, name=name, start_directory=start_directory),
        )
        return LazyWindow(self.plan, slot)

    def rename(self, name: str) -> LazySession:
        """Record a rename; return self for chaining."""
        self.plan.add(RenameSession(target=self.ref, name=name))
        return self

    def kill(self) -> LazySession:
        """Record a kill; return self for chaining."""
        self.plan.add(KillSession(target=self.ref))
        return self


@dataclass(frozen=True)
class AsyncSession:
    """An async live session handle: the eager session, awaited."""

    engine: AsyncTmuxEngine
    session_id: str
    version: str | None = None

    async def new_window(
        self,
        *,
        name: str | None = None,
        start_directory: str | None = None,
    ) -> AsyncWindow:
        """Create a window in this session; return a live async window handle."""
        result = await arun(
            NewWindow(
                target=SessionId(self.session_id),
                name=name,
                start_directory=start_directory,
            ),
            self.engine,
            version=self.version,
        )
        result.raise_for_status()
        assert result.new_id is not None
        return AsyncWindow(self.engine, result.new_id, self.version)

    async def rename(self, name: str) -> Result:
        """Rename this session."""
        return await arun(
            RenameSession(target=SessionId(self.session_id), name=name),
            self.engine,
            version=self.version,
        )

    async def kill(self) -> Result:
        """Kill this session."""
        return await arun(
            KillSession(target=SessionId(self.session_id)),
            self.engine,
            version=self.version,
        )
