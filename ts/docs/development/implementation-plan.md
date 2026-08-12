# libtmux TypeScript implementation plan

Status: accepted execution plan after renewed TypeScript, Bun/Node, and safety
review of the Task 4 daemon-generation correction.

Goal: publish an ESM npm package named `libtmux` whose async TypeScript facade
tracks Python libtmux 0.62.0 across tmux 3.2a through 3.7b, while preserving the
architecture in `architecture.md`.

This plan creates a fresh implementation after the disposable spikes. It does
not authorize commits, tags, pushes, publication, or unrelated Python changes.

## Working rules

Every behavior follows the same cycle:

1. Add or activate its parity-manifest entry.
2. Write a test that names an observable break and derives its expectation from
   pinned Python behavior or raw tmux.
3. Run the narrow test and witness a behavioral failure.
4. Implement the smallest production path that makes it pass.
5. Refactor without changing behavior.
6. Run the slice gate and update the manifest only when all evidence passes.

An import failure is acceptable only for the first test of a new module. Later
RED states must reach the behavior under test. A recording transport is allowed
at the process seam and must return complete realistic results. I/O behavior
also needs a real-tmux test. Tests never assert merely that a mock or source line
exists.

Each numbered task is an independent review boundary. No review boundary is a
commit unless the user separately authorizes commits.

## Cumulative gates

A task is incomplete unless:

- Every production behavior had a witnessed RED.
- Unit tests, declaration tests, and relevant real-tmux tests pass.
- Manifest entries name pinned source evidence and their TypeScript tests.
- Schema and protocol failures propagate instead of becoming empty results.
- The fixture leak audit reports no daemon, socket, or reservation.
- `bun run format:check`, `bun run lint`, `bun run typecheck`, and the cumulative
  test set remain green.
- Version-sensitive work passes every applicable compatibility cell.

The blocking tmux matrix is `3.2a`, `3.3`, `3.3a`, `3.4`, `3.5`, `3.5a`, `3.6`,
`3.6a`, `3.7`, `3.7a`, and `3.7b`.

## Task 1: Bootstrap package and parity contracts

Create:

- `ts/package.json`
- `ts/bun.lock`
- `ts/tsconfig.json`
- `ts/tsconfig.build.json`
- `ts/tsconfig.tooling.json`
- `ts/.oxlintrc.json`
- `ts/.oxfmtrc.json`
- `ts/bunfig.toml`
- `ts/knip.json`
- `ts/.gitignore`
- `ts/src/index.ts`
- `ts/parity/python-0.62.0.json`
- `ts/scripts/check-parity.ts`
- `ts/scripts/check-type-aware-lint.ts`
- `ts/tests/fixtures/type-aware-lint/tsconfig.json`
- `ts/tests/fixtures/type-aware-lint/no_floating_promise.ts`
- `ts/tests/unit/package_contract.test.ts`
- `ts/tests/unit/parity_manifest.test.ts`
- `ts/tests/unit/source_map_contract.test.ts`

RED first:

- The package-contract test expects ESM-only built entrypoints, Node/Bun floors,
  ordered export conditions, no wildcard/source/CJS/Bun exports, Zod as the only
  runtime dependency, exact Node 22 and Bun 1.3.14 type lanes, and only runnable
  scripts for this task. Later tasks extend the asserted script set when their
  harnesses land.
- The parity test expects every Python 0.62.0 public class, function, method,
  property, exception, constant, format field, test helper, and documented
  compatibility alias to have one classified symbol row. The manifest has
  separate validated record sets for observable behavior clusters, TypeScript
  extensions, and deliberate internal exclusions, plus a schema-versioned
  baseline containing Python version, tag, and full resolved commit.

Minimal implementation:

- Start at version `0.1.0` with `private: true`; change it only in the final
  package task after the full export and parity gates pass.
- Pin the recorded Bun, TypeScript, Zod, Oxc, package-audit, and Node-type
  dependencies in `bun.lock`, including exact `@types/node` 22.20.1 and
  `@types/bun` 1.3.14.
- Configure strict TS7 NodeNext emit from `src/**` only, with Node types and
  `ESNext.Disposable` but no declaration maps or `skipLibCheck`. Enable
  `sourceMap` and `inlineSources`, omit `sourceRoot`, and keep source paths
  relative.
- Typecheck scripts, ordinary tests, fixtures, and support code through
  `tsconfig.tooling.json` with Bun and Node types. Exclude negative declaration
  fixtures and the intentionally invalid lint fixture so neither contaminates
  normal tooling checks or public declarations.
- Export only `.` and `./package.json` initially. Add a public subpath only when
  its implementation lands; never add an empty placeholder.
- Record syntax adaptations explicitly: promises for I/O, options objects for
  Python keywords, `.equals()` for Python `==`, async disposal for context exit,
  and Python collection behavior mapped to Selection and Where criteria.
- Record tag `v0.62.0` and its resolved commit. Validate the runtime manifest
  shape, all four record sets, and status invariants. Regeneration updates only
  derived symbol rows, preserves unchanged evidence and every manual record set
  byte-for-byte, detects removed keys, requires explicit boundary-change
  approval, and writes atomically. Independent inclusion/exclusion sentinels and
  audited per-section digests cannot be derived by the same parser.
- Use the Node-22 declaration lane with the Node 22 runtime floor. Assert the
  complete exact direct dependency maps.
- Keep the main lint input clear of the deliberately invalid type-aware fixture.
  A dedicated harness must observe the exact
  `typescript/no-floating-promises` diagnostic and nonzero Oxlint status, and
  `lint` must run that proof.

The initial script set contains only implemented format, lint, source and
tooling typecheck, build, parity, and unit-test commands. It does not advertise
declaration, Node-runtime, integration, differential, generation, package,
dead-code, full `check`, or publication gates before their harnesses exist.

The source-map test emits the entrypoint and parses its map. It rejects an
absolute source or one escaping the virtual package root, `sourceRoot`, a missing same-index
`sourcesContent`, or embedded content that does not match the named source. It
does not require the physical TypeScript source to ship in the future tarball.

Verify with `bun install`, the three targeted tests, `bun run typecheck`,
`bun run typecheck:tooling`, `bun run build`, `bun run format:check`, and
`bun run lint` from `ts/`.

## Task 2: Errors, constants, IDs, and foundational types

Create:

- `ts/src/common.ts`
- `ts/src/exc.ts`
- `ts/src/constants.ts`
- `ts/src/_internal/runtime/ids.ts`
- `ts/tests/unit/exc.test.ts`
- `ts/tests/unit/constants.test.ts`
- `ts/tests/unit/ids.test.ts`
- `ts/tests/types/common.test.ts`
- `ts/tests/types/brands.test.ts`
- `ts/tests/types/tsconfig.json`
- `ts/tests/types/assert.ts`

RED first:

- Error subclasses preserve stable names, query/count/subcommand data, message,
  and cause without exposing `ZodError`.
- `NoMatchError` extends `ObjectDoesNotExist`, `MultipleMatchesError` extends
  `MultipleObjectsReturned`, and `QueryValidationError` exposes a stable code
  without leaking Zod or regular-expression errors.
- `$1`, `@2`, and `%3` parse into owned brands; malformed or wrong-kind IDs fail.
- Raw strings remain accepted at public inputs, while an already branded wrong
  kind fails a declaration test.
- Direction and option-scope constant objects match Python member names and
  values without native TypeScript enums.

Minimal implementation:

- Define I/O options, command/result fields, delivery and operation statuses,
  logger/warning interfaces, ID/input brands, and logical-ref shapes.
- Port the complete public exception hierarchy and add the three canonical
  TypeScript query errors without replacing compatibility classes.
- Keep Zod schemas private and wrap validation failures.
- Add `./common`, `./exc`, and `./constants` only after their package and
  declaration tests pass.
- Add the runnable `test:types` script with this task.

Gate: targeted Bun tests, type fixtures, typecheck, build, format, and lint.

## Task 3: Connection, subprocess transport, decoding, and batch outcomes

Create:

- `ts/src/_internal/runtime/connection.ts`
- `ts/src/_internal/transport/types.ts`
- `ts/src/_internal/transport/node_spawn_transport.ts`
- `ts/src/_internal/codec/backslash_replace.ts`
- `ts/src/_internal/operations/request.ts`
- `ts/scripts/test-node.ts`
- `ts/tests/fixtures/echo_argv.mjs`
- `ts/tests/fixtures/ignore_sigterm.mjs`
- `ts/tests/fixtures/malformed_utf8.mjs`
- `ts/tests/unit/connection.test.ts`
- `ts/tests/unit/transport.test.ts`
- `ts/tests/unit/cancellation.test.ts`
- `ts/tests/unit/backslash_replace.test.ts`

RED first:

- Connections reject conflicting selectors and freeze copied configuration and
  environment data.
- Spaces, leading dashes, quotes, backslashes, Unicode, and a literal semicolon
  reach a child as distinct arguments with `shell: false`.
- A nonzero child exit returns a raw result rather than throwing.
- stdout and stderr are drained concurrently; Python trimming and `has-session`
  stderr-to-stdout behavior are preserved at the public-result adapter.
- Malformed UTF-8 split across chunks uses per-byte backslash replacement.
- Pre-aborted input does not spawn; blocked stdin closes; ignored SIGTERM
  escalates to SIGKILL; abort/exit races settle once.
- Sequential independent batching returns correlated success/failure/success
  and continues after the known middle failure.

Minimal implementation:

- Use only `node:child_process.spawn`, byte streams, and literal argv.
- Close stdin, send SIGTERM, wait a bounded grace period, send SIGKILL, await
  `close`, and drain or discard both pipes.
- Keep delivery state separate from operation status.
- Use stdin only when an operation's tmux command natively accepts it.
- Add `test:node` and a runtime-neutral scenario protocol. The controller may
  use Bun, but every Node assertion must execute emitted JavaScript with the
  actual `node` executable.
- `test-node.ts --node <absolute-executable> --expect-major 22` queries that
  executable first and rejects the wrong major. Its default resolves
  `LIBTMUX_NODE22` and then `node` on `PATH` to an absolute path with the same
  check. The Task 3 floor gate receives a provisioned Node 22 path; absence of
  that executable is a failed gate, not an implicit current-Node substitute.

Gate: targeted tests under Bun and compiled Node runtime scenarios, typecheck,
build, format, and lint.

## Task 4: Supervised real-tmux test substrate

Create:

- `ts/src/_internal/test/run_root.ts`
- `ts/src/_internal/test/test_server.ts`
- `ts/src/_internal/test/control_mode.ts`
- `ts/tests/support/fixture_registry.ts`
- `ts/tests/support/bun_hooks.ts`
- `ts/tests/integration/test_server.test.ts`
- `ts/tests/integration/supervisor_cleanup.test.ts`
- `ts/tests/integration/differential_substrate.test.ts`
- `ts/tests/fixtures/leaking_tmux_worker.ts`
- `ts/tests/differential/python_oracle.py`
- `ts/tests/differential/raw_tmux.ts`
- `ts/scripts/test_supervisor.ts`
- `ts/scripts/run-integration-tests.ts`
- `ts/scripts/run-differential-tests.ts`
- `ts/scripts/reap-test-run.ts`

RED first:

- Eight concurrent fixtures reserve distinct logical names and exact `-S`
  paths, including a comma/space run root.
- Each queries and matches `#{socket_path}` and completes a bounded pane-shell
  `wait-for -S` handshake.
- A launch proven `not_started` with an absent socket and a throwing test body
  after authority publication leave no daemon, socket, registry, or
  reservation. Every other pre-authority startup failure preserves a leak.
- Under the cooperating same-UID harness threat model, if another tmux server
  wins the exact socket before the launch client runs, the bootstrap gate
  rejects it before `new-session` without signalling the daemon, unlinking its
  socket, or removing the ownership evidence.
- A fresh per-launch generation appears in both the new daemon's NUL-framed
  process environment and global tmux environment on tmux 3.2a and the current
  supported release. Connecting a later client does not install it.
- An overlong Unix socket path fails before spawn.
- A Bun worker killed by SIGTERM or SIGKILL leaves a daemon that the parent
  identifies and reaps.
- Supervisor SIGTERM cleans its worker and run root.
- Normal child exit preserves its status; child signal termination is preserved
  as the same signal or `128 + signal`. Supervisor SIGINT/SIGTERM forwards,
  escalates boundedly, reaps, then self-signals or exits 130/143. Cleanup
  replaces only an otherwise-zero result.
- Stale preflight refuses a live owner's root and reaps a dead owner's root.
- The same live PID with a different process-start identity is stale owner
  reuse. An inaccessible socket falls back to a matching daemon PID/start
  identity and launch generation. A mismatched daemon identity or generation is
  never signalled; missing, corrupt, or pre-generation identity fails safely and
  reports a leak.
- Cleanup failure fails a passing test but remains secondary to an existing test
  failure.
- The exact parallel integration command is repeatable under load. A supervised
  helper reads the published root, changes and verifies the owner record, then
  exits 7; the test proves status 7 remains primary while cleanup is reported.
  Missing-executable cleanup and direct thrown-value identity remain separate.

Minimal implementation:

- Publish the run root before spawning Bun.
- Reserve each fixture with atomic `mkdir`, register exclusively before tmux,
  and enumerate only the exact run root during cleanup.
- Resolve the trusted tmux controller to an absolute path and snapshot its file
  identity before publishing the run root. Persist it in owner protocol v2 and
  require every fixture record to match it. At fixture entry, synchronously copy
  and freeze caller options, the optional launch-only wrapper reference, and the
  base environment; never reread them or `process.env`. After reservation
  returns the winning socket path, construct and freeze the generation and
  complete literal bootstrap argv, persist the `launching` record, then spawn.
  Persist no wrapper. Give only the bootstrap request the generation environment
  overlay; the wrapper is trusted only to delay, forward, or fail.
- Bootstrap with one internal literal command list:
  `start-server ; if-shell -F <generation> <new-session> <mismatch>`. The false
  branch emits a strict randomized frame and performs no mutation. Do not expose
  this structural list as transport batching or generic semicolon folding.
- Implement fixture protocol v3 as a closed capability-bound union. `reserved`
  retains the canonical socket path but forbids generation, daemon, and socket
  identity authority. `launching` requires the exact
  generation name/value, trusted controller identity, and complete bootstrap
  argv but grants no daemon authority. `running` retains that snapshot unchanged
  and requires daemon and socket identities. Roll back only locally proven
  `delivery: not_started` with an absent socket.
- Promote the record to `running` only after strict frame parsing, full process
  identity and complete-argv validation, exact raw `/proc/<pid>/environ`
  validation, a PID-guarded `show-environment -g` through a fresh unattached
  trusted `-N` controller, and a socket-inode sandwich.
- Discover a stale `launching` candidate only through a strict `-N` exact-socket
  frame, treat the PID as untrusted, repeat the full process/global-generation
  validation and inode sandwich, then promote before cleanup. Missing socket or
  evidence remains a leak.
- Revalidate process generation, identity, resolved executable, and complete
  bootstrap argv before one connected exact-PID-and-generation guarded
  `kill-server`. A mismatch preserves the foreign socket and never falls through
  to pidfd for that pathname. Revalidate the same evidence around every pidfd
  signal when the socket is inaccessible.
- Bind a version-3 journal to the exact version-3 record inode and digest. Accept
  only `reserved` without socket authority or `running` with its exact socket;
  reject `launching`. Never migrate, normalize, unlink, signal, or delete
  version-1 owner or version-2 fixture or journal evidence.
- Add negative declaration cases for every impossible v3 phase shape and for
  transition calls without the opaque reservation or launch-attempt capability.
  Keep all fixture types under `_internal` and leave package exports unchanged.
- Use fixture `finally`, worker hooks, supervisor cleanup, and CI cleanup as
  independent layers; use `--no-orphans` only as defense in depth.
- Implement the attached-client `ControlMode` test resource without making it a
  command transport.
- Add runnable integration and differential scripts; do not add their package
  scripts earlier.
- Establish one shared raw-tmux and pinned-Python oracle protocol and run a
  substrate smoke. Every later differential scenario reuses these helpers.

Gate: repeated integration tests under Bun and emitted Node 22; bootstrap,
generation, global-environment, recovery, and guarded-kill probes in every tmux
cell from 3.2a through 3.7b; killed-worker tests; wrong-daemon
zero-signal/zero-unlink probes; and a final leak audit. Keep this reusable
substrate internal until the complete public test facade lands in Task 17.

## Task 5: Versions, capabilities, formats, codec, and criteria metadata

Create:

- `ts/src/formats.ts`
- `ts/src/_internal/codec/format_types.ts`
- `ts/src/_internal/runtime/tmux_version.ts`
- `ts/src/_internal/runtime/capabilities.ts`
- `ts/src/_internal/codec/format_registry.ts`
- `ts/src/_internal/codec/guard_codec.ts`
- `ts/src/_internal/codec/schemas.ts`
- `ts/src/_generated/format_fields.ts`
- `ts/src/_generated/where_fields.ts`
- `ts/scripts/generate-formats.ts`
- `ts/tests/fixtures/python-0.62.0-format-fields.json`
- `ts/tests/unit/tmux_version.test.ts`
- `ts/tests/unit/capabilities.test.ts`
- `ts/tests/unit/formats.test.ts`
- `ts/tests/unit/codec.test.ts`

RED first:

- Version ordering is `3.7 < 3.7a < 3.7b`; ordinary floors carry forward while
  the exact 3.7 quirk does not.
- Binding is lazy and a capability fingerprint changes with version, connection
  alias, or daemon epoch.
- The registry matches every Python `Obj` field, scope, and version floor.
- `neo.py`'s responsibilities split across the generated field metadata, the
  guard codec, graph normalization, and the handle classes; no `neo` module or
  export exists, and the parity ledger records its symbols as unsupported.
- Scalar filter domains and stable wire names generate explicit Where fields
  for Session, Window, and Pane without inspecting class methods.
- `session_name` and `window_name` map to the model-local canonical criteria
  field `name`; Pane exposes no `name`, and Client has no Where metadata. Raw
  format-token names remain separate from stable public wire names.
- Version 1 generates only canonical wire names and an empty alias table. A
  future schema version may add an alias only for a name that shipped earlier.
- Guarded frames preserve empty and embedded separator/newline data, reject
  wrong field counts and identities, detect literal unknown tokens, and never
  retry invisibly.
- Client names validate without a sigil.
- Public fields always exist as `string | null`; empty remains empty,
  unsupported is null, and malformed required identity aborts.

Minimal implementation:

- Make one registry generate schemas, declarations, getters, format requests,
  scalar criteria metadata, and parity entries deterministically. Keep cyclic
  relation specifications explicit rather than deriving them from `keyof`.
- Add `generate` and `generate:check`. Check mode renders in memory and compares
  exact bytes without writing; `build` runs it before `tsc`.
- Keep guard generation injectable for deterministic unit tests.
- Decode bytes and complete frames before Zod validation.
- Implement Python's scope selection, target-not-found translation, and
  best-winlink selection.

Gate: generated output is idempotent and drift-checked, generated criteria
expose only valid model fields, real list/fetch operations pass, and
`./formats` is exported.

## Task 6: Frozen snapshots, normalized graph, and evaluation projections

Create:

- `ts/src/_internal/graph/refs.ts`
- `ts/src/_internal/graph/model.ts`
- `ts/src/_internal/graph/normalize.ts`
- `ts/src/_internal/graph/selection_projection.ts`
- `ts/tests/unit/refs.test.ts`
- `ts/tests/unit/snapshots.test.ts`
- `ts/tests/unit/graph.test.ts`
- `ts/tests/types/snapshots.test.ts`

RED first:

- Snapshots and contained arrays are frozen.
- One `window_id` linked through two session/index pairs yields one entity, two
  ordered winlinks, and two contextual projection records.
- Two indexes in one session remain distinct.
- Server listings retain contextual duplicates; targeted lookup follows tmux's
  selected placement.
- Serialized refs expose only opaque alias/epoch/kind/id and reject invalid
  shapes or ID kinds.
- A captured evaluation projection freezes scalar rows and relation adjacency;
  later source-row or topology mutation cannot alter it.
- A projection builder cannot resolve until every relation listed by that
  model's criteria descriptor is materialized. Hydration failure remains
  distinct from an empty relation and never produces a partial public
  selection.

Minimal implementation:

- Keep mutable normalization maps internal.
- Build immutable selection projections from normalized entities and winlinks;
  actual class materialization waits for Task 7.

Gate: unit/property tests, declaration tests, and a real hydration test.

## Task 7: Public handle identity and snapshot foundations

Create:

- `ts/src/server.ts`
- `ts/src/session.ts`
- `ts/src/window.ts`
- `ts/src/pane.ts`
- `ts/src/client.ts`
- `ts/src/_internal/graph/materialize.ts`
- `ts/src/_internal/runtime/context.ts`
- `ts/src/_internal/runtime/live_handle.ts`
- `ts/src/_internal/runtime/model_kind.ts`
- `ts/tests/unit/handles.test.ts`
- `ts/tests/types/handles.test.ts`

RED first:

- `Server` directly binds an immutable connection/runtime context; child
  handles can be materialized only from validated complete snapshots.
- Each class carries a private nominal model kind so `WhereOf<T>` can later map
  actual class declarations without structural aliases or `keyof` inspection.
- Complete scalar snapshot getters are synchronous, readonly, and distinguish
  null from empty strings. A replacement is atomic.
- `Server.equals()` compares socket selectors. Session, Window, and Pane compare
  only their owner IDs, preserving Python's cross-server and cross-winlink wart.
  Client compares its exact class, Server equality, and every captured public
  snapshot field while ignoring TypeScript-only bookkeeping. Durable-reference
  equality remains separate, and equality never deduplicates Selection
  membership. Every emitted class has exactly
  `equals(other: unknown): boolean`.
- Child IDs, contextual winlink refs, runtime alias, and daemon epoch are
  validated; snapshots contain no transport, promise, logger, or credentials.
- Async reference binding rejects the wrong runtime alias or daemon generation.
- Relation materialization creates fresh actual handles from projection records;
  it does not globally intern them.
- The emitted declarations contain the actual five class identities, not
  placeholder interfaces.

Minimal implementation: complete the identity, construction, scalar snapshot,
and equality slice for all five classes. Keep their package subpaths private
until the read-only object graph is complete; this task creates usable model
cores, not empty public stubs.

Gate: unit/property and declaration tests, typecheck, build, format, and lint.

## Task 8: Selection, generated Where criteria, and compatibility lowering

Create:

- `ts/src/selection.ts`
- `ts/src/_internal/selection/compile.ts`
- `ts/src/_internal/selection/evaluate.ts`
- `ts/src/_internal/selection/legacy.ts`
- `ts/src/_internal/selection/serialization.ts`
- `ts/tests/fixtures/where_regex.json`
- `ts/tests/unit/selection.test.ts`
- `ts/tests/unit/where.test.ts`
- `ts/tests/unit/legacy_where.test.ts`
- `ts/tests/types/selection.test.ts`
- `ts/tests/types/where.test.ts`
- `ts/tests/types/stress.test.ts`
- `ts/tests/types/performance-baseline.json`
- `ts/scripts/check-type-performance.ts`

RED in this order:

1. `Selection<T>` is immutable, ordered, duplicate-preserving, replayable, and
   not an Array. Iterators are fresh; `toArray()` is defensive; `length` and
   negative `at()` follow readonly-array behavior.
2. One emitted `.filter(fn, thisArg?)` signature accepts only callbacks, passes
   value/index/readonly values, preserves `thisArg`, propagates exceptions, and
   returns `Selection<T>`. It has no type-guard or declarative overload;
   zero-argument and declarative calls fail declarations.
3. `.where(criteria)` uses actual class identities with generated
   `SessionWhere`, `WindowWhere`, and `PaneWhere`. `WhereOf<Client>` is `never`.
   Cross-model fields, methods, recursive path strings, invalid operators, and
   wrong values fail declarations or runtime validation.
4. Bare equality, canonical scalar operators, explicit insensitive mode,
   `AND`/`OR`/`NOT`, to-many `some`/`every`/`none`, and to-one `is`/`isNot` have
   the specified empty and null semantics.
5. Regex data accepts only `"" | "m" | "s" | "ms"` flags and the closed
   grammar in the architecture. Duplicate/reordered/unsupported flags and every
   excluded construct fail validation. Evaluation always adds internal `u` and
   adds `i` only for insensitive mode. One JSON corpus runs through Python `re`,
   emitted Node 22 JavaScript, and Bun 1.3.14; it covers astral dot matching, LF
   parity, and the recorded Unicode case-folding and multiline line-terminator
   adaptations.
6. `first`, `one`, `oneOrUndefined`, `exists`, and `count` accept optional
   criteria and pass the zero/one/many truth table with ordered duplicates.
   Multiple-match errors retain exact counts. Direct and legacy-lowered calls
   put only canonical criteria in compatibility `query` metadata.
7. All evaluation is eager over a captured complete projection and issues zero
   tmux commands. Empty relations are valid data; incomplete hydration cannot
   construct a public Selection.
8. `WhereDocumentV1` round-trips through Zod. Unknown versions, fields,
   operators, values, callbacks, `RegExp` instances, and invalid regex fail with
   stable validation codes. Version 1 accepts no field aliases and encodes only
   canonical names.
9. The sole compatibility adapter lowers `name__contains=<string>` into
   canonical `name` criteria for Session and Window. Pane, Client, every other
   double-underscore key, malformed input, wrong value, and `noeq` are rejected.
   The exported `parse_legacy_where(model, input)` is its only public consumer and
   returns a model-discriminated `WhereDocumentV1`; it never widens `.where()` or
   `.filter()`. Declaration negatives reject Pane/Client model names and passing
   the resulting document or criteria to a different model Selection.
10. The parity ledger maps zero-argument, callable, value, list, and lookup
    filtering; exact/default retrieval; both count meanings; truthiness;
    iteration; ordering; duplicates; first/index/slice/reverse/containment; and
    every remaining inherited list behavior to a named adaptation or exclusion.
    Value, list, count-value, containment, and index adaptations call model
    `.equals()` rather than JavaScript reference identity. No QueryList symbol
    or export exists.

Minimal implementation:

- Use one generic selection implementation with a generated descriptor that
  validates and compiles criteria once.
- Keep values and graph projection separate: iteration and callback filtering
  use live handles while declarative evaluation reads frozen projection data.
- Use explicit generated model interfaces and one-parameter `Selection<T>` plus
  nominal `WhereOf<T>`; do not use recursive mapped or template-path types.
- Serialize canonical data only. Callback predicates and legacy syntax never
  enter the wire schema.

Gate: pass the public scalar lookup crosswalk under Bun and Node, strict
declaration and JSON golden tests, the three-runtime regex corpus, and zero-I/O
local evaluation. Establish and gate a TS7 extended-diagnostics instantiation
baseline now. Do not export `./selection` until Task 9 proves actual-class
relations against real tmux.

Add `test:type-performance` and extend `test:types` to run it. From this task
onward, the cumulative type gate always enforces the recorded baseline.

## Task 9: Complete read-only object graph

Create:

- `ts/src/_internal/runtime/error_policy.ts`
- `ts/src/_internal/operations/server.ts`
- `ts/src/_internal/operations/session.ts`
- `ts/src/_internal/operations/window.ts`
- `ts/src/_internal/operations/pane.ts`
- `ts/src/_internal/operations/client.ts`
- `ts/tests/unit/server.test.ts`
- `ts/tests/integration/server_read.test.ts`
- `ts/tests/integration/session_read.test.ts`
- `ts/tests/integration/window_read.test.ts`
- `ts/tests/integration/pane_read.test.ts`
- `ts/tests/integration/client.test.ts`
- `ts/tests/differential/scenarios/server_reads.test.ts`
- `ts/tests/differential/scenarios/linked_windows.test.ts`
- `ts/tests/differential/scenarios/live_refresh.test.ts`
- `ts/tests/differential/scenarios/client_attachment.test.ts`
- `ts/tests/differential/scenarios/relation_where.test.ts`

Use raw tmux setup; do not implement `new_session()` merely to prepare these
tests.

RED first:

- Server constructor selectors, `cmd`, `is_alive`, and `raise_if_dead`.
- Validated point factories, complete getters, `.equals()`, and
  `refresh(): Promise<void>` for every child handle.
- Server sessions/windows/panes/clients and searches resolve ordered Selections;
  Session and Window relations/searches return Selections; singular relations
  remain nullable or singular handles.
- Pane window/session re-resolution and Client's nullable attached
  session/window/pane.
- The full accessor-policy table across missing daemon, socket, permission,
  executable, target, malformed row, and protocol errors. Read methods do not
  start a missing daemon.
- `attached_sessions()` matches exact client counts 0, 1, and 2 through the
  accessor-local `session_attached === "1"` adapter.
- `some`/`every`/`none` cover empty and populated relations; `is`/`isNot` cover
  populated and null to-one relations. Hydration failure follows the producer's
  policy before resolution; `.where()` makes zero transport calls.
- One window linked across two sessions and twice in one session preserves every
  placement, ambiguous cardinality, best-winlink selection, and deduplicated
  `linked_sessions()`.
- After external topology mutation or handle refresh, old selection membership,
  order, duplicates, and `.where()` results remain frozen. An iterated handle
  may expose its refreshed snapshot, and `.filter(fn)` observes that live handle.
  A repeated async read captures current tmux state.
- A retained pane re-resolves after `move-window`; contextual window refresh may
  select a new canonical winlink.
- Collection-consuming helpers accept generators and other `Iterable` inputs;
  they do not require arrays or Selection unless inspecting criteria.

Minimal implementation: prepare typed operations, execute through the runtime,
decode validated rows, normalize, materialize complete projections, and apply
only each producer's accessor policy.

Gate: port all read/identity cases from Server and the four child modules plus
the complete client and resolution suites. Pass unit, real-tmux, declaration,
and raw-tmux/Python/TypeScript differential tests, repeat the type-performance
gate against actual class mappings, then add `./server`, `./session`,
`./window`, `./pane`, `./client`, and `./selection` together.

## Task 10: Environment and `from_env`

Create:

- `ts/src/_internal/env.ts`
- `ts/src/_internal/environment.ts`
- `ts/tests/unit/environment.test.ts`
- `ts/tests/integration/from_env.test.ts`
- `ts/tests/differential/scenarios/from_env.test.ts`

RED first:

- Right-split `$TMUX` with comma-containing paths.
- Validate `%pane`, ignore stale exported session IDs, and resolve through the
  current pane.
- Cover unset/empty/malformed values, missing pane, dead daemon, and a moved or
  linked window.
- Port set, unset, remove, show, and get environment behavior, including hidden
  values and format expansion.

Gate: every Python `from_env` and environment test passes differentially.

## Task 11: Options and hooks

Create:

- `ts/src/options.ts`
- `ts/src/hooks.ts`
- `ts/src/_internal/options/parse.ts`
- `ts/src/_internal/options/registry.ts`
- `ts/src/_internal/hooks/parse.ts`
- `ts/src/_internal/hooks/registry.ts`
- `ts/src/_internal/sparse_array.ts`
- `ts/tests/unit/options.test.ts`
- `ts/tests/unit/hooks.test.ts`
- `ts/tests/unit/sparse_array.test.ts`
- `ts/tests/integration/options.test.ts`
- `ts/tests/integration/hooks.test.ts`
- `ts/tests/differential/scenarios/options_hooks.test.ts`

Use four witnessed cycles:

1. Scalar, sparse-array, complex, inherited, user-option, empty, and malformed
   parsing.
2. Set/unset/show option across server, session, window, and pane scopes.
3. Hook parse/show with sparse indexes and empty output.
4. Run/set/unset/set-many hooks across default and explicit scopes.

Port the complete Python option and hook suites, including exact error
distinctions, quiet behavior, append, all-index clearing, and version registries.

Gate: every supported tmux cell, then add `./options` and `./hooks`.

## Task 12: Creation, lifecycle, kill, and disposal

Extend the four operation modules and create:

- `ts/tests/integration/lifecycle.test.ts`
- `ts/tests/differential/scenarios/lifecycle.test.ts`

RED first:

- Server start/new session/kill/kill session.
- Session new window/kill.
- Window split/new pane/new window/kill.
- Pane split/new pane/kill.
- Each created handle validates a complete snapshot.
- `refresh()` preserves the handle and resolves void; mutators return the same
  handle only where Python does.
- Async disposal mirrors Python's conditional context-exit kill and is
  idempotent; runtime disposal remains separate.
- Oversized argument-only data is capped or rejected rather than redirected to
  stdin.

Gate: create, mutate, dispose, and leak tests plus lifecycle log records.

## Task 13: Session navigation and window topology

Create:

- `ts/tests/integration/session_navigation.test.ts`
- `ts/tests/integration/window_topology.test.ts`
- `ts/tests/differential/scenarios/window_topology.test.ts`

Implement through separate RED/GREEN cycles:

- Session lock/detach, last/next/previous/select window, attach, switch client,
  rename, and kill window.
- Window select pane, resize, layouts, link/unlink, rotate, respawn, swap, rename,
  move, and select.

After every topology mutation, rerun the linked-window and moved-pane resolution
scenarios. No mutation may collapse winlinks or leave stale contextual state.

## Task 14: Pane terminal I/O and geometry

Create:

- `ts/tests/integration/pane_io.test.ts`
- `ts/tests/integration/pane_capture.test.ts`
- `ts/tests/differential/scenarios/pane_io.test.ts`

Implement through narrow cycles:

- Resize and geometry helpers.
- Capture variants and overloads.
- Send keys, enter, select, title, display message, clear history, clear, reset.

Port the complete pane and capture test files. Assert actual pane output and
geometry, not only rendered argv. Cover literal input, flag-only calls, ranges,
pending/joined capture, malformed UTF-8, empty output, targeting, and warnings.

## Task 15: Server utilities and attached-client commands

Create:

- `ts/tests/integration/server_utilities.test.ts`
- `ts/tests/integration/server_clients.test.ts`
- `ts/tests/integration/server_ui.test.ts`
- `ts/tests/integration/buffers.test.ts`
- `ts/tests/differential/scenarios/client_counts.test.ts`
- `ts/tests/differential/scenarios/buffers.test.ts`

Implement through command-family cycles:

- `has_session`, `run_shell`, `wait_for`, bind/unbind/list keys, list commands.
- Server/client lock, access, refresh, suspend, detach, switch, and attach.
- Confirmation, prompt, menu, messages, prompt history, and display message.
- Set/show/delete/save/load/list buffers, `if_shell`, `source_file`, and
  `list_clients`.

Use stdin only for buffer commands that accept it. Interactive commands need a
real attached control client or TTY-backed scenario. Preserve client counts and
the Python 0.62 attached-session adapter.

## Task 16: Remaining Window and Pane operations

Create:

- `ts/tests/integration/window_advanced.test.ts`
- `ts/tests/integration/pane_advanced.test.ts`
- `ts/tests/differential/scenarios/versioned_operations.test.ts`

Implement every remaining canonical operation:

- Window/Pane display and popup variants.
- Paste buffer, pipe, copy and clock modes.
- Display panes, buffer/client/tree chooser, customize, and find window.
- Send prefix, respawn, move, join, break, swap, and remaining clear operations.

Each method needs rendered-argv validation and observable real-tmux behavior.
Exact 3.7 `break-pane`, 3.7a/b, floating pane, capture, popup, and versioned flag
cases run in their applicable cells.

## Task 17: Testing utilities and compatibility facade

Create:

- `ts/src/_internal/compat.ts`
- `ts/src/test/index.ts`
- `ts/src/test/run_root.ts`
- `ts/src/test/test_server.ts`
- `ts/src/test/control_mode.ts`
- `ts/src/test/environment.ts`
- `ts/src/test/random.ts`
- `ts/src/test/retry.ts`
- `ts/src/test/temporary.ts`
- `ts/tests/unit/compat.test.ts`
- `ts/tests/unit/test_utilities.test.ts`
- `ts/tests/types/compat.test.ts`

RED first:

- Port Python test constants, environment guard, random-name sequence, retry,
  and temporary session/window behavior.
- Port every legacy API test only after its canonical implementation exists.
- Deprecated names delegate to canonical behavior or raise the mapped
  `DeprecatedError`; they never become the implementation layer.
- Python subscription and context syntax that JavaScript cannot express is
  classified with its explicit adapter.
- Compatibility does not recreate QueryList, `.get()`, mutable indexing, or a
  declarative `.filter()` overload. The Task 8 `name__contains` adapter is the
  sole legacy lookup syntax and always lowers to canonical Where data.

Gate: every legacy, common, tmux-object, test-helper, warning, alias, and
deprecated manifest entry is classified and tested. The public fixture reuses
the supervised substrate and exposes the actual `Server` handle, logical socket
name, and observed socket path. Add `./test`; no public symbol remains planned
or unclassified.

## Task 18: Declaration, docs, differential, package, and CI closeout

Create:

- `ts/tests/types/public_surface.test.ts`
- `ts/scripts/test-package.ts`
- `ts/tests/package/packed_artifact.test.ts`
- `ts/scripts/ci/tmux_versions.ts`
- `ts/tests/unit/ci_matrix.test.ts`
- `ts/README.md`
- `ts/docs/` public usage and API examples
- `.github/actions/setup-tmux/action.yml`
- `.github/workflows/typescript.yml`
- `.github/workflows/typescript-tmux-master.yml`

Closeout sequence:

1. Compile every public import, exact callable signature, brand, readonly field,
   error, and deliberate invalid example under TypeScript 7. Inspect emitted
   declarations to prove `.filter()` has one callable signature. Negative cases
   include a QueryList import, declarative or zero-argument `.filter()`, mutable
   Selection methods, a second Selection type parameter, Client criteria,
   cross-model criteria, recursive path keys, wrong relation operators, and
   unversioned Where JSON.
2. Rerun the Task 8 TS7 extended-diagnostics instantiation baseline against the
   final public declarations; gate instantiation growth, not nondeterministic
   wall time.
3. Run executable examples against real tmux under Bun and packed Node.
4. Triangulate every mutation scenario across isolated raw-tmux, Python, and
   TypeScript sockets.
5. Change `private` to false only after the final explicit export allowlist and
   parity manifest are complete.
6. Build once and pack once with Bun into an absolute comma/space path. Compute
   its digest; run strict Publint and the ESM-only Are the Types Wrong profile on
   that path; inspect archive and source-map allowlists; install the same tarball
   with npm and Bun; then run both installs under Node and Bun with the exact
   Node 22 type lane, TS7 `skipLibCheck: false`, and a real tmux smoke. Recheck
   the digest after every consumer.
7. Implement `test-package.ts --create <artifact-dir>` for the single pack plus
   verification flow and `--verify <tarball> --sha256 <digest>` for downloaded
   artifacts. Verify mode must never build or pack. Preserve the created
   tarball for CI upload and make its digest the only future publication input.
   Do not publish or repack in this task.
8. Add the exact stable tmux CI matrix and a commit-keyed or uncached nonblocking
   upstream canary. Every CI test step receives a prepublished cleanup root and
   an always-run exact-root reaper.
9. Verify every collection producer returns Selection, every ordinary consumer
   accepts generator-backed Iterable input, criteria documents round-trip only
   with a supported version, and no package export or declaration contains
   QueryList.
10. Add the package, dead-code, full `check`, `prepack`, and `prepublishOnly`
    scripts only now that every referenced harness exists. The full check chains
    source, tooling, declaration, and type-performance checks.

Final differential scenarios include linked-window multiplicity, external live
mutation, accessor error policy, batch/group failure, literal semicolons,
framing guards, malformed bytes, cancellation after dispatch, client attachment
effects, selection snapshot stability, canonical scalar lookup behavior,
relation quantifiers, the sole `name__contains` adapter and rejection of every
other double-underscore key, option inheritance, hook sparse arrays, `from_env`,
and every version-gated field, flag, warning, and quirk.

## Final verification

From `ts/`, run in order:

1. `bun install --frozen-lockfile`
2. `bun run format`
3. `bun run check`

From the repository root, run in order:

1. `uv run ruff format .`
2. `uv run pytest`
3. `uv run ruff check . --fix --show-fixes`
4. `uv run mypy`
5. `uv run pytest`
6. `git diff --check`

Completion also requires every stable tmux cell, the current-head CI workflow,
the final leak audit, the packed-package cross-product, and a parity manifest
with no incomplete entry. A passing subset must not be called complete.
