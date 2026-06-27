# Topics

Explore libtmux's core functionalities and underlying principles at a high level, while providing essential context and detailed explanations to help you understand its design and usage.

::::{grid} 1 1 2 2
:gutter: 2 2 3 3

:::{grid-item-card} Architecture
:link: architecture
:link-type: doc
Module hierarchy, data flow, and internal identifiers.
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

:::{grid-item-card} Floating Panes
:link: floating_panes
:link-type: doc
Create and position floating (overlay) panes on tmux 3.7+.
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

:::{grid-item-card} Clients
:link: clients
:link-type: doc
Attached terminals, live-attachment lookup, and the view-vs-identity model.
:::

:::{grid-item-card} Format-Token Fields
:link: format-tokens
:link-type: doc
Scope- and version-gated typed fields on every libtmux object.
:::

::::

```{toctree}
:hidden:

architecture
configuration
design-decisions
public-vs-internal
traversal
filtering
pane_interaction
floating_panes
workspace_setup
automation_patterns
context_managers
options_and_hooks
clients
format-tokens
```
