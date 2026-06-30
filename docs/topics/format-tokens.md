(format-tokens)=

# Format-token fields

When you work with a libtmux object — {class}`~libtmux.Server`,
{class}`~libtmux.Session`, {class}`~libtmux.Window`,
{class}`~libtmux.Pane`, or {class}`~libtmux.Client` — you get a flat set
of typed string attributes that report the object's current state
straight from tmux, mirroring tmux's built-in
[FORMATS](https://man.openbsd.org/tmux.1#FORMATS) tokens (`pane_id`,
`window_zoomed_flag`, `session_name`, etc.). This is why a single
{class}`~libtmux.Pane` can hand you
{attr}`pane.pane_id <libtmux.Pane.pane_id>`,
{attr}`pane.window_id <libtmux.Pane.window_id>`, and
{attr}`pane.session_id <libtmux.Pane.session_id>` without you writing a raw tmux
command.

Most of the time you just read these attributes and move on. Not every
field holds a value on every object, though: the object's type and your
tmux version decide which fields are populated and which stay `None`.

Which fields hold a value comes down to two gates:

1. **Scope** — which kind of tmux object can provide the token. A `pane_*`
   token needs pane context, a `session_*` token needs session context, and
   so on.
2. **Version** — which tmux release first registered the token in
   `format.c`'s static table.

If either gate excludes a token, libtmux leaves the field at `None`
rather than risking a server-side fault on an older tmux. You trade an
occasional `None` check for attribute access that stays safe on every
supported version.

## Why a field is `None`

A typed field is `None` for one of three reasons:

- **Not yet introduced.** Older tmux doesn't know the token at all.
  {attr}`~libtmux.Pane.pane_dead_signal` is `None` on tmux 3.2a because
  the token landed in 3.3.
- **Wrong scope for this object.** A {class}`~libtmux.Client` row can report
  client tokens plus the client's current session/window/pane. `buffer_*`
  tokens never apply to client rows.
- **Live-only token.** Some tokens (`mouse_*`, `cursor_*`,
  `selection_*`) only resolve inside a live event context (key
  binding, copy-mode, popup) — never in a `list-*` snapshot. libtmux
  excludes them from every `-F` template.

The version map for post-3.2a tokens is small and stable. The
following are the tokens libtmux currently gates:

| Added in | Tokens |
|----------|--------|
| 3.3 | {attr}`~libtmux.Pane.pane_dead_signal`, {attr}`~libtmux.Pane.pane_dead_time` |
| 3.7 | {attr}`~libtmux.Pane.bracket_paste_flag`, {attr}`~libtmux.Pane.pane_flags`, {attr}`~libtmux.Pane.pane_floating_flag`, {attr}`~libtmux.Pane.pane_pb_progress`, {attr}`~libtmux.Pane.pane_pb_state`, {attr}`~libtmux.Pane.pane_pipe_pid`, {attr}`~libtmux.Pane.pane_x`, {attr}`~libtmux.Pane.pane_y`, {attr}`~libtmux.Pane.pane_z`, {attr}`~libtmux.Pane.pane_zoomed_flag`, {attr}`~libtmux.Pane.synchronized_output_flag` |

Everything not listed above is safe on every supported tmux (≥ 3.2a).
Fields for newer tmux tokens will be added as each supported version is
validated.

## Active child fields

Reach for {attr}`session.pane_id <libtmux.Session.pane_id>` and you get a real
pane id back, not an error. When tmux lists a parent object, it also reports
fields from that parent's active child — so the pane fields on a session row
describe the active pane in the session's current window.

```python
>>> session = server.new_session()
>>> session.pane_id == session.active_window.active_pane.pane_id
True
>>> session.window_id == session.active_window.window_id
True
```

The relationship is **one-way**. A {class}`~libtmux.Pane` carries
`window_*` and `session_*` fields for its parents, but a
{class}`~libtmux.Session` does not carry `client_*` fields because tmux cannot
infer one attached client from a session row. The `client_*` tokens only
appear on {class}`~libtmux.Client` rows returned by
{attr}`~libtmux.Server.clients`.

So read {attr}`session.pane_id <libtmux.Session.pane_id>` as "the active pane
of the session's current window," not "the session's pane id." Treat it as the
latter and the value will surprise you the moment the
{attr}`~libtmux.Session.active_window` changes.

## Inspecting which fields apply

For the rarer cases — contributors, or code that introspects libtmux's
own queries — you can ask, for a given `list-*` subcommand and tmux
version, which tokens libtmux will request. Use
{func}`libtmux.neo.get_output_format`:

```python
>>> from libtmux.neo import get_output_format
>>> fields, _ = get_output_format("list-sessions", "3.6a")
>>> 'session_id' in fields
True
>>> 'pane_id' in fields  # active pane for the listed session
True
>>> 'client_name' in fields  # client fields require list-clients
False
```

For `list-clients`, the gate widens to include `client_*` plus every
attached session/window/pane token:

```python
>>> from libtmux.neo import get_output_format
>>> fields, _ = get_output_format("list-clients", "3.6a")
>>> all(t in fields for t in ("client_name", "session_id", "pane_id"))
True
```

The result is cached per `(list_cmd, tmux_version)` pair.

## tmux version detection

You never call this directly, but it's worth knowing how the version
gate gets its answer. libtmux detects the live tmux version via
{func}`libtmux.common.get_version` and passes it through to
`get_output_format` whenever it builds a `-F` template. The result
is cached for the process lifetime; if you're swapping the `tmux`
binary mid-test, call
`libtmux.common.get_version.cache_clear()` to invalidate.

The {ref}`project` page tracks the project's minimum tmux version
(currently 3.2a); see {doc}`/project/compatibility` for the full
matrix.

## See also

- {doc}`/api/libtmux.neo` — API reference for format-field helpers
- {func}`libtmux.neo.get_output_format` — the scope and version filter
- {ref}`clients` — attached-client fields and live attachment lookups
- {doc}`/project/compatibility` — supported tmux versions
