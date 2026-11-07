"""Live-tmux connection helpers for chainable-commands plans.

These bridge the typed plan layer to a real :class:`libtmux.Session`:
:func:`snapshot_from_session` reads live panes into a pure
:class:`~libtmux._experimental.chain.plan.TmuxSnapshot`, and
:class:`SessionPlanExecutor` satisfies
:class:`~libtmux._experimental.chain.plan.PlanRunner` so a
:class:`~libtmux._experimental.chain.plan.CommandPlan` resolves and
dispatches against an actual tmux server in one invocation.

Note
----
This is an **experimental** API, not covered by the project's versioning policy.
It may change or be removed between any releases without notice.
"""

from __future__ import annotations

import asyncio
import typing as t

from libtmux._experimental.chain.ir import (
    Arg,
    CommandResultLike,
    CommandRunner,
)
from libtmux._experimental.chain.plan import (
    PaneRef,
    PaneTarget,
    SessionTarget,
    TmuxSnapshot,
    WindowTarget,
)

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session


def snapshot_from_session(session: Session) -> TmuxSnapshot:
    """Read a live session's panes into a pure snapshot.

    Parameters
    ----------
    session : libtmux.Session
        A live session to read panes from.

    Returns
    -------
    TmuxSnapshot
        Typed pane rows with their pane, window, and session targets.

    Examples
    --------
    >>> snapshot = snapshot_from_session(session)
    >>> len(snapshot.panes) >= 1
    True
    >>> snapshot.panes[0].pane_id.value.startswith("%")
    True
    """
    rows: list[PaneRef] = []
    for pane in session.panes:
        pane_id = pane.pane_id
        window_id = pane.window_id
        session_id = pane.session_id
        # Fail closed: a missing id would render an empty ``-t ''`` target,
        # which tmux resolves to the current/attached target. Skip the row
        # rather than emit a target that silently mis-resolves.
        if pane_id is None or window_id is None or session_id is None:
            continue
        rows.append(
            PaneRef.concrete(
                pane_id=PaneTarget(pane_id),
                window_id=WindowTarget(window_id),
                session_id=SessionTarget(session_id),
                pane_index=int(pane.pane_index) if pane.pane_index is not None else 0,
                active=pane.pane_active == "1",
                title=pane.pane_title or "",
            ),
        )
    return TmuxSnapshot(panes=tuple(rows))


class SessionPlanExecutor:
    r"""A :class:`PlanRunner` backed by a live :class:`libtmux.Session`.

    Dispatches commands through ``session.server.cmd`` and resolves snapshots
    via :func:`snapshot_from_session`, so a plan executes against real tmux in a
    single native ``\\;`` invocation.

    Examples
    --------
    >>> runner = SessionPlanExecutor(session)
    >>> runner.snapshot().panes[0].pane_id.value.startswith("%")
    True

    A plan resolves and dispatches once through the runner:

    >>> from libtmux._experimental.chain.plan import panes
    >>> plan = panes().filter(active=True).commands(
    ...     lambda pane: pane.cmd.send_keys("echo libtmux", enter=True),
    ... )
    >>> plan.run(runner)
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def cmd(
        self,
        cmd: str,
        *args: Arg,
        target: str | int | None = None,
    ) -> CommandResultLike:
        """Dispatch one tmux command through the live server.

        Examples
        --------
        >>> SessionPlanExecutor(session).cmd(
        ...     "set-option", "-g", "@cc_conn_demo", "1"
        ... ).returncode
        0
        """
        # A live Server already satisfies the CommandRunner protocol; the cast
        # keeps the variadic dispatch cleanly typed (mypy and ty both resolve
        # ``Server.cmd`` to a union otherwise).
        runner = t.cast("CommandRunner", self.session.server)
        return runner.cmd(cmd, *args, target=target)

    def snapshot(self) -> TmuxSnapshot:
        """Return a fresh snapshot of the session's panes.

        Examples
        --------
        >>> SessionPlanExecutor(session).snapshot().panes[0].pane_id.value[0]
        '%'
        """
        return snapshot_from_session(self.session)


class AsyncSessionPlanExecutor:
    """An ``AsyncPlanRunner`` backed by a live :class:`libtmux.Session`.

    libtmux dispatch is synchronous, so this offloads each blocking call to a
    worker thread with :func:`asyncio.to_thread`. The plan still compiles to one
    native sequence and dispatches once; it simply does not block the event
    loop, so independent plans can resolve and dispatch concurrently.

    Examples
    --------
    >>> import asyncio
    >>> runner = AsyncSessionPlanExecutor(session)
    >>> async def _demo() -> bool:
    ...     snapshot = await runner.snapshot()
    ...     return snapshot.panes[0].pane_id.value.startswith("%")
    >>> asyncio.run(_demo())
    True

    A plan resolves and dispatches once, without blocking the loop:

    >>> from libtmux._experimental.chain import aio
    >>> plan = aio.panes().filter(active=True).commands(
    ...     lambda pane: pane.cmd.send_keys("echo libtmux", enter=True),
    ... )
    >>> asyncio.run(plan.run(runner))
    """

    def __init__(self, session: Session) -> None:
        self._sync = SessionPlanExecutor(session)

    async def cmd(
        self,
        cmd: str,
        *args: Arg,
        target: str | int | None = None,
    ) -> CommandResultLike:
        """Dispatch one tmux command in a worker thread."""
        return await asyncio.to_thread(self._sync.cmd, cmd, *args, target=target)

    async def snapshot(self) -> TmuxSnapshot:
        """Return a fresh snapshot, read in a worker thread."""
        return await asyncio.to_thread(self._sync.snapshot)


class ServerPlanRunner:
    """A ``PlanRunner`` backed by a live :class:`libtmux.Server`.

    For create-from-scratch plans (``ForwardPlan().new_session(...)``) that have
    no -- and need no -- pre-existing session: it dispatches straight through
    ``server.cmd`` instead of borrowing an unrelated session's executor.
    ``snapshot()`` is empty, since a server-level runner is for creation, not
    query seeding -- a query-seeded plan still wants a :class:`SessionPlanExecutor`.

    Examples
    --------
    >>> runner = ServerPlanRunner(server)
    >>> runner.snapshot().panes
    ()
    >>> runner.cmd("set-option", "-g", "@cc_srv_demo", "1").returncode
    0
    """

    def __init__(self, server: Server) -> None:
        self.server = server

    def cmd(
        self,
        cmd: str,
        *args: Arg,
        target: str | int | None = None,
    ) -> CommandResultLike:
        """Dispatch one tmux command through the live server."""
        runner = t.cast("CommandRunner", self.server)
        return runner.cmd(cmd, *args, target=target)

    def snapshot(self) -> TmuxSnapshot:
        """Return an empty snapshot (a server runner is for creation, not queries)."""
        return TmuxSnapshot(panes=())


class AsyncServerPlanRunner:
    """An ``AsyncPlanRunner`` backed by a live :class:`libtmux.Server`.

    The async companion to :class:`ServerPlanRunner`; offloads the blocking
    dispatch via :func:`asyncio.to_thread`.

    Examples
    --------
    >>> import asyncio
    >>> asyncio.run(AsyncServerPlanRunner(server).snapshot()).panes
    ()
    """

    def __init__(self, server: Server) -> None:
        self._sync = ServerPlanRunner(server)

    async def cmd(
        self,
        cmd: str,
        *args: Arg,
        target: str | int | None = None,
    ) -> CommandResultLike:
        """Dispatch one tmux command in a worker thread."""
        return await asyncio.to_thread(self._sync.cmd, cmd, *args, target=target)

    async def snapshot(self) -> TmuxSnapshot:
        """Return an empty snapshot in a worker thread."""
        return await asyncio.to_thread(self._sync.snapshot)
