(test_helpers)=

# Test Helpers

Utilities for writing reliable tests against libtmux and downstream code that uses tmux.

::::{grid} 1 2 3 3
:gutter: 2 2 3 3

:::{grid-item-card} libtmux.test
:link: libtmux.test
:link-type: doc
Base test module with common setup utilities.
:::
:::{grid-item-card} Constants
:link: constants
:link-type: doc
Predefined test constants.
:::
:::{grid-item-card} Environment
:link: environment
:link-type: doc
Environment variable mocking.
:::
:::{grid-item-card} Random
:link: random
:link-type: doc
Randomized name generators.
:::
:::{grid-item-card} Retry
:link: retry
:link-type: doc
Retry logic for async/tmux operations.
:::
:::{grid-item-card} Temporary
:link: temporary
:link-type: doc
Context managers for ephemeral tmux resources.
:::

::::

```{toctree}
:hidden:
:maxdepth: 1

libtmux.test
constants
environment
random
retry
temporary
```
