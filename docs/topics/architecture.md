(about)=

# Architecture

When you use libtmux, you work through a hierarchy of typed Python
objects — {class}`~libtmux.server.Server`, {class}`~libtmux.session.Session`,
{class}`~libtmux.window.Window`, and {class}`~libtmux.pane.Pane` — each a
proxy for the tmux entity it represents. You navigate from one to the
next (a server's sessions, a session's windows, a window's panes), and
every method you call turns into a tmux command directed at that exact
object.

You don't need anything on this page to use the API; the objects and
their methods work out of the box. This is reference material for when
you're curious how libtmux tracks those objects, keeps their identities
stable across refreshes, and lays out the code underneath. Skim the
first section and stop whenever you've seen enough.

Under the hood, libtmux is a [typed](https://docs.python.org/3/library/typing.html)
abstraction layer built on two tmux primitives: targets (`-t`), which
direct a command at an individual session, window, or pane, and
`FORMATS`, the template variables tmux exposes to describe each object's
properties.

## Object hierarchy

libtmux mirrors tmux's object hierarchy as a typed Python ORM, so the
parent-child relationships you know from tmux carry over directly into
the objects you hold:

```
Server
├── Session
│   └── Window
│       └── Pane
└── Client (attached view)
```

| Object | Child | Parent |
|--------|-------|--------|
| {class}`~libtmux.server.Server` | {class}`~libtmux.session.Session`, {class}`~libtmux.client.Client` | None |
| {class}`~libtmux.session.Session` | {class}`~libtmux.window.Window` | {class}`~libtmux.server.Server` |
| {class}`~libtmux.window.Window` | {class}`~libtmux.pane.Pane` | {class}`~libtmux.session.Session` |
| {class}`~libtmux.pane.Pane` | None | {class}`~libtmux.window.Window` |
| {class}`~libtmux.client.Client` | None | {class}`~libtmux.server.Server` |

{class}`~libtmux.common.TmuxRelationalObject` acts as the base container
connecting these relationships.

One object breaks the ownership chain: {class}`~libtmux.Client` is a
*view*, not a child. Each attached terminal points at the
Session/Window/Pane it is currently displaying, but is not owned by
them — so its view can change the moment a user switches sessions. See
{ref}`clients` for the view-vs-identity distinction.

## Internal identifiers

When tmux state changes, libtmux needs a way to recognize that the same
window is still the same window. tmux assigns each session, window, and
pane a unique ID for exactly this, and libtmux holds onto it — via
{class}`~libtmux.common.TmuxMappingObject` — to track objects reliably
across state refreshes rather than relying on names or indexes that
shift around.

| Object | Prefix | Example |
|--------|--------|---------|
| {class}`~libtmux.server.Server` | N/A | Uses `socket-name` / `socket-path` |
| {class}`~libtmux.session.Session` | `$` | `$13` |
| {class}`~libtmux.window.Window` | `@` | `@3243` |
| {class}`~libtmux.pane.Pane` | `%` | `%5433` |

## Core objects

These are the five classes you'll actually hold and call methods on.
Each level wraps the tmux commands and format queries for its tier of
the hierarchy:

- {class}`~libtmux.server.Server` — entry point, manages sessions, executes raw tmux commands
- {class}`~libtmux.session.Session` — manages windows within a session
- {class}`~libtmux.window.Window` — manages panes, handles layouts
- {class}`~libtmux.pane.Pane` — terminal instance, sends keys and captures output
- {class}`~libtmux.client.Client` — attached terminal viewing a session, window, and pane

## Data flow

Every interaction follows the same round-trip: you act on a Python
object, libtmux talks to tmux, and the result comes back as more typed
objects. Reading state and changing it both cost a tmux call, which is
why an object can go stale and why you refresh it rather than trust a
cached value indefinitely.

1. User creates a `Server` (connects to a running tmux server)
2. Queries use tmux format strings ({mod}`libtmux.constants`) to fetch state
3. Results are parsed into typed Python objects
4. Mutations dispatch tmux commands via the `cmd()` method
5. Objects refresh state from tmux on demand

## Module map

The codebase splits along the same hierarchy: one module per tier, plus
shared plumbing. The first block is what you import and use day to day;
the second is lower-level and mostly of interest to contributors or
deeper integrations.

| Module | Role |
|--------|------|
| {mod}`libtmux.server` | Server connection and session management |
| {mod}`libtmux.session` | Session operations |
| {mod}`libtmux.window` | Window operations and pane management |
| {mod}`libtmux.pane` | Pane I/O and capture |
| {mod}`libtmux.client` | Attached-client view and live-attachment lookup |
| {mod}`libtmux.common` | Base classes, command execution |

The remaining modules are advanced — reach for them only when the core
objects don't cover your case:

| Module | Role |
|--------|------|
| {mod}`libtmux.neo` | Modern dataclass-based query interface |
| {mod}`libtmux.constants` | Format string constants |
| {mod}`libtmux.options` | tmux option get/set |
| {mod}`libtmux.hooks` | tmux hook management |
| {mod}`libtmux.exc` | Exception hierarchy |

## Naming conventions

tmux commands use dashes (`new-window`). libtmux replaces these with
underscores (`new_window`) to follow Python naming conventions.

## References

- [tmux man page](https://man.openbsd.org/tmux.1)
- [tmux source code](https://github.com/tmux/tmux)
