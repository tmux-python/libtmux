# libtmux TypeScript architecture

Status: accepted implementation architecture after renewed TypeScript, Bun/Node,
and safety review of the Task 4 daemon-generation correction. The lifecycle,
killed-worker, supervisor-signal, packed-artifact, and collection probes are
recorded in the spike findings.

Compatibility baseline: Python libtmux 0.62.0 and tmux 3.2a through 3.7b.

## Outcome

The package will expose libtmux's live `Server`, `Session`, `Window`, `Pane`,
and `Client` vocabulary through explicit asynchronous methods. Each live
handle owns a replaceable frozen snapshot, while an internal normalized graph
keeps tmux entities separate from session-local winlinks.

Async collection producers return immutable `Selection<T>` values. Native
callback filtering remains `.filter(fn)`; serializable declarative filtering is
`.where(criteria)` with generated model-specific criteria.

One Node-compatible transport contract executes literal argument vectors.
`execute_batch()` means ordered independent requests. It never means a tmux
semicolon group. Bun supplies package management and the primary test runner;
published runtime code uses Node built-ins and runs unchanged under Node and
Bun.

## Decision drivers

The design is ordered by these requirements:

1. Preserve observable Python behavior, including ordering, duplicates,
   refresh identity, exceptions, and accessor-specific error policy, while
   classifying the required TypeScript collection adaptations explicitly.
2. Represent tmux's graph without collapsing linked-window context.
3. Keep all I/O explicit and cancellable.
4. Validate external data once, at the process and serialization boundaries.
5. Leave a stable operation and reference seam for future execution engines.
6. Publish declarations that remain fast and useful in strict TypeScript.
7. Test real tmux processes with isolated, recoverable fixtures.

## Architecture bakeoff

Scores use parity 30, tmux correctness 25, TypeScript ergonomics 15, engine
extensibility 15, and packaging and testability 15.

| Contender                                                     | Parity | tmux | TypeScript | Engines | Package/test |  Total |
| ------------------------------------------------------------- | -----: | ---: | ---------: | ------: | -----------: | -----: |
| Direct Python mirror with mutable models and Array subclasses |     24 |   10 |          7 |       7 |           10 |     58 |
| Stateless commands over immutable snapshot trees              |     14 |   16 |         14 |      12 |           14 |     70 |
| Live handles over a normalized graph and frozen snapshots     |     28 |   24 |         13 |      14 |           14 | **93** |

The third contender wins. It grafts the Python mirror's names and observable
behavior, the snapshot design's validation and serialization, and the
engine-oriented design's immutable requests, stable references, and explicit
outcomes.

The rejected designs each lose a required invariant. A direct mirror couples
every object to subprocess details and misrepresents batching. A snapshot tree
cannot preserve live-handle identity or a window linked through several
session/index pairs.

## System boundaries

```text
Public live facade
  Server -> Session -> Window -> Pane
       \-> Client
          |
          v
Runtime context -> operation preparation -> transport -> tmux
          |                                  |
          v                                  v
Frozen snapshots <- normalized entities/edges <- validated format rows
```

The layers have one-way responsibilities:

- The public facade preserves libtmux behavior and raises libtmux errors.
- The runtime binds an immutable connection, capabilities, logger, and
  transport.
- Operation preparation produces immutable, literal command requests.
- The transport owns process lifetime and returns command results without
  interpreting tmux object semantics.
- The codec parses raw bytes into validated rows.
- The graph preserves entities, winlinks, ordering, and contextual duplicates.
- Frozen snapshots contain data only. They never contain transports, promises,
  loggers, or credentials.

## Package layout

The source tree mirrors Python's public modules while giving TypeScript-only
mechanics a private boundary.

```text
ts/
  src/
    index.ts
    server.ts
    session.ts
    window.ts
    pane.ts
    client.ts
    common.ts
    neo.ts
    options.ts
    hooks.ts
    constants.ts
    formats.ts
    exc.ts
    selection.ts
    test/
    _generated/
    _internal/
      codec/
      graph/
      operations/
      runtime/
      selection/
      transport/
  tests/
    unit/
    integration/
    differential/
    package/
    types/
  scripts/
  docs/development/
```

The root export contains the five object classes and stable supporting types.
Explicit subpath exports cover every public module above, including `./test`
and `./selection`. Nothing below `src/_internal` is exported. There is no
`QueryList` export or alias.

## Runtime and command execution

### Immutable connection context

`TmuxConnection` is an immutable value containing the executable and exactly
one connection selector: default server, socket name, or socket path. Config,
color, and environment choices are immutable as well. Public methods cannot
mutate a server's connection after construction.

A runtime context combines that connection with a transport, a logger, and a
capability snapshot. Capabilities are measured from the connected daemon and
include its raw version string. An upgraded client binary may still be talking
to an older daemon, so `tmux -V` alone is insufficient.

Binding is lazy. Constructing a `Server` or listing against a server that has
not started does not start a daemon merely to measure capabilities. Live daemon
identity uses fields such as `#{pid}` and `#{start_time}` when available, plus a
runtime-local epoch that is invalidated after observed loss or reconnect.

Prepared operations carry the capability fingerprint used to prepare them.
Execution rejects a stale fingerprint rather than assuming flags and format
fields still apply. The runtime checks capabilities and epoch immediately before
preparation or execution, but does not claim atomicity across subprocesses.

### Literal requests

Command requests contain a readonly argument vector. They do not contain a
shell string. Structural sequences, references, and dependencies are separate
types; a literal `";"` remains a literal argument.

The transport uses `node:child_process.spawn` with `shell: false`, drains stdout
and stderr concurrently, accepts `AbortSignal`, and supports stdin where the
tmux command has a native stdin operand. Buffer loading through `-` uses stdin;
argument-only data remains subject to tmux's client-message bound and requires
a command-specific cap, reduction, split, or rejection.

On cancellation, the transport closes stdin, sends SIGTERM, waits a bounded
grace period, sends SIGKILL if necessary, awaits `close`, and drains or discards
both output streams. It records whether spawn and command submission occurred.
Cancellation before submission is a transport failure; cancellation after
submission without a terminal response has an unknown effect. Runtime-specific
`AbortError` shapes are not public API.

`execute()` returns a raw command result for zero and nonzero tmux exits. A
spawn, pipe, timeout, cancellation, or protocol failure is a transport error
that records whether dispatch definitely did not occur or may have reached
tmux. Cancellation bounds local waiting; it does not imply rollback or
non-execution. The facade decides when a nonzero result becomes a named libtmux
exception.

`execute_batch()` accepts independent requests and returns correlated outcomes
in input order. Its reference implementation executes sequentially and attempts
later independent requests after a known failure. Delivery is recorded as
`not_started`, `written`, `replied`, or `indeterminate`. Operation status is
`complete` only for a zero tmux exit, `failed` for a nonzero result or a
pre-dispatch error, `skipped` for an intentionally unattempted request, and
`unknown` when dispatch may have reached tmux without a terminal result.
Cancellation never leaves an unread response on a reusable connection.

Semicolon folding, persistent control mode, and imsg are outside the first
implementation. A later transport may optimize independent execution only if
it preserves the same result correlation and state semantics.

### Public command results

`Server.cmd()` and object-level `cmd()` methods expose Python-compatible `cmd`,
`stdout`, `stderr`, and `returncode` fields. The `has-session` special case
copies the first stderr line to stdout when stdout is empty while retaining
stderr. The internal transport retains bytes until framing and decoding finish.
A package-owned incremental UTF-8 decoder emits Python-compatible per-byte
backslash escapes, including malformed sequences split across stream chunks.

## Live handles, snapshots, and identity

`Session`, `Window`, `Pane`, and `Client` are stable live handles. Direct scalar
getters synchronously read the current frozen snapshot and never perform I/O.
Relations, listings, and searches are explicit async methods such as
`await session.windows()` and resolve fully materialized `Selection<Model>`
values.

`refresh()` fetches and validates a complete replacement snapshot, swaps it
atomically on the retained handle, and resolves `void`. Relation calls may
construct distinct handles; no daemon-wide handle interning is promised.
Mutators return the same handle where Python does. A killed object produces the
corresponding object-gone error; a dead daemon remains a connection or tmux
command failure.

A selection freezes its membership, order, contextual duplicates, and an
evaluation projection from the normalized graph. Refreshing a contained live
handle or changing tmux cannot alter those properties or later `.where()`
results. Repeating the async producer obtains a new projection. `.where()`
evaluates the captured projection and never reads mutable handle snapshots or
performs hidden I/O. `.filter()` receives the iterated live handles and may
therefore observe a refreshed handle snapshot. Collection immutability does not
freeze the live handles returned by iteration.

Direct subprocess hydration may require several independent list commands. The
projection is a validated capture, not a daemon transaction; it records one
capability fingerprint and epoch, applies the accessor's topology-race policy,
and either resolves complete or fails. It never claims all rows came from one
instant.

Branded `$session`, `@window`, and `%pane` strings prove only kind and syntax.
Public boundaries accept a valid raw string but statically reject a string with
the wrong existing brand. A live logical reference separately contains an
opaque connection alias and runtime-local daemon epoch. The epoch changes after
observed daemon loss or reconnect.

Synchronous decoding validates serialized shape and restores ID brands. Async
`bind(runtime)` verifies the connection alias and current daemon epoch. A
serialized reference never contains an executable, environment, or socket path.
Capability and epoch checks are stale-detection aids, not transactional
guarantees: direct subprocess transport has an unavoidable probe-to-command
race.

Python-compatible `.equals()` mirrors each owner's explicit behavior.
`Server.equals()` compares socket name and socket path. Session, Window, and
Pane compare only their respective raw tmux IDs, including Python's cross-server
and cross-winlink equality wart. Client has no owner override in Python, so its
dataclass equality compares the exact class, Server equality, and every captured
public snapshot field while ignoring TypeScript-only bookkeeping. Selection
membership and contextual duplicates are never deduplicated merely because two
values are `.equals()`. Durable-reference equality separately compares
connection alias, epoch, entity kind, and entity ID. JavaScript `===` remains
instance identity. Every public model declares the same non-overloaded surface:
`equals(other: unknown): boolean`.

### Winlinks are edges

A window entity is global to a daemon. Its placement in a session is a winlink
identified by the daemon generation, session ID, and window index, with the
window ID attached. Active flags and contextual session fields live on that
edge.

Consequences are part of the public contract:

- Server-wide window and pane listings preserve contextual duplicates.
- One window may occur in several sessions or several indexes in one session.
- A contextual `Window` carries both its window reference and optional winlink
  reference.
- `.one({ window_id: ... })` can be ambiguous on a server-wide selection.
- `from_window_id()` asks tmux for its canonical target selection instead of
  scanning and deduplicating a graph snapshot.
- Refreshing a contextual window targets its `@id` and may replace its winlink
  context with tmux's newly selected canonical placement.
- Retained pane handles re-resolve their session after a window move.
- `linked_sessions()` returns an ordered selection, deduplicates sessions in
  tmux order, and tolerates a target disappearing between its two reads.

## Selection and declarative criteria

`Selection<T>` is an eager, immutable, ordered, duplicate-preserving local
collection. It is an iterable wrapper, never an Array subclass, proxy,
decorated array, or `QueryList` alias. Each call to `[Symbol.iterator]()` returns
a fresh iterator. `length`, `at()`, and `toArray()` provide explicit access;
`toArray()` returns a defensive array copy whose mutation cannot affect the
selection.

The emitted public contract has one semantic signature per method:

```ts
export interface Selection<T> extends Iterable<T> {
  readonly length: number;
  [Symbol.iterator](): IterableIterator<T>;
  at(index: number): T | undefined;
  toArray(): T[];
  filter(
    predicate: (value: T, index: number, values: readonly T[]) => unknown,
    thisArg?: unknown,
  ): Selection<T>;
  where(criteria: WhereOf<T>): Selection<T>;
  first(criteria?: WhereOf<T>): T | undefined;
  one(criteria?: WhereOf<T>): T;
  oneOrUndefined(criteria?: WhereOf<T>): T | undefined;
  exists(criteria?: WhereOf<T>): boolean;
  count(criteria?: WhereOf<T>): number;
}
```

`.filter()` requires one callback and preserves the runtime callback contract
of `Array.prototype.filter`: value, index, readonly values, `thisArg`, eager
order, and exception propagation. It has no declarative overload and does not
promise type-guard narrowing. `.where()` accepts only serializable declarative
data and evaluates synchronously and eagerly.

The public collection has one type parameter. `WhereOf<T>` uses the models'
private nominal-kind contract to map only `Session`, `Window`, and `Pane` to
explicit generated `SessionWhere`, `WindowWhere`, and `PaneWhere` interfaces.
`WhereOf<Client>` and unknown model types are `never`; those selections retain
callback filtering and criteria-free cardinality. Generation uses field
metadata rather than recursive mapped types over `keyof T`, so methods never
become criteria and cyclic relations do not inflate downstream declarations.

Bare scalar values mean equality. Generated public model fields are strings or
null, so their filter objects expose `equals`, `contains`, `startsWith`,
`endsWith`, `in`, `notIn`, `regex`, and the sole case toggle
`mode: "insensitive"`. The default is case-sensitive. An explicit `null`
matches a captured null field; other operators never match a null or missing
left-hand value. This explicit-null behavior is a TypeScript extension over
Python QueryList's missing/`None` handling.

Regular expressions are `{ pattern, flags }` data, never `RegExp` instances.
`flags` is the closed canonical union `"" | "m" | "s" | "ms"`; duplicate,
reordered, `i`, `g`, `y`, `u`, `v`, and `d` flags are rejected. Case mode is
expressed only by `mode`. The evaluator always adds internal ECMAScript `u`, and
adds internal `i` only for insensitive mode; neither internal flag serializes.
The accepted search grammar is literals, escaped regular-expression
metacharacters, `.`, ASCII character-class literals and ranges, capturing and
noncapturing groups, alternation, `^`/`$`, and greedy `*`, `+`, `?`, `{m}`,
`{m,}`, and `{m,n}` quantifiers. Backreferences, lookaround, named or
conditional groups, inline flags, shorthand/property classes, class set
operations, atomic groups, and possessive or lazy quantifiers are rejected.
TypeScript uses ECMAScript Unicode search semantics. Python
`re.IGNORECASE` case-folding differences and multiline handling of CR,
U+2028, and U+2029 are recorded adaptations. The shared corpus includes astral
dot matching, LF parity, and those explicit divergence cases under Python,
Node 22, and Bun 1.3.14. Non-regex insensitive string operators use ECMAScript
`toLowerCase`; any Python `.lower()` divergences use the same adaptation ledger.

Generated criteria use stable wire field names and support:

- array-valued `AND`, `OR`, and `NOT`, with empty identities true, false, and
  true;
- `some`, `every`, and `none` for to-many relations, where an empty relation
  yields false, true, and true;
- `is` and `isNot` for to-one relations, including explicit `null`;
- generated nested criteria, not string paths or recursive template types.

A generated model descriptor validates criteria and compiles them once into an
evaluator over the selection's frozen projection. Relation predicates traverse
captured graph adjacency. A public producer whose `Where` type exposes a
relation must materialize that relation before resolving. Hydration failure is
handled by that producer's accessor policy; no resolved public selection has an
unknown relation state. `QueryValidationError` is reserved for invalid criteria
or serialized schema data.

Cardinality is explicit. Optional criteria are applied eagerly to the frozen
projection before counting; order and contextual duplicates are retained.

| Method             | Zero matches   | One match | Many matches                     |
| ------------------ | -------------- | --------- | -------------------------------- |
| `first()`          | `undefined`    | first     | first in frozen order            |
| `one()`            | `NoMatchError` | value     | `MultipleMatchesError`           |
| `oneOrUndefined()` | `undefined`    | value     | `MultipleMatchesError`           |
| `exists()`         | `false`        | `true`    | `true`                           |
| `count()`          | `0`            | `1`       | exact duplicate-preserving count |

Multiple-match errors retain the exact count. The compatibility `query` field
is `{}` when criteria are absent and the canonical criteria object when called
directly. Criteria produced by `parse_legacy_where()` also report the lowered
canonical criteria; the legacy spelling never enters an evaluator error or wire
document. No method silently treats an ambiguous result as one.

Canonical criteria serialize as a versioned `WhereDocumentV1` containing a
model name and `where` data. Version 1 has no aliases because no earlier
TypeScript wire field has shipped. A future schema migration may register an
alias only for a field name present in an earlier released schema; encoding
continues to emit one canonical spelling. Zod validates decoding at the
boundary. Unknown versions, fields, operators, invalid values, callbacks, and
`RegExp` objects fail with stable query validation codes. The package exposes
the document for future engine reuse; it does not ship an MCP or CLI query
facade in version 1.

The sole legacy edge adapter accepts exactly one key,
`name__contains=<string>`, for a Session or Window descriptor that exposes the
canonical `name` field, and lowers it to `{ name: { contains: value } }`. Pane,
Client, and other descriptors reject it. The legacy key never appears in
`WhereOf<T>` or serialized output. Every other double-underscore key, including
valid Python lookup names and the accidental `noeq`, is rejected.

The exported `parse_legacy_where(model, input)` is this adapter's only public
consumer. `model` is `"session" | "window"`; `input` is untrusted data; and the
result is a model-discriminated `WhereDocumentV1` whose `where` member can be
passed to the matching Selection. It is a boundary parser, not a second
filtering method. Validation errors may identify the rejected input path, but
successful output retains no legacy spelling.

```ts
export type WhereDocumentV1 =
  | { readonly version: 1; readonly model: "session"; readonly where: SessionWhere }
  | { readonly version: 1; readonly model: "window"; readonly where: WindowWhere }
  | { readonly version: 1; readonly model: "pane"; readonly where: PaneWhere };

export function parse_legacy_where<M extends "session" | "window">(
  model: M,
  input: unknown,
): Extract<WhereDocumentV1, { readonly model: M }>;
```

The parity ledger treats Python's private `QueryList` implementation as source
evidence for behavior exposed by public collection accessors, not as a public
class to reproduce. Its behavior clusters have explicit adaptations:

| Python observable behavior           | TypeScript adaptation                                        |
| ------------------------------------ | ------------------------------------------------------------ |
| iteration, order, duplicates         | `Iterable`, fresh iterators, preserved membership            |
| `len(rows)` / truthiness             | `length` or `count()` / `exists()`                           |
| callable `filter(fn)`                | callback-only `filter(fn)`                                   |
| zero-argument `filter()`             | new equivalent `where({})` or `filter(() => true)` Selection |
| value or list `filter(matcher)`      | predicate calling model `.equals()`                          |
| Session/Window/Pane lookup filtering | generated canonical `where()` criteria                       |
| Client lookup filtering              | callback `filter()` because `WhereOf<Client>` is `never`     |
| `get()` exactly-one behavior         | `one()`                                                      |
| `get(default=...)`                   | `oneOrUndefined()` plus an explicit undefined fallback       |
| inherited `count(value)`             | `.equals()` predicate followed by cardinality `count()`      |
| first item / slicing / reverse       | `first()` or `at(0)` / `toArray()` operations                |
| containment and `index(value)`       | `.equals()` predicate or `findIndex()` on `toArray()`        |
| concatenation, repetition, copy      | explicit `toArray()` operations                              |
| mutation and item assignment         | excluded; selections are immutable                           |
| direct indexing and list methods     | excluded from `Selection`; use named APIs above              |
| `items()` / `pk_key`                 | excluded private machinery                                   |
| QueryList equality                   | excluded defective private implementation                    |

Python's public Session, Window, and Pane scalar lookup behavior maps to
canonical string filters as follows; this is evaluator parity, not additional
legacy syntax:

| Python lookup                | Canonical criteria                           |
| ---------------------------- | -------------------------------------------- |
| bare, `eq`, `exact`          | bare value or `equals`                       |
| `iexact`                     | `equals` with insensitive mode               |
| `contains`, `icontains`      | `contains`, with mode for the latter         |
| `startswith`, `istartswith`  | `startsWith`, with mode for the latter       |
| `endswith`, `iendswith`      | `endsWith`, with mode for the latter         |
| `in` with list RHS           | `in`                                         |
| `nin` with list RHS          | `notIn`                                      |
| `in` / `nin` with string RHS | `contains` / top-level `NOT` plus `contains` |
| `regex`, `iregex`            | `regex`, with mode for the latter            |

Public model criteria expose no list- or mapping-valued scalar fields. Python's
list membership, mapping-key membership, structural list/map equality, and the
unsupported-combination behavior of private lookup helpers are therefore
recorded internal exclusions rather than claimed evaluator behavior.
Downstream APIs produce `Selection<T>` and accept `Iterable<T>` unless they
require criteria inspection.

## Formats and validation

One format registry is the source of truth for field name, scope, tmux version,
raw representation, snapshot destination, and scalar filter domain. It
generates runtime Zod schemas, snapshot declarations, getters, format requests,
scalar `Where` fields, and parity inventory entries. A small explicit relation
registry generates cyclic relation criteria and projection traversal without
deriving them from `keyof` model classes.

Criteria metadata distinguishes raw tmux tokens from stable public wire names.
The Session `session_name` token and Window `window_name` token both generate
their model-local canonical `name` field; this is an initial mapping, not a
rename alias. Pane has no canonical `name`, and Client has no generated Where
type.

Raw strings remain authoritative. Derived numeric and boolean views cannot
collapse empty, missing, malformed, or unsupported values into one state.
Capability floors use ordered tmux versions and normally carry into later patch
releases. A separate exact-version quirk registry handles exceptions such as a
`break-pane` defect present only in raw version `3.7`.

The initial `FormatCodec` is explicitly probabilistic. It parses bytes using
per-request start, field, and end guards; validates the expected field count for
each completed frame; validates the list kind's primary identity (`$`, `@`, `%`,
or `client_name`); applies the version-selected field set; detects literal
unknown format tokens; and runs Zod validation. Detected ambiguity fails as a
protocol error. It is never returned as an empty collection.

The codec does not claim a known record count or collision-free framing. A
retry, when requested by the caller, is an explicit new relation read that may
observe different state; it is not a transparent parser action. Guards are
correctness sentinels, not a security boundary.

Codec selection is capability-driven. tmux versions with argument escaping may
use it after differential tests prove equivalence. No codec assumes that newline
or a fixed Unicode character is absent from user-controlled data.

Generated public raw properties always exist as `string | null`. Empty strings
remain empty, version-unsupported fields are `null`, and malformed or missing
required row data aborts refresh. This complete-snapshot representation is a
manifested adaptation from Python's field-by-field update behavior.

## Errors, warnings, and logs

Stable library errors preserve Python's distinctions between no match, multiple
matches, missing objects, dead servers, invalid targets, options and hooks,
command failures, and missing executables. `NoMatchError` extends the
Python-compatible `ObjectDoesNotExist`; `MultipleMatchesError` extends
`MultipleObjectsReturned`; and `QueryValidationError` carries a stable code and
wrapped cause. Zod errors are wrapped; Zod's own error type is not public API.

The observed Python 0.62.0 compatibility profile keeps error leniency above the
transport:

| Accessor                                                | Recognized command/transport failure                                        | Schema/protocol failure |
| ------------------------------------------------------- | --------------------------------------------------------------------------- | ----------------------- |
| `Server.sessions()`, `clients()`, `attached_sessions()` | Empty selection for mapped `LibTmuxException`, including missing executable | Propagate               |
| `Server.windows()`, `panes()`, and server searches      | Empty only for a recognized missing/dead daemon                             | Propagate               |
| Session/window relations and searches                   | Propagate                                                                   | Propagate               |
| `Window.linked_sessions()`                              | Empty on either listing failure; skip vanished sessions                     | Propagate               |
| Point lookup                                            | Translate only a recognized missing target                                  | Propagate               |

Arbitrary JavaScript exceptions that are not mapped library failures propagate.
When a producer needs several independent reads to complete its evaluation
projection, its accessor policy applies to the operation as a whole. It never
returns a partially hydrated selection; schema and protocol failures still
propagate.

The logger is a small injected interface, not a dependency-specific public
type. Stable scalar tmux context fields accompany useful events. stdout and
stderr arrays are debug-only. Warnings pass through an injectable sink so tests
can assert them without global interception.

## API conventions

- Classes and TypeScript type names use PascalCase.
- Python-facing methods, parameters, and result fields use snake_case.
  Collection vocabulary retains JavaScript and Prisma spellings such as
  `toArray`, `oneOrUndefined`, `startsWith`, and `isNot`; camelCase aliases are
  not added elsewhere.
- Public enum member names and values match Python exactly. Erasable readonly
  constant objects and derived union types replace native TypeScript enums.
  ECMAScript names such as `Symbol.asyncDispose` and native callback parameters
  such as `thisArg` retain their standard spelling.
- I/O methods always return promises. Scalar snapshot getters are synchronous.
- Collection producers return `Selection<T>`. Collection consumers accept
  `Iterable<T>` unless they need a `Where` document or captured projection.
- Keyword-heavy Python signatures become one options object after any natural
  leading positional value.
- Child-handle construction goes through validated async factories. `Server`
  remains directly constructible.
- `Server`, `Session`, `Window`, and `Pane` expose idempotent `dispose()` and
  `Symbol.asyncDispose` aliases that mirror Python context exit by conditionally
  killing the represented tmux object. `Client` is not disposable.
- Runtime disposal closes only a transport owned by that runtime and never kills
  a tmux object. Injected transports are borrowed unless ownership is explicitly
  transferred.
- Public functions and methods have explicit exported return types.

## Packaging and tooling

The npm package is named `libtmux`. It is ESM-only, requires Node 22 or newer
and Bun 1.3.14 or newer, and publishes JavaScript, declarations, and source maps
from `dist`. Source maps use `inlineSources: true`, relative `sources`, no
`sourceRoot`, and complete `sourcesContent`; packed tests reject absolute or
unsafe paths. A source is unresolved when its map path is absolute, escapes the
virtual package root, lacks a same-index `sourcesContent` entry, or names content that does
not match its embedded source; absence of the physical `.ts` file from the
tarball is intentional. Declaration maps are omitted while source files are
absent from the tarball. No CommonJS or Bun-specific condition is advertised.
Source imports include emitted `.js` extensions.

The package contract includes `packageManager: "bun@1.3.14"`, matching Node and
Bun engine floors, `main`, `types`, `files`, `sideEffects: false`, and
`trustedDependencies: []`. Every code export maps `types`, then `import`, then
`default` to matching `dist` files. There are no wildcard, source, `require`,
`bun`, private, or `dist/*` exports.

The explicit export allowlist is:

```text
.
./server
./session
./window
./pane
./client
./common
./neo
./options
./hooks
./constants
./formats
./exc
./selection
./test
./package.json
```

Bun owns installation, the lockfile, scripts, and primary tests. Runtime source
contains no `Bun.*` or `bun:*` imports. Zod 4 is the only runtime dependency.
The declaration lane pins an exact Node 22 `@types/node` release and the package
contract rejects another major. Tooling and tests pin `@types/bun` 1.3.14 to the
Bun floor. Development gates use TypeScript 7, Oxlint with
`oxlint-tsgolint`, Oxfmt, Publint, Are the Types Wrong, and Knip.

TypeScript 7's `tsc` is authoritative for checking and emitting. Declaration
fixtures use `tsc --noEmit`, literal exact-type helpers, and
`@ts-expect-error`; the build gate also inspects actual TS7 declaration emit.
No build or test step requires TypeScript's JavaScript compiler API. TSTyche is
excluded until it supports TypeScript 7.

`test-node.ts` accepts `--node <absolute-executable>` and
`--expect-major <major>`, queries that executable before running scenarios, and
rejects a mismatch. Without `--node`, it resolves `LIBTMUX_NODE22` and then the
`node` on `PATH` to an absolute path, but still requires major 22. Floor CI
always passes its provisioned absolute executable explicitly. Every scenario is
emitted JavaScript executed by that Node process; Bun is only the controller.

Compiler gates include `strict`, `NodeNext`, `verbatimModuleSyntax`,
`isolatedDeclarations`, `isolatedModules`, `erasableSyntaxOnly`,
`exactOptionalPropertyTypes`, `noUncheckedIndexedAccess`,
`ESNext.Disposable`, and no `skipLibCheck`. The build includes only `src/**`
with Node types; Bun test types cannot leak into declarations. A separate
`tsconfig.tooling.json` typechecks `scripts/**/*.ts`, ordinary tests, fixtures,
and support code with pinned Bun and Node types. It excludes negative
declaration fixtures and the deliberately invalid type-aware-lint fixture.

The required scripts are:

```json
{
  "build": "bun run generate:check && tsc -p tsconfig.build.json",
  "format": "oxfmt --write .",
  "format:check": "oxfmt --check .",
  "generate": "bun scripts/generate-formats.ts --write",
  "generate:check": "bun scripts/generate-formats.ts --check",
  "lint": "oxlint . --deny-warnings --report-unused-disable-directives && bun scripts/check-type-aware-lint.ts",
  "typecheck": "tsc -p tsconfig.json --noEmit",
  "typecheck:tooling": "tsc -p tsconfig.tooling.json --noEmit",
  "test:unit": "bun test --parallel=4 --no-orphans tests/unit",
  "test:integration": "bun scripts/run-integration-tests.ts",
  "test:differential": "bun scripts/run-differential-tests.ts",
  "test:node": "bun run build && bun scripts/test-node.ts --expect-major 22",
  "test:type-performance": "bun scripts/check-type-performance.ts",
  "test:types": "tsc -p tests/types/tsconfig.json --noEmit && bun run test:type-performance",
  "test:package": "bun run build && bun scripts/test-package.ts --create .artifacts/package",
  "dead-code": "knip",
  "test": "bun run test:unit && bun run test:integration && bun run test:differential",
  "check": "bun run format:check && bun run lint && bun run typecheck && bun run typecheck:tooling && bun run test && bun run test:node && bun run test:types && bun run test:package && bun run dead-code",
  "prepack": "bun run build",
  "prepublishOnly": "bun run check"
}
```

Type-aware Oxlint augments, but does not replace, `tsc --noEmit`. Its checked-in
configuration enables the TypeScript, Node, Promise, and Unicorn plugins;
correctness and performance categories are errors; `typeAware` is true; and
experimental `typeCheck` is false. An ignored fixture directory has its own
`tsconfig` and a known `typescript/no-floating-promises` violation. A dedicated
harness requires the exact diagnostic and nonzero exit, proving
`oxlint-tsgolint` is active instead of merely installed.

## Real-tmux fixture

Each integration test owns one normal auto-daemonized tmux server through an
explicit `-S` socket path. The controller creates and publishes a short run root
before spawning Bun. Each fixture retries an atomic
`mkdir(<run-root>/<candidate>, 0o700)` on `EEXIST`; the reserved basename is its
unique logical socket name and `<reservation>/s` is its socket. Ownership is
registered through exclusive creation before the first tmux command. The
fixture rejects a socket path that exceeds the conservative Unix-domain byte
limit, queries `#{socket_path}`, and asserts the observed path matches its
registration.

Socket occupancy is not daemon ownership. Before the run root is published, the
supervisor resolves the trusted tmux controller to an absolute path and
snapshots its file identity in owner protocol version 2. At fixture entry, the
fixture synchronously copies and freezes caller options, the launch-only wrapper
reference, and the base environment; it never rereads them or `process.env`.
After reservation returns the winning socket path, the fixture constructs and
freezes the UUID generation, derived random environment name and value, and
complete literal bootstrap argv. It persists that `launching` record before
spawn. Only the bootstrap request receives the generation overlay; readiness,
validation, ordinary commands, control clients, and cleanup use the snapshotted
base environment without it. A missing or replaced controller path fails
closed.

A newly auto-daemonized tmux inherits both its process environment and its
initial global tmux environment from the bootstrap client. A later client does
not add the random variable to the global environment. Environment names and
values use a fixed ASCII-safe grammar. The generation is a collision-resistant
provenance marker, not a secret; guarantees against a foreign socket winner
assume cooperating, non-colluding same-UID processes and a launch wrapper that
only delays, forwards, or fails. A process that reads or alters the protected
record or launch environment, or colludes with the wrapper, is out of scope.

The bootstrap is one literal tmux command list:
`start-server ; if-shell -F <generation-condition> <new-session> <mismatch>`.
`start-server` is the nonmutating `CMD_STARTSERVER` command on tmux 3.2a through
3.7b. The true branch is the only `new-session`; the false branch emits one
randomized mismatch frame and performs no mutation. The list is an internal
fixture protocol, not generic semicolon folding or `executeBatch` behavior.

Fixture protocol version 3 is a closed discriminated union:

| Phase       | Required authority                                                            |
| ----------- | ----------------------------------------------------------------------------- |
| `reserved`  | owner-bound controller identity and socket path; no generation or daemon data |
| `launching` | unchanged base plus exact generation name/value and complete bootstrap argv   |
| `running`   | unchanged launch snapshot plus validated daemon and socket identities         |

`launching` is evidence, not authority. Capability-bound transition functions
reread the current record under a reservation-path lock; there is no generic
phase setter. `launching` returns to `reserved` only after locally observing
transport delivery `not_started` and an absent socket. Nonzero, partial,
indeterminate, or missing evidence remains a preserved `launching` leak. The
owner, fixture, and cleanup-journal protocols are bumped together. Version-1
owner records and version-2 fixture or journal records are never migrated,
normalized, signalled, unlinked, or removed.

The bootstrap is accepted only after all of these agree across one bounded
validation window:

- the strict success frame, canonical positive decimal PID, and absence of the
  randomized mismatch frame;
- PID, process-start, comm, resolved executable identity, and the complete
  snapshotted bootstrap argv;
- one exact NUL-framed generation entry in `/proc/<pid>/environ`;
- a fresh unattached `-N` controller call whose PID-guarded true branch runs
  `show-environment -g <name>` and returns the exact global name/value; and
- the registered Unix-socket inode before and after that guard.

The launch executable used by fault-injection tests is distinct from the
trusted controller executable used for validation and cleanup. A wrapper that
connects to a server already occupying the reservation fails generation
validation at the bootstrap gate, before `new-session`. Cleanup preserves that
server, socket, reservation, and record without changing the foreign server.

Cleanup has three layers:

1. The fixture's `finally` block kills the server, waits for the client, unlinks
   the socket, and removes its reservation.
2. A Bun worker hook reaps fixtures abandoned by a failed test.
3. An outer supervisor reaps the run directory after normal exit, assertion
   failure, timeout, SIGINT, SIGTERM, or a killed worker.

The supervisor enumerates only its exact published run directory. Cleanup is
idempotent and uses exact socket paths. Stale preflight reaps only a run root
whose recorded owner PID and process-start identity are no longer live; it never
scans or kills arbitrary tmux sockets. A `launching` record may acquire cleanup
authority only through a strict `-N` exact-socket discovery frame for an
untrusted candidate PID. Cleanup then validates its process identity, resolved
executable, complete bootstrap argv, and process generation before a second
PID-guarded global-environment query inside one socket-inode sandwich. It
promotes the record to `running` before signalling or journaling. A missing,
inaccessible, malformed, or mismatched socket or candidate remains a leak.

A `running` record already carries that authority. Accessible cleanup
immediately revalidates process generation, identity, resolved executable, and
complete bootstrap argv, then uses one connected exact-PID-and-generation
guarded `kill-server`; mismatch output preserves the foreign socket and does not
fall through to that pathname again.
Inaccessible cleanup uses pidfd and revalidates identity, complete argv, and the
generation entry before opening the pidfd, after opening it, before TERM, and
before KILL. Missing, malformed, or mismatched generation evidence is never
signalled or unlinked. A replacement-socket mismatch may reap only the
independently authenticated intended PID and must preserve the replacement
socket and authority record. A supervisor or host killed with SIGKILL cannot
run cleanup; CI therefore has an always-run reaper that receives the published
root before the test step.

A version-3 cleanup journal binds the exact version-3 record inode and content
digest. It accepts only `reserved` with no socket authority or `running` with
the record's exact socket identity, and rejects `launching`. Recovery verifies
the record before any socket mutation.

A cleanup failure fails an otherwise passing test. When the test already
failed, its failure remains primary and the cleanup failure is reported. Normal
child completion preserves its exit status. Child signal termination is
preserved as the same signal or `128 + signal`. On SIGINT or SIGTERM, the
supervisor forwards the signal, escalates after a bound, reaps, then self-signals
or exits 130 or 143. Cleanup can replace only an otherwise-zero status. The
final leak audit fails if any registered daemon, socket, or reservation remains.

The fixture exposes the `Server`, logical socket name, observed socket path,
bounded raw execution, explicit cleanup, and an async-disposal hook. Parallel
integration execution is capped at four workers and uses Bun's `--no-orphans`
as defense in depth. Pane-shell readiness uses a generated bounded
`tmux wait-for -S` handshake, never a sleep or a daemon-only listing. Dedicated
cases cover comma/space paths, parsing `$TMUX` from the right, owner PID reuse,
inaccessible-socket fallback, daemon identity or generation mismatch, a foreign
server winning the pre-launch socket race, and corrupt or older-version identity
records. No cleanup signal is sent unless PID, process start, launch argv, and
daemon generation all match. A pre-authority launch returns to `reserved` only
for delivery `not_started` with an absent socket; every other uncertain startup
preserves evidence instead of guessing. Tests that exercise cleanup precedence
use a child that reads the published root, changes and verifies the owner-record
mode, then exits 7. The child status remains primary while cleanup is reported.
A clean missing-executable case and direct thrown-value identity matrix cover
their separate boundaries; an event-loop polling race is not accepted as
evidence.

## Test architecture

The acceptance suite has five independent tracks:

- Unit tests for requests, parsing, schemas, Selection, generated criteria,
  errors, options, hooks, graph normalization, and serialization.
- Real-tmux integration tests for every public operation.
- Differential scenarios that seed twin sockets and compare raw tmux, Python
  libtmux, and TypeScript results.
- Declaration tests for exact callable signatures, brands, invalid
  combinations, emitted declarations, and compiler performance.
- A packed-tarball cross-product installed with npm and Bun, then executed under
  both Node and Bun without workspace fallback.

`test-package.ts --create <artifact-dir>` resolves the directory absolutely,
creates one tarball with
`bun pm pack --ignore-scripts --filename <absolute-tarball>` in a path
containing a comma and space, and writes its digest. Create mode then runs the
same verification as `--verify <tarball> --sha256 <digest>`. Verify mode never
builds or packs: it runs `publint --strict <tarball>` and
`attw <tarball> --profile esm-only`, checks the archive and every source map
against allowlists, installs that same tarball into separate private ESM
consumers with npm and Bun, and executes each installation under both Node and
Bun. Every export resolves below the consumer's `node_modules`; TS7 checks
declarations with the exact Node 22 type lane and `skipLibCheck: false`; and a
representative real-tmux create/query/kill flow runs. Both modes recheck the
digest after every consumer. Create mode preserves the artifact for CI upload;
publication uses that exact artifact rather than repacking the source tree.

Blocking compatibility covers `3.2a`, `3.3`, `3.3a`, `3.4`, `3.5`, `3.5a`,
`3.6`, `3.6a`, `3.7`, `3.7a`, and `3.7b`. Release candidates are excluded from
the supported matrix. The scheduled `master` canary resolves upstream HEAD
before cache lookup and keys the build by that commit, or runs uncached. It is
nonblocking and never substitutes for the newest stable release.

Static gates run once. The full packed npm/Bun installation and Node/Bun runtime
cross-product runs at the Bun 1.3.14 and Node 22 floors. Current-runtime jobs
download the same digest-verified artifact rather than packing again. Real-tmux
integration and differential gates run in every tmux cell. CI creates and
exports the cleanup root before tests so an `if: always()` reaper can find it
after supervisor death.

Hard differential cases include linked-window multiplicity, live external
mutation, accessor error policy, grouped-command failure, independent batch
correlation, literal semicolons, awkward bytes and separators, cancellation
after write, client attachment effects, option inheritance, hook sparse arrays,
and version-gated fields and flags.

## Parity control

A machine-readable parity manifest has a schema version, a baseline object, and
four separately validated record sets: Python public runtime symbols, observable
behavior clusters, TypeScript extensions, and deliberate internal exclusions.
The baseline records Python version, tag, and full resolved commit. Python
type-only aliases and unstable internal symbols are outside the runtime symbol
inventory; private QueryList source appears only as pinned evidence on behavior
clusters owned by public collection accessors.

Symbol rows carry the Python owner and TypeScript target. Behavior rows carry
public accessor owners and a named adaptation. Extension rows carry the new
TypeScript surface and rationale. Exclusion rows carry pinned evidence and a
concrete boundary reason. Every applicable row names unit, declaration, and
real-tmux evidence, compatibility status, and syntax adaptation. Implementation
work cannot mark a component complete while an activated record lacks required
evidence.

Validation fails clearly when a shallow checkout lacks the baseline object or
the tag resolves to a different commit. Inventory regeneration updates only the
derived symbol boundary, preserves all maintained fields for unchanged keys and
all manual record sets byte-for-byte, rejects removed keys without explicit
boundary-change approval, and writes atomically. Independent required and
forbidden sentinels plus audited per-section digests prevent the generator and
manifest from jointly redefining completeness.

One observed defect is recorded rather than generalized: Python
`attached_sessions` effectively matches `session_attached == "1"` through an
unsupported `noeq` suffix and a permissive nested-key fallback. It returns no
session when two clients are attached. Under the Python 0.62 compatibility
profile, `attached_sessions()` reproduces that result through an accessor-local
`session_attached === "1"` adapter. The compatibility edge parser rejects
`noeq`; canonical `Where` data has no such operator. The documented
count-greater-than-zero behavior remains a deliberate future compatibility
decision, not an unmarked change.

Full package completion requires clean format, lint, type, unit, integration,
differential, declaration, package, and Python regression gates. A passing
feature subset is not completion.

## Future engine seam

The first release ships only direct async execution. Its internal operation
values already separate immutable input, prepared request, output schema,
effects, and logical output references. Stable node/output references survive
plan insertion and reordering; positional array slots do not.

Prepared plans bind to immutable capabilities and daemon generation. Serialized
plans contain versioned data and stable references, never handles or transports.
Future query and plan facades compile into the same operations rather than
redefining command behavior.

`Selection.where()` is synchronous evaluation over captured local data. It is
not a deferred query plan and does not become one implicitly. A future remote
query facade may accept the same versioned criteria document, but it compiles
operations separately and returns a new selection.

Operations requiring strict generation safety need an in-daemon guard. They
remain unsupported when the direct subprocess transport cannot provide one.

## Disqualifying cases

The implementation is rejected if it exports `QueryList`, overloads
`.filter()` with declarative data, mutates an existing selection, performs tmux
I/O during local filtering, accepts criteria for the wrong model, serializes an
unversioned filter, collapses a contextual duplicate, or treats many matches as
one. Transport, codec, cancellation, fixture-leak, and package-consumer
violations described above are equally blocking.

## Source basis

- [libtmux object model and refresh behavior](https://github.com/tmux-python/libtmux/blob/v0.62.0/docs/topics/architecture.md)
- [libtmux traversal contracts](https://github.com/tmux-python/libtmux/blob/v0.62.0/docs/topics/traversal.md)
- [libtmux filtering and linked-window behavior](https://github.com/tmux-python/libtmux/blob/v0.62.0/docs/topics/filtering.md)
- [libtmux private collection behavior source](https://github.com/tmux-python/libtmux/blob/v0.62.0/src/libtmux/_internal/query_list.py)
- [libtmux format registry and version gates](https://github.com/tmux-python/libtmux/blob/v0.62.0/src/libtmux/neo.py)
- [libtmux resolution scenarios](https://github.com/tmux-python/libtmux/blob/v0.62.0/tests/test_resolution.py)
- [libtmux error hierarchy](https://github.com/tmux-python/libtmux/blob/v0.62.0/src/libtmux/exc.py)
- [tmux 3.2a command queue](https://github.com/tmux/tmux/blob/3.2a/cmd-queue.c)
- [tmux 3.7b command queue](https://github.com/tmux/tmux/blob/3.7b/cmd-queue.c)
- [tmux 3.7b format expansion](https://github.com/tmux/tmux/blob/3.7b/format.c)
- [tmux 3.7b argument escaping](https://github.com/tmux/tmux/blob/3.7b/arguments.c)
- [tmux 3.7b client message bound](https://github.com/tmux/tmux/blob/3.7b/compat/imsg.h)
