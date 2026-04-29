(about)=

# Architecture

libtmux is a [typed](https://docs.python.org/3/library/typing.html)
abstraction layer for tmux. It builds upon tmux's concept of targets
(`-t`) to direct commands against individual sessions, windows, and panes,
and `FORMATS` — template variables tmux exposes to describe object
properties.

## Object Hierarchy

libtmux mirrors tmux's object hierarchy as a typed Python ORM:

```
Server
└── Session
    └── Window
        └── Pane
```

| Object | Child | Parent |
|--------|-------|--------|
| {class}`~libtmux.server.Server` | {class}`~libtmux.session.Session` | None |
| {class}`~libtmux.session.Session` | {class}`~libtmux.window.Window` | {class}`~libtmux.server.Server` |
| {class}`~libtmux.window.Window` | {class}`~libtmux.pane.Pane` | {class}`~libtmux.session.Session` |
| {class}`~libtmux.pane.Pane` | None | {class}`~libtmux.window.Window` |

{class}`~libtmux.common.TmuxRelationalObject` acts as the base container
connecting these relationships.

## Internal Identifiers

tmux assigns unique IDs to sessions, windows, and panes. libtmux uses
these — via {class}`~libtmux.common.TmuxMappingObject` — to track objects
reliably across state refreshes.

| Object | Prefix | Example |
|--------|--------|---------|
| {class}`~libtmux.server.Server` | N/A | Uses `socket-name` / `socket-path` |
| {class}`~libtmux.session.Session` | `$` | `$13` |
| {class}`~libtmux.window.Window` | `@` | `@3243` |
| {class}`~libtmux.pane.Pane` | `%` | `%5433` |

## Core Objects

Each level wraps tmux commands and format queries:

- {class}`~libtmux.server.Server` — entry point, manages sessions, executes raw tmux commands
- {class}`~libtmux.session.Session` — manages windows within a session
- {class}`~libtmux.window.Window` — manages panes, handles layouts
- {class}`~libtmux.pane.Pane` — terminal instance, sends keys and captures output

## Data Flow

1. User creates a `Server` (connects to a running tmux server)
2. Queries use tmux format strings ({mod}`libtmux.constants`) to fetch state
3. Results are parsed into typed Python objects
4. Mutations dispatch tmux commands via the `cmd()` method
5. Objects refresh state from tmux on demand

## Engine Layer

Command execution is routed through an engine abstraction. Three
engines ship with libtmux today:

| Engine         | Per-call cost                                    | Persistent? | Notifications |
|----------------|--------------------------------------------------|-------------|---------------|
| `subprocess`   | fork + exec + connect + parse                    | No          | No            |
| `imsg`         | open AF_UNIX socket + handshake + binary message | No          | No            |
| `control_mode` | one stdin write + parser dispatch                | **Yes**     | **Yes**       |

- `subprocess` is the default engine and preserves the traditional
  `tmux` CLI-backed behavior.
- `imsg` is a binary engine that talks directly to the tmux server socket.
  It resolves versioned protocol handlers through a registry, with the
  current implementation stored in `libtmux.engines.imsg.v8` and keyed as
  protocol version `8`.
- `control_mode` keeps one long-lived `tmux -C` subprocess and routes
  every command through its stdin/stdout pipes. A daemon reader thread
  drives a `selectors.DefaultSelector` loop and feeds a state-machine
  parser. Returns `Block` events (matched `%begin`/`%end`/`%error`) to
  the run-queue; `%subscription-changed` events are routed to user
  subscribers. See {doc}`engines` for usage and the subscription API.
- All socket-level transport stays selector-based; no asyncio runtime
  is required.
- The recommended public API is string-first, with overloads preserving
  typed validation for valid engine and protocol combinations:

  ```python
  from libtmux import Server
  from libtmux.engines import ImsgProtocolVersion

  server = Server(engine="imsg", protocol_version=ImsgProtocolVersion.V8)
  ```

- The subprocess backend stays the default and can be selected explicitly:

  ```python
  server = Server(engine="subprocess")
  ```

- The persistent control-mode backend is opt-in:

  ```python
  server = Server(engine="control_mode")
  ```

- `EngineSpec` remains available for normalization and advanced callers, but
  is not the primary DX path:

  ```python
  from libtmux.engines import EngineSpec

  assert EngineSpec.imsg(8).protocol_version == 8
  ```

## Module Map

| Module | Role |
|--------|------|
| {mod}`libtmux.server` | Server connection and session management |
| {mod}`libtmux.session` | Session operations |
| {mod}`libtmux.window` | Window operations and pane management |
| {mod}`libtmux.pane` | Pane I/O and capture |
| {mod}`libtmux.common` | Base classes, command execution |
| {mod}`libtmux.engines` | Engine registry and backend implementations |
| {mod}`libtmux.neo` | Modern dataclass-based query interface |
| {mod}`libtmux.constants` | Format string constants |
| {mod}`libtmux.options` | tmux option get/set |
| {mod}`libtmux.hooks` | tmux hook management |
| {mod}`libtmux.exc` | Exception hierarchy |

## Naming Conventions

tmux commands use dashes (`new-window`). libtmux replaces these with
underscores (`new_window`) to follow Python naming conventions.

## References

- [tmux man page](https://man.openbsd.org/tmux.1)
- [tmux source code](https://github.com/tmux/tmux)
