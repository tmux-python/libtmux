"""The AgentMonitor: integrates signals, store, and the engine event loop.

Every notification from the tmux control-mode engine passes through
:meth:`AgentMonitor.ingest`, a synchronous reducer that classifies the raw
string, feeds the appropriate signal parser, and writes the result into the
coalescing :class:`~libtmux.experimental.agents.store.AgentStore` via
:func:`~libtmux.experimental.agents.store.apply`.

The async half (:meth:`AgentMonitor.start`, :meth:`AgentMonitor.stop`,
:meth:`AgentMonitor.reconcile`) wires the live engine subscribe loop and
performs a periodic full-pane reconciliation to catch panes the stream missed.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import typing as t

from libtmux.experimental.agents.merge import MonotonicCounter, Stamp
from libtmux.experimental.agents.signals import SUBSCRIPTION, OptionSignal, OscSignal
from libtmux.experimental.agents.store import (
    AgentStore,
    Observed,
    Storage,
    Vanished,
    apply,
)
from libtmux.experimental.agents.tree import PANE_FORMAT, diff_panes, panes_of

if t.TYPE_CHECKING:
    from libtmux.experimental.agents.merge import Clock
    from libtmux.experimental.agents.signals import Reading
    from libtmux.experimental.agents.state import Agent
    from libtmux.experimental.agents.store import AgentStore
    from libtmux.experimental.models.snapshots import ServerSnapshot

logger = logging.getLogger(__name__)

# The separator between tmux format fields in list-panes output rows.
_SEP = "\t"
# Pre-build the -F format string from the PANE_FORMAT tuple once.
_PANE_FORMAT_STR = _SEP.join(f"#{{{field}}}" for field in PANE_FORMAT)


class AgentMonitor:
    """Wire signals, the coalescing store, and the engine event loop.

    Parameters
    ----------
    engine : object
        An async tmux engine with ``run``, ``subscribe``, ``add_subscription``,
        and ``set_attach_targets`` methods.
    sink : Storage or None
        Optional persistence sink; if present and non-empty on startup the
        store is seeded from it.
    clock : Clock or None
        Logical clock for stamping updates. Defaults to
        :class:`~libtmux.experimental.agents.merge.MonotonicCounter`.

    Examples
    --------
    >>> class _Fake:
    ...     async def run(self, request): ...
    ...     async def subscribe(self): ...
    ...     def add_subscription(self, spec): ...
    ...     def set_attach_targets(self, ids): ...
    >>> mon = AgentMonitor(_Fake())
    >>> mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : running")
    >>> mon.agents[0].pane_id
    '%1'
    """

    def __init__(
        self,
        engine: t.Any,
        *,
        sink: Storage | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._engine = engine
        self._sink = sink
        self._clock: Clock = clock or MonotonicCounter()
        self._osc = OscSignal()
        self._prev_panes: dict[str, t.Any] = {}
        self._task: asyncio.Task[None] | None = None

        # Seed the store from a persistent sink when one is provided.
        if sink is not None:
            data = sink.load()
            if data:
                self._store = AgentStore.from_dict(data)
            else:
                self._store = AgentStore()
        else:
            self._store = AgentStore()

    # ------------------------------------------------------------------
    # Synchronous reducer pipeline
    # ------------------------------------------------------------------

    def ingest(self, notification_raw: str) -> None:
        """Classify one control-mode notification and update the agent store.

        This method is **synchronous** so that unit tests can drive it
        directly without a live engine. The async drain loop calls it per
        notification.

        - ``%output <pane_id> <bytes>`` → fed to :class:`OscSignal`.
        - Everything else → tried against :class:`OptionSignal`.

        Parameters
        ----------
        notification_raw : str
            A raw tmux control-mode notification string.

        Examples
        --------
        >>> class _Fake:
        ...     async def run(self, request): ...
        ...     async def subscribe(self): ...
        ...     def add_subscription(self, spec): ...
        ...     def set_attach_targets(self, ids): ...
        >>> mon = AgentMonitor(_Fake())
        >>> mon.ingest("%subscription-changed agentstate $0 @0 1 %2 : idle")
        >>> mon.agents[0].state.value
        'idle'
        """
        if notification_raw.startswith("%output "):
            # Split on first two spaces: ["%output", pane_id, rest]
            parts = notification_raw.split(" ", 2)
            if len(parts) < 3:
                return
            _tag, pane_id, rest = parts
            for reading in self._osc.feed(pane_id, rest.encode()):
                self._observe(reading)
        else:
            opt_reading = OptionSignal.parse(notification_raw)
            if opt_reading is not None:
                self._observe(opt_reading)

    def _observe(self, reading: Reading) -> None:
        """Apply one parsed reading to the store (latest-wins via :func:`apply`).

        Parameters
        ----------
        reading : Reading
            A parsed signal reading from :class:`OptionSignal` or
            :class:`OscSignal`.
        """
        observed = Observed(
            pane_id=reading.pane_id,
            key=reading.pane_id,
            name=reading.name,
            state=reading.state,
            stamp=Stamp(self._clock(), reading.source),
            source=reading.source,
            pid=None,
        )
        self._store = apply(self._store, observed, now=time.monotonic())
        if self._sink is not None:
            self._sink.save(self._store.to_dict())
        logger.debug(
            "observed agent state %s on pane %s from %s",
            reading.state.value,
            reading.pane_id,
            reading.source,
        )

    # ------------------------------------------------------------------
    # Public read API
    # ------------------------------------------------------------------

    @property
    def agents(self) -> list[Agent]:
        """A snapshot of all currently tracked agents.

        Returns
        -------
        list[Agent]
            One :class:`~libtmux.experimental.agents.state.Agent` per
            monitored pane.

        Examples
        --------
        >>> class _Fake:
        ...     async def run(self, request): ...
        ...     async def subscribe(self): ...
        ...     def add_subscription(self, spec): ...
        ...     def set_attach_targets(self, ids): ...
        >>> mon = AgentMonitor(_Fake())
        >>> mon.agents
        []
        >>> mon.ingest(
        ...     "%subscription-changed agentstate $0 @0 1 %3 : running")
        >>> len(mon.agents)
        1
        """
        return list(self._store.agents.values())

    def status(self) -> dict[str, t.Any]:
        """Return a lightweight health/stats dict for the monitor.

        Returns
        -------
        dict[str, Any]
            ``agents`` — number of tracked agents;
            ``generation`` — engine generation counter (0 if not exposed).

        Examples
        --------
        >>> class _Fake:
        ...     async def run(self, request): ...
        ...     async def subscribe(self): ...
        ...     def add_subscription(self, spec): ...
        ...     def set_attach_targets(self, ids): ...
        >>> AgentMonitor(_Fake()).status()
        {'agents': 0, 'generation': 0}
        """
        return {
            "agents": len(self._store.agents),
            "generation": getattr(self._engine, "_generation", 0),
        }

    # ------------------------------------------------------------------
    # Async lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Install the subscription, attach a session, and drain the event stream.

        Three steps:

        1. Install the ``@agent_state`` subscription on the engine.
        2. Attach the engine to a session. tmux only delivers per-pane
           ``%subscription-changed`` notifications to an *attached* control
           client, so without this the option channel is silent against a live
           server. A control client attaches to one session at a time; v1
           attaches to the first session reported by ``list-sessions`` and
           records it via :meth:`set_attach_targets` so the engine re-attaches
           across reconnects. The ``%*`` subscription still installs across all
           panes, but per-pane option signals for *other* sessions' panes need
           their own attached client — a known v1 limitation.
        3. Spawn the drain task feeding every notification into :meth:`ingest`,
           then run an initial :meth:`reconcile` to sync the pane tree.

        All attach steps are defensive: a failed ``list-sessions`` or
        ``attach-session`` is logged and skipped so :meth:`start` never crashes.
        """
        from libtmux.experimental.engines.base import CommandRequest

        self._engine.add_subscription(SUBSCRIPTION)

        # Attach a session so per-pane %subscription-changed actually flows.
        session_id = await self._primary_session_id()
        if session_id is not None:
            self._engine.set_attach_targets([session_id])
            try:
                await self._engine.run(
                    CommandRequest.from_args("attach-session", "-t", session_id)
                )
                # Mirror the events layer: record the sticky attach so a later
                # _ensure_attached (MCP) does not redundantly re-attach.
                self._engine._attached_session = session_id
                logger.debug("monitor attached session %s", session_id)
            except Exception:
                logger.debug("monitor attach-session failed", exc_info=True)

        self._task = asyncio.get_running_loop().create_task(self._drain())
        await self.reconcile()

    async def _primary_session_id(self) -> str | None:
        """Return the first *real* session id to attach to, or ``None``.

        A ``tmux -C`` control client creates its own throwaway session on
        connect (``tmux -C`` with no command implies ``new-session``); that
        phantom holds no agent panes and per-pane notifications for it are
        useless. So this skips the control client's own session (identified via
        ``display-message -p '#{session_id}'``) and returns the first remaining
        session — tmux orders ``list-sessions`` by name, so this is the
        alphabetically-first real session. Falls back to the client's own
        session only when no other exists (an otherwise empty server).

        Defensive: any engine error (no daemon, list failure) is logged and
        yields ``None`` so :meth:`start` can proceed without attaching.

        Returns
        -------
        str | None
            The session id to attach to, or ``None`` when the list is empty or
            the engine call failed.
        """
        from libtmux.experimental.engines.base import CommandRequest

        own = await self._own_session_id()
        try:
            result = await self._engine.run(
                CommandRequest.from_args("list-sessions", "-F", "#{session_id}")
            )
        except Exception:
            logger.debug(
                "list-sessions failed — monitor will not attach", exc_info=True
            )
            return None
        ids: list[str] = [
            str(line).strip() for line in result.stdout if str(line).strip()
        ]
        for sid in ids:
            if sid != own:
                return sid
        # Only the control client's own session exists: nothing real to watch,
        # but attaching to it is harmless (and keeps the option channel live).
        return ids[0] if ids else None

    async def _own_session_id(self) -> str | None:
        """Return the control client's own session id, or ``None``.

        Right after the engine connects, ``tmux -C`` is attached to the
        throwaway session it created; ``display-message -p '#{session_id}'``
        (no target → the client's current session) reports it. Used by
        :meth:`_primary_session_id` to avoid attaching the monitor to its own
        phantom session. Defensive: any engine error yields ``None``.

        Returns
        -------
        str | None
            The control client's current ``#{session_id}``, or ``None`` if the
            engine call failed or returned nothing.
        """
        from libtmux.experimental.engines.base import CommandRequest

        try:
            result = await self._engine.run(
                CommandRequest.from_args("display-message", "-p", "#{session_id}")
            )
        except Exception:
            logger.debug(
                "display-message failed — cannot detect own session", exc_info=True
            )
            return None
        for line in result.stdout:
            if str(line).strip():
                return str(line).strip()
        return None

    async def stop(self) -> None:
        """Cancel the drain task and optionally flush the sink."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._sink is not None:
            self._sink.save(self._store.to_dict())

    async def reconcile(self) -> None:
        """Reconcile the store against the live pane tree.

        Runs ``list-panes -a -F`` via the engine, diffs the result against
        the previously seen pane set, and applies :class:`Vanished` for any
        panes that have disappeared. This is defensive: any error from the
        engine is caught and logged so the monitor stays alive.
        """
        try:
            from libtmux.experimental.engines.base import CommandRequest
            from libtmux.experimental.models.snapshots import ServerSnapshot

            fmt_str = _PANE_FORMAT_STR
            req = CommandRequest.from_args("list-panes", "-a", "-F", fmt_str)
            result = await self._engine.run(req)
            rows = _parse_pane_rows(result.stdout)
            snapshot: ServerSnapshot = ServerSnapshot.from_pane_rows(rows)
            current_panes = panes_of(snapshot)
            _added, removed = diff_panes(self._prev_panes, current_panes)
            for pane_id in removed:
                self._store = apply(
                    self._store,
                    Vanished(pane_id=pane_id),
                    now=time.monotonic(),
                )
            self._prev_panes = dict(current_panes)
        except Exception:
            logger.debug("reconcile skipped — engine call failed", exc_info=True)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _drain(self) -> None:
        """Background task: forward every engine notification to :meth:`ingest`."""
        async for note in self._engine.subscribe():
            self.ingest(note.raw)


def _parse_pane_rows(
    stdout: tuple[str, ...],
) -> list[dict[str, str]]:
    """Parse ``list-panes -F`` tab-separated output into field dicts.

    Parameters
    ----------
    stdout : tuple[str, ...]
        Lines from the engine's command result stdout.

    Returns
    -------
    list[dict[str, str]]
        One dict per non-empty line, keyed by :data:`PANE_FORMAT` fields.
    """
    rows: list[dict[str, str]] = []
    fields = PANE_FORMAT
    for line in stdout:
        if not line:
            continue
        parts = line.split(_SEP)
        # zip stops at the shorter sequence — tolerate truncated rows
        rows.append(dict(zip(fields, parts, strict=False)))
    return rows
