(workspace-setup)=

# Workspace Setup

libtmux makes it easy to create and configure multi-pane workspaces programmatically.
This is useful for setting up development environments, running parallel tasks,
and orchestrating terminal-based workflows.

Open two terminals:

Terminal one: start tmux in a separate terminal:

```console
$ tmux
```

Terminal two, `python` or `ptpython` if you have it:

```console
$ python
```

## Creating Windows

The {meth}`~libtmux.Session.new_window` method creates new windows within a session.

### Basic window creation

```python
>>> new_window = session.new_window(window_name='workspace')
>>> new_window  # doctest: +ELLIPSIS
Window(@... ...:workspace, Session($... ...))

>>> # Window is part of the session
>>> new_window in session.windows
True
```

### Create without attaching

Use `attach=False` to create a window in the background:

```python
>>> background_window = session.new_window(
...     window_name='background-task',
...     attach=False,
... )
>>> background_window  # doctest: +ELLIPSIS
Window(@... ...:background-task, Session($... ...))

>>> # Clean up
>>> background_window.kill()
```

### Create with specific shell

```python
>>> shell_window = session.new_window(
...     window_name='shell-test',
...     attach=False,
...     window_shell='sh -c "echo Hello; exec sh"',
... )
>>> shell_window  # doctest: +ELLIPSIS
Window(@... ...:shell-test, Session($... ...))

>>> # Clean up
>>> shell_window.kill()
```

## Splitting Panes

The {meth}`~libtmux.Window.split` method divides windows into multiple panes.

### Vertical split (top/bottom)

```python
>>> import time
>>> from libtmux.constants import PaneDirection

>>> # Create a window with enough space
>>> v_split_window = session.new_window(window_name='v-split-demo', attach=False)
>>> v_split_window.resize(height=40, width=120)  # doctest: +ELLIPSIS
Window(@... ...)

>>> # Default split is vertical (creates pane below)
>>> top_pane = v_split_window.active_pane
>>> bottom_pane = v_split_window.split()
>>> bottom_pane  # doctest: +ELLIPSIS
Pane(%... Window(@... ..., Session($... ...)))

>>> len(v_split_window.panes)
2

>>> # Clean up
>>> v_split_window.kill()
```

### Horizontal split (left/right)

```python
>>> from libtmux.constants import PaneDirection

>>> # Create a fresh window for this demo
>>> h_split_window = session.new_window(window_name='h-split', attach=False)
>>> h_split_window.resize(height=40, width=120)  # doctest: +ELLIPSIS
Window(@... ...)

>>> left_pane = h_split_window.active_pane
>>> right_pane = left_pane.split(direction=PaneDirection.Right)
>>> right_pane  # doctest: +ELLIPSIS
Pane(%... Window(@... ..., Session($... ...)))

>>> len(h_split_window.panes)
2

>>> # Clean up
>>> h_split_window.kill()
```

### Split with specific size

```python
>>> # Create a fresh window for size demo
>>> size_window = session.new_window(window_name='size-demo', attach=False)
>>> size_window.resize(height=40, width=120)  # doctest: +ELLIPSIS
Window(@... ...)

>>> main_pane = size_window.active_pane
>>> # Create pane with specific percentage
>>> small_pane = main_pane.split(size='20%')
>>> small_pane  # doctest: +ELLIPSIS
Pane(%... Window(@... ..., Session($... ...)))

>>> # Clean up
>>> size_window.kill()
```

## Layout Management

The {meth}`~libtmux.Window.select_layout` method arranges panes using built-in layouts.

### Available layouts

tmux provides five built-in layouts:

| Layout | Description |
|--------|-------------|
| `even-horizontal` | Panes spread evenly left to right |
| `even-vertical` | Panes spread evenly top to bottom |
| `main-horizontal` | Large pane on top, others below |
| `main-vertical` | Large pane on left, others on right |
| `tiled` | Panes spread evenly in rows and columns |

### Applying layouts

```python
>>> # Create window with multiple panes
>>> layout_window = session.new_window(window_name='layout-demo', attach=False)
>>> layout_window.resize(height=60, width=120)  # doctest: +ELLIPSIS
Window(@... ...)

>>> pane1 = layout_window.active_pane
>>> pane2 = layout_window.split()
>>> pane3 = layout_window.split()
>>> pane4 = layout_window.split()

>>> # Apply tiled layout
>>> layout_window.select_layout('tiled')  # doctest: +ELLIPSIS
Window(@... ...)

>>> # Apply even-horizontal layout
>>> layout_window.select_layout('even-horizontal')  # doctest: +ELLIPSIS
Window(@... ...)

>>> # Apply main-vertical layout
>>> layout_window.select_layout('main-vertical')  # doctest: +ELLIPSIS
Window(@... ...)

>>> # Clean up
>>> layout_window.kill()
```

## Renaming and Organizing

### Rename windows

```python
>>> rename_window = session.new_window(window_name='old-name', attach=False)
>>> rename_window.rename_window('new-name')  # doctest: +ELLIPSIS
Window(@... ...:new-name, Session($... ...))

>>> rename_window.window_name
'new-name'

>>> # Clean up
>>> rename_window.kill()
```

### Access window properties

```python
>>> demo_window = session.new_window(window_name='props-demo', attach=False)

>>> # Window index
>>> demo_window.window_index  # doctest: +ELLIPSIS
'...'

>>> # Window ID
>>> demo_window.window_id  # doctest: +ELLIPSIS
'@...'

>>> # Parent session
>>> demo_window.session  # doctest: +ELLIPSIS
Session($... ...)

>>> # Clean up
>>> demo_window.kill()
```

## Practical Recipes

### Recipe: Create a development workspace

```python
>>> import time
>>> from libtmux.constants import PaneDirection

>>> def create_dev_workspace(session, name='dev'):
...     """Create a typical development workspace layout."""
...     window = session.new_window(window_name=name, attach=False)
...     window.resize(height=50, width=160)
...
...     # Main editing pane (large, left side)
...     main_pane = window.active_pane
...
...     # Terminal pane (bottom)
...     terminal_pane = main_pane.split(size='30%')
...
...     # Logs pane (right side of terminal)
...     log_pane = terminal_pane.split(direction=PaneDirection.Right)
...
...     return {
...         'window': window,
...         'main': main_pane,
...         'terminal': terminal_pane,
...         'logs': log_pane,
...     }

>>> workspace = create_dev_workspace(session, 'my-project')
>>> len(workspace['window'].panes)
3

>>> # Clean up
>>> workspace['window'].kill()
```

### Recipe: Create a grid of panes

```python
>>> from libtmux.constants import PaneDirection

>>> def create_pane_grid(session, rows=2, cols=2, name='grid'):
...     """Create an NxM grid of panes."""
...     window = session.new_window(window_name=name, attach=False)
...     window.resize(height=50, width=160)
...
...     panes = []
...     base_pane = window.active_pane
...     panes.append(base_pane)
...
...     # Create first row of panes
...     current = base_pane
...     for _ in range(cols - 1):
...         new_pane = current.split(direction=PaneDirection.Right)
...         panes.append(new_pane)
...         current = new_pane
...
...     # Create additional rows
...     for _ in range(rows - 1):
...         row_start = panes[-cols]
...         current = row_start
...         for col in range(cols):
...             new_pane = panes[-cols + col].split(direction=PaneDirection.Below)
...             panes.append(new_pane)
...
...     # Apply tiled layout for even distribution
...     window.select_layout('tiled')
...     return window, panes

>>> grid_window, grid_panes = create_pane_grid(session, rows=2, cols=2, name='test-grid')
>>> len(grid_panes) >= 4
True

>>> # Clean up
>>> grid_window.kill()
```

### Recipe: Run commands in multiple panes

```python
>>> import time

>>> def run_in_panes(panes, commands):
...     """Run different commands in each pane."""
...     for pane, cmd in zip(panes, commands):
...         pane.send_keys(cmd)

>>> multi_window = session.new_window(window_name='multi-cmd', attach=False)
>>> multi_window.resize(height=40, width=120)  # doctest: +ELLIPSIS
Window(@... ...)

>>> pane_a = multi_window.active_pane
>>> pane_b = multi_window.split()
>>> pane_c = multi_window.split()

>>> run_in_panes(
...     [pane_a, pane_b, pane_c],
...     ['echo "Task A"', 'echo "Task B"', 'echo "Task C"'],
... )

>>> # Give commands time to execute
>>> time.sleep(0.2)

>>> # Verify all commands ran
>>> 'Task A' in '\\n'.join(pane_a.capture_pane())
True

>>> # Clean up
>>> multi_window.kill()
```

## Window Context Managers

Windows can be used as context managers for automatic cleanup:

```python
>>> with session.new_window(window_name='temp-window') as temp_win:
...     pane = temp_win.active_pane
...     pane.send_keys('echo "temporary workspace"')
...     temp_win in session.windows
True

>>> # Window is automatically killed after exiting context
>>> temp_win not in session.windows
True
```

:::{seealso}
- {ref}`pane-interaction` for working with pane content
- {ref}`automation-patterns` for advanced orchestration
- {class}`~libtmux.Window` for all window methods
- {class}`~libtmux.Session` for session management
:::
