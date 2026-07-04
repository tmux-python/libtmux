"""The AgentMonitor: integrates signals, store, and the engine event loop.

Every notification from the tmux control-mode engine passes through
:meth:`AgentMonitor.ingest`, a synchronous reducer that classifies the raw
string, feeds the appropriate signal parser, and writes the result into the
coalescing :class:`~libtmux.experimental.agents.store.AgentStore` via
:func:`~libtmux.experimental.agents.store.apply`.

The async half (:meth:`AgentMonitor.start`, :meth:`AgentMonitor.stop`,
:meth:`AgentMonitor.reconcile`) wires the live engine subscribe loop in a
supervised task that re-subscribes and reconciles on every engine (re)connect,
so a tmux restart or socket blip can never leave the store serving a stale
snapshot.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import time
import typing as t

from libtmux.experimental.agents.drive import DedupLedger
from libtmux.experimental.agents.health import is_alive
from libtmux.experimental.agents.hud import HudRenderer
from libtmux.experimental.agents.merge import MonotonicCounter, Stamp
from libtmux.experimental.agents.signals import (
    SUBSCRIPTION,
    OptionSignal,
    OscSignal,
    Reading,
)
from libtmux.experimental.agents.state import AgentState, AgentTransition
from libtmux.experimental.agents.store import (
    AgentStore,
    Observed,
    Storage,
    Vanished,
    apply,
)
from libtmux.experimental.agents.tree import PANE_FORMAT, diff_panes, panes_of
from libtmux.experimental.agents.wait import WaiterRegistry

if t.TYPE_CHECKING:
    from collections.abc import Callable

    from libtmux.experimental.agents.merge import Clock
    from libtmux.experimental.agents.signals import Reading
    from libtmux.experimental.agents.state import Agent
    from libtmux.experimental.models.snapshots import PaneSnapshot, ServerSnapshot

logger = logging.getLogger(__name__)

# The separator between tmux format fields in list-panes output rows.
_SEP = "\t"
# Pre-build the -F format string from the PANE_FORMAT tuple once.
_PANE_FORMAT_STR = _SEP.join(f"#{{{field}}}" for field in PANE_FORMAT)


def _notify_observer(
    observer: Callable[[AgentTransition], None],
    transition: AgentTransition,
) -> None:
    """Invoke a transition observer, swallowing its errors (kept out of the loop)."""
    try:
        observer(transition)
    except Exception:
        logger.debug("agent transition observer failed", exc_info=True)


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
    hud : bool
        Show a floating HUD pane (tmux 3.7+) that repaints the agent store on
        every change. Off by default; the HUD pane is excluded from agent
        tracking and torn down on :meth:`stop`.

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
        hud: bool = False,
    ) -> None:
        self._engine = engine
        self._sink = sink
        self._clock: Clock = clock or MonotonicCounter()
        self._osc = OscSignal()
        self._prev_panes: dict[str, t.Any] = {}
        self._task: asyncio.Task[None] | None = None
        # Supervised-drain control: stop() flips this; _run() exits its loop.
        self._stopping = False
        # Optional floating HUD (tmux 3.7+): a single floating pane that repaints
        # the agent store on every change. Opt-in so existing callers (and older
        # tmux) are unaffected; the pane is excluded from agent tracking.
        self._hud_enabled = hud
        self._hud_renderer = HudRenderer()
        self._hud_pane_id: str | None = None
        self._hud_dirty = False
        # Bounded poll between reconcile retries while the engine is reconnecting,
        # so the supervised drain waits (not busy-spins) for the engine to revive.
        self._reconnect_poll = 0.5
        # Synchronization layer: waiters parked by wait_for_agent_state (woken
        # from the single _observe/reconcile mutation point), the send
        # idempotency ledger, and transition observers.
        self._waiters = WaiterRegistry()
        self._dedup = DedupLedger()
        self._transition_observers: list[Callable[[AgentTransition], None]] = []

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
            # The counter is assigned at RECEIVE time — correct for the single
            # stream / single host this monitor drives. A future multi-host pivot
            # needs an emit-time clock carried in the wire format too (so ordering
            # survives across hosts), not merely swapping this Clock implementation.
            stamp=Stamp(self._clock(), reading.source),
            source=reading.source,
            pid=None,
        )
        before = self._store.agents.get(reading.pane_id)
        self._store = apply(self._store, observed, now=time.monotonic())
        after = self._store.agents.get(reading.pane_id)
        self._hud_dirty = True
        if self._sink is not None:
            self._sink.save(self._store.to_dict())
        logger.debug(
            "observed agent state %s on pane %s from %s",
            reading.state.value,
            reading.pane_id,
            reading.source,
        )
        self._notify_change(before, after)

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

    @property
    def waiters(self) -> WaiterRegistry:
        """The registry backing :func:`~..wait.wait_for_agent_state`.

        Examples
        --------
        >>> from libtmux.experimental.engines import AsyncConcreteEngine
        >>> from libtmux.experimental.agents.wait import WaiterRegistry
        >>> isinstance(AgentMonitor(AsyncConcreteEngine()).waiters, WaiterRegistry)
        True
        """
        return self._waiters

    @property
    def dedup(self) -> DedupLedger:
        """The idempotency ledger backing :func:`~..drive.send_to_agent` keys.

        Examples
        --------
        >>> from libtmux.experimental.engines import AsyncConcreteEngine
        >>> from libtmux.experimental.agents.drive import DedupLedger
        >>> isinstance(AgentMonitor(AsyncConcreteEngine()).dedup, DedupLedger)
        True
        """
        return self._dedup

    @property
    def engine(self) -> t.Any:
        """The async engine this monitor drives (reused by ``send_to_agent``).

        Examples
        --------
        >>> from libtmux.experimental.engines import AsyncConcreteEngine
        >>> e = AsyncConcreteEngine()
        >>> AgentMonitor(e).engine is e
        True
        """
        return self._engine

    def agent_for(self, pane_id: str) -> Agent | None:
        """Return the current :class:`~..state.Agent` for *pane_id*, or ``None``.

        Examples
        --------
        >>> from libtmux.experimental.engines import AsyncConcreteEngine
        >>> mon = AgentMonitor(AsyncConcreteEngine())
        >>> mon.agent_for("%1") is None
        True
        >>> mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : running")
        >>> mon.agent_for("%1").state
        <AgentState.RUNNING: 'running'>
        """
        return self._store.agents.get(pane_id)

    def add_transition_observer(
        self,
        callback: Callable[[AgentTransition], None],
    ) -> None:
        """Register *callback*, invoked with each :class:`~..state.AgentTransition`.

        Called on every state change (the edge), after the store is updated.

        Examples
        --------
        >>> from libtmux.experimental.engines import AsyncConcreteEngine
        >>> seen = []
        >>> mon = AgentMonitor(AsyncConcreteEngine())
        >>> mon.add_transition_observer(seen.append)
        >>> mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : running")
        >>> seen[0].after
        <AgentState.RUNNING: 'running'>
        """
        self._transition_observers.append(callback)

    def _notify_change(self, before: Agent | None, after: Agent | None) -> None:
        """Wake waiters and emit the transition edge for a changed pane record.

        Called from every store-mutation site (``_observe``, the reconcile
        ``Vanished`` loop, the health sweep). Logs a structured ``agent_*``
        record and fans an :class:`~..state.AgentTransition` to observers only on
        an actual *state* change; waiters are notified on any updated record so
        their predicates re-evaluate.
        """
        if after is None:
            return
        state_changed = before is None or before.state is not after.state
        if state_changed:
            logger.info(
                "agent state changed",
                extra={
                    "tmux_pane": after.pane_id,
                    "agent_state_before": before.state.value if before else None,
                    "agent_state_after": after.state.value,
                    "agent_name": after.name,
                    "agent_source": after.source,
                },
            )
            transition = AgentTransition(
                pane_id=after.pane_id,
                before=before.state if before else None,
                after=after.state,
                agent=after,
            )
            for observer in tuple(self._transition_observers):
                _notify_observer(observer, transition)
        self._waiters.notify(after)

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
        3. Run an initial :meth:`reconcile` to sync the pane tree, then spawn the
           supervised drain task (:meth:`_run`), which re-subscribes and
           reconciles on every engine (re)connect so a tmux restart or socket
           blip can never leave the store stale.

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
                result = await self._engine.run(
                    CommandRequest.from_args("attach-session", "-t", session_id)
                )
                # A tmux-side failure (e.g. a stale session id) is *data* -- a
                # non-zero returncode, not an exception -- so only record the
                # sticky attach when the command actually succeeded. Recording a
                # failed attach would point _attached_session at an unattached
                # session and silence the option channel.
                if result.returncode == 0:
                    # Mirror the events layer: record the sticky attach so a later
                    # _ensure_attached (MCP) does not redundantly re-attach.
                    self._engine._attached_session = session_id
                    logger.debug("monitor attached session %s", session_id)
                else:
                    logger.debug(
                        "monitor attach-session failed for %s: %s",
                        session_id,
                        result.stderr,
                    )
            except Exception:
                logger.debug("monitor attach-session failed", exc_info=True)

        # Sync the tree once before returning (callers expect a ready snapshot),
        # then hand off to the supervised drain for the engine's whole lifetime.
        self._stopping = False
        await self.reconcile()
        if self._hud_enabled:
            await self._ensure_hud()
        self._task = asyncio.get_running_loop().create_task(self._run())

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
        yields ``None`` so :meth:`start` can proceed without attaching. The
        own-session probe failing is treated the same way: without knowing which
        session is the phantom, ``list-sessions[0]`` would be the phantom
        ``tmux -C`` session (it sorts first), so this returns ``None`` and skips
        attach rather than binding to a session that holds no agent panes.

        Returns
        -------
        str | None
            The session id to attach to, or ``None`` when the list is empty, the
            engine call failed, or the own-session probe failed.
        """
        from libtmux.experimental.engines.base import CommandRequest

        own = await self._own_session_id()
        if own is None:
            # Without the phantom's id, ids[0] would be tmux's own throwaway
            # `tmux -C` session — attaching there delivers no real agent panes.
            logger.debug("own-session probe failed — monitor will not attach")
            return None
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
        """Stop the supervised drain task and optionally flush the sink.

        Flips :attr:`_stopping` first so the loop will not re-enter, then cancels
        the task. The cancel interrupts a ``subscribe()`` parked on
        ``queue.get()`` even when the engine is permanently closed (no more
        stream-end sentinels will arrive), so :meth:`stop` never hangs.
        """
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._waiters.fail_all()
        await self._teardown_hud()
        if self._sink is not None:
            self._sink.save(self._store.to_dict())

    async def reconcile(self) -> None:
        """Reconcile the store against the live pane tree (defensive).

        Public, never-raising wrapper around :meth:`_reconcile_once`: any error
        from the engine or parse is caught and logged so a direct caller (or the
        initial sync in :meth:`start`) stays alive. The supervised drain calls
        :meth:`_reconcile_once` directly instead, so it can *retry* on failure.
        """
        try:
            await self._reconcile_once()
        except Exception:
            logger.debug("reconcile skipped — engine call failed", exc_info=True)

    async def _reconcile_once(self) -> None:
        """Reconcile against the live pane tree; **raises** on engine failure.

        Runs ``list-panes -a -F`` via the engine, diffs the result against the
        previously seen pane set, applies :class:`Vanished` for panes that
        disappeared, then runs the health sweep (:meth:`_apply_health`). Lets the
        engine error propagate (e.g. the dead-window ``ControlModeError``) so the
        supervised drain can wait for the engine to revive before re-subscribing.
        """
        from libtmux.experimental.engines.base import CommandRequest
        from libtmux.experimental.models.snapshots import ServerSnapshot

        req = CommandRequest.from_args("list-panes", "-a", "-F", _PANE_FORMAT_STR)
        result = await self._engine.run(req)
        rows = _parse_pane_rows(result.stdout)
        snapshot: ServerSnapshot = ServerSnapshot.from_pane_rows(rows)
        # The monitor's own floating HUD is not an agent pane: keep it out of the
        # tracked set so it never enters the diff or the health sweep.
        current_panes = {
            pane_id: pane
            for pane_id, pane in panes_of(snapshot).items()
            if pane_id != self._hud_pane_id
        }
        self._observe_pane_options(current_panes)
        _added, removed = diff_panes(self._prev_panes, current_panes)
        for pane_id in removed:
            before = self._store.agents.get(pane_id)
            self._store = apply(
                self._store,
                Vanished(pane_id=pane_id),
                now=time.monotonic(),
            )
            self._notify_change(before, self._store.agents.get(pane_id))
        self._apply_health(current_panes)
        self._prev_panes = dict(current_panes)
        self._hud_dirty = True

    def _observe_pane_options(self, current_panes: dict[str, PaneSnapshot]) -> None:
        """Seed/refresh store entries from durable per-pane option values."""
        for pane_id, pane in current_panes.items():
            raw_state = pane.fields.get("@agent_state", "").strip()
            if not raw_state:
                continue
            state = AgentState.from_signal(raw_state)
            name = pane.fields.get("@agent_name") or None
            current = self._store.agents.get(pane_id)
            if current is not None:
                if current.source != "option":
                    continue
                if current.state is state and current.name == name:
                    continue
            self._observe(Reading(pane_id, state, name, "option"))

    def _apply_health(self, current_panes: dict[str, PaneSnapshot]) -> None:
        """Refresh tracked agents' ``pid``/``alive`` from the pane tree.

        For each tracked agent still present in *current_panes*, copy the live
        ``pane_pid`` from the snapshot and probe it with
        :func:`~libtmux.experimental.agents.health.is_alive`:

        - A **local** pane (``pid`` is not ``None``) whose process is dead is
          marked :attr:`~..state.AgentState.EXITED` (``alive=False``).
        - A **remote / PID-less** pane (``pid`` is ``None``) is *never*
          auto-EXITED by this probe — it is left at its last-known state and
          only becomes EXITED via the :class:`Vanished` diff when its tmux pane
          actually disappears (no keepalive/TTL in v1) (D5).
        - Otherwise the agent's ``pid`` is refreshed and ``alive`` set ``True``.

        Panes absent from *current_panes* are left untouched here; their removal
        is handled by the :class:`Vanished` diff in :meth:`_reconcile_once`.

        Parameters
        ----------
        current_panes : dict[str, PaneSnapshot]
            The live ``{pane_id: PaneSnapshot}`` map from this reconcile.
        """
        agents = dict(self._store.agents)
        changed = False
        exits: list[tuple[Agent, Agent]] = []
        now = time.monotonic()
        for pane_id, agent in self._store.agents.items():
            pane = current_panes.get(pane_id)
            if pane is None:
                continue  # not in the tree → Vanished handles it
            pid = pane.pid
            if pid is not None and not is_alive(pid):
                if agent.alive or agent.state is not AgentState.EXITED:
                    exited = dataclasses.replace(
                        agent,
                        state=AgentState.EXITED,
                        alive=False,
                        pid=pid,
                        since=now,
                    )
                    agents[pane_id] = exited
                    exits.append((agent, exited))
                    changed = True
            elif agent.pid != pid or not agent.alive:
                agents[pane_id] = dataclasses.replace(agent, pid=pid, alive=True)
                changed = True
        if changed:
            self._store = AgentStore(agents=agents, stamps=dict(self._store.stamps))
            for before, after in exits:
                self._notify_change(before, after)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _ensure_hud(self) -> None:
        """Create the floating HUD pane over the primary session and paint it.

        Best-effort: with no session to host it, an engine error, or a server
        older than tmux 3.7 (``new-pane`` is unknown there), the HUD is silently
        skipped and the monitor runs without it.
        """
        from libtmux.experimental.ops import NewPane, arun
        from libtmux.experimental.ops._types import SessionId

        session_id = await self._primary_session_id()
        if session_id is None:
            logger.debug("no session to host the agent HUD — skipping")
            return
        op = NewPane(
            target=SessionId(session_id),
            detach=True,
            width="40%",
            height="40%",
            shell_command=self._hud_renderer.paint_command(self._store),
        )
        try:
            result = await arun(op, self._engine)
        except Exception:
            logger.debug("agent HUD creation failed", exc_info=True)
            return
        if not result.ok or result.new_pane_id is None:
            logger.debug("agent HUD unavailable (new-pane failed)")
            return
        self._hud_pane_id = result.new_pane_id
        self._hud_dirty = False
        logger.debug("agent HUD created on pane %s", self._hud_pane_id)

    async def _repaint_hud(self) -> None:
        """Repaint the HUD pane from the current store when it has changed.

        A failed repaint -- the HUD pane vanished (e.g. a full tmux restart) --
        drops :attr:`_hud_pane_id` so :meth:`_run` recreates the HUD on its next
        pass; the dirty flag stays set so the fresh pane shows the current state.
        """
        if self._hud_pane_id is None or not self._hud_dirty:
            return
        from libtmux.experimental.ops import arun

        op = self._hud_renderer.repaint_op(self._hud_pane_id, self._store)
        try:
            result = await arun(op, self._engine)
        except Exception:
            logger.debug("agent HUD repaint failed", exc_info=True)
            self._hud_pane_id = None
            return
        if not result.ok:
            # arun returns failure as data (no raise); a dead pane id means the
            # HUD is gone, so drop it for _run to recreate.
            self._hud_pane_id = None
            return
        self._hud_dirty = False

    async def _teardown_hud(self) -> None:
        """Kill the floating HUD pane if one was created."""
        if self._hud_pane_id is None:
            return
        from libtmux.experimental.ops import KillPane, arun
        from libtmux.experimental.ops._types import PaneId

        hud_pane_id, self._hud_pane_id = self._hud_pane_id, None
        with contextlib.suppress(Exception):
            await arun(KillPane(target=PaneId(hud_pane_id)), self._engine)

    async def _run(self) -> None:
        """Supervised drain: re-subscribe + reconcile across engine reconnects.

        Each iteration reconciles **first** (so ``subscribe()`` only runs against
        a live engine), then drains the notification stream until it ends. When
        the engine disconnects the stream ends via its ``_STREAM_END`` sentinel;
        the loop comes back around, :meth:`_reconcile_once` retries until the
        supervisor has reconnected (and replayed subscriptions + attach), then a
        fresh ``subscribe()`` re-registers against the reconnected engine. This
        is the self-heal that keeps the store live across a tmux restart or
        socket blip. :meth:`stop` flips :attr:`_stopping` and cancels the task.
        """
        while not self._stopping:
            try:
                await self._reconcile_once()
            except Exception:
                logger.debug("agents: reconcile not ready, retrying", exc_info=True)
                await asyncio.sleep(self._reconnect_poll)
                continue
            if self._hud_enabled and self._hud_pane_id is None:
                await self._ensure_hud()  # (re)create after a restart dropped it
            await self._repaint_hud()
            try:
                async with contextlib.aclosing(self._engine.subscribe()) as stream:
                    async for note in stream:
                        self.ingest(note.raw)
                        await self._repaint_hud()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("agents: drain error", exc_info=True)
            # Stream ended (disconnect/sentinel): loop → reconcile + re-subscribe.


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
