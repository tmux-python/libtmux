(workspace-setup)=

# Workspace setup

A workspace is a single window carved into panes, each running its own
program: an editor in one, a dev server in another, a log tail in a third.
With libtmux you build that layout from Python instead of arranging it by
hand — you open a window, split it into panes, arrange them with a layout,
and send commands into each.

You will reach for four methods more than any others:
{meth}`~libtmux.Session.new_window` to open a window,
{meth}`~libtmux.Window.split` to carve it into panes,
{meth}`~libtmux.Window.select_layout` to arrange them, and
{meth}`~libtmux.Pane.send_keys` to drive a command into one. The defaults
are sensible, so most of what you build needs nothing more — the recipes
near the end are ready-made patterns you can copy whole and adapt.

To follow along you need two terminals: one running a live tmux server, one
running a Python prompt to drive it.

In the first terminal, start tmux:

```console
$ tmux
```

In the second, start Python (`ptpython` if you have it):

```console
$ python
```

## Creating windows

Every workspace begins with a window. {meth}`~libtmux.Session.new_window`
opens one inside a session and hands you back a {class}`~libtmux.Window` you
can split, rename, and fill with panes.

### Basic window creation

Hand {meth}`~libtmux.Session.new_window` a name and you get a
{class}`~libtmux.Window` back, added to the session's window list. By
default the window is created in the background — it doesn't pull your
focus from the window you're already on:

```python
>>> new_window = session.new_window(window_name='workspace')
>>> new_window  # doctest: +ELLIPSIS
Window(@... ...:workspace, Session($... ...))

>>> # Window is part of the session
>>> new_window in session.windows
True
```

### Create without attaching

Because `attach=False` is the default, the windows you build stay in the
background while you assemble a workspace — focus never jumps to each one as
it appears. Pass it explicitly when you want that intent on the page, and
reach for `attach=True` only when a window should take focus as it's created:

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

You can also choose what runs inside the window instead of the default shell
— handy when a pane should boot straight into a REPL, a server, or a one-off
script:

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

## Splitting panes

A window with one pane is just a terminal. Splitting is what turns it into a
workspace: {meth}`~libtmux.Window.split` (or the same method on a specific
{meth}`~libtmux.Pane.split`) divides the available space and returns the new
{class}`~libtmux.Pane`. Each split and {meth}`~libtmux.Window.resize` is a
round-trip to the tmux server; the resize calls below buy a window large
enough that the splits have room to land on a small terminal.

### Vertical split (top/bottom)

Splitting top-and-bottom is the default — the new pane opens below the one
you split:

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

Pass a direction to split side-by-side instead.
{class}`~libtmux.constants.PaneDirection` names where the new pane goes —
here, to the right of the one you split:

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

By default tmux halves the space. Ask for a specific share — a percentage or
a cell count — when one pane should be smaller than the rest:

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

## Layout management

Once a window holds several panes, a layout decides how they share the
screen. {meth}`~libtmux.Window.select_layout` applies one of tmux's built-in
arrangements so you don't have to size each pane by hand.

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

Pass a layout name and tmux re-tiles every pane in the window. You can switch
layouts as often as you like — the panes and their contents stay put, only
their geometry changes:

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

## Renaming and organizing

### Rename windows

A window's name is how you find it later, so give each one a label that says
what it's for. {meth}`~libtmux.Window.rename_window` updates it in place:

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

A {class}`~libtmux.Window` object reflects tmux's state at the moment you ask:
its index in the session, its stable id, and the {class}`~libtmux.Session` it
belongs to are all available as attributes. libtmux reads them once when it
builds the object, so if something changes the window externally, call
{meth}`~libtmux.Window.refresh` to re-fetch from tmux before you read them
again:

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

## Practical recipes

The methods above are enough to build any workspace. The recipes below stitch
them into patterns worth keeping — lift one and adapt it, or read them as
worked examples of how the pieces fit together.

### Recipe: create a development workspace

A common shape: one large editing pane, a smaller terminal beneath it, and a
log pane beside the terminal. This helper wires that up and returns the panes
keyed by role, so the caller can drive each one by name:

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

### Recipe: create a grid of panes

Need a uniform grid — four panes, nine, sixteen — for watching parallel jobs?
Split a row across, repeat down the rows, then let the `tiled`
{meth}`~libtmux.Window.select_layout` even everything out:

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

### Recipe: run commands in multiple panes

Sending keys is how you put work into a pane.
{meth}`~libtmux.Pane.send_keys` returns as soon as the keystrokes are
delivered — the command itself runs asynchronously — so when you need to read
its output back with {meth}`~libtmux.Pane.capture_pane`, give it a beat to
finish first:

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

## Window context managers

When a window is only meant to live for the span of a task — a test run, a
quick capture — let a `with` block own it. The window is created on entry and
killed on exit, so you never leak a stray window even if something raises
midway through:

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
