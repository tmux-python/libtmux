"""Client-scope objects (eager / lazy / async) over the operation spine.

A client is a *view* (a terminal attachment keyed by name/tty), not part of the
ownership chain, but tmux exposes client-scoped commands -- ``detach-client``,
``switch-client``, ``refresh-client`` -- so it gets a object like any other scope.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops import (
    DetachClient,
    RefreshClient,
    SwitchClient,
    arun,
    run,
)
from libtmux.experimental.ops._types import ClientName

if t.TYPE_CHECKING:
    from libtmux.experimental.engines.base import AsyncTmuxEngine, TmuxEngine
    from libtmux.experimental.ops.plan import LazyPlan
    from libtmux.experimental.ops.results import Result


@dataclass(frozen=True)
class EagerClient:
    """A live client object; methods execute immediately.

    Examples
    --------
    >>> from libtmux.experimental.engines import MockEngine
    >>> client = EagerClient(MockEngine(), "/dev/pts/3")
    >>> client.refresh().ok
    True
    >>> client.switch_to("$1").ok
    True
    """

    engine: TmuxEngine
    client_name: str
    version: str | None = None

    def detach(self) -> Result:
        """Detach this client."""
        return run(
            DetachClient(target=ClientName(self.client_name)),
            self.engine,
            version=self.version,
        )

    def refresh(self) -> Result:
        """Refresh this client."""
        return run(
            RefreshClient(target=ClientName(self.client_name)),
            self.engine,
            version=self.version,
        )

    def switch_to(self, session_id: str) -> Result:
        """Switch this client to a session."""
        return run(
            SwitchClient(client=self.client_name, to_session=session_id),
            self.engine,
            version=self.version,
        )


@dataclass(frozen=True)
class LazyClient:
    """A deferred client object; methods record into a plan."""

    plan: LazyPlan
    client_name: str

    def detach(self) -> LazyClient:
        """Record a detach; return self for chaining."""
        self.plan.add(DetachClient(target=ClientName(self.client_name)))
        return self

    def refresh(self) -> LazyClient:
        """Record a refresh; return self for chaining."""
        self.plan.add(RefreshClient(target=ClientName(self.client_name)))
        return self

    def switch_to(self, session_id: str) -> LazyClient:
        """Record a switch-client; return self for chaining."""
        self.plan.add(SwitchClient(client=self.client_name, to_session=session_id))
        return self


@dataclass(frozen=True)
class AsyncClient:
    """An async live client object: the eager client, awaited."""

    engine: AsyncTmuxEngine
    client_name: str
    version: str | None = None

    async def detach(self) -> Result:
        """Detach this client."""
        return await arun(
            DetachClient(target=ClientName(self.client_name)),
            self.engine,
            version=self.version,
        )

    async def refresh(self) -> Result:
        """Refresh this client."""
        return await arun(
            RefreshClient(target=ClientName(self.client_name)),
            self.engine,
            version=self.version,
        )

    async def switch_to(self, session_id: str) -> Result:
        """Switch this client to a session."""
        return await arun(
            SwitchClient(client=self.client_name, to_session=session_id),
            self.engine,
            version=self.version,
        )
