(api)=

(reference)=

# API Reference

libtmux's public API mirrors tmux's object hierarchy:

```
Server -> Session -> Window -> Pane
```

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

```{toctree}
:hidden:
:maxdepth: 1

libtmux.server
libtmux.session
libtmux.window
libtmux.pane
libtmux.common
libtmux.neo
libtmux.options
libtmux.hooks
libtmux.constants
libtmux.exc
```

## Test Utilities

If you're testing code that uses libtmux, see the test helpers and pytest plugin:

```{toctree}
:maxdepth: 1

test-helpers/index
pytest-plugin/index
```

## API Contract

```{toctree}
:maxdepth: 1

public-api
compatibility
deprecations
```
