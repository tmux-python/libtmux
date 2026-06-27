"""The durable agent-state store and its pure reducer.

The store maps each pane to its current :class:`Agent` and the :class:`Stamp`
that produced it. The only mutator is :func:`apply`, a pure reducer that applies
the latest-wins guard. ``Storage``/``JsonFile`` persist the store atomically;
persistence is an optional seed in v1 (agents re-announce on reconnect).
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import os
import pathlib
import tempfile
import typing as t
from dataclasses import dataclass, field

from libtmux.experimental.agents.merge import Stamp, latest
from libtmux.experimental.agents.state import Agent, AgentState

if t.TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True)
class Observed:
    """An observed agent-state update from a signal source.

    Parameters
    ----------
    pane_id : str
        The tmux pane identifier (e.g., '%1').
    key : str
        The unique key for this pane's agent.
    name : str | None
        The agent name (e.g., 'claude', 'codex').
    state : AgentState
        The agent's current state.
    stamp : Stamp
        Logical clock tag ordering updates.
    source : str
        The signal source (e.g., 'option', 'osc').
    pid : int | None
        The agent process ID, if known.

    Examples
    --------
    >>> o = Observed(
    ...     pane_id="%1", key="%1", name="claude",
    ...     state=AgentState.RUNNING, stamp=Stamp(1, "option"),
    ...     source="option", pid=42
    ... )
    >>> o.pane_id
    '%1'
    """

    pane_id: str
    key: str
    name: str | None
    state: AgentState
    stamp: Stamp
    source: str
    pid: int | None


@dataclass(frozen=True)
class Vanished:
    """A pane that no longer exists (from reconcile or the health sweep).

    Parameters
    ----------
    pane_id : str
        The tmux pane identifier (e.g., '%1').

    Examples
    --------
    >>> v = Vanished(pane_id="%1")
    >>> v.pane_id
    '%1'
    """

    pane_id: str


@dataclass(frozen=True)
class AgentStore:
    """The current agent per pane plus the stamp that produced it.

    Attributes
    ----------
    agents : dict[str, Agent]
        Maps pane_id to the pane's current Agent.
    stamps : dict[str, Stamp]
        Maps pane_id to the Stamp that produced its Agent.

    Examples
    --------
    >>> store = AgentStore()
    >>> store.agents
    {}
    >>> store.stamps
    {}
    """

    agents: dict[str, Agent] = field(default_factory=dict)
    stamps: dict[str, Stamp] = field(default_factory=dict)

    def to_dict(self) -> dict[str, t.Any]:
        """Serialize to plain JSON-able data.

        Returns
        -------
        dict[str, Any]
            A dictionary with 'agents' and 'stamps' keys.

        Examples
        --------
        >>> store = AgentStore()
        >>> store.to_dict()
        {'agents': {}, 'stamps': {}}
        """
        return {
            "agents": {
                key: {
                    "pane_id": a.pane_id,
                    "key": a.key,
                    "name": a.name,
                    "state": a.state.value,
                    "since": a.since,
                    "source": a.source,
                    "pid": a.pid,
                    "alive": a.alive,
                }
                for key, a in self.agents.items()
            },
            "stamps": {key: [s.counter, s.writer] for key, s in self.stamps.items()},
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, t.Any]) -> AgentStore:
        """Reconstruct from :meth:`to_dict` output.

        Parameters
        ----------
        data : Mapping[str, Any]
            A dictionary with 'agents' and 'stamps' keys from :meth:`to_dict`.

        Returns
        -------
        AgentStore
            A reconstructed store.

        Examples
        --------
        >>> data = {'agents': {}, 'stamps': {}}
        >>> AgentStore.from_dict(data)
        AgentStore(agents={}, stamps={})
        """
        agents = {
            key: Agent(
                pane_id=a["pane_id"],
                key=a["key"],
                name=a["name"],
                state=AgentState(a["state"]),
                since=a["since"],
                source=a["source"],
                pid=a["pid"],
                alive=a["alive"],
            )
            for key, a in data.get("agents", {}).items()
        }
        stamps = {
            key: Stamp(counter=v[0], writer=v[1])
            for key, v in data.get("stamps", {}).items()
        }
        return cls(agents=agents, stamps=stamps)


def apply(store: AgentStore, event: Observed | Vanished, *, now: float) -> AgentStore:
    """Return a new store with *event* applied (pure; latest-wins for Observed).

    Parameters
    ----------
    store : AgentStore
        The current store.
    event : Observed | Vanished
        The event to apply.
    now : float
        The current timestamp (used as 'since' for the agent).

    Returns
    -------
    AgentStore
        A new store with the event applied. For :class:`Observed`,
        applies the latest-wins guard via :func:`latest`. For
        :class:`Vanished`, marks the agent as EXITED.

    Examples
    --------
    >>> from libtmux.experimental.agents.merge import Stamp
    >>> s = apply(
    ...     AgentStore(),
    ...     Observed("%1", "%1", "c", AgentState.RUNNING,
    ...              Stamp(1, "option"), "option", 7),
    ...     now=1.0
    ... )
    >>> s.agents["%1"].state
    <AgentState.RUNNING: 'running'>
    """
    agents = dict(store.agents)
    stamps = dict(store.stamps)
    if isinstance(event, Vanished):
        prev = agents.get(event.pane_id)
        if prev is not None:
            agents[event.pane_id] = dataclasses.replace(
                prev, state=AgentState.EXITED, alive=False, since=now
            )
        return AgentStore(agents=agents, stamps=stamps)
    if not latest(stamps.get(event.pane_id), event.stamp):
        return store
    stamps[event.pane_id] = event.stamp
    agents[event.pane_id] = Agent(
        pane_id=event.pane_id,
        key=event.key,
        name=event.name,
        state=event.state,
        since=now,
        source=event.source,
        pid=event.pid,
        alive=True,
    )
    return AgentStore(agents=agents, stamps=stamps)


@t.runtime_checkable
class Storage(t.Protocol):
    """A persistence sink for the store.

    Methods
    -------
    load()
        Return the persisted dict, or None if absent.
    save(data)
        Persist data durably.

    Examples
    --------
    >>> class MockStorage:
    ...     def __init__(self):
    ...         self._data = None
    ...     def load(self):
    ...         return self._data
    ...     def save(self, data):
    ...         self._data = data
    >>> storage = MockStorage()
    >>> storage.save({"agents": {}, "stamps": {}})
    >>> storage.load()
    {'agents': {}, 'stamps': {}}
    """

    def load(self) -> dict[str, t.Any] | None:
        """Return the persisted dict, or ``None`` if absent."""
        ...

    def save(self, data: dict[str, t.Any]) -> None:
        """Persist *data* durably."""
        ...


class JsonFile:
    """An atomic JSON :class:`Storage` (temp file + ``os.replace`` + ``fsync``).

    Parameters
    ----------
    path : str | pathlib.Path
        The file path to persist to.

    Examples
    --------
    >>> import tempfile, pathlib
    >>> d = pathlib.Path(tempfile.mkdtemp())
    >>> sink = JsonFile(d / "x.json")
    >>> sink.save({"agents": {}, "stamps": {}})
    >>> sink.load()["agents"]
    {}
    """

    def __init__(self, path: str | pathlib.Path) -> None:
        self._path = pathlib.Path(path)

    def load(self) -> dict[str, t.Any] | None:
        """Return the persisted dict, or ``None`` if the file is absent.

        Returns
        -------
        dict[str, Any] | None
            The loaded data, or None if the file does not exist.
        """
        try:
            with self._path.open(encoding="utf-8") as handle:
                return t.cast(dict[str, t.Any], json.load(handle))
        except FileNotFoundError:
            return None

    def save(self, data: dict[str, t.Any]) -> None:
        """Write *data* atomically (no partial file ever survives a crash).

        Parameters
        ----------
        data : dict[str, Any]
            The data to persist.

        Notes
        -----
        Uses a temporary file + fsync + os.replace to ensure atomicity.
        The temporary file is cleaned up on any exception.
        """
        directory = self._path.parent
        directory.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(directory), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
                handle.flush()
                os.fsync(handle.fileno())
            pathlib.Path(tmp).replace(self._path)
        except BaseException:
            with contextlib.suppress(OSError):
                pathlib.Path(tmp).unlink()
            raise
