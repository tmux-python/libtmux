# Public vs Internal API

## The Boundary

libtmux draws a clear line between public and internal code:

| Import path | Status | Stability |
|-------------|--------|-----------|
| `libtmux.*` | Public | Covered by [deprecation policy](../api/public-api.md) |
| `libtmux._internal.*` | Internal | No guarantee — may break between any release |
| `libtmux._vendor.*` | Vendored | Not part of the API at all |

If you can import it without a leading underscore in the module path, it's public.

## Why the Split

Internal modules exist so the library can iterate freely on implementation details without breaking downstream users. A refactor of `libtmux._internal.query_list` doesn't require a deprecation cycle — it's explicitly not part of the contract.

This separation also keeps the public API surface intentionally small. Every public module is a commitment to maintain. Internal modules earn promotion through proven stability and user demand.

## What `_internal/` Contains

The `_internal` package holds implementation details that support the public API:

- **`query_list`** — the filtering engine behind `.filter()` and `.get()` on collections
- **`dataclasses`** — base dataclass utilities used by the ORM objects
- **`constants`** — internal constants not meaningful to end users
- **`types`** — type aliases used across the codebase

These are documented in [Internals](../internals/index.md) for contributors, but downstream projects should not import from them.

## What `_vendor/` Contains

The `_vendor` package holds vendored third-party code — copies of external libraries included directly to avoid adding dependencies. This code is not written by the libtmux authors and is not part of the API.

## How Internal APIs Get Promoted

1. **Internal**: lives in `_internal/`, no stability promise
2. **Experimental**: documented, usable, but explicitly marked as subject to change
3. **Public**: moved to a top-level module, covered by the deprecation policy

Promotion happens when an internal API proves stable across multiple releases and users request it. If you depend on an internal API, [file an issue](https://github.com/tmux-python/libtmux/issues) — that signal helps prioritize promotion.

## Reference

- [Public API](../api/public-api.md) — the authoritative list of what's stable
- [Compatibility](../api/compatibility.md) — platform and version support
- [Deprecations](../api/deprecations.md) — what's changing
