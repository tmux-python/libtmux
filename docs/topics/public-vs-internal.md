# Public vs internal API

You can import anything from the `libtmux` namespace and build on it: those
names are the public API — documented, and changed only through a deprecation
process announced ahead of time. (libtmux is pre-1.0, so a minor version can
still carry a breaking change; pin a version when you need to lock things
down.) See the {doc}`public API reference </project/public-api>` for the
stability policy. Anything with a
leading underscore in its module path — `libtmux._internal.*`,
`libtmux._vendor.*` — is implementation detail that can change without warning.
If you only reach for the public API, that's the whole story, and you can stop
reading here.

## The boundary

The rule is mechanical: if you can import a name without a leading underscore
anywhere in its module path, it's public. The table maps each import prefix to
exactly what you can count on.

| Import path | Status | Stability |
|-------------|--------|-----------|
| `libtmux.*` | Public | Covered by [deprecation policy](../project/public-api.md) |
| `libtmux._internal.*` | Internal | No guarantee — may break between any release |
| `libtmux._vendor.*` | Vendored | Not part of the API at all |

The authoritative list of what's stable lives in
{doc}`Public API </project/public-api>`.

## Why the split

Staying on the public API buys you a predictable migration path: when a public
name changes, it goes through a deprecation process first — a warning for at
least one release, documented in the changelog — rather than vanishing without
notice. (libtmux is pre-1.0, so a minor version can still carry a breaking
change; pin a version when you need to lock things down.) Reaching into an
internal module buys you none of that — a refactor of
{mod}`~libtmux._internal.query_list` ships with no deprecation cycle, so an import
that works today can break on the very next release. That freedom is the point: internal modules let the library iterate on
implementation details without dragging downstream users through a migration for
each one.

The same line keeps the public surface intentionally small. Every public module
is a commitment to maintain, so internal modules earn promotion only through
proven stability and real user demand.

## What `_internal/` contains

The `_internal/` package holds the machinery the public objects run on —
implementation details you never need to understand to use libtmux:

- {mod}`~libtmux._internal.query_list` — the filtering engine behind
  {meth}`.filter() <libtmux._internal.query_list.QueryList.filter>` and
  {meth}`.get() <libtmux._internal.query_list.QueryList.get>` on collections
- {mod}`~libtmux._internal.dataclasses` — base dataclass utilities used by the ORM objects
- {mod}`~libtmux._internal.constants` — internal constants not meaningful to end users
- {mod}`~libtmux._internal.sparse_array` — the sparse-index mapping behind indexed hooks and options
- `libtmux._internal.control_mode` — spawns a real `tmux -C attach-session`
  client so this project's own tests have one to exercise; see below

These are documented in {ref}`internals` for contributors, but downstream
projects should not import from them.

## libtmux has no streaming API

There is no event stream: nothing in libtmux calls you back when a window
opens, a pane's process exits, or output arrives. `ControlMode`
(`libtmux._internal.control_mode.ControlMode`) looks like it might be one —
it spawns a `tmux -C attach-session` client, tmux's own control-mode
protocol — but it decodes none of that protocol. It exists so tests can
assert against a real attached client (`Server.list_clients()` needs one to
list, `display_popup()` needs one to run a popup's command against); reading
its `stdout` further is not something this class does or was built for.

Given that, keeping it internal is not a placeholder for a public version
later — it is not a partial streaming API with a rough edge, it is not a
streaming API at all, and calling it one would promise a decoder that isn't
there. If a real control-mode client (`%output`, `%window-add`,
`%session-changed`, and the rest of tmux's event stream, actually parsed)
becomes a deliverable, it starts as a new module, not a promotion of this
one — a stability statement can't retroactively apply to code that already
shipped without one. Until then, this is where a reader looking for
"streaming" or "async" in libtmux should stop looking, and reach instead for:

- **Polling.** `Session.windows`, `Window.panes`, and `Server.sessions`
  re-query tmux on every access — nothing is cached. Wrap a check in
  {func}`~libtmux.test.retry.retry_until` (also public, despite living under
  `libtmux.test`) to wait for a condition rather than a fixed sleep. This is
  the pattern the rest of the library is built around, including its own
  test suite.
- **`Pane.pipe()`.** The closest thing to real streaming here:
  {meth}`~libtmux.Pane.pipe` wraps `pipe-pane`, handing a pane's raw output
  to an external command as tmux produces it, without libtmux in the loop
  at all.
- **Hooks.** {mod}`~libtmux.hooks` runs a tmux command when a server-side
  event fires — `window-linked`, `pane-died`, and the rest of the table.
  It is still tmux invoking a command, not a Python callback, but it is
  genuinely event-driven rather than polled.

None of the three is async, and neither is anything else in libtmux: the
library has no `asyncio` integration anywhere in `src/`. Every call blocks
on a subprocess; `Server.timeout` and {meth}`~libtmux.Server.cmd`'s
per-call `timeout` bound how long, and `raise`d {exc}`~libtmux.exc.TmuxTimeout`
is how a caller finds out a bound was hit. `send_keys()` not waiting for its
command to finish is the one place non-blocking dispatch already exists —
polling is how you find out what happened next.

## What `_vendor/` contains

The `_vendor/` package holds vendored third-party code — copies of external
libraries bundled directly so libtmux can avoid adding dependencies. You're not
meant to import from it; it isn't written by the libtmux authors and isn't part
of the API.

## How internal APIs get promoted

Most readers never need this section — it's for contributors and for anyone
tempted to depend on an internal name. An API travels three stages on its way to
the public contract:

1. **Internal**: lives in `_internal/`, no stability promise
2. **Experimental**: documented, usable, but explicitly marked as subject to change
3. **Public**: moved to a top-level module, covered by the deprecation policy

Promotion happens when an internal API proves stable across multiple releases and
users ask for it. If you depend on an internal API, [file an
issue](https://github.com/tmux-python/libtmux/issues) — that signal helps
prioritize promotion.

Once a name is public and later has to change, it doesn't vanish quietly; it
moves through {doc}`a deprecation cycle </project/deprecations>` first. For the
platforms and tmux versions that stability is promised against, see
{doc}`Compatibility </project/compatibility>`.
