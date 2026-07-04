"""Reverse-analyze a live server snapshot into the declarative IR -- the round-trip.

:func:`~libtmux.experimental.workspace.analyzer.analyze` lowers a tmuxp-style
config *into* a :class:`~libtmux.experimental.workspace.ir.Workspace`;
:func:`freeze` is its inverse over **live** state. It walks an immutable
:class:`~libtmux.experimental.models.snapshots.ServerSnapshot` back into a
``Workspace`` that :meth:`~..ir.Workspace.build` / :meth:`~..ir.Workspace.compile`
can replay, so a running session can be captured as reusable, version-controllable
IR (tmuxp's ``freeze``). It is **lossy by design**: scrollback, live process
state, and a pane sitting at a bare shell are not reconstructed.

The north star -- *fewest backend calls* -- holds: :func:`freeze_server` /
:func:`afreeze_server` rebuild the **entire** session/window/pane tree from a
**single** ``list-panes -a -F`` read; the mapping itself is pure.
"""

from __future__ import annotations

import typing as t

from libtmux.experimental.models.snapshots import ServerSnapshot
from libtmux.experimental.workspace.ir import Pane, Window, Workspace

if t.TYPE_CHECKING:
    from collections.abc import Collection, Iterable

    from libtmux.experimental.engines.base import AsyncTmuxEngine, TmuxEngine
    from libtmux.experimental.models.snapshots import (
        PaneSnapshot,
        SessionSnapshot,
        WindowSnapshot,
    )

#: Bare shells whose presence as a pane's *current command* means "no command":
#: freezing such a pane yields an empty pane, not a nested shell (tmuxp parity).
#: Override via the ``shells`` argument to keep or widen the set.
SHELLS: frozenset[str] = frozenset(
    {
        "sh",
        "bash",
        "zsh",
        "fish",
        "dash",
        "ksh",
        "tcsh",
        "csh",
        "ash",
        "nu",
        "xonsh",
        "elvish",
        "pwsh",
    },
)

#: The tmux fields one ``list-panes -a -F`` read needs to rebuild the whole tree.
FREEZE_FIELDS: tuple[str, ...] = (
    "session_id",
    "session_name",
    "window_id",
    "window_index",
    "window_name",
    "window_layout",
    "window_active",
    "pane_id",
    "pane_index",
    "pane_active",
    "pane_current_command",
    "pane_current_path",
)
_SEP = "\t"
#: The ``-F`` format string covering :data:`FREEZE_FIELDS` (one read, whole tree).
FREEZE_FORMAT: str = _SEP.join(f"#{{{field}}}" for field in FREEZE_FIELDS)


def _pick_session(
    server: ServerSnapshot,
    selector: str | None,
) -> SessionSnapshot:
    """Choose the one session to freeze (by name/id, or the sole one)."""
    sessions = server.sessions
    if not sessions:
        msg = "cannot freeze an empty server (no sessions)"
        raise ValueError(msg)
    if selector is None:
        if len(sessions) == 1:
            return sessions[0]
        names = ", ".join(s.name or s.session_id for s in sessions)
        msg = (
            f"ambiguous freeze: {len(sessions)} sessions ({names}); "
            f"pass session= to choose one"
        )
        raise ValueError(msg)
    for session in sessions:
        if selector in (session.name, session.session_id):
            return session
    names = ", ".join(s.name or s.session_id for s in sessions)
    msg = f"no session matching {selector!r} (have: {names})"
    raise ValueError(msg)


def _freeze_pane(pane: PaneSnapshot, shells: Collection[str]) -> Pane:
    """Map one pane snapshot to a declarative :class:`~..ir.Pane`.

    A pane sitting at a bare shell (its ``current_command`` is in *shells*)
    freezes to an empty pane -- replaying it as a command would nest a shell.
    """
    command = pane.current_command
    run = None if command is None or command in shells else command
    return Pane(run=run, focus=pane.active, start_directory=pane.current_path)


def _freeze_window(window: WindowSnapshot, shells: Collection[str]) -> Window:
    """Map one window snapshot and its panes to a declarative :class:`~..ir.Window`."""
    return Window(
        name=window.name,
        layout=window.layout,
        focus=window.active,
        panes=[_freeze_pane(pane, shells) for pane in window.panes],
    )


def freeze(
    snapshot: ServerSnapshot,
    *,
    session: str | None = None,
    shells: Collection[str] = SHELLS,
) -> Workspace:
    """Reverse-analyze a live :class:`ServerSnapshot` into a declarative Workspace.

    The inverse of :func:`~..analyzer.analyze`: capture what is *running* as
    reusable IR. Pure -- no tmux. Lossy by design (no scrollback / process state;
    a bare-shell pane becomes an empty pane).

    Parameters
    ----------
    snapshot : ServerSnapshot
        The live server tree (e.g. from :meth:`ServerSnapshot.from_pane_rows`).
    session : str or None
        Which session to freeze, by ``session_name`` or ``session_id``. ``None``
        freezes the sole session and raises when the server holds several.
    shells : Collection[str]
        Commands treated as "a bare shell" -> an empty pane (default
        :data:`SHELLS`).

    Returns
    -------
    Workspace
        A declarative spec that ``build``/``compile`` replays.

    Raises
    ------
    ValueError
        When the server is empty, *session* is ambiguous, or the named session
        is absent.

    Examples
    --------
    >>> from libtmux.experimental.models.snapshots import ServerSnapshot
    >>> server = ServerSnapshot.from_pane_rows([
    ...     {"session_id": "$0", "session_name": "dev", "window_id": "@1",
    ...      "window_index": "0", "window_name": "editor", "pane_id": "%1",
    ...      "pane_index": "0", "pane_active": "1", "pane_current_command": "vim"},
    ...     {"session_id": "$0", "session_name": "dev", "window_id": "@1",
    ...      "window_index": "0", "window_name": "editor", "pane_id": "%2",
    ...      "pane_index": "1", "pane_current_command": "zsh"},
    ... ])
    >>> ws = freeze(server)
    >>> ws.name
    'dev'
    >>> [c.cmd for c in ws.windows[0].panes[0].commands]
    ['vim']
    >>> ws.windows[0].panes[1].run is None  # a bare shell -> empty pane
    True
    """
    chosen = _pick_session(snapshot, session)
    return Workspace(
        name=chosen.name or chosen.session_id,
        windows=[_freeze_window(window, shells) for window in chosen.windows],
    )


def _rows(stdout: Iterable[str]) -> list[dict[str, str]]:
    """Parse ``list-panes -F`` tab-separated lines into per-pane field dicts."""
    rows: list[dict[str, str]] = []
    for line in stdout:
        if not line:
            continue
        parts = line.split(_SEP)
        # zip(strict=False) tolerates a short row (a trailing empty field tmux drops)
        rows.append(dict(zip(FREEZE_FIELDS, parts, strict=False)))
    return rows


def freeze_server(
    engine: TmuxEngine,
    *,
    session: str | None = None,
    shells: Collection[str] = SHELLS,
) -> Workspace:
    r"""Freeze a live server into IR with a **single** ``list-panes`` read.

    Reads the whole session/window/pane tree in one ``list-panes -a -F`` dispatch,
    builds a :class:`ServerSnapshot`, and reverse-analyzes it via :func:`freeze`.

    Examples
    --------
    >>> from libtmux.experimental.engines.base import CommandResult
    >>> class _Engine:  # one read returns the whole tree
    ...     def run(self, request):
    ...         row = "$0\tdev\t@1\t0\teditor\t\t1\t%1\t0\t1\tvim\t/work"
    ...         return CommandResult(cmd=("tmux",), stdout=(row,))
    >>> freeze_server(_Engine()).name
    'dev'
    """
    from libtmux.experimental.engines.base import CommandRequest

    result = engine.run(
        CommandRequest.from_args("list-panes", "-a", "-F", FREEZE_FORMAT),
    )
    server = ServerSnapshot.from_pane_rows(_rows(result.stdout))
    return freeze(server, session=session, shells=shells)


async def afreeze_server(
    engine: AsyncTmuxEngine,
    *,
    session: str | None = None,
    shells: Collection[str] = SHELLS,
) -> Workspace:
    r"""Async twin of :func:`freeze_server` (one awaited ``list-panes`` read).

    Examples
    --------
    >>> import asyncio
    >>> from libtmux.experimental.engines.base import CommandResult
    >>> class _AEngine:
    ...     async def run(self, request):
    ...         row = "$0\tdev\t@1\t0\tmain\t\t1\t%1\t0\t1\tvim\t/w"
    ...         return CommandResult(cmd=("tmux",), stdout=(row,))
    >>> asyncio.run(afreeze_server(_AEngine())).name
    'dev'
    """
    from libtmux.experimental.engines.base import CommandRequest

    result = await engine.run(
        CommandRequest.from_args("list-panes", "-a", "-F", FREEZE_FORMAT),
    )
    server = ServerSnapshot.from_pane_rows(_rows(result.stdout))
    return freeze(server, session=session, shells=shells)
