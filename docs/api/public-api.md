# Public API

## What Is Public

Every module documented under [API Reference](index.md) is public API.
This includes:

### Core Library

| Module | Import Path |
|--------|-------------|
| Server | `from libtmux.server import Server` |
| Session | `from libtmux.session import Session` |
| Window | `from libtmux.window import Window` |
| Pane | `from libtmux.pane import Pane` |
| Common | `from libtmux.common import ...` |
| Neo | `from libtmux.neo import ...` |
| Options | `from libtmux.options import ...` |
| Hooks | `from libtmux.hooks import ...` |
| Constants | `from libtmux.constants import ...` |
| Exceptions | `from libtmux.exc import ...` |

### Test Utilities

| Module | Import Path |
|--------|-------------|
| Test helpers | `from libtmux.test import ...` |
| Pytest plugin | `libtmux.pytest_plugin` (auto-loaded) |

## What Is Internal

Modules under `libtmux._internal` and `libtmux._vendor` are **not public**.
They may change or be removed without notice between any release.

Do not import from:
- `libtmux._internal.*`
- `libtmux._vendor.*`

## Pre-1.0 Stability Policy

libtmux is pre-1.0. This means:

- **Minor versions** (0.x -> 0.y) may include breaking API changes
- **Patch versions** (0.x.y -> 0.x.z) are bug fixes only
- **Pin your dependency**: use `libtmux>=0.55,<0.56` or `libtmux~=0.55.0`

Breaking changes are documented in the [changelog](../history.md) and
the [deprecations](deprecations.md) page before removal.

## Deprecation Process

Before removing or changing public API:

1. A deprecation warning is added for at least one minor release
2. The change is documented in [deprecations](deprecations.md)
3. Migration guidance is provided
4. The old API is removed in a subsequent minor release
