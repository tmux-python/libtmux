"""Session-scope objects (eager / lazy / async) over the operation spine."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.objects.window import AsyncWindow, EagerWindow, LazyWindow
from libtmux.experimental.ops import (
    KillSession,
    NewWindow,
    RenameSession,
    arun,
    run,
)
from libtmux.experimental.ops._types import SessionId
from libtmux.experimental.ops.results import _require_created_id

if t.TYPE_CHECKING:
    from libtmux.experimental.engines.base import AsyncTmuxEngine, TmuxEngine
    from libtmux.experimental.ops._types import Target
    from libtmux.experimental.ops.plan import LazyPlan
    from libtmux.experimental.ops.results import Result


@dataclass(frozen=True)
class EagerSession:
    """A live session object; methods execute immediately.

    Attributes
    ----------
    engine : TmuxEngine
        Engine used to execute session operations.
    session_id : str
        Stable tmux session identifier.
    version : str or None
        tmux version used when rendering operations.

    Examples
    --------
    >>> from libtmux.experimental.engines import MockEngine
    >>> session = EagerSession(MockEngine(), "$0")
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
        """Create a window in this session; return a live window object."""
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
        created_id = _require_created_id(result)
        return EagerWindow(self.engine, created_id, self.version)

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
    """A deferred session object; methods record into a plan.

    Attributes
    ----------
    plan : LazyPlan
        Plan that receives recorded session operations.
    ref : Target
        Concrete or deferred target for this session.

    Examples
    --------
    >>> from libtmux.experimental.engines import MockEngine
    >>> from libtmux.experimental.ops import LazyPlan
    >>> from libtmux.experimental.ops._types import SessionId
    >>> plan = LazyPlan()
    >>> session = LazySession(plan, SessionId("$0"))
    >>> window = session.new_window(name="build")
    >>> _ = session.rename("work")
    >>> plan.execute(MockEngine()).ok
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
        """Record a new window; return a deferred window object."""
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
    """An async live session object: the eager session, awaited.

    Attributes
    ----------
    engine : AsyncTmuxEngine
        Engine used to execute session operations asynchronously.
    session_id : str
        Stable tmux session identifier.
    version : str or None
        tmux version used when rendering operations.
    """

    engine: AsyncTmuxEngine
    session_id: str
    version: str | None = None

    async def new_window(
        self,
        *,
        name: str | None = None,
        start_directory: str | None = None,
    ) -> AsyncWindow:
        """Create a window in this session; return a live async window object."""
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
        created_id = _require_created_id(result)
        return AsyncWindow(self.engine, created_id, self.version)

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
