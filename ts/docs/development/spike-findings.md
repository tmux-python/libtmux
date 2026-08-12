# libtmux TypeScript spike findings

Date: 2026-08-09.

Purpose: record the source-informed disposable prototypes and adversarial
bakeoffs that select the implementation architecture. Prototype files are not
shipped verbatim. Implementation provenance follows the cited libtmux MIT and
tmux ISC sources; this document makes no clean-room claim.

## Baseline

- Python source baseline: tag `v0.62.0`, resolved to commit `38e368c`.
- Local runtimes: tmux 3.7b, Bun 1.3.14, and Node 24.8.0. The required Node 22
  floor remains a final implementation gate rather than a result of these
  local probes.
- Supported tmux floor: 3.2a.
- Current registry checks: TypeScript 7.0.2, Zod 4.4.3, Oxlint 1.77.0,
  Oxfmt 0.62.0, and `oxlint-tsgolint` 7.0.2001.
- The npm registry returned no published package named `libtmux`. Publication
  must recheck ownership because registry state can change.
- The checkout was clean before and after all inline probes.

The Python regression baseline produced 1,454 passes, one skip, and one failure.
The failure was `test_new_session_shell_env`: the inherited process environment
made the generated `new-session -e` command exceed tmux's client-message bound.
No source change caused it. The TypeScript design therefore sends large payloads
through stdin only when a tmux command natively accepts it. Argument-only data,
including `new-session -e`, still needs a command-specific bound or strategy.
The final regression gate must run Python in a controlled process environment
without setting `HOME`.

## Process transport

### Question

Should runtime execution use Bun-native process APIs or Node-compatible process
APIs?

### Probe

The same literal tmux argument vector ran through `Bun.spawn` and
`node:child_process.spawn`. The Node implementation then ran unchanged under
Bun and Node. A blocking `tmux wait-for` child was cancelled through an
`AbortSignal` under both runtimes.

### Result

Both runtimes returned equivalent output. Both cancellation paths reported an
`AbortError` with `ABORT_ERR`; neither required a shell.

A follow-up lifecycle probe covered an already-aborted signal, abort during a
blocked multi-megabyte stdin write, a SIGTERM-ignoring child, and an abort/exit
race. Node and Bun both avoided spawning for the pre-aborted case, escalated the
ignoring child to SIGKILL, awaited `close`, and drained both streams. The race
settled once with an indeterminate delivery and a terminating signal.

### Decision

Use `node:child_process.spawn` in published runtime code with explicit stdin
closure, SIGTERM, bounded SIGKILL escalation, stream drainage, and close
awaiting. Bun remains the package manager and primary test runner. A second
Bun-specific process adapter would add surface area without a measured benefit.

## Batch and tmux command groups

### Question

Can a batch be optimized into one tmux semicolon group?

### Probe

A real group executed a successful display command, a failing `has-session`,
and another display command. The same three commands then ran as independent
process calls.

### Result

The group returned the first output and the middle error; tmux removed the final
command. Independent calls returned success, failure, success. Source review at
tmux 3.2a and 3.7b confirmed that an error removes the remaining command group.

Existing positional control-mode prototypes count the separators and wait for
replies that tmux will never emit. That can hang and then misattribute a later
independent reply.

### Decision

`execute_batch()` means independent requests with one correlated outcome per
input. Sequential execution is the reference behavior. No semicolon folding or
persistent control transport ships initially.

## Format framing

### Question

Is one fixed field delimiter sufficient for tmux format output?

### Probe

A session name containing the proposed Unicode record-separator character was
listed with that same separator between fields. A second listing used a fresh
per-command guard.

### Result

The fixed delimiter produced three fields where two were expected. The fresh
guard preserved the session name and produced two fields. Newline was not proven
safe as a universal record boundary.

### Decision

Use a capability-owned codec with independent random record and field guards,
guard fields, exact counts, identity checks, version-selected schemas,
unknown-token detection, retry, and an explicit protocol error. Zod validates a
framed row; it cannot repair a bad frame.

## Selection and criteria representation

### First probe

An initial Python-shape probe compared an Array subclass, immutable wrapper,
proxy, and decorated plain array. The decorated array was the least surprising
way to emulate Python list mutation and indexing, but that surface is not an
eligible TypeScript API: the collection contract requires immutable
`Selection<T>`, predicate-only `.filter(fn)`, declarative `.where(criteria)`,
and no QueryList alias.

### Selection contenders

| Representation                                | Runtime shape                     | Type surface                         | Outcome  |
| --------------------------------------------- | --------------------------------- | ------------------------------------ | -------- |
| Generic selection with per-row interpretation | One collection implementation     | Explicit generated `WhereOf<T>`      | Rejected |
| Generic selection with compiled descriptor    | One collection and evaluator seam | Explicit generated `WhereOf<T>`      | Selected |
| Generated collection class per model          | Duplicated collection methods     | Direct but repeated model signatures | Rejected |

### Probe

All three working contenders used frozen backing arrays and explicit generated
model criteria rather than recursive `keyof` types. A strict TypeScript 7 probe
verified model-field rejection, predicate-only `.filter()`, and the absence of
`.get()` and mutable methods. The probe's type-guard overload exceeded the
selected single-signature contract and is not part of the decision.

The runtime cases covered `AND`, `OR`, `NOT`, to-many `some`/`every`/`none`,
to-one `is`/`isNot`, the empty-relation identities, case mode, ordered eager
filtering, all five cardinality methods, fresh iterators, defensive `toArray()`,
and a versioned JSON criteria document. The same emitted JavaScript passed under
Bun and Node.

### Decision

Use one immutable `Selection<T>` implementation with a generated model
descriptor. The descriptor validates and compiles criteria once, then evaluates
them against a captured frozen graph projection. `.filter(fn, thisArg?)` keeps
native callback runtime semantics through one emitted signature;
`.where(criteria)` is the only declarative entry point. Generated
`SessionWhere`, `WindowWhere`, and `PaneWhere` flow through `WhereOf<T>`;
`WhereOf<Client>` is `never`. Criteria serialize through a versioned document;
callback predicates never serialize.

Python QueryList remains parity evidence, not a TypeScript export. Its callable
filtering, ordering, duplicates, and cardinality map to Selection behavior.
Session, Window, and Pane scalar lookups map to canonical generated criteria;
Client lookups map to callback filtering because `WhereOf<Client>` is `never`.
Mutation, indexing, `items()`/`pk_key`, and its private equality implementation
are explicit exclusions. The exported edge parser accepts only
`name__contains` for Session and Window and returns a canonical versioned
document; its public name is `parse_legacy_where`. Pane, Client, and every other
double-underscore key are rejected.

## I/O surface

### Question

Should async relations look like properties, methods, or lazy thenables?

### Probe

Three call shapes were compared: a promise-returning property getter, an
explicit method, and a lazy thenable collection.

### Result

The property started I/O merely by being read. The thenable permitted chaining
before awaiting but was neither an array nor an ordinary promise and required
inspection magic. The method made cost, cancellation, and failure explicit.

### Decision

Use snake_case async methods such as `await server.sessions()`. Keep direct
scalar getters synchronous over the current snapshot.

## Live handles and immutable data

### Question

Can immutable snapshots replace Python's refreshable objects?

### Finding

Python keeps handle identity, refreshes fields on the same object, and resolves
relations against current tmux state. A retained pane must find its new session
after its window moves. Snapshot-only values cannot provide this behavior.

### Decision

Use stable live handles over atomically replaced frozen snapshots. `refresh()`
updates the retained handle and resolves `void`, matching Python's return value.
Snapshot serialization remains independent from live resources.

## Window graph

### Question

Can snapshots be keyed only by `window_id`?

### Finding

One tmux window can be linked to several sessions and to multiple indexes in one
session. Session-local index and active state belong to a winlink. Server-wide
listings intentionally retain contextual duplicates, and point lookup lets tmux
choose its preferred winlink.

### Decision

Normalize window entities and winlink edges. A contextual `Window` may carry
both references. Never build the server hierarchy as a `window_id`-keyed tree.

## Real-tmux fixture

### Contenders

| Fixture                                                              | Isolation | Crash cleanup | Runtime fidelity |  Score |
| -------------------------------------------------------------------- | --------: | ------------: | ---------------: | -----: |
| Node APIs, explicit per-test `-S`, fixture cleanup, outer supervisor |     29/30 |         23/25 |            20/20 | **94** |
| Bun-native process API, per-test `-L`, Bun hooks only                |     25/30 |         12/25 |            10/20 |     66 |
| One server per worker with unique sessions                           |     14/30 |         12/25 |            19/20 |     65 |

### Probe

Eight fixtures started concurrently under Bun and then Node. Every fixture had
a distinct logical name and observed socket path. Socket roots containing commas
and spaces worked. Cleanup removed every socket after success and after an
intentional assertion failure.

A follow-up started a real daemon inside `bun test --parallel=4 --no-orphans`,
registered its exact socket before launch, and killed the Bun worker separately
with SIGTERM and SIGKILL. In both cases the daemon remained observable before
the parent reaper, then `has-session` failed and the socket was absent after
reaping. A second probe sent SIGTERM to the supervisor itself; its handler
killed the worker, killed the daemon, removed the socket and run root, and
exited zero. Cleanup passed, but zero status after SIGTERM failed the acceptance
contract because it could make a cancelled CI job appear successful.

### Decision

Use one explicit socket path per test and a run-scoped outer supervisor.
Register ownership before launch. Reap in the fixture, worker hooks, supervisor
exit, and CI's always-run cleanup. No implementation can clean up after the
supervisor or host itself receives SIGKILL, so owner-checked stale-run preflight
is also required. The implementation must additionally preserve child failure
or signal status; cleanup replaces only an otherwise-successful result.

## Attached-session ambiguity

### Source finding

Python's `attached_sessions` passes `session_attached__noeq="1"`, but `noeq` is
not a registered lookup operator. The nested-key fallback silently leaves the
last value in place when the suffix does not exist.

### Real-tmux probe

- With one attached control client, the source session had
  `session_attached == "1"` and appeared in `attached_sessions`.
- With two attached control clients, the source session had
  `session_attached == "2"` and did not appear.
- Both temporary daemons and sockets were removed after the probe.

### Decision

Record the versioned observable facade behavior in the parity ledger, but do not
make unsupported lookup suffixes silently alias an earlier field. The sole
compatibility edge adapter accepts `name__contains`; it rejects `noeq`.

## Package and repository studies

The local study set supplied source-informed patterns:

- Pretext: static ESM exports and declaration emission.
- OpenTUI: installing a real tarball in fresh Node and Bun consumers.
- browser-control: child-process ownership and cancellation.
- Class Variance Authority and Satteri: small explicit export surfaces.
- Oxc: type-aware Oxlint through `oxlint-tsgolint`.
- The experimental libtmux engine branch: immutable requests/results,
  capability-bound preparation, and the hazards of positional result slots.

The package grafts those bounded patterns into the architecture record.

## Packed-artifact contract

### Probe

A disposable ESM package used Node-core runtime code, TypeScript 7 declaration
emit, explicit root and module exports, and no source export. It was built and
packed once with `bun pm pack --ignore-scripts` into a path containing a comma
and space.

The archive contained only package metadata, license/readme files, JavaScript,
source maps, and declarations. The same tarball was installed into separate
private ESM consumers by npm and Bun. Each installation passed a TypeScript 7
consumer check with `skipLibCheck: false`, then ran under both Node and Bun.
Every runtime performed a real tmux create/list/kill flow and resolved imports
below its own `node_modules/libtmux/dist` path.

### Decision

Use the explicit ESM export map and real-tarball cross-product in the package
gate. `bun pm pack` 1.3.14 does not accept `--destination` and `--filename`
together, so the pack script supplies one absolute `--filename`. Publication
must use the tested artifact instead of repacking the source tree.

## Disqualifying acceptance cases

An implementation is rejected if any of these occurs:

- A linked window loses a session/index placement or contextual duplicate.
- Refresh replaces a live handle when Python returns the same logical object.
- A retained pane reports its old session after a move.
- A schema or framing error becomes an empty collection.
- A grouped failure is reported as if every group member executed.
- An independent command reply is assigned to a skipped group member.
- A literal semicolon becomes structural syntax.
- Cancellation leaves a reusable connection desynchronized.
- An invalid tmux ID kind passes a branded public boundary.
- `QueryList` or a declarative `.filter()` overload appears in the public API.
- Local criteria trigger tmux I/O or observe mutable state after capture.
- Criteria for one model compile against another model or serialize without a
  supported schema version.
- A package consumer resolves source files instead of the tarball's `dist`.
- A killed test worker leaves a daemon after supervisor cleanup.

## Goal reconciliation

Date: 2026-08-12.

### Question

The accepted plan targets near-total Python symbol parity, exports `./neo`, and
keeps Python's snake_case public names. The current goal subordinates inherited
convention to TypeScript DX, drops the `neo` parity requirement, and adds two
in-tree consumers. What survives?

### Finding

Measured against the goal, the tree splits cleanly along one line: the
infrastructure matches, the public surface does not exist yet.

Matching already, no change needed:

- Toolchain: Bun 1.3.14, TypeScript 7.0.2, Zod 4.4.3, Oxlint, Oxfmt, and
  `oxlint-tsgolint`.
- The entire query API. `Selection<Model>` is an `Iterable` with `length`,
  `at()`, `toArray()`, an unoverloaded native `filter()`, a declarative
  `where()`, and `first`/`one`/`oneOrUndefined`/`exists`/`count` each taking
  optional criteria. `WhereOf<Model>` keeps generated criteria out of public
  signatures, `SessionWhere`/`WindowWhere`/`PaneWhere` are generated rather than
  recursive mapped types, regex criteria are `{pattern, flags}` data, and
  `WhereDocumentV1` is the versioned wire form. There is no `get()` and no
  `QueryList`. This is the goal's most constrained section and it is already
  satisfied.
- The `neo.py` responsibility split the goal asks for exists as
  `_generated/format_fields.ts`, `_internal/codec/format_registry.ts`,
  `_internal/graph/normalize.ts`, and `_internal/graph/materialize.ts`.

Diverging from the goal:

- `src/neo.ts` is a literal `neo.py` port — an `Obj` class, `get_output_format`,
  and `parse_output` — layered on top of the split that already replaced it. It
  is a redundant parity shim and the `./neo` export exists only to serve it.
- Public names are Python's: `Server.config_file`, `socket_name`, `socket_path`,
  `tmux_bin`, and `parse_legacy_where`.
- `Session`, `Window`, `Pane`, and `Client` are 21-line identity stubs carrying
  a brand and `equals()`. No relation, accessor, or I/O method exists on any of
  them.
- Control mode is a test-only resource, explicitly barred from being a command
  transport.
- Neither in-tree consumer exists.

### Result

The expensive proven work is infrastructure: transport, guard codec, normalized
graph, Selection evaluator, generated field metadata, and the supervised
real-tmux substrate. Verified green on this machine — 333 unit, 9 differential,
and 132 of 134 integration tests, with static, parity, declaration, and
instantiation gates passing.

The two integration failures are environmental, not defects. `LIBTMUX_NODE22` is
unset and the emitted-Node lane refuses to substitute the current runtime, which
the plan requires. Separately, `run_root.ts` resolves its pidfd reaper through
`python3` on `PATH`; in this checkout that is the repository virtualenv, a
free-threading build compiled without `os.pidfd_open`. The reaper then cannot
signal daemons whose socket was already unlinked, so each run leaks daemons and
reservation directories that corrupt the next run's results. Pointing
`LIBTMUX_TEST_PYTHON` at an interpreter exposing `pidfd_open` makes the suite
deterministic.

### Decision

Keep the infrastructure and the query API. Treat the public surface as unwritten
rather than as work to unwind, because it very nearly is.

Retire the parity-first framing that the remaining plan tasks assume. Delete
`src/neo.ts` and its export rather than porting more of `neo.py` behind it.
Public names follow TypeScript convention, and Python spellings survive only
where they are already idiomatic. Python's deprecated surface —
`attached_pane`, `attach_session`, `kill_session`, `get_by_id`, `find_where`,
`list_windows`, `children` — is not ported at all; `Selection` supersedes it.

Command wrappers drop the receiver's noun when the remainder stays unambiguous
on that receiver, so `Session.lock_session` becomes `lock` and
`rename_session` becomes `rename`, while `Pane.breakPane` keeps its noun because
a bare `break` does not read as one.

The pidfd reaper must resolve an interpreter it has verified exposes
`pidfd_open` instead of trusting `PATH`, and fail loudly when none is found. A
silent fallback presents as substrate flakiness, which is what stalled the
previous review cycle.

## Relation traversal and snapshot acquisition

Date: 2026-08-12.

### Question

Relations can either perform I/O per traversal — `await session.windows()` —
or resolve against one explicitly acquired snapshot. The goal requires eager
evaluation against an explicit snapshot and forbids iteration from shelling out,
so the open question is what a snapshot costs and whether one can be acquired
without losing information.

### Probe

A disposable integration spike built two sessions, each holding one single-pane
window from session creation plus three two-pane windows, and counted `list-*`
invocations through an instrumented transport. A second scenario linked one
window into a second session at an explicit index.

### Result

Per-relation traversal costs one tmux invocation per parent object. Selecting
the panes of every window named `editor` across two sessions took five
invocations — one `list-sessions`, two `list-windows`, two `list-panes` — and
grows as sessions plus windows.

A single `list-panes -a` returned all fourteen panes, and every row carried its
complete ancestry: `pane_id`, `window_id`, `window_index`, `session_id`, and
`session_name`. `list-panes` resolves the universal, session, window, and pane
scopes, so one invocation is sufficient to construct every session, window, and
pane entity locally. Cost is constant in the size of the topology.

Winlink multiplicity survives that single invocation. A window linked into a
second session appeared under one `window_id` with two contextual placements,
matching the two rows `list-windows -a` reports independently. The single-call
snapshot therefore loses no placement information, which was the risk that would
have disqualified it.

Sessions holding no windows are not a practical gap, because tmux gives every
new session a window.

### Decision

Acquisition is an explicit named operation. Relations resolve against the
acquired snapshot and issue no commands, so traversal depth and topology size do
not change command count.

Implementing it corrected the listing set this probe first proposed. Measuring
tmux output alone suggested `list-panes -a` plus `list-clients` would do,
because a pane row does carry every ancestor field. Normalization does not work
that way: one row becomes exactly one record whose model its subcommand fixes,
so a pane row registers session and window entities but produces no session or
window record. Selections draw members from records, so each model needs its own
listing.

Acquisition therefore issues `list-sessions`, `list-windows -a`, `list-panes
-a`, and `list-clients` concurrently. Four is still constant in the size of the
topology, which was the property that decided the fork; the per-relation
alternative grows as sessions plus windows.

This fork does not need a bakeoff. Per-relation I/O is dominated on command
count, it cannot satisfy the requirement that iteration never shells out, and
its only advantage — narrower reads — is unavailable anyway because tmux emits
full ancestry on every pane row regardless.

Both scenarios ran on tmux 3.7b. `list-panes -a` ancestry and linked-window
multiplicity still need confirming across the supported cells down to 3.2a
before the acquisition path is final.

## Public shape of snapshot acquisition

Date: 2026-08-12.

### Contenders

Acquisition cost is settled, so the remaining fork is what a caller writes.
Three shapes were built over one shared acquisition and graph, so the comparison
isolates public shape:

- Acquisition returns a value from the handle: `await server.snapshot()`.
- Acquisition mutates the handle, mirroring Python: `await server.refresh()`
  followed by a synchronous `server.panes`.
- Acquisition is a free function: `await snapshotOf(connection)`.

### Probe

Each contender answered the same query — the panes of the window named `editor`
in a named session — against real tmux. Two further scenarios acquired twice
across an intervening `new-window`, and inspected the pre-acquisition state.

### Result

All three return identical results, so correctness does not separate them.

The two value-returning shapes let views of different instants coexist. A view
acquired before a window was added still reported one matching pane after a
later acquisition reported two.

The mutating shape fails on two counts. Its accessor silently changes meaning
under a caller who never asked for new data, which contradicts the requirement
that results be immutable and replayable. Worse, a freshly constructed handle
has no snapshot at all, so every accessor either throws or returns an empty
result until someone remembers to call `refresh()`. That is an illegal state
reachable by construction, and it pushes a defensive check into every consumer.

Concurrency decides it independently. The planned MCP server serves overlapping
requests against one server handle; a single mutable current snapshot cannot
serve two requests observing different instants.

### Decision

Acquisition is a method returning an immutable value: `await server.snapshot()`.
The method form wins over the free function on discoverability, which matters
more here than tree-shaking a single call; the free function's real virtue —
that acquisition produces a plain value instead of binding into the handle — is
kept.

`refresh()` is not reused for acquisition despite the Python precedent, because
it names mutation. It stays reserved for Python's genuinely mutating single
handle re-read, which is a different operation on a different receiver.

## Projection descriptors are generated, not authored

Date: 2026-08-12.

### Question

Building `Selection<Session>` needs a projection descriptor naming the model's
criteria fields and relations. An early implementation copied the descriptors
from an existing graph test, which declares sessions as having no relations.

### Finding

Selection construction rejected that projection. Members, records, scalars, and
materialized handles were all correct — one session member, one session record,
thirty-two scalar keys matching the generated wire names exactly — and the
failure came from relation validation instead.

Selection validates each record's adjacency against generated
`WHERE_RELATIONS_V1`, not against the descriptor it was handed. Sessions declare
`windows`, `panes`, `active_window`, and `active_pane`; windows declare
`session`, `linked_sessions`, `panes`, and more; panes declare `window` and
`session`. A descriptor that understates a model's relations cannot produce a
usable selection no matter how well formed everything else is.

### Decision

Descriptors are derived from `WHERE_FIELDS_V1` and `WHERE_RELATIONS_V1`, never
authored by hand, so the criteria surface and the projection contract cannot
drift apart. Test fixtures that declare a narrower relation set are fixtures,
not a specification, and must not be copied into production code.

The consequence for acquisition is structural rather than incidental. Because
relations must resolve locally, every relation the generated metadata declares
for a member's model has to be hydrated while the snapshot is built. Selections
of sessions, windows, and panes therefore cannot land as independent slices;
they need one hydration pass that walks winlinks and assigns panes to their
contextual window placement.

## What `neo.ts` actually is

Date: 2026-08-12.

### Question

The goal removes the `neo` parity requirement and asks for `neo.py`'s
responsibilities to be split across generated field metadata, acquisition,
format parsing, relation normalization, and entity construction. An earlier
reconciliation here called `src/neo.ts` a redundant shim layered on top of that
split, and proposed deleting it.

### Finding

That was wrong, and acting on it would have broken the build.

`src/neo.ts` holds the shared type vocabulary the split depends on:
`ListCommand`, `FormatScope`, `FormatFieldName`, `OutputFormatField`, and the
`Obj` entity class. Both generated modules import from it, as do `normalize.ts`,
`model.ts`, `schemas.ts`, `guard_codec.ts`, and `format_registry.ts` — which
additionally emits import specifiers pointing back at it, so the generator's
byte-identical output depends on its path.

Only two of its exports are genuinely parity-shaped: `get_output_format` and
`parse_output`, whose sole consumers are their own tests and the packed-artifact
smoke test.

Removing the `./neo` export is therefore a ledger migration rather than a
deletion. The generator emits a parity row per `Obj` field token keyed to
`./neo`, and the package contract asserts the export map, reads the emitted
`neo.d.ts` for declaration self-containment, and imports `libtmux/neo` from the
packed tarball.

### Decision

Keep the vocabulary and relocate it under `_internal` rather than deleting it,
retire only the two parity-shaped functions, and treat the `./neo` export
removal as one coordinated change spanning the generator, the regenerated
manifest, the package contract, and the packed-artifact smoke test. Splitting
that work leaves the parity gate red against a ledger that no longer matches its
generator.

The responsibilities the goal asks to be split already are: generated field
metadata in `_generated`, acquisition in `operations/acquire.ts`, format parsing
in `codec`, relation normalization in `graph/normalize.ts`, and entity
construction in `graph/materialize.ts`. What remains in `neo.ts` is naming, not
structure.

### Outcome

`ListCommand`, `OutputFormatField`, `TmuxVersionView`, and the entity class —
renamed `ParsedFormatRow` for what it is — live in
`_internal/codec/format_types.ts`. `FormatScope` and `FormatFieldName` moved
into `_generated/format_fields.ts` instead: a vocabulary module that names the
generated union while the generated union imports the vocabulary is a cycle,
and TypeScript resolves it by silently degrading `FormatFieldName` to `any`,
which costs every scalar field its type without failing a build.

The ledger carries the 183 `neo.py` symbols as `unsupported` with all three
evidence lanes not-applicable, since an unported symbol has no declaration,
unit test, or tmux scenario to point at.

### Cost

The type-instantiation baseline moved from 222,309 to 287,526, and the increase
is intrinsic to the move rather than to anything else in it. Applying only the
union relocation to an otherwise untouched tree reproduces it (289,963);
applying every other source change while leaving the union in place does not.
The added instantiations are a roughly uniform 1.4x across Zod's generic graph,
with no libtmux module gaining types of its own.

The old number depended on `neo.ts` and `format_registry.ts` importing each
other. Inside that cycle TypeScript resolved the row types once; across an
ordinary edge it re-resolves them per relation. Three plausible-sounding
remedies measured as noise: splitting the union away from the field table,
restoring the class's private constructor, and replacing
`Record<FormatFieldName, string | null>` with an explicit 178-property
interface. Only the last is a design question rather than a performance one,
and it loses on readability — it forces a cast in `normalize.ts` and widens
every index-by-token site.

287,526 instantiations is not a compile-time problem in absolute terms. The
gate is a drift detector, and this is a deliberate one-time step recorded so a
later 30% jump is not mistaken for this one.

## Handles do not observe their own mutations

Date: 2026-08-12.

### Finding

Writing the lifecycle tests surfaced a consequence of immutability that the read
path never exposed. A handle resolves relations from the graph it was
materialized against, so a window created before a split keeps reporting one
pane after `window.split()` resolves a second. Both assertions in the first
draft of those tests were wrong for this reason, and the behaviour they found is
correct rather than a defect.

The mutation itself returns a live handle for what it created, so the created
object is never stale. What goes stale is the receiver.

### Decision

Keep the semantics. A snapshot that silently tracked later mutations would
contradict replayability, which the acquisition bakeoff already settled, and
would reintroduce the accessor whose meaning changes under a caller.

Close the ergonomic gap with `refresh()`, which the acquisition bakeoff reserved
for exactly this: a mutating single-handle re-read that returns the same
receiver updated to the current instant. Until it exists, callers re-snapshot,
and the lifecycle tests document that by asserting both the handle's own instant
and a fresh snapshot's.

## Menus hold the client until dismissed

Date: 2026-08-12.

### Finding

`display-menu` does not resolve when the menu appears; it resolves when someone
chooses an entry or cancels, because tmux keeps the menu open on the client.
Awaiting it from a non-interactive driver waits forever.

Dismissing it needs input routed to the client rather than the pane.
`send-keys -t <pane>` reaches the pane underneath the overlay and leaves the
menu open, and a control-mode client offers no route to the overlay, so the
harness here cannot close a menu it opened.

A separator is also not a name/key/command triple. tmux spells it as one empty
argument, so a menu model that requires three fields per entry produces a
command tmux rejects.

### Decision

`MenuItem` is `MenuEntry | "separator"` so a separator cannot be expressed as
three empty fields. The blocking behaviour is documented on the operation rather
than smoothed over, since a caller who awaits it without arranging dismissal has
a hang, not a slow call.

The menu has no integration test. Asserting it needs a TTY-backed client that
can receive the dismissing key, which this harness does not provide, and a test
that opens a menu it cannot close hangs the suite and holds a client open. The
adjacent client-owned commands that do complete on their own — popups, the
choosers, `find-window`, `customize-mode`, `send-prefix` — are covered.

## Unreachable servers raise instead of reading empty

Date: 2026-08-12.

### Question

Python's list-shaped accessors are lenient by design: `Server.sessions` answers
an empty list whether the server holds no sessions or cannot be reached at all,
and `is_alive()`/`raise_if_dead()` exist to tell those apart. Should the
TypeScript port inherit that?

### Finding

Adding `isAlive()` exposed that the port already diverges. Acquisition binds
tmux capabilities before listing, so a missing socket surfaces as a raised
version-probe failure rather than an empty selection.

The lenient contract makes the common case silently wrong. A caller that writes
`if ((await server.sessions()).length === 0)` reads a dead server as a tidy one,
and nothing in the type or the value hints that a question went unanswered.
Leniency only pays off when the caller remembers to ask `is_alive()` first,
which is precisely the caller who did not need the leniency.

### Decision

Collection accessors raise when the server cannot be reached. `isAlive()`
answers the same question without raising, and `raiseIfDead()` states it as an
assertion carrying tmux's own message.

This is a deliberate divergence from Python, taken under the rule that inherited
conventions are subordinate to quality. An empty result now means exactly one
thing.

## Sources

- [libtmux 0.62.0 QueryList](https://github.com/tmux-python/libtmux/blob/v0.62.0/src/libtmux/_internal/query_list.py)
- [libtmux 0.62.0 server facade](https://github.com/tmux-python/libtmux/blob/v0.62.0/src/libtmux/server.py)
- [libtmux 0.62.0 real-tmux fixtures](https://github.com/tmux-python/libtmux/blob/v0.62.0/src/libtmux/pytest_plugin.py)
- [tmux 3.2a command queue](https://github.com/tmux/tmux/blob/3.2a/cmd-queue.c)
- [tmux 3.7b command queue](https://github.com/tmux/tmux/blob/3.7b/cmd-queue.c)
- [tmux 3.7b client transport](https://github.com/tmux/tmux/blob/3.7b/client.c)
