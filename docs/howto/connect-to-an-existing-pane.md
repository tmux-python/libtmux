(howto-connect-to-an-existing-pane)=

# Connect to an existing pane

A {class}`~libtmux.Pane` is the leaf of the hierarchy — the terminal a shell is
actually running in — and it is what you need a handle on before you can type
into it or read it back. Panes belong to a window, so you find one by getting
the window first and asking it what it holds.

```python
from libtmux import Server

server = Server()
session = server.sessions.get(session_name="editor", default=None)

if session is None:
    print("no session named 'editor' — use a session name of your own")
else:
    window = session.active_window
    for pane in window.panes:
        print(
            f"{pane.pane_index}\t{pane.pane_id}\t{pane.pane_width}x{pane.pane_height}"
        )
```

If that printed *no session named 'editor'*, change the name before pasting the
next block. Finding the session and the window is covered in
{ref}`howto-connect-to-an-existing-session` and
{ref}`howto-connect-to-an-existing-window`; from here on the window is a given.

## The one you want is usually the active one

{attr}`~libtmux.Window.active_pane` is the pane that window's cursor is in — the
one a keystroke would land in. It is the right answer surprisingly often, and it
saves you from picking a pane out of a list.

```python
pane = window.active_pane

print(f"active: {pane.pane_id}")
print(f"first:  {window.panes[0].pane_id}")
print(f"last:   {window.panes[-1].pane_id}")
```

:::{warning}
{attr}`~libtmux.Window.panes` is ordered by {attr}`~libtmux.Pane.pane_index`,
and a pane's index is its **position in the layout**, not its age. Split the
same pane twice and the second new pane lands *between* the original and the
first one, so the newest pane sits at index 1 while `panes[-1]` is the pane you
split off before it. Close a pane and every index after it shifts down.

`panes[-1]` therefore means "bottom-right-most", never "newest". When you want
the pane you just created, keep the {class}`~libtmux.Pane` that
{meth}`~libtmux.Window.split` handed back — that is what it is for.
:::

## Hold the id

{attr}`~libtmux.Pane.pane_id` — the `%`-prefixed value in the listing above — is
fixed for the pane's lifetime, which makes it the only one of these handles
worth storing. An index describes where a pane sits right now, and layouts
change.

{meth}`~libtmux.Pane.from_pane_id` turns a stored id back into an object,
targeting tmux directly rather than scanning a listing, and raising
{exc}`~libtmux.exc.TmuxObjectDoesNotExist` if the pane is gone.

```python
from libtmux import Pane

pane_id = pane.pane_id
found = Pane.from_pane_id(server, pane_id)

print(found.pane_id == pane_id, found.window.window_id == window.window_id)
```

That id is also the value tmux exports as `$TMUX_PANE` inside every pane, so a
program running under tmux can recover its own handle without being told where
it is — {meth}`Pane.from_env() <libtmux.Pane.from_env>` reads it for you. See
{ref}`self-location` for the full story, including the difference between the
pane your code runs in and the pane a user is looking at.

## Related

- {ref}`pane-interaction` — what to do with a pane once you hold one:
  `send_keys`, `capture_pane`, and waiting for output.
- {ref}`howto-send-keys-to-every-pane` — drive all of a window's panes at once.
- {ref}`traversal` — walking back up from a pane to its window, session, and
  server.
