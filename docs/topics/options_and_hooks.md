(options-and-hooks)=

# Options and Hooks

libtmux provides a unified API for managing tmux options and hooks across all
object types (Server, Session, Window, Pane).

## Options

tmux options control the behavior and appearance of sessions, windows, and
panes. libtmux provides a consistent interface through
{class}`~libtmux.options.OptionsMixin`.

### Getting options

Use {meth}`~libtmux.options.OptionsMixin.show_options` to get all options:

```python
>>> session.show_options()  # doctest: +ELLIPSIS
{...}
```

Use {meth}`~libtmux.options.OptionsMixin.show_option` to get a single option:

```python
>>> server.show_option('buffer-limit')
50
```

### Setting options

Use {meth}`~libtmux.options.OptionsMixin.set_option` to set an option:

```python
>>> window.set_option('automatic-rename', False)  # doctest: +ELLIPSIS
Window(@... ...)

>>> window.show_option('automatic-rename')
False
```

### Unsetting options

Use {meth}`~libtmux.options.OptionsMixin.unset_option` to revert an option to
its default:

```python
>>> window.unset_option('automatic-rename')  # doctest: +ELLIPSIS
Window(@... ...)
```

### Option scopes

tmux options exist at different scopes. Use the `scope` parameter to specify:

```python
>>> from libtmux.constants import OptionScope

>>> # Get window-scoped options from a session
>>> session.show_options(scope=OptionScope.Window)  # doctest: +ELLIPSIS
{...}
```

### Global options

Use `global_=True` to work with global options:

```python
>>> server.show_option('buffer-limit', global_=True)
50
```

## Hooks

tmux hooks allow you to run commands when specific events occur. libtmux
provides hook management through {class}`~libtmux.hooks.HooksMixin`.

### Setting and getting hooks

Use {meth}`~libtmux.hooks.HooksMixin.set_hook` to set a hook and
{meth}`~libtmux.hooks.HooksMixin.show_hook` to get its value:

```python
>>> session.set_hook('session-renamed', 'display-message "Session renamed"')  # doctest: +ELLIPSIS
Session(...)

>>> session.show_hook('session-renamed')  # doctest: +ELLIPSIS
{0: 'display-message "Session renamed"'}

>>> session.show_hooks()  # doctest: +ELLIPSIS
{...}
```

Note that hooks are stored as indexed arrays in tmux, so `show_hook()` returns a
{class}`~libtmux._internal.sparse_array.SparseArray` (dict-like) with index keys.

### Removing hooks

Use {meth}`~libtmux.hooks.HooksMixin.unset_hook` to remove a hook:

```python
>>> session.unset_hook('session-renamed')  # doctest: +ELLIPSIS
Session(...)
```

### Indexed hooks

tmux hooks support multiple values via indices (e.g., `session-renamed[0]`,
`session-renamed[1]`). This allows multiple commands to run for the same event:

```python
>>> session.set_hook('after-split-window[0]', 'display-message "Split 0"')  # doctest: +ELLIPSIS
Session(...)

>>> session.set_hook('after-split-window[1]', 'display-message "Split 1"')  # doctest: +ELLIPSIS
Session(...)

>>> hooks = session.show_hook('after-split-window')
>>> sorted(hooks.keys())
[0, 1]
```

The return value is a {class}`~libtmux._internal.sparse_array.SparseArray`,
which preserves sparse indices (e.g., indices 0 and 5 with no 1-4).

### Bulk hook operations

Use {meth}`~libtmux.hooks.HooksMixin.set_hooks` to set multiple indexed hooks:

```python
>>> session.set_hooks('window-linked', {
...     0: 'display-message "Window linked 0"',
...     1: 'display-message "Window linked 1"',
... })  # doctest: +ELLIPSIS
Session(...)

>>> # Clean up
>>> session.unset_hook('after-split-window[0]')  # doctest: +ELLIPSIS
Session(...)
>>> session.unset_hook('after-split-window[1]')  # doctest: +ELLIPSIS
Session(...)
>>> session.unset_hook('window-linked[0]')  # doctest: +ELLIPSIS
Session(...)
>>> session.unset_hook('window-linked[1]')  # doctest: +ELLIPSIS
Session(...)
```

## tmux version compatibility

| Feature | Minimum tmux |
|---------|-------------|
| All options/hooks features | 3.2+ |
| Window/Pane hook scopes (`-w`, `-p`) | 3.2+ |
| `client-active`, `window-resized` hooks | 3.3+ |
| `pane-title-changed` hook | 3.5+ |

:::{seealso}
- {ref}`api` for the full API reference
- {class}`~libtmux.options.OptionsMixin` for options methods
- {class}`~libtmux.hooks.HooksMixin` for hooks methods
- {class}`~libtmux._internal.sparse_array.SparseArray` for sparse array handling
:::
