(clients)=

# Clients

A tmux {term}`Client` is an attached terminal — the side of the tmux
connection a user sees. The same tmux server can host many clients at
once (one per `$ tmux attach` from different terminals), and each
client has its own view of the active session, window, and pane.

{class}`~libtmux.Client` is the libtmux object for that attached terminal.
It sits outside the
{class}`~libtmux.server.Server` → {class}`~libtmux.session.Session` →
{class}`~libtmux.window.Window` → {class}`~libtmux.pane.Pane`
ownership hierarchy: a client *points at* a Session/Window/Pane it is
currently viewing, but is not owned by them.

Most code reads a client's current attachment once and branches on it;
the details about staleness and refresh below rarely matter in practice.

## View, not identity

You rarely need this detail unless you're tracking a client across
several user commands, but it's worth understanding why certain fields
go stale. The fields that look like foreign keys — `client_session`,
`session_id`, `window_id`, and `pane_id` — are snapshots of where the
client was attached when libtmux read it. They go stale the instant the
user runs `switch-client`, `select-window`, or `select-pane`. The
client's *identity* is `client_name` (the tty path on Unix), which is
stable for the lifetime of the attachment.

| Field | What it is | Stable? |
|-------|------------|---------|
| `client_name` | tty path tmux assigned at attach time | Yes — identity |
| `session_id` / `window_id` / `pane_id` | the client's *attached view* when read | No — snapshot |
| `client_session` | session name of the same attached view | No — snapshot |
| `client_pid` / `client_tty` / `client_user` | terminal-level facts | Yes — identity-adjacent |

## Live attachment with `attached_*`

When you want the *current* attachment — not the snapshot — use the
three live properties. Each calls {meth}`~libtmux.Client.refresh` to
query the current state (one tmux round-trip) and then resolves the
typed Session/Window/Pane it's viewing. This costs a little — you're
asking for the live state — but you get the current view in return:

```python
>>> with control_mode() as ctl:
...     client = server.clients.get(client_name=ctl.client_name)
...     attached = client.attached_session
>>> attached is not None
True
```

{attr}`~libtmux.Client.attached_window` follows the client's attached
session to its
{attr}`~libtmux.session.Session.active_window`, and
{attr}`~libtmux.Client.attached_pane` follows that window to its
{attr}`~libtmux.window.Window.active_pane`. The three properties chain,
so reading {attr}`~libtmux.Client.attached_pane` does one
`list-clients` refresh, then walks to the active window and its active pane.

```python
>>> with control_mode() as ctl:
...     client = server.clients.get(client_name=ctl.client_name)
...     pane = client.attached_pane
>>> pane is None or pane.pane_id.startswith('%')
True
```

## Iterating attached clients

If you need to find or filter clients, you iterate over or query the
server's client collection. {attr}`~libtmux.Server.clients` returns a
{class}`~libtmux._internal.query_list.QueryList` of every client tmux
reports through `list-clients`. Filter or `get()` it the same way as
{attr}`~libtmux.Server.sessions`:

```python
>>> with control_mode() as ctl:
...     attached = [
...         c
...         for c in server.clients
...         if c.client_name == ctl.client_name
...     ]
>>> bool(attached)
True
```

For filtering clients, use `server.clients.filter(...)` or iterate over
{attr}`~libtmux.Server.clients` directly; see {ref}`native-filtering` if
you want tmux's native format-based filtering on sessions, windows,
panes, and buffers.

## When `attached_*` returns `None`

When a client detaches or its view becomes stale, the `attached_*`
properties return `None` so you can branch on truthiness without a
`try`/`except` block. This happens in three cases:

- the snapshot `session_id` is empty (e.g. the client is at the tmux
  command prompt rather than viewing a session),
- the snapshot `session_id` no longer names a live session (the
  session was killed between the client read and access), or
- the client has detached and `list-clients` no longer reports it.

Calling {meth}`~libtmux.Client.refresh` directly still raises
{exc}`~libtmux.exc.TmuxObjectDoesNotExist` on a detached client; the
`attached_*` properties catch that case and return `None` for you.

## See also

- {doc}`/api/libtmux.client` — autodoc reference
- {ref}`about` — where `Client` fits in the overall object model
- {ref}`native-filtering` — tmux-native filtering for sessions, windows, panes,
  and buffers
