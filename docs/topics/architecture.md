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

## Module Map

| Module | Role |
|--------|------|
| {mod}`libtmux.server` | Server connection and session management |
| {mod}`libtmux.session` | Session operations |
| {mod}`libtmux.window` | Window operations and pane management |
| {mod}`libtmux.pane` | Pane I/O and capture |
| {mod}`libtmux.common` | Base classes, command execution |
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
