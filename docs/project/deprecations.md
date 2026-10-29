# Deprecations

Active deprecations with timeline and migration paths.

## Active Deprecations

<!-- Pull active deprecations from CHANGES when they exist -->

The following {class}`~libtmux.Window` methods emit `DeprecationWarning`:

| Deprecated | Replacement |
|------------|-------------|
| {meth}`~libtmux.Window.set_window_option` | {meth}`~libtmux.Window.set_option` |
| {meth}`~libtmux.Window.show_window_option` | {meth}`~libtmux.Window.show_option` |
| {meth}`~libtmux.Window.show_window_options` | {meth}`~libtmux.Window.show_options` |

The legacy `g` parameter on option methods also emits `DeprecationWarning`;
use `global_` instead. No removal release is scheduled here.

See [history](../history.md) for past changes and the
[migration guide](../migration.md) for upgrading between versions.

## Deprecation Policy

See [Public API -- Deprecation Process](public-api.md#deprecation-process).
