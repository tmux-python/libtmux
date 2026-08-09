(howto-create-panes)=

# Create panes

A window starts as a single {class}`~libtmux.Pane`, and splitting is what turns
it into a workspace. {meth}`Window.split() <libtmux.Window.split>` divides the
window's active pane; {meth}`Pane.split() <libtmux.Pane.split>` divides the pane
you name. Either way you get back the **new** pane, which is the handle you keep
— splitting the pane you were just handed is how a layout grows.

The three blocks below run in sequence. Paste the first into a Python session,
then the second, then the third.

## Build a layout

```python
from libtmux import Server
from libtmux.constants import PaneDirection

server = Server(socket_name="libtmux-howto")
session = server.new_session(session_name="layout", kill_session=True)
window = session.active_window
window.resize(height=40, width=120)

editor = window.active_pane
shell = editor.split(direction=PaneDirection.Right, percentage=40)
logs = shell.split(direction=PaneDirection.Below, size=10, start_directory="/tmp")

print("panes:", len(window.panes))
print("shell is", shell.pane_width, "columns wide")
print("logs is", logs.pane_height, "rows tall, in", logs.pane_current_path)
```

That is an editor filling the left of the window, a shell taking the right-hand
40%, and a log pane ten rows tall beneath the shell — built by splitting the
*returned* pane each time rather than the window, which is what puts the log
pane inside the right-hand column instead of across the whole window.

{class}`~libtmux.constants.PaneDirection` names where the new pane goes:
`Right`, `Left`, `Above`, `Below`. Leave it out and tmux splits downwards. Size
the new pane with `percentage=` for a share of the space or `size=` for an exact
count of cells — rows for a horizontal division, columns for a vertical one —
and give it a working directory of its own with `start_directory=`. The two size
arguments are mutually exclusive; pass one or neither.

Sizes are shares of the window, and nothing is attached to this session, so the
window is tmux's default 80×24 — the `resize` call is what makes `percentage=40`
mean 48 columns rather than 32. Attach a client later and the window takes that
client's size instead. Space runs out either way: a split with nowhere to go
raises {exc}`~libtmux.exc.LibTmuxException` carrying tmux's own complaint that
there is no space for a new pane — the exact wording moved in tmux 3.7, so
match loosely if you branch on it.

## Pane order is layout position, not creation order

```python
banner = editor.split(direction=PaneDirection.Above, size=3)

print("created:", [pane.pane_id for pane in (editor, shell, logs, banner)])
print("window.panes:", [pane.pane_id for pane in window.panes])
print("focus stayed put:", window.active_pane.pane_id == editor.pane_id)
```

The banner was created last and lists first, because {attr}`Window.panes
<libtmux.Window.panes>` walks the window's layout from top-left, and the banner
sits above everything. Reach for a pane through that list by position and you
are addressing whatever happens to occupy that corner of the screen today; hold
the handle `split()` gave you and you are addressing the pane you made. Prefer
the handle — or look one up by identity with
`window.panes.get(pane_id=..., default=None)`.

Focus stayed on the editor throughout, because {meth}`~libtmux.Pane.split`
defaults to `attach=False`. Pass `attach=True` for the one pane a person should
land in when they open the session.

## Panes you are holding go stale

```python
print("editor thinks it is pane", editor.pane_index)

editor.refresh()

print("editor is actually pane", editor.pane_index)

session.kill()
```

A {class}`~libtmux.Pane` reads its fields from tmux once, when the object is
built, so the editor still remembers the index it had before the banner pushed
it down. {meth}`~libtmux.Pane.refresh` re-reads them. Identity is what survives:
`pane_id` never changes for the life of the pane, while index, size, and
position all move as the layout does — so key your own bookkeeping on the id and
refresh before trusting anything else.

Reading `window.panes` again costs a round-trip to tmux and hands back freshly
built objects, which is the other way to get current values.

{meth}`~libtmux.Session.kill` tears the session down. For work that should clean
up after itself even when something raises, see {ref}`context_managers`.

## Related

- {ref}`workspace-setup` — arranging panes with tmux's built-in layouts, and
  the window-level machinery around them.
- {ref}`howto-create-a-floating-pane` — a pane that hovers above the layout
  instead of dividing it.
- {ref}`howto-send-keys` — put a command into a pane once you have one.
