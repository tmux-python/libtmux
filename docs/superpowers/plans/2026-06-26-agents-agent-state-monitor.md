# Agents — Agent-State Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `libtmux.experimental.agents` — a headless, resilient monitor that reports each tmux pane's coding-agent state (`RUNNING`/`AWAITING_INPUT`/`IDLE`/`EXITED`/`UNKNOWN`), fed by cooperative agent hooks (Claude Code + Codex), observed over the async control-mode engine, and exposed via FastMCP tools.

**Architecture:** tmux is the authority for the observed tree (the monitor is a projection); the monitor is the authority for agent state. State flows one direction: `subscribe() → classify → latest()-merge → store → derived tree → MCP`. A supervisor loop makes the control connection self-healing (reconnect → re-attach → resubscribe → reconcile). Per-pane agent state is a latest-wins entry (`Stamp(counter, writer)`), transport-shaped for a future multi-host pivot but single-host in v1.

**Tech Stack:** Python 3.10+, asyncio, the existing `experimental/engines` (AsyncControlModeEngine), `experimental/ops`, `experimental/models/snapshots.py`, `experimental/mcp` (FastMCP). No new third-party dependencies.

## Global Constraints

- `from __future__ import annotations` at the top of every module.
- Namespace stdlib imports: `import enum`, `import dataclasses`, `import typing as t`, `import os`, `import json`, `import asyncio`. `from dataclasses import dataclass, field` is the one allowed `from` for stdlib.
- NumPy-style docstrings on every public function/method/class; a **working doctest** on every public symbol (no `# doctest: +SKIP`).
- Functional tests only (no `class TestFoo`). Reuse fixtures `server`, `session`, `window`, `pane`. No `pytest-asyncio` — async tests wrap an inner `async def main()` driven by `asyncio.run`.
- Lazy `%`-style logging via `logging.getLogger(__name__)`; never f-strings in log calls.
- New package lives under `src/libtmux/experimental/agents/`; tests under `tests/experimental/agents/`.
- Naming is fixed: module/object names are `AgentState`, `Agent`, `Stamp`, `latest`, `AgentStore`, `apply`, `Storage`, `JsonFile`, `AgentMonitor`, `OptionSignal`, `OscSignal`, `AgentHook`, `ClaudeCodeHook`, `CodexHook`. Do not rename.
- Pre-commit gate (run before each commit): `uv run ruff format .` → `uv run ruff check . --fix` → `uv run mypy src tests` → `uv run pytest`.
- The design spec (`docs/superpowers/specs/2026-06-26-agents-agent-state-monitor-design.md`) must be excluded from the Sphinx build (Task 16) so `just build-docs` stays clean.

---

### Task 1: `AgentState` enum + `Agent` record

**Files:**
- Create: `src/libtmux/experimental/agents/__init__.py`
- Create: `src/libtmux/experimental/agents/state.py`
- Test: `tests/experimental/agents/__init__.py`, `tests/experimental/agents/test_state.py`

**Interfaces:**
- Produces: `AgentState` (str enum: `RUNNING`, `AWAITING_INPUT`, `IDLE`, `EXITED`, `UNKNOWN`); `Agent` frozen dataclass with fields `pane_id: str`, `key: str`, `name: str | None`, `state: AgentState`, `since: float`, `source: str`, `pid: int | None`, `alive: bool`, and properties `is_awaiting`/`is_running`; `AgentState.from_signal(value: str) -> AgentState` (maps a hook's raw string, unknown → `UNKNOWN`).

- [ ] **Step 1: Write the failing test**

```python
# tests/experimental/agents/test_state.py
"""Tests for the AgentState enum and Agent record."""

from __future__ import annotations

from libtmux.experimental.agents.state import Agent, AgentState


def test_from_signal_maps_known_and_unknown() -> None:
    assert AgentState.from_signal("running") is AgentState.RUNNING
    assert AgentState.from_signal("awaiting_input") is AgentState.AWAITING_INPUT
    assert AgentState.from_signal("idle") is AgentState.IDLE
    assert AgentState.from_signal("garbage") is AgentState.UNKNOWN


def test_agent_helpers() -> None:
    agent = Agent(
        pane_id="%1", key="%1", name="claude", state=AgentState.AWAITING_INPUT,
        since=1.0, source="option", pid=42, alive=True,
    )
    assert agent.is_awaiting is True
    assert agent.is_running is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/experimental/agents/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: libtmux.experimental.agents.state`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/libtmux/experimental/agents/__init__.py
"""Agent-state monitoring over tmux (experimental)."""

from __future__ import annotations
```

```python
# src/libtmux/experimental/agents/state.py
"""The agent-state vocabulary: the AgentState enum and the Agent record."""

from __future__ import annotations

import enum
from dataclasses import dataclass


class AgentState(str, enum.Enum):
    """What a coding agent in a pane is doing.

    Examples
    --------
    >>> AgentState.from_signal("running")
    <AgentState.RUNNING: 'running'>
    >>> AgentState.from_signal("nonsense")
    <AgentState.UNKNOWN: 'unknown'>
    """

    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    IDLE = "idle"
    EXITED = "exited"
    UNKNOWN = "unknown"

    @classmethod
    def from_signal(cls, value: str) -> AgentState:
        """Map a hook's raw state string to an :class:`AgentState`.

        Unrecognized values become :attr:`UNKNOWN` rather than raising, so a
        malformed signal can never crash the monitor.
        """
        try:
            return cls(value.strip().lower())
        except ValueError:
            return cls.UNKNOWN


@dataclass(frozen=True)
class Agent:
    """A pane's coding agent and its current state.

    Examples
    --------
    >>> a = Agent(pane_id="%1", key="%1", name="claude",
    ...           state=AgentState.RUNNING, since=1.0, source="option",
    ...           pid=42, alive=True)
    >>> a.is_running, a.is_awaiting
    (True, False)
    """

    pane_id: str
    key: str
    name: str | None
    state: AgentState
    since: float
    source: str
    pid: int | None
    alive: bool

    @property
    def is_awaiting(self) -> bool:
        """True when the agent is paused waiting on the human/orchestrator."""
        return self.state is AgentState.AWAITING_INPUT

    @property
    def is_running(self) -> bool:
        """True when the agent is actively working."""
        return self.state is AgentState.RUNNING
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/experimental/agents/test_state.py -v`
Expected: PASS (2 tests). Also `uv run pytest --doctest-modules src/libtmux/experimental/agents/state.py`.

- [ ] **Step 5: Commit**

```bash
git add src/libtmux/experimental/agents/__init__.py src/libtmux/experimental/agents/state.py tests/experimental/agents/
git commit -m "$(cat <<'EOF'
Agents(feat[state]): Add AgentState enum + Agent record

why: The shared vocabulary every agents module reads/writes.

what:
- AgentState (running/awaiting_input/idle/exited/unknown) with from_signal
- frozen Agent record + is_running/is_awaiting helpers
EOF
)"
```

---

### Task 2: `merge.py` — latest-wins ordering (`Stamp` + `latest`)

**Files:**
- Create: `src/libtmux/experimental/agents/merge.py`
- Test: `tests/experimental/agents/test_merge.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Stamp` frozen dataclass `(counter: int, writer: str)` with total ordering; `latest(current: Stamp | None, incoming: Stamp) -> bool`; `Clock = t.Callable[[], int]`; `MonotonicCounter` callable (a stateful `__call__() -> int` that strictly increments) usable as a default `Clock`.

- [ ] **Step 1: Write the failing test**

```python
# tests/experimental/agents/test_merge.py
"""Tests for latest-wins ordering."""

from __future__ import annotations

from libtmux.experimental.agents.merge import MonotonicCounter, Stamp, latest


def test_latest_prefers_higher_counter() -> None:
    assert latest(Stamp(1, "option"), Stamp(2, "option")) is True
    assert latest(Stamp(2, "option"), Stamp(1, "option")) is False


def test_latest_tie_breaks_on_writer() -> None:
    # equal counters: deterministic tie-break, never a coin flip
    assert latest(Stamp(1, "option"), Stamp(1, "osc")) is True
    assert latest(Stamp(1, "osc"), Stamp(1, "option")) is False


def test_latest_accepts_first_value() -> None:
    assert latest(None, Stamp(0, "option")) is True


def test_monotonic_counter_strictly_increases() -> None:
    clock = MonotonicCounter()
    assert [clock(), clock(), clock()] == [1, 2, 3]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/experimental/agents/test_merge.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# src/libtmux/experimental/agents/merge.py
"""Latest-wins ordering: when two updates for one pane race, keep the newer.

A ``Stamp`` is a logical clock ``(counter, writer)``. ``latest`` decides whether
an incoming stamp should replace the current one. The clock is pluggable: a
monotonic counter is single-host-correct; an HLC can drop in later for multi-host
without touching call sites.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

Clock = t.Callable[[], int]


@dataclass(frozen=True, order=True)
class Stamp:
    """A logical-clock tag on one state update.

    Ordered by ``counter`` first, then ``writer`` (a deterministic tie-break when
    two sources stamp the same counter).

    Examples
    --------
    >>> Stamp(2, "option") > Stamp(1, "osc")
    True
    >>> Stamp(1, "osc") > Stamp(1, "option")
    True
    """

    counter: int
    writer: str


def latest(current: Stamp | None, incoming: Stamp) -> bool:
    """Return ``True`` if *incoming* should replace *current* (it is newer).

    Examples
    --------
    >>> latest(None, Stamp(0, "option"))
    True
    >>> latest(Stamp(5, "option"), Stamp(4, "option"))
    False
    """
    return current is None or incoming > current


class MonotonicCounter:
    """A strictly-increasing integer clock for single-host stamping.

    Examples
    --------
    >>> clock = MonotonicCounter()
    >>> clock(), clock()
    (1, 2)
    """

    def __init__(self) -> None:
        self._value = 0

    def __call__(self) -> int:
        """Return the next integer (strictly greater than the previous)."""
        self._value += 1
        return self._value
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/experimental/agents/test_merge.py --doctest-modules src/libtmux/experimental/agents/merge.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/libtmux/experimental/agents/merge.py tests/experimental/agents/test_merge.py
git commit -m "$(cat <<'EOF'
Agents(feat[merge]): Add latest-wins Stamp ordering

why: Out-of-order/replayed agent-state updates must converge to newest.

what:
- Stamp(counter, writer) with deterministic tie-break
- latest() guard + pluggable Clock + MonotonicCounter default
EOF
)"
```

---

### Task 3: `store.py` — `AgentStore`, `apply` reducer, `Storage` + `JsonFile`

**Files:**
- Create: `src/libtmux/experimental/agents/store.py`
- Test: `tests/experimental/agents/test_store.py`

**Interfaces:**
- Consumes: `Agent`, `AgentState` (Task 1); `Stamp`, `latest` (Task 2).
- Produces:
  - `Observed` frozen dataclass `(pane_id, key, name, state: AgentState, stamp: Stamp, source: str, pid: int | None)` — a state event.
  - `Vanished` frozen dataclass `(pane_id)` — a pane is gone.
  - `AgentStore` frozen dataclass with `agents: dict[str, Agent]` and `stamps: dict[str, Stamp]`, plus `to_dict()`/`from_dict()`.
  - `apply(store: AgentStore, event: Observed | Vanished, *, now: float) -> AgentStore` — pure; applies the `latest()` guard for `Observed`, marks `EXITED` for `Vanished`.
  - `Storage` protocol (`load() -> dict | None`, `save(data: dict) -> None`).
  - `JsonFile(path)` — atomic `Storage` (temp file + `os.replace` + `fsync`).

- [ ] **Step 1: Write the failing test**

```python
# tests/experimental/agents/test_store.py
"""Tests for the durable store + reducer."""

from __future__ import annotations

import json

from libtmux.experimental.agents.merge import Stamp
from libtmux.experimental.agents.state import AgentState
from libtmux.experimental.agents.store import (
    AgentStore,
    JsonFile,
    Observed,
    Vanished,
    apply,
)


def _observed(state: str, counter: int) -> Observed:
    return Observed(
        pane_id="%1", key="%1", name="claude",
        state=AgentState.from_signal(state), stamp=Stamp(counter, "option"),
        source="option", pid=42,
    )


def test_apply_keeps_latest_and_ignores_stale() -> None:
    store = AgentStore()
    store = apply(store, _observed("running", 2), now=10.0)
    # a stale (lower-counter) update must not clobber the fresher one
    store = apply(store, _observed("idle", 1), now=11.0)
    assert store.agents["%1"].state is AgentState.RUNNING


def test_apply_advances_on_newer() -> None:
    store = AgentStore()
    store = apply(store, _observed("running", 1), now=10.0)
    store = apply(store, _observed("awaiting_input", 2), now=11.0)
    assert store.agents["%1"].state is AgentState.AWAITING_INPUT


def test_vanished_marks_exited() -> None:
    store = AgentStore()
    store = apply(store, _observed("running", 1), now=10.0)
    store = apply(store, Vanished(pane_id="%1"), now=12.0)
    assert store.agents["%1"].state is AgentState.EXITED
    assert store.agents["%1"].alive is False


def test_jsonfile_atomic_roundtrip(tmp_path) -> None:
    store = AgentStore()
    store = apply(store, _observed("running", 1), now=10.0)
    sink = JsonFile(tmp_path / "agents.json")
    sink.save(store.to_dict())
    # a partial temp file must never be left behind
    assert not list(tmp_path.glob("*.tmp"))
    restored = AgentStore.from_dict(sink.load())
    assert restored.agents["%1"].state is AgentState.RUNNING
    # the saved file is valid JSON
    assert json.loads((tmp_path / "agents.json").read_text())["agents"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/experimental/agents/test_store.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# src/libtmux/experimental/agents/store.py
"""The durable agent-state store and its pure reducer.

The store maps each pane to its current :class:`Agent` and the :class:`Stamp`
that produced it. The only mutator is :func:`apply`, a pure reducer that applies
the latest-wins guard. ``Storage``/``JsonFile`` persist the store atomically;
persistence is an optional seed in v1 (agents re-announce on reconnect).
"""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
import typing as t
from dataclasses import dataclass, field

from libtmux.experimental.agents.merge import Stamp, latest
from libtmux.experimental.agents.state import Agent, AgentState

if t.TYPE_CHECKING:
    import pathlib
    from collections.abc import Mapping


@dataclass(frozen=True)
class Observed:
    """An observed agent-state update from a signal source."""

    pane_id: str
    key: str
    name: str | None
    state: AgentState
    stamp: Stamp
    source: str
    pid: int | None


@dataclass(frozen=True)
class Vanished:
    """A pane that no longer exists (from reconcile or the health sweep)."""

    pane_id: str


@dataclass(frozen=True)
class AgentStore:
    """The current agent per pane plus the stamp that produced it.

    Examples
    --------
    >>> AgentStore().agents
    {}
    """

    agents: dict[str, Agent] = field(default_factory=dict)
    stamps: dict[str, Stamp] = field(default_factory=dict)

    def to_dict(self) -> dict[str, t.Any]:
        """Serialize to plain JSON-able data."""
        return {
            "agents": {
                key: {
                    "pane_id": a.pane_id, "key": a.key, "name": a.name,
                    "state": a.state.value, "since": a.since,
                    "source": a.source, "pid": a.pid, "alive": a.alive,
                }
                for key, a in self.agents.items()
            },
            "stamps": {
                key: [s.counter, s.writer] for key, s in self.stamps.items()
            },
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, t.Any]) -> AgentStore:
        """Reconstruct from :meth:`to_dict` output."""
        agents = {
            key: Agent(
                pane_id=a["pane_id"], key=a["key"], name=a["name"],
                state=AgentState(a["state"]), since=a["since"],
                source=a["source"], pid=a["pid"], alive=a["alive"],
            )
            for key, a in data.get("agents", {}).items()
        }
        stamps = {
            key: Stamp(counter=v[0], writer=v[1])
            for key, v in data.get("stamps", {}).items()
        }
        return cls(agents=agents, stamps=stamps)


def apply(
    store: AgentStore, event: Observed | Vanished, *, now: float
) -> AgentStore:
    """Return a new store with *event* applied (pure; latest-wins for Observed).

    Examples
    --------
    >>> from libtmux.experimental.agents.merge import Stamp
    >>> s = apply(AgentStore(), Observed("%1", "%1", "c", AgentState.RUNNING,
    ...           Stamp(1, "option"), "option", 7), now=1.0)
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
        pane_id=event.pane_id, key=event.key, name=event.name,
        state=event.state, since=now, source=event.source,
        pid=event.pid, alive=True,
    )
    return AgentStore(agents=agents, stamps=stamps)


@t.runtime_checkable
class Storage(t.Protocol):
    """A persistence sink for the store."""

    def load(self) -> dict[str, t.Any] | None:
        """Return the persisted dict, or ``None`` if absent."""
        ...

    def save(self, data: dict[str, t.Any]) -> None:
        """Persist *data* durably."""
        ...


class JsonFile:
    """An atomic JSON :class:`Storage` (temp file + ``os.replace`` + ``fsync``).

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
        self._path = os.fspath(path)

    def load(self) -> dict[str, t.Any] | None:
        """Return the persisted dict, or ``None`` if the file is absent."""
        try:
            with open(self._path, encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError:
            return None

    def save(self, data: dict[str, t.Any]) -> None:
        """Write *data* atomically (no partial file ever survives a crash)."""
        directory = os.path.dirname(self._path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self._path)
        except BaseException:
            with __import__("contextlib").suppress(OSError):
                os.unlink(tmp)
            raise
```

> Note: replace the inline `__import__("contextlib")` with a top-level `import contextlib` and `contextlib.suppress(OSError)` — shown inline only to keep the snippet self-contained.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/experimental/agents/test_store.py --doctest-modules src/libtmux/experimental/agents/store.py -v`
Expected: PASS (4 tests + doctests).

- [ ] **Step 5: Commit**

```bash
git add src/libtmux/experimental/agents/store.py tests/experimental/agents/test_store.py
git commit -m "Agents(feat[store]): Add AgentStore + pure apply reducer + atomic JsonFile"
```

---

### Task 4: `signals.py` — `OptionSignal` + `OscSignal` parsers

**Files:**
- Create: `src/libtmux/experimental/agents/signals.py`
- Test: `tests/experimental/agents/test_signals.py`

**Interfaces:**
- Consumes: `AgentState` (Task 1).
- Produces:
  - `Reading` frozen dataclass `(pane_id: str, state: AgentState, name: str | None, source: str)`.
  - `OptionSignal.parse(notification_raw: str) -> Reading | None` — parses a `%subscription-changed agentstate $S @W idx %P : VALUE` line; returns `None` for non-matching lines. The subscription spec constant `SUBSCRIPTION = "agentstate:%*:#{@agent_state}"`.
  - `OscSignal` — a per-pane byte accumulator: `feed(pane_id: str, data: bytes) -> list[Reading]` scans for `OSC 3008 ;state=… ST` across fragmented chunks, returning a Reading per complete sequence; tolerant of partial sequences spanning calls.

- [ ] **Step 1: Write the failing test**

```python
# tests/experimental/agents/test_signals.py
"""Tests for the two agent-state signal parsers."""

from __future__ import annotations

from libtmux.experimental.agents.state import AgentState
from libtmux.experimental.agents.signals import OptionSignal, OscSignal


def test_option_signal_parses_subscription_changed() -> None:
    line = "%subscription-changed agentstate $0 @0 1 %3 : running"
    reading = OptionSignal.parse(line)
    assert reading is not None
    assert reading.pane_id == "%3"
    assert reading.state is AgentState.RUNNING
    assert reading.source == "option"


def test_option_signal_ignores_other_notifications() -> None:
    assert OptionSignal.parse("%output %1 hello") is None
    assert OptionSignal.parse("%window-add @3") is None


def test_osc_signal_reassembles_fragmented_bytes() -> None:
    osc = OscSignal()
    # the probe proved %output arrives byte-fragmented; feed one byte at a time
    payload = b"\033]3008;state=awaiting_input\033\\"
    readings: list = []
    for i in range(len(payload)):
        readings.extend(osc.feed("%2", payload[i : i + 1]))
    assert len(readings) == 1
    assert readings[0].pane_id == "%2"
    assert readings[0].state is AgentState.AWAITING_INPUT
    assert readings[0].source == "osc"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/experimental/agents/test_signals.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# src/libtmux/experimental/agents/signals.py
"""The two channels an agent uses to report state.

``OptionSignal`` reads tmux ``@agent_state`` user-options surfaced as
``%subscription-changed`` (local; ~1 s debounced, re-queryable). ``OscSignal``
reads a bare ``OSC 3008`` escape out of ``%output`` (remote/SSH; instant), with a
per-pane accumulator because tmux delivers ``%output`` byte-fragmented.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from libtmux.experimental.agents.state import AgentState

#: The ``refresh-client -B`` spec the monitor installs for the local channel.
SUBSCRIPTION = "agentstate:%*:#{@agent_state}"

_SUB_RE = re.compile(
    r"^%subscription-changed\s+agentstate\s+\S+\s+\S+\s+\S+\s+(?P<pane>%\d+)\s+:\s+(?P<value>\S+)"
)
_OSC_RE = re.compile(rb"\033\]3008;([^\033\007]*)(?:\033\\|\007)")


@dataclass(frozen=True)
class Reading:
    """One observed agent-state reading from a signal channel."""

    pane_id: str
    state: AgentState
    name: str | None
    source: str


def _parse_payload(payload: str) -> tuple[AgentState, str | None]:
    """Parse an OSC/option payload like ``state=running`` (``name=`` optional)."""
    state = AgentState.UNKNOWN
    name: str | None = None
    for part in payload.split(";"):
        key, _, value = part.partition("=")
        if key == "state":
            state = AgentState.from_signal(value)
        elif key == "name":
            name = value or None
    return state, name


class OptionSignal:
    """Parse the local ``@agent_state`` subscription channel."""

    @staticmethod
    def parse(notification_raw: str) -> Reading | None:
        """Parse a ``%subscription-changed`` line; ``None`` if it isn't one.

        Examples
        --------
        >>> r = OptionSignal.parse(
        ...     "%subscription-changed agentstate $0 @0 1 %3 : running")
        >>> r.pane_id, r.state.value
        ('%3', 'running')
        >>> OptionSignal.parse("%output %1 hi") is None
        True
        """
        match = _SUB_RE.match(notification_raw)
        if match is None:
            return None
        state = AgentState.from_signal(match.group("value"))
        return Reading(match.group("pane"), state, None, "option")


class OscSignal:
    """Reassemble ``OSC 3008`` agent-state escapes out of fragmented ``%output``.

    Examples
    --------
    >>> osc = OscSignal()
    >>> osc.feed("%1", b"\\033]3008;state=idle\\033\\\\")[0].state.value
    'idle'
    """

    def __init__(self) -> None:
        self._buffers: dict[str, bytes] = {}

    def feed(self, pane_id: str, data: bytes) -> list[Reading]:
        """Append *data* for *pane_id*; return a Reading per complete escape."""
        buffer = self._buffers.get(pane_id, b"") + data
        readings: list[Reading] = []
        while True:
            match = _OSC_RE.search(buffer)
            if match is None:
                break
            payload = match.group(1).decode(errors="replace")
            state, name = _parse_payload(payload)
            readings.append(Reading(pane_id, state, name, "osc"))
            buffer = buffer[match.end() :]
        # keep only a bounded tail so a never-terminated OSC can't grow unbounded
        self._buffers[pane_id] = buffer[-4096:]
        return readings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/experimental/agents/test_signals.py --doctest-modules src/libtmux/experimental/agents/signals.py -v`
Expected: PASS (3 tests + doctests).

- [ ] **Step 5: Commit**

```bash
git add src/libtmux/experimental/agents/signals.py tests/experimental/agents/test_signals.py
git commit -m "Agents(feat[signals]): Add OptionSignal + fragmented-OSC OscSignal parsers"
```

---

### Task 5: `health.py` — process-aliveness check

**Files:**
- Create: `src/libtmux/experimental/agents/health.py`
- Test: `tests/experimental/agents/test_health.py`

**Interfaces:**
- Produces: `is_alive(pid: int | None) -> bool` — `os.kill(pid, 0)` semantics (`True` if signalable, `False` on `ProcessLookupError`, `True` on `PermissionError` — exists but not ours; `None` → `True` (PID-less remote: never declared dead by this check)).

- [ ] **Step 1: Write the failing test**

```python
# tests/experimental/agents/test_health.py
"""Tests for process-aliveness."""

from __future__ import annotations

import os

from libtmux.experimental.agents.health import is_alive


def test_self_is_alive() -> None:
    assert is_alive(os.getpid()) is True


def test_absent_pid_is_dead() -> None:
    # PID 0x7FFFFFFF is almost certainly not a live process
    assert is_alive(2_147_483_646) is False


def test_pidless_remote_never_declared_dead() -> None:
    assert is_alive(None) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/experimental/agents/test_health.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# src/libtmux/experimental/agents/health.py
"""Is the process behind a pane still alive?

Local panes carry a ``pane_pid`` we can probe with ``os.kill(pid, 0)``. Remote
(SSH) panes are PID-less; this check never declares them dead — they expire on a
keepalive TTL owned by the monitor instead.
"""

from __future__ import annotations

import os


def is_alive(pid: int | None) -> bool:
    """Return whether *pid* is a live process (``None`` → always alive).

    Examples
    --------
    >>> import os
    >>> is_alive(os.getpid())
    True
    >>> is_alive(None)
    True
    """
    if pid is None:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/experimental/agents/test_health.py --doctest-modules src/libtmux/experimental/agents/health.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/libtmux/experimental/agents/health.py tests/experimental/agents/test_health.py
git commit -m "Agents(feat[health]): Add is_alive process probe (PID-less remote safe)"
```

---

### Task 6: `tree.py` — live session→window→pane tree

**Files:**
- Create: `src/libtmux/experimental/agents/tree.py`
- Test: `tests/experimental/agents/test_tree.py`

**Interfaces:**
- Consumes: `ServerSnapshot.from_pane_rows` from `libtmux.experimental.models.snapshots`.
- Produces:
  - `PANE_FORMAT: tuple[str, ...]` — the format fields to request: `("session_id","session_name","window_id","window_index","window_name","window_active","pane_id","pane_index","pane_active","pane_pid","pane_current_command","pane_title")`.
  - `panes_of(snapshot) -> dict[str, PaneSnapshot]` — flatten a `ServerSnapshot` to `{pane_id: PaneSnapshot}`.
  - `diff_panes(old: dict, new: dict) -> tuple[list[str], list[str]]` — returns `(added_pane_ids, removed_pane_ids)` for synthetic reconcile events.

- [ ] **Step 1: Write the failing test**

```python
# tests/experimental/agents/test_tree.py
"""Tests for the derived tmux tree helpers."""

from __future__ import annotations

from libtmux.experimental.agents.tree import diff_panes, panes_of
from libtmux.experimental.models.snapshots import ServerSnapshot


def _snap(pane_ids: list[str]) -> ServerSnapshot:
    rows = [
        {"session_id": "$0", "window_id": "@0", "window_index": "0",
         "pane_id": pid, "pane_index": str(i)}
        for i, pid in enumerate(pane_ids)
    ]
    return ServerSnapshot.from_pane_rows(rows)


def test_panes_of_flattens() -> None:
    assert set(panes_of(_snap(["%1", "%2"]))) == {"%1", "%2"}


def test_diff_panes_reports_added_and_removed() -> None:
    old = panes_of(_snap(["%1", "%2"]))
    new = panes_of(_snap(["%2", "%3"]))
    added, removed = diff_panes(old, new)
    assert added == ["%3"]
    assert removed == ["%1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/experimental/agents/test_tree.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# src/libtmux/experimental/agents/tree.py
"""The live session→window→pane tree, derived from tmux (never the truth).

A thin layer over ``ServerSnapshot.from_pane_rows``: the format to request, a
flattener to a ``{pane_id: PaneSnapshot}`` map, and a diff used by the monitor's
reconcile to synthesize the add/remove events the notification stream missed.
"""

from __future__ import annotations

import typing as t

if t.TYPE_CHECKING:
    from libtmux.experimental.models.snapshots import PaneSnapshot, ServerSnapshot

PANE_FORMAT: tuple[str, ...] = (
    "session_id", "session_name",
    "window_id", "window_index", "window_name", "window_active",
    "pane_id", "pane_index", "pane_active", "pane_pid",
    "pane_current_command", "pane_title",
)


def panes_of(snapshot: ServerSnapshot) -> dict[str, PaneSnapshot]:
    """Flatten a server snapshot to ``{pane_id: PaneSnapshot}``.

    Examples
    --------
    >>> from libtmux.experimental.models.snapshots import ServerSnapshot
    >>> snap = ServerSnapshot.from_pane_rows(
    ...     [{"session_id": "$0", "window_id": "@0", "pane_id": "%1"}])
    >>> list(panes_of(snap))
    ['%1']
    """
    return {
        pane.pane_id: pane
        for session in snapshot.sessions
        for window in session.windows
        for pane in window.panes
    }


def diff_panes(
    old: dict[str, t.Any], new: dict[str, t.Any]
) -> tuple[list[str], list[str]]:
    """Return ``(added_pane_ids, removed_pane_ids)`` between two pane maps.

    Examples
    --------
    >>> diff_panes({"%1": 1, "%2": 1}, {"%2": 1, "%3": 1})
    (['%3'], ['%1'])
    """
    added = [pid for pid in new if pid not in old]
    removed = [pid for pid in old if pid not in new]
    return added, removed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/experimental/agents/test_tree.py --doctest-modules src/libtmux/experimental/agents/tree.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/libtmux/experimental/agents/tree.py tests/experimental/agents/test_tree.py
git commit -m "Agents(feat[tree]): Add derived pane tree + reconcile diff helpers"
```

---

### Task 7: Extend the `refresh-client` op with `-B`/`-C`

**Files:**
- Modify: `src/libtmux/experimental/ops/_ops/refresh_client.py`
- Test: `tests/experimental/ops/test_refresh_client_subscribe.py`

**Interfaces:**
- Consumes/Produces: `RefreshClient` gains two optional fields — `subscribe: str | None = None` (emits `-B <spec>`) and `size: str | None = None` (emits `-C <size>`). `args()` returns them in order: `-B` then `-C`. Existing behavior (empty args) unchanged when both are `None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/experimental/ops/test_refresh_client_subscribe.py
"""Tests for refresh-client -B/-C support."""

from __future__ import annotations

from libtmux.experimental.ops._ops.refresh_client import RefreshClient
from libtmux.experimental.ops._types import ClientName


def test_subscribe_emits_dash_b() -> None:
    op = RefreshClient(target=ClientName("/dev/pts/3"),
                       subscribe="agentstate:%*:#{@agent_state}")
    assert op.render() == (
        "refresh-client", "-t", "/dev/pts/3",
        "-B", "agentstate:%*:#{@agent_state}",
    )


def test_size_emits_dash_c() -> None:
    op = RefreshClient(target=ClientName("/dev/pts/3"), size="200x50")
    assert op.render() == ("refresh-client", "-t", "/dev/pts/3", "-C", "200x50")


def test_no_extra_args_by_default() -> None:
    op = RefreshClient(target=ClientName("/dev/pts/3"))
    assert op.render() == ("refresh-client", "-t", "/dev/pts/3")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/experimental/ops/test_refresh_client_subscribe.py -v`
Expected: FAIL — `TypeError: unexpected keyword 'subscribe'`.

- [ ] **Step 3: Write minimal implementation**

Modify `src/libtmux/experimental/ops/_ops/refresh_client.py`: add the two fields and rewrite `args()`:

```python
    subscribe: str | None = None
    size: str | None = None

    def args(self, *, version: str | None = None) -> tuple[str, ...]:
        """Emit ``-B <spec>`` and/or ``-C <size>`` when set."""
        out: list[str] = []
        if self.subscribe is not None:
            out += ["-B", self.subscribe]
        if self.size is not None:
            out += ["-C", self.size]
        return tuple(out)
```

Add a doctest line to the class docstring demonstrating `subscribe=`. Confirm `render()` already prefixes `-t <target>` (it does, via `Operation.render`).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/experimental/ops/test_refresh_client_subscribe.py --doctest-modules src/libtmux/experimental/ops/_ops/refresh_client.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/libtmux/experimental/ops/_ops/refresh_client.py tests/experimental/ops/test_refresh_client_subscribe.py
git commit -m "Ops(feat[refresh_client]): Add typed -B subscription + -C size"
```

---

### Task 8: Engine death-sentinel — close subscriber generators on death

**Files:**
- Modify: `src/libtmux/experimental/engines/async_control_mode.py`
- Test: `tests/experimental/engines/test_async_control_mode_sentinel.py`

**Interfaces:**
- Consumes: existing `AsyncControlModeEngine` internals (`_subscribers`, `_mark_dead`, `subscribe`, `_reader`, `aclose` at lines 144–414).
- Produces: a private sentinel object `_STREAM_END`; `subscribe()` raises `StopAsyncIteration` (ends the `async for`) when it dequeues `_STREAM_END`; `_mark_dead` and `aclose` broadcast `_STREAM_END` to every subscriber queue (via the existing `_offer`/`put_nowait` path) so a dead stream **closes** consumers instead of hanging — making `accumulate_until_settle` return `reason="stream_end"` (it already does on `StopAsyncIteration`, `_settle.py:259`).

- [ ] **Step 1: Write the failing test**

```python
# tests/experimental/engines/test_async_control_mode_sentinel.py
"""A dead engine must CLOSE subscriber generators, not hang them."""

from __future__ import annotations

import asyncio

from libtmux.experimental.engines.async_control_mode import (
    AsyncControlModeEngine,
    ControlModeError,
)


def test_subscribe_ends_when_engine_marked_dead() -> None:
    async def main() -> list:
        engine = AsyncControlModeEngine()
        # do not spawn tmux: drive _subscribers + _mark_dead directly
        queue: asyncio.Queue = asyncio.Queue(maxsize=16)
        engine._subscribers.add(queue)

        seen: list = []

        async def consume() -> None:
            agen = engine.subscribe()
            # re-register the real subscribe queue, then mark dead
            async for note in agen:
                seen.append(note)

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.05)
        engine._mark_dead(ControlModeError("boom"))
        await asyncio.wait_for(task, timeout=1.0)  # must NOT hang
        return seen

    asyncio.run(main())
```

> The test asserts the consumer task completes (no `asyncio.TimeoutError`). The exact `seen` contents don't matter — only that the generator ends.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/experimental/engines/test_async_control_mode_sentinel.py -v`
Expected: FAIL — `asyncio.TimeoutError` (the generator hangs on `queue.get()`).

- [ ] **Step 3: Write minimal implementation**

In `async_control_mode.py`:

1. Add a module-level sentinel after the imports:

```python
_STREAM_END = object()  # broadcast to subscriber queues to end their async for
```

2. In `subscribe()` (line ~277), end on the sentinel:

```python
        try:
            while True:
                item = await queue.get()
                if item is _STREAM_END:
                    return
                yield item
        finally:
            self._subscribers.discard(queue)
```

(Type the queue as `asyncio.Queue[t.Any]` so the sentinel is allowed.)

3. Add a broadcast helper and call it from `_mark_dead` and `aclose`:

```python
    def _broadcast_stream_end(self) -> None:
        """Push the stream-end sentinel to every subscriber, then clear them."""
        for queue in list(self._subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(_STREAM_END)
        self._subscribers.clear()
```

Call `self._broadcast_stream_end()` at the end of `_mark_dead` (after `_fail_pending`) and inside `aclose` (after cancelling the reader, before failing pending).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/experimental/engines/test_async_control_mode_sentinel.py tests/experimental/ -k "control_mode" -v`
Expected: PASS, and no regressions in existing control-mode tests.

- [ ] **Step 5: Commit**

```bash
git add src/libtmux/experimental/engines/async_control_mode.py tests/experimental/engines/test_async_control_mode_sentinel.py
git commit -m "$(cat <<'EOF'
Engines(fix[async_control_mode]): Close subscribers on engine death

why: A dead stream left consumers hanging on queue.get(), so settle
reported a false 'settled' (success-shaped) instead of stream_end.

what:
- broadcast a _STREAM_END sentinel to subscriber queues on death/close
- subscribe() ends its async for on the sentinel
EOF
)"
```

---

### Task 9: Engine supervisor — reconnect → re-attach → resubscribe → reconcile

**Files:**
- Modify: `src/libtmux/experimental/engines/async_control_mode.py`
- Test: `tests/experimental/engines/test_async_control_mode_supervisor.py`

**Interfaces:**
- Consumes: the death-sentinel (Task 8); `start`/`aclose`/`_reader`.
- Produces:
  - Desired-state fields on the engine: `self._desired_subscriptions: list[str]` and `self._desired_attach: list[str]` (sessions to attach), plus `self._generation: int` (bumped each (re)connect).
  - `add_subscription(spec: str)` / `set_attach_targets(session_ids: list[str])` — record desired state (idempotent; replayed on reconnect).
  - A `_closing: bool` flag set by `aclose()` before teardown so an intentional close isn't retried.
  - A supervised reconnect: when the reader returns on EOF (not `_closing`), spawn a fresh proc with jittered backoff, reset the parser + fail pending, clear the sticky attach (Task 10 wires `events._attached_session`), replay subscriptions, then continue reading. v1 keeps this minimal: the test exercises one reconnect cycle.

> This task is the largest brownfield change. Implement it against the file read in context. The reconnect lives in a `_supervisor()` task that owns the proc lifecycle; `start()` launches `_supervisor()` instead of `_reader()` directly. Keep the existing FIFO/`_pending` correlation; reconnect is the only place permitted to `_fail_pending` + fresh-`ControlModeParser`.

- [ ] **Step 1: Write the failing test**

```python
# tests/experimental/engines/test_async_control_mode_supervisor.py
"""The engine reconnects and replays desired state after the proc dies."""

from __future__ import annotations

import asyncio

from libtmux.experimental.engines.async_control_mode import AsyncControlModeEngine


def test_desired_subscriptions_recorded_idempotently() -> None:
    engine = AsyncControlModeEngine()
    engine.add_subscription("agentstate:%*:#{@agent_state}")
    engine.add_subscription("agentstate:%*:#{@agent_state}")  # idempotent
    assert engine._desired_subscriptions == ["agentstate:%*:#{@agent_state}"]


def test_reconnects_after_proc_exits(server) -> None:
    async def main() -> int:
        engine = AsyncControlModeEngine.for_server(server)
        await engine.start()
        gen0 = engine._generation
        # simulate the control proc dying
        assert engine._proc is not None
        engine._proc.terminate()
        await asyncio.sleep(1.5)  # supervisor backoff + reconnect
        # a fresh run must succeed over the reconnected proc
        from libtmux.experimental.engines.base import CommandRequest
        result = await engine.run(CommandRequest.from_args("list-sessions"))
        await engine.aclose()
        assert result.returncode == 0
        return engine._generation - gen0

    bumped = asyncio.run(main())
    assert bumped >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/experimental/engines/test_async_control_mode_supervisor.py -v`
Expected: FAIL — `AttributeError: _desired_subscriptions` / no reconnect.

- [ ] **Step 3: Write minimal implementation**

Implement in `async_control_mode.py`:
- Add `__init__` fields: `self._desired_subscriptions: list[str] = []`, `self._desired_attach: list[str] = []`, `self._generation = 0`, `self._closing = False`, `self._supervisor_task: asyncio.Task[None] | None = None`.
- `add_subscription(spec)` appends `spec` if absent. `set_attach_targets(ids)` stores a copy.
- Replace the `start()` reader launch with a `_supervisor()` task. `_supervisor()`:
  1. spawn proc + `_consume_startup()` (extract the spawn from `start()` into `_spawn()`),
  2. `self._generation += 1`,
  3. replay: `await self.run_batch([CommandRequest.from_args("refresh-client", "-B", s) for s in self._desired_subscriptions])` (skip if empty),
  4. run the existing `_reader()` loop inline,
  5. on EOF/return when not `self._closing`: `self._parser = ControlModeParser()`, `self._fail_pending(...)`, jittered `await asyncio.sleep(backoff)` (e.g. `min(0.1 * 2**n, 5.0)` plus a small fixed jitter derived from `n`, never `random`), loop.
- `aclose()` sets `self._closing = True` first, cancels `_supervisor_task`.

> Attach replay (`_desired_attach`) is wired in Task 10 (it lives in `events._ensure_attached`). For this task, replaying subscriptions + bumping generation + reconnect is sufficient.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/experimental/engines/test_async_control_mode_supervisor.py -v`
Expected: PASS (2 tests). Run the full control-mode suite for regressions: `uv run pytest tests/experimental/ -k control_mode -v`.

- [ ] **Step 5: Commit**

```bash
git add src/libtmux/experimental/engines/async_control_mode.py tests/experimental/engines/test_async_control_mode_supervisor.py
git commit -m "Engines(feat[async_control_mode]): Add supervised reconnect + desired-state replay"
```

---

### Task 10: Reset the sticky attach on reconnect

**Files:**
- Modify: `src/libtmux/experimental/mcp/events.py` (`_ensure_attached`, ~line 374–396)
- Modify: `src/libtmux/experimental/engines/async_control_mode.py` (clear the flag on reconnect)
- Test: `tests/experimental/mcp/test_attach_reset.py`

**Interfaces:**
- Produces: `_ensure_attached` stores the attached session on the engine and the engine's `_supervisor()` clears it on each (re)connect so the next `_ensure_attached` re-attaches (today the flag is sticky and a reconnect silently emits no `%output`). Add `AsyncControlModeEngine._reset_attach()` that sets `self._attached_session = None`; call it in `_supervisor()` right after `_spawn()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/experimental/mcp/test_attach_reset.py
"""A reconnect must clear the sticky attach so %output flows again."""

from __future__ import annotations

from libtmux.experimental.engines.async_control_mode import AsyncControlModeEngine


def test_reset_attach_clears_flag() -> None:
    engine = AsyncControlModeEngine()
    engine._attached_session = "$0"
    engine._reset_attach()
    assert getattr(engine, "_attached_session", "sentinel") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/experimental/mcp/test_attach_reset.py -v`
Expected: FAIL — `AttributeError: _reset_attach`.

- [ ] **Step 3: Write minimal implementation**

- In `async_control_mode.py`: add `self._attached_session: str | None = None` to `__init__`; add `def _reset_attach(self) -> None: self._attached_session = None`; call `self._reset_attach()` in `_supervisor()` immediately after spawning a fresh proc.
- In `events.py`: confirm `_ensure_attached` reads/writes `engine._attached_session` (it already does at lines 387/396); no change needed beyond the field now being declared on the engine (remove the `# type: ignore` since the attribute is now real).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/experimental/mcp/test_attach_reset.py tests/experimental/mcp/ -k event -v`
Expected: PASS, no event-tool regressions.

- [ ] **Step 5: Commit**

```bash
git add src/libtmux/experimental/engines/async_control_mode.py src/libtmux/experimental/mcp/events.py tests/experimental/mcp/test_attach_reset.py
git commit -m "Engines(fix[async_control_mode]): Reset sticky attach on reconnect"
```

---

### Task 11: `monitor.py` — `AgentMonitor` core

**Files:**
- Create: `src/libtmux/experimental/agents/monitor.py`
- Test: `tests/experimental/agents/test_monitor.py` (unit, fake engine)

**Interfaces:**
- Consumes: `AgentStore`/`apply`/`Observed`/`Vanished` (Task 3); `OptionSignal`/`OscSignal`/`Reading`/`SUBSCRIPTION` (Task 4); `is_alive` (Task 5); `panes_of`/`diff_panes`/`PANE_FORMAT` (Task 6); `Stamp`/`MonotonicCounter` (Task 2); `Agent`/`AgentState` (Task 1); an engine with `run`, `subscribe`, `add_subscription`, `set_attach_targets`.
- Produces:
  - `AgentMonitor(engine, *, sink: Storage | None = None, clock: Clock | None = None)`.
  - `agents` property → `list[Agent]` snapshot (from the coalescing store).
  - `ingest(notification_raw: str) -> None` — classify one notification (option line → `Observed`; `%output` → feed `OscSignal`) and `apply()` with the `latest()` guard, stamping via the clock.
  - `async start()` / `async stop()` / `async reconcile()` / `status() -> dict`.
  - The reducer write site applies the `latest()` guard inside `apply` **before** the store overwrites (Task 3 guarantees this).

- [ ] **Step 1: Write the failing test** (unit: drive `ingest` directly, no tmux)

```python
# tests/experimental/agents/test_monitor.py
"""Unit tests for AgentMonitor.ingest (no live tmux)."""

from __future__ import annotations

from libtmux.experimental.agents.monitor import AgentMonitor
from libtmux.experimental.agents.state import AgentState


class _FakeEngine:
    async def run(self, request): ...
    async def subscribe(self): ...
    def add_subscription(self, spec): ...
    def set_attach_targets(self, ids): ...


def test_ingest_option_line_updates_agent() -> None:
    mon = AgentMonitor(_FakeEngine())
    mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : running")
    by_pane = {a.pane_id: a for a in mon.agents}
    assert by_pane["%1"].state is AgentState.RUNNING


def test_ingest_osc_output_updates_agent() -> None:
    mon = AgentMonitor(_FakeEngine())
    mon.ingest("%output %2 \033]3008;state=awaiting_input\033\\")
    by_pane = {a.pane_id: a for a in mon.agents}
    assert by_pane["%2"].state is AgentState.AWAITING_INPUT


def test_stale_does_not_clobber() -> None:
    mon = AgentMonitor(_FakeEngine())
    mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : running")
    mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : idle")
    # newest wins; both via the option writer so the second (newer counter) wins
    by_pane = {a.pane_id: a for a in mon.agents}
    assert by_pane["%1"].state is AgentState.IDLE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/experimental/agents/test_monitor.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

Implement `AgentMonitor` with:
- `__init__` stores engine, sink, `self._clock = clock or MonotonicCounter()`, `self._store = AgentStore()` (seeded from `sink.load()` if present), `self._osc = OscSignal()`.
- `ingest(raw)`:
  - if `raw` starts with `%output `: split `"%output", pane, rest`; for each `Reading` from `self._osc.feed(pane, rest_bytes)` → `self._observe(reading)`.
  - else try `OptionSignal.parse(raw)`; if a `Reading`, `self._observe(reading)`.
- `_observe(reading)`: build `Observed(pane_id=reading.pane_id, key=reading.pane_id, name=reading.name, state=reading.state, stamp=Stamp(self._clock(), reading.source), source=reading.source, pid=None)`; `self._store = apply(self._store, observed, now=<monotonic>)`; if `self._sink`: `self._sink.save(self._store.to_dict())`.
- `agents` property returns `list(self._store.agents.values())`.
- `async start()`: `self._engine.add_subscription(SUBSCRIPTION)`; record attach targets from a `list-sessions` (Task 12 wires the live loop); spawn a task draining `engine.subscribe()` into `ingest`.
- `async reconcile()`: run `list-panes -a -F <PANE_FORMAT>` via the engine, build a `ServerSnapshot`, diff vs the prior pane set, `apply(Vanished)` for removed panes; refresh `pid`/`alive` via `is_alive`.
- `status()` returns `{"agents": len(self._store.agents), "generation": getattr(engine, "_generation", 0)}`.

> Keep `ingest` synchronous and pure-ish (mutating only `self._store`/`self._osc`) so the unit test needs no tmux. The async drain loop calls `ingest` per notification.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/experimental/agents/test_monitor.py --doctest-modules src/libtmux/experimental/agents/monitor.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/libtmux/experimental/agents/monitor.py tests/experimental/agents/test_monitor.py
git commit -m "Agents(feat[monitor]): Add AgentMonitor ingest + store wiring"
```

---

### Task 12: `hooks/emit.py` — the shared emitter + console entry point

**Files:**
- Create: `src/libtmux/experimental/agents/hooks/__init__.py`
- Create: `src/libtmux/experimental/agents/hooks/emit.py`
- Modify: `pyproject.toml` (add a `[project.scripts]` entry `libtmux-agent-emit`)
- Test: `tests/experimental/agents/hooks/__init__.py`, `tests/experimental/agents/hooks/test_emit.py`

**Interfaces:**
- Produces: `emit(state: str, *, name: str | None = None, runner=subprocess.run, tty_path="/dev/tty", env=None) -> None` — when `$TMUX` is set in `env`, runs `tmux set-option -p -t $TMUX_PANE @agent_state <state>` (and `@agent_name` if `name`); else writes the `OSC 3008` escape to `tty_path`. `main(argv)` is the console entry point (`libtmux-agent-emit <state> [--name NAME]`).

- [ ] **Step 1: Write the failing test** (inject a fake runner + a tmp tty file)

```python
# tests/experimental/agents/hooks/test_emit.py
"""Tests for the shared agent-state emitter."""

from __future__ import annotations

from libtmux.experimental.agents.hooks.emit import emit


def test_local_uses_set_option() -> None:
    calls: list = []
    emit(
        "running",
        runner=lambda argv, **kw: calls.append(argv),
        env={"TMUX": "/tmp/x,1,0", "TMUX_PANE": "%4"},
    )
    assert calls[0][:5] == ["tmux", "set-option", "-p", "-t", "%4"]
    assert calls[0][5:] == ["@agent_state", "running"]


def test_remote_writes_osc_to_tty(tmp_path) -> None:
    tty = tmp_path / "tty"
    tty.write_bytes(b"")
    emit("idle", tty_path=str(tty), env={})  # no TMUX → remote path
    data = tty.read_bytes()
    assert b"\033]3008;state=idle\033\\" in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/experimental/agents/hooks/test_emit.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# src/libtmux/experimental/agents/hooks/__init__.py
"""Agent-side hook emitters + installers."""

from __future__ import annotations
```

```python
# src/libtmux/experimental/agents/hooks/emit.py
"""Emit an agent-state signal from inside an agent's lifecycle hook.

Local (tmux reachable): write the ``@agent_state`` pane option. Remote (SSH):
write an ``OSC 3008`` escape to ``/dev/tty`` -- NOT stdout, which agent hooks
pipe/null -- so it reaches the pane pty and travels over SSH into tmux %output.
"""

from __future__ import annotations

import os
import subprocess
import sys
import typing as t

if t.TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def emit(
    state: str,
    *,
    name: str | None = None,
    runner: t.Callable[..., t.Any] = subprocess.run,
    tty_path: str = "/dev/tty",
    env: Mapping[str, str] | None = None,
) -> None:
    """Signal *state* for the current pane (local set-option, else remote OSC).

    Examples
    --------
    >>> calls = []
    >>> emit("running", runner=lambda a, **k: calls.append(a),
    ...      env={"TMUX": "x", "TMUX_PANE": "%1"})
    >>> calls[0][:2]
    ['tmux', 'set-option']
    """
    environ = os.environ if env is None else env
    pane = environ.get("TMUX_PANE")
    if environ.get("TMUX") and pane:
        runner(
            ["tmux", "set-option", "-p", "-t", pane, "@agent_state", state],
            check=False,
        )
        if name:
            runner(
                ["tmux", "set-option", "-p", "-t", pane, "@agent_name", name],
                check=False,
            )
        return
    payload = f"state={state}"
    if name:
        payload += f";name={name}"
    escape = f"\033]3008;{payload}\033\\".encode()
    with open(tty_path, "wb", buffering=0) as tty:
        tty.write(escape)


def main(argv: Sequence[str] | None = None) -> int:
    """Console entry point: ``libtmux-agent-emit <state> [--name NAME]``."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return 2
    state = args[0]
    name = None
    if "--name" in args:
        name = args[args.index("--name") + 1]
    emit(state, name=name)
    return 0
```

Add to `pyproject.toml` under `[project.scripts]`:

```toml
libtmux-agent-emit = "libtmux.experimental.agents.hooks.emit:main"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/experimental/agents/hooks/test_emit.py --doctest-modules src/libtmux/experimental/agents/hooks/emit.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/libtmux/experimental/agents/hooks/ tests/experimental/agents/hooks/ pyproject.toml
git commit -m "Agents(feat[hooks]): Add shared emitter (local set-option / remote OSC to tty)"
```

---

### Task 13: `hooks/base.py` + `hooks/registry.py` — the `AgentHook` protocol + registry

**Files:**
- Create: `src/libtmux/experimental/agents/hooks/base.py`
- Create: `src/libtmux/experimental/agents/hooks/registry.py`
- Test: `tests/experimental/agents/hooks/test_registry.py`

**Interfaces:**
- Produces:
  - `EVENT_STATE: dict[str, str]` — canonical lifecycle→state map keyed by a neutral event name: `{"turn_start": "running", "needs_approval": "awaiting_input", "turn_end": "awaiting_input", "session_start": "idle"}`.
  - `AgentHook` protocol: `name: str`, `detect() -> bool`, `install() -> None`, `uninstall() -> None`, `status() -> str` (`"installed"`/`"outdated"`/`"absent"`).
  - `registry() -> list[AgentHook]` returning `[ClaudeCodeHook(), CodexHook()]` (imported lazily to avoid cycles).
  - `get(name: str) -> AgentHook` (raises `KeyError` if unknown).

- [ ] **Step 1: Write the failing test**

```python
# tests/experimental/agents/hooks/test_registry.py
"""Tests for the hook registry + canonical event map."""

from __future__ import annotations

from libtmux.experimental.agents.hooks.base import EVENT_STATE
from libtmux.experimental.agents.hooks.registry import get, registry


def test_event_state_map_is_canonical() -> None:
    assert EVENT_STATE["turn_start"] == "running"
    assert EVENT_STATE["needs_approval"] == "awaiting_input"


def test_registry_has_claude_and_codex() -> None:
    names = {hook.name for hook in registry()}
    assert {"claude", "codex"} <= names


def test_get_unknown_raises() -> None:
    try:
        get("nope")
    except KeyError:
        return
    raise AssertionError("expected KeyError")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/experimental/agents/hooks/test_registry.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

`base.py` defines `EVENT_STATE` and the `AgentHook` `t.Protocol`. `registry.py` imports `ClaudeCodeHook`/`CodexHook` (Tasks 14/15) lazily inside `registry()` and `get()`. (Implement `registry()`/`get()` now; the two hook classes are filled in next. To keep this task green standalone, stub `ClaudeCodeHook`/`CodexHook` as classes with `name` attributes and no-op `detect/install/uninstall/status` returning `"absent"`, then flesh them out in Tasks 14–15.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/experimental/agents/hooks/test_registry.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/libtmux/experimental/agents/hooks/base.py src/libtmux/experimental/agents/hooks/registry.py tests/experimental/agents/hooks/test_registry.py
git commit -m "Agents(feat[hooks]): Add AgentHook protocol + registry + event→state map"
```

---

### Task 14: `hooks/claude.py` — Claude Code installer

**Files:**
- Create: `src/libtmux/experimental/agents/hooks/claude.py`
- Test: `tests/experimental/agents/hooks/test_claude.py`

**Interfaces:**
- Consumes: `EVENT_STATE` (Task 13).
- Produces: `ClaudeCodeHook(settings_path: pathlib.Path | None = None)` implementing `AgentHook`. `install()` merges hook entries into `~/.claude/settings.json` (`UserPromptSubmit`→running, `Notification`→awaiting_input, `Stop`→awaiting_input, `SessionStart`→idle), each running `libtmux-agent-emit <state>`. `status()` returns `installed`/`outdated`/`absent`. `uninstall()` removes only our entries (never clobbers unrelated user hooks).

- [ ] **Step 1: Write the failing test** (round-trip against a `tmp_path` settings file)

```python
# tests/experimental/agents/hooks/test_claude.py
"""Tests for the Claude Code hook installer."""

from __future__ import annotations

import json

from libtmux.experimental.agents.hooks.claude import ClaudeCodeHook


def test_install_status_uninstall_roundtrip(tmp_path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": "echo user-owned"}]}]}}))
    hook = ClaudeCodeHook(settings_path=settings)

    assert hook.status() == "absent"
    hook.install()
    assert hook.status() == "installed"

    data = json.loads(settings.read_text())
    stop_cmds = [
        h["command"] for grp in data["hooks"]["Stop"] for h in grp["hooks"]
    ]
    assert any("libtmux-agent-emit awaiting_input" in c for c in stop_cmds)
    assert "echo user-owned" in stop_cmds  # never clobber the user's hook

    hook.uninstall()
    assert hook.status() == "absent"
    data = json.loads(settings.read_text())
    stop_cmds = [
        h["command"] for grp in data["hooks"].get("Stop", []) for h in grp["hooks"]
    ]
    assert "echo user-owned" in stop_cmds  # still there


def test_install_is_idempotent(tmp_path) -> None:
    settings = tmp_path / "settings.json"
    hook = ClaudeCodeHook(settings_path=settings)
    hook.install()
    hook.install()
    assert hook.status() == "installed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/experimental/agents/hooks/test_claude.py -v`
Expected: FAIL — `ClaudeCodeHook` is the stub.

- [ ] **Step 3: Write minimal implementation**

Implement `ClaudeCodeHook`. Map Claude event → state: `{"UserPromptSubmit": "running", "Notification": "awaiting_input", "Stop": "awaiting_input", "SessionStart": "idle"}`. Tag our entries with a stable marker (e.g. `command` contains `libtmux-agent-emit`) so `status()`/`uninstall()` can find them without touching user entries. `install()` is idempotent (remove-then-add our entries). Default `settings_path` = `pathlib.Path.home() / ".claude" / "settings.json"`. Write atomically (reuse `JsonFile` from Task 3 or an equivalent temp+replace).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/experimental/agents/hooks/test_claude.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/libtmux/experimental/agents/hooks/claude.py tests/experimental/agents/hooks/test_claude.py
git commit -m "Agents(feat[hooks]): Add Claude Code hook installer (non-clobbering)"
```

---

### Task 15: `hooks/codex.py` — Codex installer

**Files:**
- Create: `src/libtmux/experimental/agents/hooks/codex.py`
- Test: `tests/experimental/agents/hooks/test_codex.py`

**Interfaces:**
- Produces: `CodexHook(config_path: pathlib.Path | None = None)` implementing `AgentHook`. `install()` writes command hooks into Codex `[hooks]` TOML (`~/.codex/config.toml`): `user_prompt_submit`→running, `permission_request`→awaiting_input, `stop`→awaiting_input, `session_start`→idle, each a `{ type = "command", command = "libtmux-agent-emit <state>" }`. Codex passes the event JSON on stdin, but each event registers a separate hook so the command hard-codes its state. `status()`/`uninstall()` are non-clobbering. Use a TOML lib already in the deps (`tomllib` for read on 3.11+, plus the project's existing TOML writer; if none, write the `[hooks]` block as text idempotently between marker comments).

- [ ] **Step 1: Write the failing test**

```python
# tests/experimental/agents/hooks/test_codex.py
"""Tests for the Codex hook installer."""

from __future__ import annotations

from libtmux.experimental.agents.hooks.codex import CodexHook


def test_install_writes_event_hooks(tmp_path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("model = \"o4\"\n")  # pre-existing unrelated config
    hook = CodexHook(config_path=config)

    assert hook.status() == "absent"
    hook.install()
    assert hook.status() == "installed"

    text = config.read_text()
    assert "user_prompt_submit" in text
    assert "libtmux-agent-emit running" in text
    assert "permission_request" in text
    assert "libtmux-agent-emit awaiting_input" in text
    assert "model = \"o4\"" in text  # untouched

    hook.uninstall()
    assert hook.status() == "absent"
    assert "model = \"o4\"" in config.read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/experimental/agents/hooks/test_codex.py -v`
Expected: FAIL — `CodexHook` is the stub.

- [ ] **Step 3: Write minimal implementation**

Implement `CodexHook`. Write our hooks between marker comments `# >>> libtmux-agent-state >>>` / `# <<< libtmux-agent-state <<<` so `status()`/`uninstall()` operate only on our block and preserve the rest of `config.toml` verbatim. Map: `{"user_prompt_submit": "running", "permission_request": "awaiting_input", "stop": "awaiting_input", "session_start": "idle"}`. Default `config_path` = `pathlib.Path.home() / ".codex" / "config.toml"`. Document the legacy `notify` fallback in the docstring (not implemented in v1; modern `[hooks]` is primary).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/experimental/agents/hooks/test_codex.py tests/experimental/agents/hooks/test_registry.py -v`
Expected: PASS (registry now sees a real CodexHook).

- [ ] **Step 5: Commit**

```bash
git add src/libtmux/experimental/agents/hooks/codex.py tests/experimental/agents/hooks/test_codex.py
git commit -m "Agents(feat[hooks]): Add Codex [hooks] installer (marker-bounded, non-clobbering)"
```

---

### Task 16: MCP surface — `register_agents` + `list_agents`/`watch_agents`/`install_agent_hooks`

**Files:**
- Create: `src/libtmux/experimental/mcp/vocabulary/agents.py`
- Modify: the MCP server builder to call `register_agents` (follow how `register_events` is wired — grep `register_events` in `mcp/fastmcp_adapter.py`/`mcp/registry.py`)
- Test: `tests/experimental/mcp/test_agents_tools.py`

**Interfaces:**
- Consumes: `AgentMonitor` (Task 11); `registry`/`get` (Task 13); the engine + the `register_events` wiring pattern.
- Produces: `register_agents(mcp, engine, *, sink=None) -> AgentMonitor` that starts a monitor and registers three tools: `list_agents()` (snapshot list), `watch_agents(timeout_s)` (transition stream), `install_agent_hooks(agent)` (calls `get(agent).install()` then returns `status()`).

- [ ] **Step 1: Write the failing test** (drive the monitor + the tool callables directly, no live MCP transport)

```python
# tests/experimental/mcp/test_agents_tools.py
"""Tests for the agents MCP tools (callables driven directly)."""

from __future__ import annotations

from libtmux.experimental.agents.monitor import AgentMonitor


class _FakeEngine:
    async def run(self, request): ...
    async def subscribe(self): ...
    def add_subscription(self, spec): ...
    def set_attach_targets(self, ids): ...


def test_list_agents_reflects_ingested_state() -> None:
    mon = AgentMonitor(_FakeEngine())
    mon.ingest("%subscription-changed agentstate $0 @0 1 %1 : running")
    listing = [
        {"pane_id": a.pane_id, "state": a.state.value} for a in mon.agents
    ]
    assert {"pane_id": "%1", "state": "running"} in listing
```

> The full `register_agents` wiring is integration-tested live in Task 17; this unit test pins the snapshot shape the `list_agents` tool returns.

- [ ] **Step 2: Run test to verify it fails / passes**

Run: `uv run pytest tests/experimental/mcp/test_agents_tools.py -v`
Expected: PASS once Task 11 exists (this asserts the data shape). Then implement `register_agents` and confirm it imports cleanly.

- [ ] **Step 3: Write minimal implementation**

Implement `vocabulary/agents.py::register_agents` mirroring `register_events`. The three tool callables read `monitor.agents` / iterate `engine.subscribe()` mapped through `monitor.ingest` for `watch_agents` / call the registry for installs. Wire `register_agents` into the async server builder next to `register_events`.

- [ ] **Step 4: Run the suite**

Run: `uv run pytest tests/experimental/mcp/ -v`
Expected: PASS, no regressions.

- [ ] **Step 5: Commit**

```bash
git add src/libtmux/experimental/mcp/vocabulary/agents.py src/libtmux/experimental/mcp/ tests/experimental/mcp/test_agents_tools.py
git commit -m "Mcp(feat[agents]): Add list_agents/watch_agents/install_agent_hooks tools"
```

---

### Task 17: Live integration — observe state against a real tmux

**Files:**
- Create: `tests/experimental/agents/test_live_monitor.py`

**Interfaces:**
- Consumes: `AgentMonitor`, `AsyncControlModeEngine`, the `server`/`session` fixtures.

- [ ] **Step 1: Write the live test**

```python
# tests/experimental/agents/test_live_monitor.py
"""Live: a real @agent_state write becomes observable through the monitor."""

from __future__ import annotations

import asyncio

from libtmux.experimental.agents.monitor import AgentMonitor
from libtmux.experimental.engines.async_control_mode import AsyncControlModeEngine


def test_monitor_observes_running(session) -> None:
    async def main() -> str:
        engine = AsyncControlModeEngine.for_server(session.server)
        monitor = AgentMonitor(engine)
        await monitor.start()
        pane_id = session.active_window.active_pane.pane_id
        # the agent hook's effect, simulated:
        session.cmd("set-option", "-p", "-t", pane_id, "@agent_state", "running")
        # tmux's subscription timer is ~1 s; poll up to 3 s
        for _ in range(30):
            await asyncio.sleep(0.1)
            match = {a.pane_id: a for a in monitor.agents}.get(pane_id)
            if match is not None and match.state.value == "running":
                break
        await monitor.stop()
        return match.state.value if match else "missing"

    assert asyncio.run(main()) == "running"
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/experimental/agents/test_live_monitor.py -v`
Expected: PASS (state observed within ~3 s). If flaky on the 1 s debounce, raise the poll budget — do not assert sub-second.

- [ ] **Step 3: Commit**

```bash
git add tests/experimental/agents/test_live_monitor.py
git commit -m "Agents(test): Live tmux test — @agent_state observed through the monitor"
```

---

### Task 18: Docs, CHANGES, Sphinx exclude, final gate

**Files:**
- Modify: `docs/conf.py` (exclude `superpowers/**` from the build) or `docs/justfile`
- Modify: `docs/experimental.md` (add an Agents section linking the new symbols)
- Modify: `CHANGES` (a `#### Agent-state monitor` deliverable under `### What's new`)

- [ ] **Step 1: Exclude the spec/plan from Sphinx**

Add to `docs/conf.py`: `exclude_patterns += ["superpowers/**"]` (create `exclude_patterns` if absent). Verify: `just build-docs` emits no "not in any toctree" warning for the spec/plan.

- [ ] **Step 2: Document the module**

Add an `## Agents` section to `docs/experimental.md` with a short prose intro and autodoc/cross-refs for `AgentMonitor`, `AgentState`, `Agent`, the MCP tools. Include one working doctest-style usage block already covered by Task 17.

- [ ] **Step 3: CHANGES entry**

Under the unreleased `### What's new`, add `#### Agent-state monitor` with 1–2 prose paragraphs (user vocabulary: "see which agent in which pane needs you"), linking `{class}` / `{meth}` roles.

- [ ] **Step 4: Run the full gate**

```bash
rm -rf docs/_build && uv run ruff format . && uv run ruff check . --fix && uv run mypy src tests && uv run pytest --reruns 0 -vvv && just build-docs
```

Expected: all green. Re-run `test_retry_three_times` / build-docs in isolation if either flakes (known-flaky), per project guidance.

- [ ] **Step 5: Commit**

```bash
git add docs/ CHANGES
git commit -m "Agents(docs): Document the agent-state monitor + CHANGES entry"
```

---

## Self-Review

**Spec coverage:** state model (T1–3), latest-wins/LWW (T2–3), two signals incl. fragmented OSC (T4), health/TTL probe (T5), derived tree + reconcile diff (T6), `refresh-client -B/-C` op (T7), death-sentinel false-`settled` fix (T8), supervisor reconnect/resubscribe (T9), sticky-attach reset (T10), monitor wiring (T11), shared emitter + `/dev/tty` (T12), hook protocol/registry (T13), Claude + Codex installers (T14–15), MCP tools incl. `install_agent_hooks` (T16), live test (T17), docs/CHANGES/Sphinx-exclude/gate (T18). The remote keepalive TTL sweep (D5) is represented by `is_alive` (T5) + the reconcile sweep (T11); the periodic timer firing is wired in T11's `reconcile()` and exercised live — acceptable for v1. The daemon/CLI hosts are out of v1 scope per the spec.

**Type consistency:** `Stamp(counter, writer)`, `latest(current, incoming)`, `Observed`/`Vanished`, `apply(store, event, *, now)`, `Reading(pane_id, state, name, source)`, `Agent(pane_id, key, name, state, since, source, pid, alive)`, `emit(state, *, name, runner, tty_path, env)` are used identically across tasks. The engine gains `add_subscription`/`set_attach_targets`/`_reset_attach`/`_generation`/`_closing` (T9–10) consumed by T11/T16.

**Placeholder scan:** the one `__import__("contextlib")` in Task 3 is flagged with an explicit replacement note; no `TBD`/`add error handling`/`similar to Task N` remain.
