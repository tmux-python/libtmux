"""Server-scope objects -- the entry points for object navigation."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.objects.session import (
    AsyncSession,
    EagerSession,
    LazySession,
)
from libtmux.experimental.ops import NewSession, arun, run

if t.TYPE_CHECKING:
    from libtmux.experimental.engines.base import AsyncTmuxEngine, TmuxEngine
    from libtmux.experimental.ops.plan import LazyPlan


@dataclass(frozen=True)
class EagerServer:
    """A live server object; the root of eager object navigation.

    Examples
    --------
    >>> from libtmux.experimental.engines import ConcreteEngine
    >>> server = EagerServer(ConcreteEngine())
    >>> session = server.new_session(name="work")
    >>> session.session_id
    '$1'
    >>> pane = session.new_window().split()
    >>> pane.pane_id
    '%1'
    """

    engine: TmuxEngine
    version: str | None = None

    def new_session(
        self,
        *,
        name: str | None = None,
        start_directory: str | None = None,
    ) -> EagerSession:
        """Create a detached session; return a live session object."""
        result = run(
            NewSession(session_name=name, start_directory=start_directory),
            self.engine,
            version=self.version,
        )
        result.raise_for_status()
        assert result.new_id is not None
        return EagerSession(self.engine, result.new_id, self.version)

    @classmethod
    def for_server(cls, server: t.Any, *, version: str | None = None) -> EagerServer:
        """Bind an eager object to a live :class:`libtmux.Server`'s classic engine."""
        from libtmux.experimental.engines import SubprocessEngine

        return cls(SubprocessEngine.for_server(server), version=version)


@dataclass(frozen=True)
class LazyServer:
    """A deferred server object; records session creation into a plan.

    Examples
    --------
    >>> from libtmux.experimental.engines import ConcreteEngine
    >>> from libtmux.experimental.ops import LazyPlan
    >>> plan = LazyPlan()
    >>> server = LazyServer(plan)
    >>> session = server.new_session(name="work")
    >>> _ = session.new_window(name="build")
    >>> plan.execute(ConcreteEngine()).ok
    True
    """

    plan: LazyPlan

    def new_session(
        self,
        *,
        name: str | None = None,
        start_directory: str | None = None,
    ) -> LazySession:
        """Record a new session; return a deferred session object."""
        slot = self.plan.add(
            NewSession(session_name=name, start_directory=start_directory),
        )
        return LazySession(self.plan, slot)


@dataclass(frozen=True)
class AsyncServer:
    """An async live server object: the eager server, awaited."""

    engine: AsyncTmuxEngine
    version: str | None = None

    async def new_session(
        self,
        *,
        name: str | None = None,
        start_directory: str | None = None,
    ) -> AsyncSession:
        """Create a detached session; return a live async session object."""
        result = await arun(
            NewSession(session_name=name, start_directory=start_directory),
            self.engine,
            version=self.version,
        )
        result.raise_for_status()
        assert result.new_id is not None
        return AsyncSession(self.engine, result.new_id, self.version)

    @classmethod
    def for_server(cls, server: t.Any, *, version: str | None = None) -> AsyncServer:
        """Bind an async object to a live :class:`libtmux.Server`'s socket."""
        from libtmux.experimental.engines import AsyncSubprocessEngine

        return cls(AsyncSubprocessEngine.for_server(server), version=version)
