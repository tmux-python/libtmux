# Design Decisions

## Why ORM-Style Objects

tmux organizes terminals in a strict hierarchy: Server → Session → Window → Pane. Each level owns the next. libtmux mirrors this with Python objects that maintain the same parent-child relationships.

The alternative — a flat command-builder API (`tmux("new-session", "-s", "foo")`) — loses the relational structure. You'd have to track which windows belong to which session manually. The ORM approach lets you write `session.windows` and get a live, filterable collection.

## Why Format Strings

tmux exposes object properties through its format system (`-F` flags). For example, `tmux list-sessions -F '#{session_id}:#{session_name}'` returns structured data.

libtmux uses this instead of parsing human-readable `tmux ls` output because:

- **Stability**: format variables are part of tmux's documented interface
- **Precision**: no regex fragility from parsing prose output
- **Completeness**: formats expose properties (like `session_id`) that don't appear in default output

Format constants are defined in {mod}`libtmux.formats`.

## Why Dataclasses in neo.py

{mod}`libtmux.neo` provides a modern dataclass-based interface alongside the legacy dict-style objects. The motivation:

- **Type safety**: dataclass fields have declared types, enabling mypy checks and IDE completion
- **Predictability**: attribute access (`session.session_name`) instead of dict access (`session["session_name"]`)
- **Migration path**: the two interfaces coexist, allowing gradual adoption without breaking existing code

## Pre-1.0 API Evolution

libtmux is pre-1.0. This is a deliberate choice — the API is still maturing. What this means in practice:

- **Minor versions** (0.x → 0.y) may include breaking changes
- **Patch versions** (0.x.y → 0.x.z) are bug fixes only
- **Pin your dependency**: use `libtmux>=0.55,<0.56` or `libtmux~=0.55.0`

Breaking changes always get:
1. A deprecation warning for at least one minor release
2. Documentation in the [changelog](../history.md) and [deprecations](../api/deprecations.md)
3. Migration guidance

See [Public API](../api/public-api.md) for the stability contract.
