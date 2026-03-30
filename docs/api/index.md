(api)=

(reference)=

# API Reference

libtmux's public API mirrors tmux's object hierarchy:
`Server` → `Session` → `Window` → `Pane`

## What do you want to do?

::::{grid} 1 2 2 2
:gutter: 2

:::{grid-item-card} Find a session, window, or pane?
:link: libtmux.server
:link-type: doc
Use `server.sessions.get()`, `session.windows.get()`.
:::

:::{grid-item-card} Send commands or keys to a terminal?
:link: libtmux.pane
:link-type: doc
Use `pane.send_keys()` and `pane.enter()`.
:::

:::{grid-item-card} Capture output from a pane?
:link: libtmux.pane
:link-type: doc
Use `pane.capture_pane()`.
:::

:::{grid-item-card} Write tests against tmux?
:link: testing/index
:link-type: doc
Use the pytest plugin and test helpers.
:::

::::

## Core Objects

::::{grid} 1 1 2 2
:gutter: 2 2 3 3

:::{grid-item-card} Server
:link: libtmux.server
:link-type: doc
Entry point. Manages sessions and executes raw tmux commands.
:::

:::{grid-item-card} Session
:link: libtmux.session
:link-type: doc
Manages windows within a tmux session.
:::

:::{grid-item-card} Window
:link: libtmux.window
:link-type: doc
Manages panes, layouts, and window operations.
:::

:::{grid-item-card} Pane
:link: libtmux.pane
:link-type: doc
Terminal instance. Send keys and capture output.
:::

::::

## Supporting Modules

::::{grid} 1 2 3 3
:gutter: 2 2 3 3

:::{grid-item-card} Common
:link: libtmux.common
:link-type: doc
Base classes and command execution.
:::

:::{grid-item-card} Neo
:link: libtmux.neo
:link-type: doc
Dataclass-based query interface.
:::

:::{grid-item-card} Options
:link: libtmux.options
:link-type: doc
tmux option get/set.
:::

:::{grid-item-card} Hooks
:link: libtmux.hooks
:link-type: doc
tmux hook management.
:::

:::{grid-item-card} Constants
:link: libtmux.constants
:link-type: doc
Format strings and constants.
:::

:::{grid-item-card} Exceptions
:link: libtmux.exc
:link-type: doc
Exception hierarchy.
:::

::::

## Testing

::::{grid} 1 1 1 1
:gutter: 2

:::{grid-item-card} Testing Utilities
:link: testing/index
:link-type: doc
pytest plugin, fixtures, and test helpers for testing code that uses libtmux.
:::

::::

## API Policy and Guarantees

These documents define the project's promises about the public API.

::::{grid} 1 2 3 3
:gutter: 2

:::{grid-item-card} Public API
:link: ../project/public-api
:link-type: doc
What is and is not considered stable public API.
:::

:::{grid-item-card} Compatibility
:link: ../project/compatibility
:link-type: doc
Supported versions of Python and tmux.
:::

:::{grid-item-card} Deprecations
:link: ../project/deprecations
:link-type: doc
Active deprecations and migration guidance.
:::

::::

```{toctree}
:hidden:
:maxdepth: 1

Server <libtmux.server>
Session <libtmux.session>
Window <libtmux.window>
Pane <libtmux.pane>
Common <libtmux.common>
Neo <libtmux.neo>
Options <libtmux.options>
Hooks <libtmux.hooks>
Constants <libtmux.constants>
Exceptions <libtmux.exc>
```
