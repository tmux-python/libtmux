# Design: `libtmux.experimental.agents` — a tmux-native agent-state monitor

- **Date:** 2026-06-26
- **Branch:** `engine-ops`
- **Status:** Approved for spec review → planning
- **Topic:** the orchestration spine of a "tmux-powered supacode clone", reframed as a headless, resilient, agent-state monitor over libtmux's experimental stack.

---

## 1. Goal

Build a headless module that knows, for every pane running a coding agent, **what that agent is doing** — `RUNNING` / `AWAITING_INPUT` / `IDLE` / `EXITED` / `UNKNOWN` — signaled *cooperatively* by the agent's own lifecycle hooks, observed over a single attached control-mode connection, reconciled against tmux as the authority, and exposed through the existing FastMCP server.

This is the one capability that turns `tmux list-panes` into a supacode-style command center: *which of my parallel agents needs me right now?* Everything supacode adds on top (the macOS GUI, Ghostty embedding, the SwiftUI sidebar) is out of scope and unwanted; the orchestration spine it is built around is mostly already present on this branch (`engines`, `ops`, `workspace`, `mcp`).

**v1 is a vertical slice:** the agent-state model + the two signaling sources + the *minimal* slice of connection-resilience the model cannot function without. The distributed-systems garnish is explicitly cut (see §12).

---

## 2. Validated facts (live probe, tmux 3.6a)

The design rests on observed behavior, not assumption. A throwaway-socket probe established:

| Path | Result |
|---|---|
| **Local:** agent runs `tmux set-option -p @agent_state running`; an attached control client with `refresh-client -B 'agentstate:%*:#{@agent_state}'` receives `%subscription-changed agentstate $0 @0 1 %0 : running` | ✅ works; carries session/window/pane + value |
| **Local latency** | ~1 s (tmux's debounced subscription timer) |
| **Local reliability** | option is always re-queryable via `show-options -p -v` → a lost notification self-heals on reconcile |
| **Remote:** a bare `OSC 3008 ;state=running ST` printed in a pane appears verbatim in control-mode `%output` (even with `allow-passthrough off`) | ✅ works |
| **`%output` framing** | delivered **byte-fragmented** (often one byte per `%output` line) → the OSC parser must buffer per-pane and scan for boundaries |
| **Attach requirement** | the control client must `attach-session` to receive `%output` *and* subscriptions (the "attach gap") |

Two complementary failure modes justify supporting **both** sources: the **option** path is slow (~1 s) but lossless/re-queryable (state lives in tmux); the **OSC** path is instant but rides the lossy `%output` stream and is the only path that survives SSH (a remote `tmux set-option` can't reach the local socket).

---

## 3. Core principle: source of truth is split by kind

The central design invariant; conflating the two halves is the mistake that sinks designs like this.

- **Observed state** — the session/window/pane tree, layout, activity. **tmux is authoritative.** The monitor is a **projection/controller** (a tmux-backed read-model), never a competing store. Hydrate once via `list-panes -a -F` → `ServerSnapshot.from_pane_rows` (already in `models/snapshots.py`); keep it live by applying structural `%`-notifications. Never poll-on-loop; never treat this derived tree (`tree.py`) as truth.
- **Intent / run-state** — agent identity, agent state, and (later) the project↔worktree↔pane-role mapping. **The monitor is authoritative.** tmux holds none of this and has zero disk persistence (server death = total amnesia). This tier lives in the monitor's own (optional in v1) durable store and is reconstructable against a freshly-restarted empty server.

**Litmus:** if tmux can report it, *derive* it; if it encodes what an agent/project *means* by a pane, *persist* it.

**Reconciliation is one-directional and event-sourced:**

```
live tmux ──▶ engine.subscribe() ──▶ classify ──▶ pure apply(state, event) ──▶ durable store ──▶ derived tree ──▶ hosts
```

Watchers *emit*; only `apply()` mutates the store (load-bearing invariant). **Deltas** drive the fast path; a **full `list-*` snapshot diff** is the correctness backstop, run on connect / on drop / on a slow timer — because tmux's change feed has blind spots (pane-died/pane-exited, window-resized, pane-title-changed emit *no* notification; `refresh-client -B` is a ~1 Hz edge-triggered sample that misses `A→B→A`). This is the Hadoop pattern: notifications = heartbeat/edit-log (optimistic), `list-*` reconcile = block-report (authoritative).

---

## 4. Locked decisions

| # | Decision |
|---|---|
| **Naming** | `agents` / `AgentState`. Avoids tmux's `status`/`activity`/`monitor`/`state` vocabulary collisions; matches OpenHands `AgentState` (`RUNNING`/`AWAITING_USER_INPUT`). |
| **D1 — multi-host horizon** | *Insure now, single-host in v1.* Agent state is a per-pane latest-wins entry whose deltas are transport-shaped (`counter, writer, value`); the clock is a pluggable callable (monotonic counter now, HLC later); skew is bounded (reject samples older than a budget) so a future multi-host pivot is a clock+transport swap, not a rewrite. **No multi-host code ships in v1.** |
| **D2 — resilience scope** | Build the supervisor reconnect loop + death-sentinel + sticky-attach fix + idempotent reducer + reconcile. Cut the garnish (no cross-restart epoch/seq replay, no `refresh-client -A` pause/hysteresis, no origin-tag guard). |
| **D3 — agent-state data model** | One latest-wins map keyed by pane business-key; `writer = source` (`option`/`osc`, later `host:source`); the reducer applies the `(counter, writer)` `latest()` guard **before** writing the coalescing latest-value slot (resolves the arrival-order contradiction). |
| **D4 — persistence / runtime** | Runtime-agnostic core; **embedded-in-MCP** is the only v1 host. Durable store is a single atomic JSON checkpoint (temp+rename+fsync), scoped per `(socket, server-instance)`, under an XDG state dir — **optional in v1** (see §6). A best-effort **per-socket advisory lease** guards the two-clients-on-one-socket case. Daemon + one-shot CLI are deferred thin hosts. |
| **D5 — remote health / TTL** | Local panes expire via `os.kill(pid, 0)`. PID-less remote panes can't be swept, so the remote hook wrapper emits a periodic **keepalive** (re-emits the current `state` at a configurable interval); a remote pane is marked **stale** (not auto-`EXITED`) only after a TTL ≈ 2× that interval with no signal. Absent a keepalive, remote health is best-effort last-seen and a busy remote agent is **never** auto-expired (no false `EXITED`). |

---

## 5. Module layout

New package `src/libtmux/experimental/agents/`, depending only on the `AsyncTmuxEngine` protocol (`engines/base.py`) + a `Storage` sink + a `subscribe()` source:

| Module | Responsibility |
|---|---|
| `state.py` | `AgentState` enum + the immutable `Agent` record (with `is_awaiting`/`is_running` helpers). Pure values. |
| `merge.py` | The "latest update wins" rule: a `Stamp(counter, writer)` ordering tag + `latest(current, incoming) -> bool`. Pluggable clock (counter now → HLC later). Makes state convergent, idempotent, out-of-order/duplicate-tolerant. |
| `store.py` | Durable value tier: frozen `AgentStore` + the pure `apply(state, event) -> state` reducer + `Storage` protocol + `JsonFile` (atomic write). `to_dict`/`from_dict` mirror `models/snapshots.py`. |
| `tree.py` | The live session→window→pane tree, derived from `ServerSnapshot.from_pane_rows`; targeted per-pane invalidation, full rebuild only on structural events / reconcile. |
| `signals.py` | `AgentSignal` protocol + `OptionSignal` (local, via `@agent_state`) + `OscSignal` (remote, via OSC 3008) — the two channels agents use to report state, both consuming `engine.subscribe()`. |
| `health.py` | Is the pane's process still alive: `is_alive(pid)` via `#{pane_pid}` + `os.kill(pid, 0)`, sweeping dead local panes; remote PID-less panes use the keepalive TTL. Never infers death from a missing notification. |
| `monitor.py` | `AgentMonitor` core: the supervisor loop, reducer pipeline, coalescing slots, the `start/stop/status/reconcile` contract, `agents` snapshot + async `watch()`. |
| `hooks/emit.py` | The shared emitter: `emit(state, name=None)` → local `tmux set-option -p -t $TMUX_PANE @agent_state <state>` when `$TMUX` is reachable, else remote OSC 3008 written to **`/dev/tty`** (the pane pty — survives SSH). Exposed as a console entry point. |
| `hooks/base.py` | `AgentHook` protocol (`name`, `detect()`, `install()`, `uninstall()`, `status()`) + the canonical event→`AgentState` map type. |
| `hooks/claude.py` | `ClaudeCodeHook`: transactional installer into Claude Code settings (`~/.claude/settings.json`). |
| `hooks/codex.py` | `CodexHook`: transactional installer into Codex `[hooks]` command hooks (`~/.codex/config.toml`), with the legacy `notify` program as a fallback for older Codex. |
| `hooks/registry.py` | The agent-hook registry (`ClaudeCodeHook`, `CodexHook`) used by the installer + the `install_agent_hooks` MCP tool. |

Plus surgical changes outside the package:

- `ops/_ops/refresh_client.py` — add typed `-B <subscription>` and `-C <size>` support (today `RefreshClient.args()` returns empty; `-B` is only a raw `CommandRequest` in `events.py`).
- `engines/async_control_mode.py` — the supervisor loop, death-sentinel broadcast, sticky-attach reset, `TaskGroup` peer supervision (§7).
- `mcp/vocabulary/agents.py` — `list_agents` / `watch_agents` tools + `register_agents(mcp, engine, sink)`.

---

## 6. State model

```python
class AgentState(str, enum.Enum):
    RUNNING = "running"               # working
    AWAITING_INPUT = "awaiting_input" # paused, needs the human/orchestrator
    IDLE = "idle"                     # alive, no active task
    EXITED = "exited"                 # process gone (health sweep)
    UNKNOWN = "unknown"               # no signal observed yet

@dataclasses.dataclass(frozen=True)
class Agent:
    pane_id: str            # live %N within a connection
    key: str                # durable business key; pane_id in v1
    name: str | None        # agent identity (OSC 3008 name= / config); None until announced
    state: AgentState
    since: float            # monotonic stamp of the last transition
    source: str             # "option" | "osc"
    pid: int | None         # pane_pid; None for remote/ssh
    alive: bool

    @property
    def is_awaiting(self) -> bool: return self.state is AgentState.AWAITING_INPUT
    @property
    def is_running(self) -> bool: return self.state is AgentState.RUNNING
```

**Latest-wins merge** (`merge.py`) — when two updates for the same pane race (out of order, replayed, or from both channels), keep the newer one:

```python
Clock = t.Callable[[], int]   # monotonic counter now; HLC later

@dataclasses.dataclass(frozen=True, order=True)
class Stamp:
    counter: int              # logical clock; higher = newer
    writer: str               # tie-break when counters equal: "option"/"osc" (v1), "host:source" (multi-host)

def latest(current: Stamp | None, incoming: Stamp) -> bool:
    """True if *incoming* should replace *current* (it is strictly newer)."""
    return current is None or incoming > current
```

The store keeps `pane_key -> (Stamp, AgentState)` and calls `latest()` **before** overwriting the coalescing slot — so a stale replayed update can never clobber a fresher one.

**Durable vs derived (v1 is deliberately thin).** Because agents re-announce on every state change and tmux is the tree authority, **v1 needs no load-bearing durable state**: on restart the monitor rebuilds the tree from `list-*` and refills agent state from the next heartbeat. The `store.py`/`JsonFile` machinery is built (it becomes load-bearing for the milestone-3 worktree manager's intent mapping) but in v1 the checkpoint is an **optional seed** for instant restart UX. This further de-risks v1: correctness does not depend on persistence.

---

## 7. Resilience: the supervisor

The existing stack is **fail-fast, not self-healing** (verified): the reader calls `_mark_dead` and stops forever; death is invisible to `subscribe()` consumers (they hang); `_attached_session` is sticky so a reconnect silently emits no `%output`; `-B` subscriptions vanish on reconnect and are never replayed; backpressure is silent drop-oldest; a dead stream is mis-reported by `wait_for_output` as `settled` (a false *DONE*). v1 closes the slice the monitor needs.

**`_supervisor()` loop** (single owner of engine health, gated on a `_closing` flag):

1. **connect** — spawn `tmux -C`.
2. **reset** — fresh `ControlModeParser` + fail pending command futures (the only place permitted to break the `_pending`↔bytes lockstep).
3. **re-attach** — clear the sticky `_attached_session`, re-attach declared sessions (the one-time redraw re-seeds the tree).
4. **resubscribe** — replay the stored `refresh-client -B` specs (server-side-per-client; gone with the connection).
5. **full reconcile** — `list-sessions`/`list-windows -a`/`list-panes -a` → `ServerSnapshot.from_pane_rows` → diff vs the tree → emit synthetic add/remove/rename for whatever the stream missed; bump the **generation** counter.
6. **read** the notification stream.
7. on a non-`CancelledError`, non-`_closing` return/crash → jittered exponential backoff → goto 1.

**Death sentinel.** On death/reconnect, broadcast a generation/death sentinel to every subscriber queue **and close the generators** — so `accumulate_until_settle` returns `stream_end` (not a false `settled`), `subscribe()` consumers end instead of hanging, and the pull ring re-syncs.

**Backpressure (replaces drop-oldest).** Split by data shape: **agent-state / topology** → a coalescing latest-value slot per entity (`dict[pane_key -> (Stamp, AgentState)]`; the reducer overwrites *after* the `latest()` guard — only the newest state matters, so this is correct, not lossy; the reconcile snapshot is the authoritative refill). **Ordered `%output`** → the existing byte/time caps (`max_bytes`, settle timeout). *No* `refresh-client -A` pause/hysteresis in v1 (deferred until a demonstrated sustained-flood pane).

**Structured concurrency.** Lift the long-lived peers (supervisor, MCP server, ring drainer) into an `asyncio.TaskGroup` (abort-siblings + aggregate); absorb transient connection death *below* the group in the supervisor; keep per-client consumers isolated so one client's failure can't abort the shared engine. Generalize the existing cancellation-safe teardown; close every subscriber generator via `contextlib.aclosing`.

**Health (process aliveness, `health.py`).** `#{pane_dead}`/`#{pane_pid}` + a periodic `os.kill(pid, 0)` sweep that **preserves PID-less remote records** (marked *stale* on the D5 keepalive TTL, never auto-`EXITED`); never infer death from a missing notification.

**Lease.** A best-effort per-`(socket)` advisory lock (`flock` on a state-dir file) acquired by the monitor; a second monitor on the same socket runs read-only or declines to attach/drive — guarding double-attach and double-drive. Convergence of the *observed tree* across monitors is free (each reconciles independently); the lease protects *intent*-tier actions.

**Self-heal scorecard (honest):**

| Failure | Recovers? | Note |
|---|---|---|
| Connection EOF mid-stream | ✅ | supervisor reconnect + reconcile; `%output` bytes lost in the dead window are gone (tree restored, not capture) |
| Lost notification under load | ⚠️ within reconcile cadence | catches *final* state, not the missed *transition* (fine for latest-wins agent state) |
| tmux server restart | ⚠️ | tree re-derived from `list-*`; agents re-announce; no scrollback restore (tmux limitation) |
| Daemon crash + restart | ⚠️ | atomic checkpoint + reconcile (v1: no durable state to corrupt) |
| Dead connection mis-read as DONE | ✅ | sentinel closes generators → `stream_end` |
| Two monitors on one socket | ⚠️ | lease → one read-only; without lease, double-attach (operational, not state-corruption in v1) |
| Pane dies w/o emitting idle | ⚠️ cadence | no notification exists; caught by pid sweep |
| SSH agent disconnect | ⚠️ | PID-less → D5 TTL declares it stale |

---

## 8. The two agent-state sources

Both consume `engine.subscribe()`; both write into the **same** per-pane latest-wins key with `writer = source`.

**`OptionSignal` (local).** On (re)attach, install `refresh-client -B 'agentstate:%*:#{@agent_state}'` (and `…#{@agent_name}` for identity). Parse `%subscription-changed agentstate $S @W idx %P : VALUE` → `AgentState`. Reconcile via `show-options -p -v -t %P @agent_state`. Spec stored as desired-state and replayed on reconnect.

**`OscSignal` (remote).** A per-pane byte accumulator scans `%output %P <bytes>` for `OSC 3008 … ST` (the probe proved `%output` is byte-fragmented, so boundary-scanning across frames is mandatory). Payload grammar: `state=<value>` and `name=<b64>`; an optional `kind=notify;title=<b64>;body=<b64>` shape is parsed but routing is deferred (no headless notification sink in v1 — milestone 2).

**Attribution** derives from *which pane tmux says emitted the signal*, never from an id embedded in agent text. Tie-break/precedence between the two signals is the `(counter, writer)` compare; both carry the agent's emit-time clock so a replayed stale OSC loses to a fresher option write.

**Hook emitters (Claude Code + Codex, v1).** A single shared emitter (`hooks/emit.py`, exposed as a console entry point) does the transport choice; each agent's hooks just call it with a state:

```bash
# local: tmux reachable
tmux set-option -p -t "$TMUX_PANE" @agent_state running
# remote (SSH): write the OSC to the pane pty, NOT stdout (hooks pipe/null stdout)
printf '\033]3008;state=running\033\\' > /dev/tty
```

The remote→`/dev/tty` detail is load-bearing: both Claude Code and Codex capture hook stdout, so an OSC on stdout never reaches the terminal; the controlling tty *is* the pane's pty, so `/dev/tty` reaches tmux (and travels over SSH).

Per-agent installers map lifecycle events → `AgentState` and write the emitter invocation transactionally (detect / install / outdated / rollback):

| Event | `ClaudeCodeHook` (`~/.claude/settings.json`) | `CodexHook` (`~/.codex/config.toml` `[hooks]`) | → state |
|---|---|---|---|
| turn starts | `UserPromptSubmit` | `user_prompt_submit` | `running` |
| needs approval | `Notification` | `permission_request` | `awaiting_input` |
| turn ends | `Stop` | `stop` | `awaiting_input` |
| session begins | `SessionStart` | `session_start` | `idle` |

Both agents deliver the event as JSON on the hook command's stdin (verified in Codex `engine/command_runner.rs`), but because each event registers a *separate* hook, the command can hard-code its state and need not parse stdin. Codex's older single-program `notify` (turn-complete only → `awaiting_input`) is the `CodexHook` fallback. Remaining agents (Copilot/Kiro/OpenCode/Pi) are added as more `hooks/registry.py` entries in milestone 2.

---

## 9. Runtime & MCP surface

**Core contract** (every host calls identically): `start()` / `stop()` / `status()` / `reconcile()` (+ async siblings). The core owns no `asyncio.run`, argparse, fastmcp, signals, or pidfiles.

**Embedded-in-MCP (PRIMARY, v1).** `register_agents(mcp, engine, sink)` registers alongside `register_events`, reusing the already-persistent `AsyncControlModeEngine`, its single `subscribe()` stream, the `_lifespan` startup preflight as a fail-fast gate, and the existing attach path. Three MCP tools:

- **`list_agents()`** → snapshot: `[{pane_id, name, state, since, alive, source}]`, read from the coalescing slot (no tmux round-trip). Sortable "awaiting-input first" by the caller.
- **`watch_agents(timeout_s)`** → a stream of `AgentStateChanged` transitions (semantic counterpart to `watch_events`), terminating cleanly on `stream_end`.
- **`install_agent_hooks(agent)`** → run a `hooks/registry.py` installer (`claude` | `codex`) for the calling user; reports `installed` / `outdated` / `absent` per `AgentHook.status()`.

**Daemon** (deferred) and **one-shot CLI** (deferred, `reconcile→print→exit` like `workspace load`) are thin hosts enabled by the same contract.

---

## 10. Testing strategy

Per repo conventions (functional tests, existing fixtures, no `pytest-asyncio`):

- **Unit (no tmux):** feed raw `%subscription-changed` lines into `OptionSignal`; feed byte-fragmented OSC streams into `OscSignal`; feed events into `apply()`; property-test `merge.latest` ordering (idempotent/out-of-order/duplicate-tolerant); test `JsonFile` atomicity (temp+rename+fsync, crash-mid-write leaves the old file intact); `ClaudeCodeHook`/`CodexHook` install→status→uninstall round-trips against a `tmp_path` fake config dir (idempotent, rollback on failure, no clobber of unrelated user hooks).
- **Live (real tmux, `session` fixture):** `def test_agent_monitor_observes_running(session)` wrapping an `async def main()` driven by `asyncio.run` — set `@agent_state`, assert the monitor reports `RUNNING` within ~1.5 s (covers the 1 s debounce). A second live test kills+restarts the control connection and asserts reconnect+reconcile restores the tree.
- **Doctests** on every public symbol (`AgentState`, `Agent`, `AgentMonitor`, `latest`) using the `doctest_namespace` fixtures.
- **Gate** (per the user's pre-commit sequence): `rm -rf docs/_build` → `ruff check --fix` → `ruff format` → `mypy src tests` → `pytest --reruns 0 -vvv` → `just build-docs`.

---

## 11. Build methodology

Per the user's plan: **prototype the slice here → `git stash` the rough pass → rebuild clean** with the structure above now that the shape is known → run the full gate to confirm. The slice is deliberately small enough to build twice.

---

## 12. Out of scope (v1) / future milestones

- **Cut garnish:** cross-restart epoch/seq replay (the pull ring is in-memory), `refresh-client -A` pause/continue flow control, origin-tag self-write filtering (rely on idempotent `apply()` + reconcile).
- **Milestone 2:** more agents in the hook registry (Copilot/Kiro/OpenCode/Pi — Claude Code + Codex ship in v1); OSC notification routing/sink; `OscSignal` hardening.
- **Milestone 3:** the full repo/worktree manager (sibling git module shelling to `git worktree`) that spins a worktree-per-agent via the `workspace` builder and feeds panes into the monitor — at which point the durable intent mapping becomes load-bearing.
- **Later:** multi-host agent-state aggregation (deltas already transport-shaped; swap clock→HLC + bound skew); standalone daemon + one-shot CLI hosts; macOS/GUI surfaces (never — delegated to the human's terminal or a future TUI).

---

## 13. Acceptance criteria for v1

1. A Claude Code **and** a Codex agent in a local tmux pane, with the installed hook, each drive `AgentState` transitions observable through `list_agents`/`watch_agents` within ~1.5 s.
2. An agent over SSH drives the same transitions via the OSC signal written to `/dev/tty`.
3. Killing the control connection (or the tmux server) does **not** freeze the monitor: it reconnects, re-attaches, resubscribes, reconciles, and never reports a dead stream as a false `settled`.
4. Two MCP clients on one socket do not double-attach/double-drive (lease).
5. The full gate passes: lint, types, all tests (unit + live), doctests, docs build.
