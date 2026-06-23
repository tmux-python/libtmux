"""Session-scope vocabulary: create, rename, kill, list, existence.

Each tool is written once as an ``async def`` over an
:class:`~libtmux.experimental.engines.base.AsyncTmuxEngine`; the public sync name
is a :func:`~._bridge.synced` twin.
"""

from __future__ import annotations

import typing as t

from libtmux.experimental.engines.base import AsyncTmuxEngine
from libtmux.experimental.mcp.target_resolver import resolve_target
from libtmux.experimental.mcp.vocabulary._bridge import synced
from libtmux.experimental.mcp.vocabulary._resolve import guard_self_kill, session_id_of
from libtmux.experimental.mcp.vocabulary._results import Listing, SessionResult
from libtmux.experimental.ops import (
    HasSession,
    KillSession,
    ListSessions,
    NewSession,
    RenameSession,
    arun,
)
from libtmux.experimental.ops._types import Target


async def acreate_session(
    engine: AsyncTmuxEngine,
    *,
    name: str | None = None,
    start_directory: str | None = None,
    environment: t.Mapping[str, str] | None = None,
    width: int | None = None,
    height: int | None = None,
    version: str | None = None,
) -> SessionResult:
    """Create a detached session (mirrors ``server.new_session``).

    Examples
    --------
    >>> from libtmux.experimental.engines import ConcreteEngine
    >>> r = create_session(ConcreteEngine(), name="work")
    >>> (r.session_id, r.name, r.first_pane_id)
    ('$1', 'work', '%1')
    """
    result = await arun(
        NewSession(
            session_name=name,
            start_directory=start_directory,
            environment=environment,
            width=width,
            height=height,
            capture_panes=True,
        ),
        engine,
        version=version,
    )
    result.raise_for_status()
    return SessionResult(
        session_id=result.new_id or "",
        name=name,
        first_window_id=result.first_window_id,
        first_pane_id=result.first_pane_id,
    )


async def arename_session(
    engine: AsyncTmuxEngine,
    target: str | Target,
    name: str,
    *,
    version: str | None = None,
) -> None:
    """Rename a session (mirrors ``session.rename_session``)."""
    (
        await arun(
            RenameSession(target=resolve_target(target), name=name),
            engine,
            version=version,
        )
    ).raise_for_status()


async def akill_session(
    engine: AsyncTmuxEngine,
    target: str | Target,
    *,
    version: str | None = None,
) -> None:
    """Kill a session (mirrors ``session.kill``)."""
    target_session = await session_id_of(engine, target, version)
    await guard_self_kill(engine, session=target_session, version=version)
    (
        await arun(KillSession(target=resolve_target(target)), engine, version=version)
    ).raise_for_status()


async def alist_sessions(
    engine: AsyncTmuxEngine,
    *,
    version: str | None = None,
) -> Listing:
    """List the server's sessions (mirrors ``server.sessions``)."""
    result = await arun(ListSessions(), engine, version=version)
    result.raise_for_status()
    return Listing(rows=result.rows)


async def ahas_session(
    engine: AsyncTmuxEngine,
    target: str | Target,
    *,
    version: str | None = None,
) -> bool:
    """Return whether a session exists (``has-session``).

    Examples
    --------
    >>> from libtmux.experimental.engines import ConcreteEngine
    >>> has_session(ConcreteEngine(), "$1")
    True
    """
    result = await arun(
        HasSession(target=resolve_target(target)),
        engine,
        version=version,
    )
    result.raise_for_status()
    return result.exists


create_session = synced(acreate_session)
rename_session = synced(arename_session)
kill_session = synced(akill_session)
list_sessions = synced(alist_sessions)
has_session = synced(ahas_session)
