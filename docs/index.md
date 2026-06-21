(index)=

# libtmux

Typed Python API for [tmux](https://github.com/tmux/tmux). Control
servers, sessions, windows, and panes as Python objects.

::::{grid} 1 1 3 3
:gutter: 2 2 3 3

:::{grid-item-card} Quickstart
:link: quickstart
:link-type: doc
Install and make your first API call in 5 minutes.
:::

:::{grid-item-card} Topics
:link: topics/index
:link-type: doc
Architecture, traversal, filtering, and automation patterns.
:::

:::{grid-item-card} API Reference
:link: api/index
:link-type: doc
Every public class, function, and exception.
:::

:::{grid-item-card} Testing
:link: api/testing/index
:link-type: doc
Isolated tmux fixtures and test helpers.
:::

:::{grid-item-card} Contributing
:link: project/index
:link-type: doc
Development setup, code style, release process.
:::

::::

## Install

```console
$ pip install libtmux
```

```console
$ uv add libtmux
```

Tip: libtmux is pre-1.0. Pin to a range: `libtmux>=0.55,<0.56`

See [Quickstart](quickstart.md) for all methods and first steps.

## At a glance

```python
>>> demo_window = session.new_window(window_name="my-project")
>>> demo_pane = demo_window.active_pane
>>> demo_pane.send_keys("echo hello")
>>> demo_window.kill()
```

```
Server  →  Session  →  Window  →  Pane
```

Every level of the [tmux hierarchy](topics/architecture.md) is a typed
Python object with traversal, filtering, and command execution.

| Object | What it wraps |
|--------|---------------|
| {class}`~libtmux.server.Server` | tmux server / socket |
| {class}`~libtmux.session.Session` | tmux session |
| {class}`~libtmux.window.Window` | tmux window |
| {class}`~libtmux.pane.Pane` | tmux pane |

## Testing

libtmux ships a [pytest plugin](api/testing/pytest-plugin/index.md) with
isolated tmux fixtures:

```python
>>> test_window = session.new_window(window_name="test")
>>> test_pane = test_window.active_pane
>>> test_pane.send_keys("echo hello")
>>> test_window.window_name
'test'
>>> test_window.kill()
```

```{toctree}
:hidden:

quickstart
topics/index
api/index
api/testing/index
internals/index
project/index
experimental
history
migration
glossary
MCP <https://libtmux-mcp.git-pull.com>
GitHub <https://github.com/tmux-python/libtmux>
```
