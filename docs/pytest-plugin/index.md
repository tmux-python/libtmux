---
myst:
  html_meta:
    description: "libtmux pytest plugin for testing tmux applications with pytest"
    keywords: "tmux, pytest, plugin, testing, libtmux"
---

(pytest_plugin)=

# tmux `pytest` plugin

```{toctree}
:hidden:
:maxdepth: 2

getting-started
fixtures
usage-examples
advanced-techniques
```

libtmux provides pytest fixtures for tmux, making it easy to test tmux-related functionality with complete isolation. The plugin automatically manages setup and teardown of independent tmux servers, sessions, windows, and panes.

```{admonition} Connect with us!
:class: seealso

Do you want more flexibility? Correctness? Power? Defaults changed? [Connect with us](https://github.com/tmux-python/libtmux/discussions) on the tracker. We want to know your use case and won't stabilize APIs until we're sure everything is by the book.
```

## Benefits at a glance

- **Isolated Testing Environment**: Each test gets a fresh tmux server that won't interfere with other tests
- **Automatic Cleanup**: Servers, sessions, and other resources are automatically cleaned up after tests
- **Simplified Setup**: Common fixtures for server, session, window, and pane management
- **Reliable Testing**: Consistent environment for reproducible test results
- **Custom Configuration**: Easily test with different tmux configurations and settings

## Quick installation

Install `libtmux` via the Python package manager of your choice:

```{code-block} console
$ pip install libtmux
```

The pytest plugin will be automatically detected by pytest, and the fixtures will be available in your test environment.

## See real-world examples

View libtmux's own [tests/](https://github.com/tmux-python/libtmux/tree/master/tests) as well as tmuxp's [tests/](https://github.com/tmux-python/tmuxp/tree/master/tests) for real-world examples.

For detailed code examples and usage patterns, refer to the {ref}`usage-examples` page.

## Module reference

```{module} libtmux.pytest_plugin
```

```{eval-rst}
.. automodule:: libtmux.pytest_plugin
    :members:
    :inherited-members:
    :private-members:
    :show-inheritance:
    :member-order: bysource