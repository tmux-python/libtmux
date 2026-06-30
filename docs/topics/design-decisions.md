# Design decisions

This page explains the "why" behind libtmux's shape: the four core choices it
makes about representing tmux to your Python code. You don't need any of it to
get started — the defaults work out of the box, and most code never thinks about
the rationale below. Read on when a choice starts to matter to you: why
{attr}`session.windows <libtmux.Session.windows>` is a live collection, why
properties read cleanly off an object, and what to expect from a pre-1.0 API.

## Why ORM-style objects

Most of your code just writes {attr}`session.windows <libtmux.Session.windows>`
and gets a live, filterable collection back — you rarely think about why it's
shaped that way. This section is for when you're curious about the design.

tmux organizes terminals in a strict hierarchy: {class}`~libtmux.Server` →
{class}`~libtmux.Session` → {class}`~libtmux.Window` →
{class}`~libtmux.Pane`. Each level owns the next. libtmux mirrors that
hierarchy with Python objects that maintain the same parent-child
relationships, so navigating tmux feels like navigating Python.

What you get is a relational structure you can walk in either direction:
{attr}`session.windows <libtmux.Session.windows>` lists a session's windows,
{attr}`pane.window <libtmux.Pane.window>` points back up to the pane's parent.
The alternative — a flat command-builder API
(`tmux("new-session", "-s", "foo")`) — hands back raw strings and leaves you to
track which windows belong to which session yourself.

The trade-off is that an object is a snapshot. If tmux state changes out from
under you — another client splits a window, a process exits — your object can go
stale, and you reach for {meth}`~libtmux.Session.refresh` to re-read it. You
trade that occasional refresh for an API that reads like the hierarchy it
models.

## Why format strings

tmux exposes object properties through its format system (`-F` flags). For
example, `tmux list-sessions -F '#{session_id}:#{session_name}'` returns
structured data.

libtmux queries through this system instead of parsing human-readable `tmux ls`
output because:

- **Stability**: format variables are part of tmux's documented interface
- **Precision**: no regex fragility from parsing prose output
- **Completeness**: formats expose properties (like `session_id`) that don't appear in default output

The cost is a tmux round-trip on the live collections: reading a property like
{attr}`session.windows <libtmux.Session.windows>` runs a subprocess against the
server each time you access it, not a cached value (the scalar fields like
{attr}`session.session_name <libtmux.Session.session_name>` are different —
read once when the object is built). What it buys is a value
you can trust — pulled straight from tmux's own reporting, not reconstructed by
guessing at the layout of display text. The format constants that make this work
live in {mod}`libtmux.formats`.

## Why dataclasses in `neo.py`

Advanced — for contributors and lower-level query work. Most code uses the ORM
objects above and never touches this layer directly.

{mod}`libtmux.neo` provides a modern dataclass-based interface alongside the
legacy dict-style objects. The motivation:

- **Type safety**: dataclass fields have declared types, enabling mypy checks and IDE completion
- **Predictability**: attribute access (`session.session_name`) instead of dict access (`session["session_name"]`)
- **Migration path**: the two interfaces coexist, allowing gradual adoption without breaking existing code

Coexistence is the honest trade-off: two interfaces are more surface area to
learn than one. The payoff is that you can adopt the typed path incrementally,
file by file, without a flag-day rewrite.

## Pre-1.0 API evolution

libtmux is pre-1.0. This is a deliberate choice — the API is still maturing.
What this means in practice for code you write today:

- **Minor versions** (0.x → 0.y) may include breaking changes
- **Patch versions** (0.x.y → 0.x.z) are bug fixes only
- **Pin your dependency**: use `libtmux>=0.55,<0.56` or `libtmux~=0.55.0`

Breaking changes always get:
1. A deprecation warning for at least one minor release
2. Documentation in the [changelog](../history.md) and [deprecations](../project/deprecations.md)
3. Migration guidance

See [Public API](../project/public-api.md) for the stability contract.
