(options-and-hooks)=

# Options and hooks

You shape how tmux sessions, windows, and panes behave by setting *options* —
values like `automatic-rename` or the status-bar format — and by registering
*hooks*, commands that tmux runs when an event fires, such as `session-renamed`
or `after-split-window`. libtmux gives you one consistent Python API to read,
set, and remove both, and it works the same way on every object in the
hierarchy: {class}`~libtmux.Server`, {class}`~libtmux.Session`,
{class}`~libtmux.Window`, and {class}`~libtmux.Pane`.

Most scripts run happily on tmux's defaults and never open this page — reaching
for options and hooks is entirely optional. Read on only when you need to tweak
how a session behaves or react to something that happens inside it.

## Options

Options are the knobs that control tmux's behavior and appearance, from whether
a window renames itself to how the status line looks. Whatever object you hold,
you read and change its options through the same four methods on
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

Use {meth}`~libtmux.options.OptionsMixin.set_option` to set an option. The call
returns the object you set it on, so the change is live the moment it returns —
no {meth}`~libtmux.Window.refresh` needed:

```python
>>> window.set_option('automatic-rename', False)  # doctest: +ELLIPSIS
Window(@... ...)

>>> window.show_option('automatic-rename')
False
```

### Unsetting options

Once you've overridden an option, you put it back the way tmux shipped it. Use
{meth}`~libtmux.options.OptionsMixin.unset_option` to revert an option to its
default:

```python
>>> window.unset_option('automatic-rename')  # doctest: +ELLIPSIS
Window(@... ...)
```

### Option scopes

By default a call reads or writes the option for the object you're holding — a
window's `set_option` touches that window. But tmux options live at distinct
scopes (server, session, window, pane), and sometimes you want to reach a
different level than the object in hand. Pass the `scope` parameter, drawn from
{class}`~libtmux.constants.OptionScope`, to say which one:

```python
>>> from libtmux.constants import OptionScope

>>> # Get window-scoped options from a session
>>> session.show_options(scope=OptionScope.Window)  # doctest: +ELLIPSIS
{...}
```

### Global options

Each scope also has a global layer — the fallback tmux uses when an object
hasn't set its own value. Reach it with `global_=True` when you want the
server-wide default rather than what one session or window happens to override:

```python
>>> server.show_option('buffer-limit', global_=True)
50
```

## Hooks

Hooks let you attach tmux commands to events, so something runs automatically
whenever, say, a session is renamed or a window is split. You manage them
through {class}`~libtmux.hooks.HooksMixin`, which mirrors the options API: set,
show, and unset, on any object.

### Setting and getting hooks

Use {meth}`~libtmux.hooks.HooksMixin.set_hook` to set a hook and
{meth}`~libtmux.hooks.HooksMixin.show_hook` to read it back. The hook is
registered with tmux the instant `set_hook` returns — there's no refresh step
before it starts firing:

```python
>>> session.set_hook('session-renamed', 'display-message "Session renamed"')  # doctest: +ELLIPSIS
Session(...)

>>> session.show_hook('session-renamed')  # doctest: +ELLIPSIS
{0: 'display-message "Session renamed"'}

>>> session.show_hooks()  # doctest: +ELLIPSIS
{...}
```

A single hook reads back as a dict keyed by index rather than a bare string,
because tmux stores hooks as arrays (more on that under indexed hooks,
below). `show_hook()` returns a
{class}`~libtmux._internal.sparse_array.SparseArray`, a dict-like type whose
keys are those array indices.

### Removing hooks

Use {meth}`~libtmux.hooks.HooksMixin.unset_hook` to remove a hook:

```python
>>> session.unset_hook('session-renamed')  # doctest: +ELLIPSIS
Session(...)
```

### Indexed hooks

A single event can fire more than one command. tmux models this by indexing
each hook (`session-renamed[0]`, `session-renamed[1]`, …), so you register
several commands against the same event and they all run:

```python
>>> session.set_hook('after-split-window[0]', 'display-message "Split 0"')  # doctest: +ELLIPSIS
Session(...)

>>> session.set_hook('after-split-window[1]', 'display-message "Split 1"')  # doctest: +ELLIPSIS
Session(...)

>>> hooks = session.show_hook('after-split-window')
>>> sorted(hooks.keys())
[0, 1]
```

This is why a hook comes back as a dict-like object: the index *is* part of the
data, and those indices can be sparse. If you set index 0 and index 5 but
nothing in between, tmux keeps the gap, and so does the
{class}`~libtmux._internal.sparse_array.SparseArray` you get back — its keys
stay exactly the indices tmux holds (0 and 5, with no 1–4), rather than
collapsing into a contiguous list.

### Bulk hook operations

When you're setting several indices at once, you don't have to call
{meth}`~libtmux.hooks.HooksMixin.set_hook` per index. Use
{meth}`~libtmux.hooks.HooksMixin.set_hooks` to set multiple indexed hooks in one
call, passing the index-to-command mapping directly:

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

Options and hooks need a reasonably recent tmux, and a few specific hooks
arrived later still. The floor for everything on this page is tmux 3.2:

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
