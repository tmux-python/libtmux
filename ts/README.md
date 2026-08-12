# libtmux

Typed, Bun-first TypeScript control of [tmux](https://github.com/tmux/tmux).

Acquire an immutable snapshot of a tmux server, query it with declarative
criteria, and drive sessions, windows, and panes with a fully typed API.

Requires tmux 3.2a or newer, and Node 22+ or Bun 1.3.14+.

```console
$ bun add libtmux
```

## Quickstart

```ts
import { Server } from "libtmux";

const server = new Server();

const session = await server.newSession({ name: "work" });
const editor = await session.newWindow({ name: "editor" });
await editor.split();

const snapshot = await server.snapshot();
const window = snapshot.windows.where({ name: "editor" }).one();

console.log(window.panes.length); // 2
await window.panes.at(0)?.sendKeys("echo hello");
```

## Snapshots

`snapshot()` is the only call that talks to tmux. It acquires the whole server
in one round of commands, and everything reachable from the result resolves
locally.

```ts
const snapshot = await server.snapshot();

snapshot.sessions; // Selection<Session>
snapshot.windows; // Selection<Window>
snapshot.panes; // Selection<Pane>
snapshot.clients; // Selection<Client>
```

A snapshot never changes. Acquire again to see later state, and the earlier
snapshot keeps reporting its own instant, so a value you captured cannot shift
underneath you.

```ts
const before = await server.snapshot();
await server.newSession({ name: "later" });

before.sessions.length; // unchanged
(await server.snapshot()).sessions.length; // includes "later"
```

To advance one handle in place rather than re-acquiring everything, call
`refresh()`. It re-reads only that handle and keeps its placement, so a window
linked into two sessions stays on the one you resolved.

## Watching

A snapshot answers what is true now. `server.watch()` answers what changed, over
one persistent `tmux -C` connection rather than a command per read.

```ts
await using events = server.watch();

for await (const event of events) {
  if (event.kind === "window-add") console.log("opened", event.windowId);
  if (event.kind === "output") process.stdout.write(event.data);
}
```

Events are a discriminated union, so `event.kind` narrows the rest of the shape
with no cast. Names are tmux's own, without the leading `%`, and a notification
this version does not model arrives as `{ kind: "unknown", name, args }` rather
than being dropped.

The stream is an `AsyncDisposable`, so `await using` ends the tmux process when
the scope exits, including on a thrown error. A consumer that falls behind gets
its oldest events dropped rather than an unbounded buffer; `events.dropped`
counts them and `bufferSize` sets the bound.

tmux sends a control client no pane output until it attaches, so watching
attaches to a session. A server with no sessions has nothing to watch.

`await using` needs `Symbol.asyncDispose`, so a consumer's `lib` includes
`ESNext.Disposable` alongside its ECMAScript target. `events.close()` is the
same operation for a project that cannot add it.

## Querying

`.where()` takes declarative, serializable criteria. `.filter()` takes an
ordinary predicate. They are never overloaded into each other.

```ts
snapshot.panes.where({ currentCommand: "vim" });
snapshot.panes.filter((pane) => pane.currentCommand?.startsWith("v") === true);
```

Criteria support equality, string operators, `AND`/`OR`/`NOT`, regular
expressions as data, and relation quantifiers:

```ts
snapshot.sessions.where({
  AND: [
    { name: { startsWith: "prod" } },
    { windows: { some: { name: { regex: { pattern: "^log", flags: "" } } } } },
  ],
});

snapshot.windows.where({ session: { is: { name: "work" } } });
```

Matching is case-sensitive unless you say otherwise:

```ts
snapshot.sessions.where({ name: { contains: "API", mode: "insensitive" } });
```

A `Selection` is immutable, ordered, and replayable. It is `Iterable`, but it is
not an `Array`:

```ts
selection.length;
selection.at(0);
selection.toArray();
[...selection];
```

Cardinality helpers each accept optional criteria:

```ts
selection.first({ name: "work" });
selection.one({ name: "work" }); // NoMatchError / MultipleMatchesError
selection.oneOrUndefined({ name: "work" });
selection.exists({ name: "work" });
selection.count({ name: "work" });
```

## Relations

Relations are plain properties, because the data was already acquired. Reading
one issues no tmux command.

```ts
session.windows; // Selection<Window>
session.panes; // Selection<Pane>
window.session; // Session | undefined
window.linkedSessions; // every session a window is linked into
pane.window;
client.pane;
```

`Server` accessors are the async ones, because they acquire:

```ts
await server.sessions();
await server.windows();
```

## Field names

Handles read in idiomatic TypeScript. tmux's own token names stay available
under `format`, which is also where you reach fields the shortened names do not
cover.

```ts
pane.id; // pane_id
pane.currentCommand; // pane_current_command
window.index; // window_index
session.name; // session_name

pane.format.pane_current_command;
```

Criteria are camelCase too, and serialize to tmux's stable spellings so a stored
query stays readable by other tools:

```ts
snapshot.panes.where({ title: { contains: "log" } });
// serializes to {"where":{"pane_title":{"contains":"log"}}}
```

A criterion is spelled like the handle accessor it filters, so a pane reads
`pane.currentCommand` and filters on `currentCommand`. Only the serialized name
is fixed by the schema. A field keeps its prefix in the rare case where dropping
it would shadow a relation: `sessionWindows` is a window count, `windows` is the
windows themselves.

Fields that carry one value for the whole server — `version`, `pid`,
`socketPath` — are readable on a handle but are not criteria, since filtering
rows by one would match all of them or none.

## Options and hooks

```ts
await session.setOption("status-left", "[work] ");
(await session.showOptions()).get("status-left");
await session.unsetOption("status-left");

await server.setHook("after-new-window", "display-message created");
await server.showHooks();
```

Window and pane scopes report only what was set on them, never inherited
values.

## Errors

A failing tmux command raises `TmuxCommandError`, which carries its parts so you
can branch without parsing a message:

```ts
import { TmuxCommandError } from "libtmux";

try {
  await pane.capture();
} catch (error) {
  if (error instanceof TmuxCommandError) {
    error.args; // the argument vector
    error.exitCode;
    error.stderr; // tmux's own lines
    error.target; // the -t target, when there was one
  }
}
```

An unreachable server raises rather than reading as empty, so an empty result
means exactly one thing. Ask without raising when you need to:

```ts
await server.isAlive(); // false for a missing daemon, socket, or binary
await server.raiseIfDead(); // the assertion form
```

## Running inside tmux

```ts
import { Session } from "libtmux";

const session = await Session.fromEnv();
```

The pane is authoritative: `$TMUX` carries a session id that goes stale when a
pane moves, so the session is resolved through `$TMUX_PANE`.

## Consumers

Two working consumers live in this repository:

- `consumers/mcp` — an MCP server exposing tmux through this library.
- `consumers/workspace` — a tmuxp-shaped workspace builder. Applying a
  workspace twice converges the running session rather than duplicating it.

## Examples

See `examples/`. Every example is executed by the integration suite.

## License

MIT
