# Topics

Explore libtmux's core functionalities and underlying principles at a high level, while providing essential context and detailed explanations to help you understand its design and usage.

::::{grid} 1 1 2 2
:gutter: 2 2 3 3

:::{grid-item-card} Architecture
:link: architecture
:link-type: doc
Module hierarchy, data flow, and internal identifiers.
:::

:::{grid-item-card} Engines
:link: engines
:link-type: doc
subprocess, imsg, and persistent control-mode backends.
:::

:::{grid-item-card} Traversal
:link: traversal
:link-type: doc
Navigate the Server, Session, Window, Pane hierarchy.
:::

:::{grid-item-card} Filtering
:link: filtering
:link-type: doc
Query and filter collections by attributes.
:::

:::{grid-item-card} Pane Interaction
:link: pane_interaction
:link-type: doc
Send keys, capture output, and interact with panes.
:::

:::{grid-item-card} Workspace Setup
:link: workspace_setup
:link-type: doc
Create sessions, windows, and panes programmatically.
:::

:::{grid-item-card} Automation Patterns
:link: automation_patterns
:link-type: doc
Common patterns for scripting and automation.
:::

:::{grid-item-card} Context Managers
:link: context_managers
:link-type: doc
Automatic cleanup with temporary sessions and windows.
:::

:::{grid-item-card} Options & Hooks
:link: options_and_hooks
:link-type: doc
Get and set tmux options and hooks.
:::

::::

```{toctree}
:hidden:

architecture
engines
configuration
design-decisions
public-vs-internal
traversal
filtering
pane_interaction
workspace_setup
automation_patterns
context_managers
options_and_hooks
```
