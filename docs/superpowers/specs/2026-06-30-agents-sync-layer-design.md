# Design: `libtmux.experimental.agents` sync layer — wait, drive, transitions

- **Date:** 2026-06-30
- **Branch:** `engine-ops-supatui`
- **Status:** Approved to build (user: "continue all the way through")
- **Topic:** the agent *synchronization* layer over the existing `AgentMonitor` —
  block until an agent reaches a state, drive an agent safely, and surface the
  state-transition edge. The fan-out/fan-in verbs an orchestrator calls.
- **Builds on:** `2026-06-26-agents-agent-state-monitor-design.md` (the monitor,
  store, signals, reconcile loop). This spec adds verbs; it does not change the
  monitor's source-of-truth model.

---

## 1. Goal & motivation

The monitor knows *what every agent is doing*. This layer adds the verbs an
orchestrator uses to **act on** that knowledge:

- **`wait_for_agent_state`** — block until a pane's agent reaches a target state
  (`AWAITING_INPUT`, `IDLE`, `EXITED`, …), with a timeout. The fan-in primitive.
- **`wait_for_agents`** — the fleet variant: await many panes (all / any).
- **`send_to_agent`** — drive an agent: optionally wait until it is ready, then
  inject a prompt **atomically** so two concurrent drivers cannot corrupt each
  other's keystrokes.
- A per-pane **drive lock** making every keystroke-injection path on a pane
  mutually exclusive (the comprehensive chokepoint).
- Rails: an optional **idempotency key** on sends, a typed **`AgentTransition`**
  event, and **structured transition logging**.

This is the single most-reused capability across the surveyed orchestrators
(workmux `wait`, agent-deck "wake parent", herdr `wait agent-status`), and the
correctness primitives (drive lock, idempotency) are ones *none* of those four
ship because they each assume a single human operator — exactly the seam a
library that lets agents drive agents must own.

### 1.1 North star: fewest backend calls ("instant magic")

The defining performance property, by construction:

- **Waits cost ZERO tmux calls.** The `AgentMonitor` drain already ingests the
  control-mode stream into an in-process store. `wait_for_agent_state` does a
  **level check** against that store (instant return if already satisfied) and
  otherwise parks on an `asyncio.Future` woken by the *existing* drain — no
  `list-panes`, no poll, no new subscription. `wait_for_agents` over N panes is
  still zero calls. (Contrast: today's `watch_agents` blindly `sleep(timeout)`s.)
- **Every multi-step or fleet send folds to ONE dispatch.** `send_to_agent`
  builds an `OpChain` / `LazyPlan` and runs it through the **`FoldingPlanner`**,
  so a multi-line prompt (`set-buffer ; paste-buffer ; send-keys Enter`) and a
  fleet broadcast (N panes' `send-keys` in one `a ; b ; c`) each dispatch as a
  **single** `tmux` invocation. This is the chainable/lazy engine used to its
  fullest: the most work per backend call, at zero extra cost.

**Invariant:** a wait adds no tmux calls; a drive adds exactly one, regardless of
step- or fleet-count, whenever the constituent ops are chainable.

---

## 2. Scope

**In scope (v1):** `wait_for_agent_state`, `wait_for_agents`, `send_to_agent`,
`send_to_agents` (fleet, folded), the per-pane drive lock (comprehensive
chokepoint — also retrofitted onto the existing `asend_input`), the idempotency
key, the `AgentTransition` value + observer hook, and structured transition
logging.

**Deferred (own specs / milestones), named so v1 stays a tight slice:**
- A4 `agents()` query + attention `rollup()` (query tier).
- A5 `freeze()` live-server → `Workspace` IR (declarative tier).
- `AgentState.DONE` (turn-complete-unseen) and failure substates.
- Composer-draft guard (presumes a human sharing the pane; speculative pane
  mutation — opt-in at most, deferred).
- Wait-graph **deadlock guard**, **ownership/sibling-clobber authz**, and
  **send-side pacing** — insurance rails, deferred (the monitor cut its
  distributed-systems garnish the same way).

---

## 3. Architecture (Approach 3: thin pure units, monitor-hosted)

New units are small, pure, and unit-testable by feeding **synthetic** `Agent`
records — the same sans-I/O testing style as `store.py`'s reducer and
`signals.py`'s parsers. The `AgentMonitor` stays the single writer; nothing here
adds a second mutation path into the store.

### 3.1 Module layout

| File | Responsibility |
|---|---|
| `agents/wait.py` *(new)* | `WaitReason` enum, `AgentWait` result, `WaiterRegistry` (pure: `register(pred) -> Future`; `notify(agent)` resolves matches; `fail_all(reason)` on teardown), and the `wait_for_agent_state` / `wait_for_agents` async fns. |
| `agents/drive.py` *(new)* | `pane_lock(pane_id) -> asyncio.Lock` (module-level `WeakValueDictionary` chokepoint registry), `DedupLedger` (`(pane,key) -> SendOutcome` within a monotonic TTL), `SendOutcome`, and the `send_to_agent` / `send_to_agents` async fns. |
| `agents/state.py` *(touch)* | Add the pure `AgentTransition(pane_id, before, after, agent)` value next to `Agent`. |
| `agents/monitor.py` *(touch)* | `_observe` diffs `before -> after`; on change it (1) emits a structured `logger.info`, (2) calls `WaiterRegistry.notify`, (3) fans the `AgentTransition` to registered observers. The monitor **hosts** a `WaiterRegistry`; `start()`/`stop()` wire `fail_all` on teardown so no waiter hangs across a monitor stop. |
| `mcp/vocabulary/pane.py` *(touch)* | `asend_input` acquires `pane_lock` — the chokepoint retrofit (all async keystroke injection serializes per pane). |
| `mcp/vocabulary/agents.py` *(touch)* | Register `wait_for_agent` + `send_to_agent` MCP tools; wire into the adapter `_TOOLS`. |

### 3.2 Types & signatures

```python
# agents/wait.py
class WaitReason(str, enum.Enum):
    REACHED = "reached"     # the target state was observed
    TIMEOUT = "timeout"     # deadline elapsed first
    EXITED = "exited"       # agent reached EXITED and EXITED was not the target
    STOPPED = "stopped"     # the monitor stopped while the wait was parked

# Note: the store has no distinct "vanished" state -- apply(Vanished) collapses a
# disappeared pane to AgentState.EXITED -- so a pane that dies before reaching the
# target resolves as EXITED (not a separate VANISHED reason).

@dataclasses.dataclass(frozen=True)
class AgentWait:
    pane_id: str
    reason: WaitReason
    agent: Agent | None          # last-known record (None if never observed)
    @property
    def reached(self) -> bool: return self.reason is WaitReason.REACHED

async def wait_for_agent_state(
    monitor, pane_id: str,
    target: AgentState | Collection[AgentState],
    *, timeout: float | None = None,
) -> AgentWait: ...

async def wait_for_agents(
    monitor, pane_ids: Collection[str],
    target: AgentState | Collection[AgentState],
    *, mode: t.Literal["all", "any"] = "all", timeout: float | None = None,
) -> list[AgentWait]: ...   # one per pane, in input order
```

```python
# agents/drive.py
@dataclasses.dataclass(frozen=True)
class SendOutcome:
    pane_id: str
    sent: bool                   # False if a readiness wait failed, or dedup no-op
    wait: AgentWait | None       # the readiness wait, when wait_ready=True
    deduplicated: bool = False   # True when an idempotency key short-circuited

async def send_to_agent(
    monitor, pane_id: str, text: str, *,
    wait_ready: bool = True,
    ready_states: Collection[AgentState] = (AgentState.AWAITING_INPUT, AgentState.IDLE),
    enter: bool = True,
    key: str | None = None,            # idempotency key
    timeout: float | None = None,
) -> SendOutcome: ...

async def send_to_agents(
    monitor, pane_ids: Collection[str], text: str, *, ...
) -> list[SendOutcome]: ...   # ready sends fold into ONE dispatch
```

### 3.3 Wake-up mechanics (the level/edge seam)

`wait_for_agent_state` closes the classic edge-vs-level gap by checking level
**before** awaiting the edge:

1. **Level check.** Read `monitor`'s current `Agent` for `pane_id`. If it already
   satisfies `target`, return `AgentWait(REACHED)` immediately — zero tmux calls,
   zero awaits.
2. **Register.** Otherwise register a predicate with the `WaiterRegistry`,
   receive a `Future`, and `await asyncio.wait_for(fut, timeout)`.
3. **Wake.** The monitor's `_observe`, after `apply()` changes a pane, calls
   `registry.notify(agent)`; the registry resolves every waiter whose predicate
   the new record satisfies (→ `REACHED`). A record that reached `EXITED` while a
   non-exit target was awaited resolves that waiter with `EXITED` (terminal:
   the agent is gone, the target is unreachable).
4. **Timeout / teardown.** `asyncio.TimeoutError` is caught → `AgentWait(TIMEOUT)`
   and the waiter is deregistered in `finally` (no leak; a real `CancelledError`
   still propagates). `monitor.stop()` calls `registry.fail_all()`, resolving
   parked waits as `STOPPED` so they return rather than hang.

Registration is synchronous and the registry is pure, so the level check + the
notify path are unit-testable with no event loop and no tmux.

### 3.4 `send_to_agent` (folded, locked, idempotent)

1. If `wait_ready`: `w = await wait_for_agent_state(monitor, pane_id, ready_states,
   timeout)`; if `not w.reached` → `SendOutcome(sent=False, wait=w)` (no dispatch).
2. `async with pane_lock(pane_id):` — the whole logical send is atomic.
3. If `key` and `DedupLedger` has a live `(pane_id, key)` → return the prior
   `SendOutcome` with `deduplicated=True` (no dispatch). This makes the obvious
   "retry after a timeout" caller-reaction a safe no-op.
4. Build the send and fold it to one dispatch via `LazyPlan` + `FoldingPlanner`:
   - single-line text → `SendKeys(keys=text, enter=enter)` (1 op, 1 dispatch);
   - multi-line text → `SetBuffer(data=text) >> PasteBuffer(target, delete=True)
     >> SendKeys(target, enter)` — all chainable, folds to one
     `set-buffer ; paste-buffer ; send-keys Enter` invocation.
5. Record in the `DedupLedger`; return `SendOutcome(sent=True, wait=...)`.

`send_to_agents` acquires per-pane locks in **sorted pane-id order** (avoids
lock-ordering deadlock between two concurrent fleet sends), folds every ready
pane's send into one chain, dispatches once, releases.

### 3.5 The drive lock chokepoint

`pane_lock(pane_id)` returns a process-wide `asyncio.Lock` from a
`WeakValueDictionary` (collected when no sender holds it). It guards the **async**
drive path — the real concurrency risk in the MCP async server, where many
coroutines share one event loop. Both `send_to_agent`/`send_to_agents` and the
retrofitted `asend_input` acquire it, so all async keystroke injection on a pane
serializes through one place. The engine's existing byte-level `_write_lock` is
untouched (it correctly guards pipe writes); this logical lock sits one layer up.

### 3.6 Transition event + structured logging (rails)

In `_observe`, when `apply()` changes a pane's state:
- `logger.info("agent state changed", extra={"tmux_pane": pane_id,
  "agent_state_before": before.value, "agent_state_after": after.value,
  "agent_name": name, "agent_source": source})` — reuses the existing
  `tmux_pane` core key and introduces the documented `agent_*` key family
  (the monitor today logs only an unstructured `DEBUG`).
- `monitor` fans an `AgentTransition` to observers registered via
  `monitor.add_transition_observer(cb)`. (An MCP `watch_agent_transitions` push
  tool is a thin follow-up; v1 ships the Python observer + the log.)

---

## 4. Error handling & semantics

- **Outcome-as-data** everywhere: `wait_*` never raise on timeout/vanish; they
  return `AgentWait` with a typed `WaitReason`. Mirrors the settle monitor's
  `MonitorResult`/`SettleReason`. (Engine-broken errors from a dispatched send
  still surface as data on the `SendOutcome`'s underlying results, per the
  engine's existing contract.)
- **Cancellation-safe:** a cancelled `wait_for_agent_state` deregisters its
  waiter in `finally`; `pane_lock` is released by `async with`.
- **Async-only:** these verbs suspend on the event loop (like `wait_for_output` /
  `watch_events`), so they have **no sync twin** — consistent with the streaming
  MCP tools.

---

## 5. MCP surface

On the async server (beside `list_agents`/`watch_agents`):
- **`wait_for_agent(pane_id, target, timeout_s=30)`** → `AgentWait` as a dict.
- **`send_to_agent(pane_id, text, wait_ready=True, timeout_s=30, key=None)`** →
  `SendOutcome` as a dict; tagged `mutating`.
- **Retrofit** `asend_input` to acquire `pane_lock` (no signature change).

---

## 6. Testing strategy

Per repo conventions (functional tests, existing fixtures, **no pytest-asyncio** —
async tests are `def test_…(): asyncio.run(...)`):

- **Unit (no tmux):** `WaiterRegistry` register/notify/predicate/`fail_all`;
  `AgentWait.reached`; level-check immediate return; timeout → `TIMEOUT`;
  `Vanished` → `VANISHED`. `DriveLock` mutual exclusion (two coroutines, assert
  serialized). `DedupLedger` TTL dedup. `send_to_agent` **folding** — drive a
  recording engine and assert a multi-line send is **one** dispatch; assert a
  not-ready pane yields `sent=False` with no dispatch; assert a dedup key
  short-circuits. Feed `monitor.ingest(...)` synthetic notifications and assert
  `wait_for_agent_state` resolves.
- **Live (real tmux, `session` fixture, `asyncio.run`):** `set-option @agent_state`
  then assert `wait_for_agent_state` resolves `REACHED` within ~1.5 s;
  `send_to_agent` into a shell pane and assert the text lands (capture).
- **Doctests** on every public symbol (`WaitReason`, `AgentWait`, `SendOutcome`,
  the verbs) via `doctest_namespace`.
- **Gate** (before commit): `rm -rf docs/_build` → `ruff check . --fix` →
  `ruff format .` → `mypy` → `pytest --reruns 0 -vvv` → `just build-docs`.

---

## 7. Acceptance criteria (v1)

1. `wait_for_agent_state` returns `REACHED` the moment a tracked agent reaches the
   target, and `TIMEOUT`/`VANISHED` as data otherwise — adding **zero** tmux calls.
2. `send_to_agent` waits for readiness, then injects a multi-line prompt in a
   **single** folded `tmux` dispatch; two concurrent sends to one pane serialize
   (no interleave); a repeated idempotency key is a no-op.
3. `asend_input` shares the same per-pane lock (chokepoint proven by a
   concurrency test).
4. Every monitor state change emits a structured `agent_*` log record and an
   `AgentTransition` to observers.
5. The full gate passes: lint, types, unit + live tests, doctests, docs build.
