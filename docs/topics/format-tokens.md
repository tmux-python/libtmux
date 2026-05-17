(format-tokens)=

# Format-Token Fields

Every libtmux object — {class}`~libtmux.Server`,
{class}`~libtmux.Session`, {class}`~libtmux.Window`,
{class}`~libtmux.Pane`, {class}`~libtmux.Client` — exposes a flat set
of typed string attributes named after tmux's
[FORMATS](https://man.openbsd.org/tmux.1#FORMATS) tokens
(`pane_id`, `window_zoomed_flag`, `client_theme`, etc.). These are
declared once on {class}`libtmux.neo.Obj`, and the same dataclass
backs every concrete object — which is why
`pane.pane_id`, `pane.window_id`, and `pane.session_id` all work on a
single {class}`~libtmux.Pane` instance.

Two gates decide which fields actually hold a value on a given object:

1. **Scope** — which tmux struct field the token's format-callback
   dereferences. A `pane_*` token reads `ft->wp`, a `session_*` token
   reads `ft->s`, and so on.
2. **Version** — which tmux release first registered the token in
   `format.c`'s static table.

If either gate excludes a token, libtmux leaves the field at `None`
rather than risking a server-side fault on an older tmux.

## Why a field is `None`

A typed field is `None` for one of three reasons:

- **Not yet introduced.** Older tmux doesn't know the token at all.
  {attr}`~libtmux.Pane.pane_dead_signal` is `None` on tmux 3.2a because
  the token landed in 3.3.
- **Wrong scope for this object.** A {class}`~libtmux.Client` row only
  emits client-scope tokens directly; cross-scope tokens reach it via
  the cascade described below, but `buffer_*` tokens never do.
- **Live-only token.** Some tokens (`mouse_*`, `cursor_*`,
  `selection_*`) only resolve inside a live event context (key
  binding, copy-mode, popup) — never in a `list-*` snapshot. libtmux
  excludes them from every `-F` template.

The version map for post-3.2a tokens is small and stable. The
following are the tokens libtmux currently gates:

| Added in | Tokens |
|----------|--------|
| 3.3 | `pane_dead_signal`, `pane_dead_time` |

Everything not listed above is safe on every supported tmux (≥ 3.2a).
Typed fields for tokens tmux added in 3.4 / 3.5 / 3.6 and the
forward-looking set from tmux master will land in a follow-up
shipment; see the {ref}`changelog` for the deferral note.

## The downward cascade

tmux fills its format context downward when a query specifies a
parent: `c->session` then `s->curw` then `wl->window->active`. That's
why pane-scope tokens have meaningful values on a session row —
they resolve to the session's current window's active pane.

```python
>>> session = server.new_session()
>>> session.pane_id == session.active_window.active_pane.pane_id
True
>>> session.window_id == session.active_window.window_id
True
```

The cascade is **one-way**. A {class}`~libtmux.Pane` carries
`window_*` and `session_*` because the parent fills in for the child,
but a {class}`~libtmux.Session` does not carry `client_*` — tmux has
no reverse cascade for clients. The `client_*` tokens only hydrate on
{class}`~libtmux.Client` rows (returned by
{attr}`~libtmux.Server.clients`, which queries `list-clients`).

If you treat `session.pane_id` as "the session's pane id" (rather
than "the active pane of the session's current window") you will be
surprised when the active window changes. That distinction is called
out in {class}`libtmux.neo.Obj`'s docstring.

## Inspecting which fields apply

Use {func}`libtmux.neo.get_output_format` to ask, for a given
`list-*` subcommand and tmux version, exactly which tokens libtmux
will emit in the `-F` template:

```python
>>> from libtmux.neo import get_output_format
>>> fields, _ = get_output_format("list-sessions", "3.6a")
>>> 'session_id' in fields
True
>>> 'pane_id' in fields  # via downward cascade
True
>>> 'client_name' in fields  # client scope is the cascade exception
False
```

For `list-clients`, the gate widens to include `client_*` plus every
downward-cascadable token:

```python
>>> from libtmux.neo import get_output_format
>>> fields, _ = get_output_format("list-clients", "3.6a")
>>> all(t in fields for t in ("client_name", "session_id", "pane_id"))
True
```

The result is memoized per `(list_cmd, tmux_version)` pair, so
repeated calls are free.

## Tmux version detection

libtmux detects the live tmux version via
{func}`libtmux.common.get_version` and passes it through to
`get_output_format` whenever it builds a `-F` template. The result
is cached for the process lifetime; if you're swapping the `tmux`
binary mid-test, call
`libtmux.common.get_version.cache_clear()` to invalidate.

The {ref}`project` page tracks the project's minimum tmux version
(currently 3.2a); see {doc}`/project/compatibility` for the full
matrix.

## See also

- {class}`libtmux.neo.Obj` — the dataclass that declares every field
- {func}`libtmux.neo.get_output_format` — the scope+version gate
- {ref}`clients` — Client is the cascade exception
- {doc}`/project/compatibility` — supported tmux versions
