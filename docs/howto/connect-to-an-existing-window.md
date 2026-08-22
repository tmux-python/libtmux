(howto-connect-to-an-existing-window)=

# Connect to an existing window

A {class}`~libtmux.Window` sits between the session that holds it and the panes
it holds, and tmux gives you two ways to say which one you mean. Its *index* is
a position — where the window sits in the session's list, the number you see in
the status bar. Its *name* is a label, defaulting to whatever is running and
freely renamed. Neither is unique across the server: two sessions can each have
a window at index 1, and each call it `logs`.

That is why a window lookup always starts from a session. List the whole server
once and the overlap shows itself.

```python
from libtmux import Server

server = Server()

for session in server.sessions:
    for window in session.windows:
        print(f"{session.session_name}:{window.window_index}\t{window.window_name}")
```

The `session:index` form is tmux's own way of naming a window unambiguously,
and it is what you would type after `-t` on the command line.

## Find one inside a session

With a session in hand, {attr}`~libtmux.Session.windows` is a
{class}`~libtmux._internal.query_list.QueryList` you can narrow.
{meth}`~libtmux._internal.query_list.QueryList.get` with `default=None` returns
the window or nothing, without raising.

```python
session = server.sessions.get(session_name="editor", default=None)

if session is None:
    print("no session named 'editor' — pick one from the listing above")
else:
    by_name = session.windows.get(window_name="logs", default=None)
    by_index = session.windows.get(
        window_index=session.active_window.window_index,
        default=None,
    )
    print(f"by name:  {by_name}")
    print(f"by index: {by_index}")
```

{attr}`~libtmux.Session.active_window` is the window that session would show a
client right now, and it is the shortest way to get a window you can work with
when you don't care which one it is.

:::{warning}
{attr}`~libtmux.Window.window_index` is a **string**, not an integer — it is a
tmux format value, and libtmux hands it to you as tmux reports it. So
`windows.get(window_index="1")` matches and `windows.get(window_index=1)` does
not. With `default=None` that mismatch does not raise; it quietly returns
`None`, which reads exactly like "no such window".

Don't hard-code the number either. Windows start at index 0 or index 1 depending
on the `base-index` setting in effect, so `"0"` is the first window on your
machine and nothing at all on someone else's. Ask an object for its index, as
above, or match on the name.
:::

## Hold the id, not the position

Both handles above move. A window is renamed by its owner or by the program
running in it; its index shifts when a window before it is closed or the session
is renumbered. The {attr}`~libtmux.Window.window_id` — the `@1` in a window's
repr — is fixed for the window's lifetime, and it is what to store when you plan
to come back.

{meth}`~libtmux.Window.from_window_id` turns one back into an object. It targets
tmux directly instead of scanning a listing, so it always resolves to exactly
one window.

```python
from libtmux import Window

window = session.active_window
window_id = window.window_id

found = Window.from_window_id(server, window_id)
print(found.window_name, found.window_id == window_id)
```

"Exactly one" is a stronger promise than it sounds, because a window can be
linked into several sessions at once — one window, one id, a position in each
session that holds it. A server-wide `server.windows.get(window_id=...)` raises
{exc}`~libtmux.exc.MultipleObjectsReturned` on such a window: that collection
enumerates positions, and it finds one row per session. Naming the id as a tmux
target instead sidesteps the whole question. See {ref}`winlinks` for when this
happens and what {attr}`~libtmux.Window.linked_sessions` tells you about it.

## Related

- {ref}`howto-connect-to-an-existing-pane` — one more level down, into the
  window you just found.
- {ref}`howto-connect-to-an-existing-session` — the level above, if you don't
  hold a session yet.
- {ref}`traversal` — moving up and down the hierarchy from any object.
