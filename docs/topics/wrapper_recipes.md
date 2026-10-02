(wrapper-recipes)=

# Replacing wrapper code

Scripts that drive tmux tend to grow the same helpers: type `cd` and `source`
into a new pane, keep a dictionary from names to panes, assume the session is
the only one. libtmux already covers each of these. This page shows the
built-in call next to the habit it replaces, so you can delete the helper.

Every block below is self-contained and runs against a throwaway tmux server.

## Start a pane in the right place

The habit: create a window, then type `cd ~/project; source .venv/bin/activate;
export MODE=ci` into it with {meth}`~libtmux.Pane.send_keys`. The keystrokes
land in whatever the shell is doing, show up in scrollback, and race the
shell's startup.

Pass the starting state to tmux instead. {meth}`Session.new_window()
<libtmux.Session.new_window>`, {meth}`Window.split() <libtmux.Window.split>`
and {meth}`Server.new_session() <libtmux.Server.new_session>` take
`start_directory=`, `environment=`, and (windows) `window_shell=`, so the
process starts there, with those variables already set:

```python
>>> from libtmux.test.retry import retry_until

>>> window = session.new_window(
...     window_name="build",
...     start_directory="/tmp",
...     environment={"MODE": "ci"},
...     window_shell='sh -c "pwd; echo mode=$MODE; exec sh"',
... )

>>> pane = window.active_pane

>>> retry_until(lambda: "mode=ci" in "\n".join(pane.capture_pane()))
True

>>> "/tmp" in pane.capture_pane()
True
```

`window_shell=` replaces the default shell, so use it to boot straight into a
virtualenv's interpreter or a server rather than into a prompt you then type
at. {ref}`workspace-setup` covers the other arguments.

## Find a window or pane by name

The habit: remember each window or pane you create in a dictionary, so you can
find it later. The dictionary goes stale the moment anything else renames or
closes a window, and it is one more thing to pass around.

Ask tmux instead. Every collection is a
{class}`~libtmux._internal.query_list.QueryList`, so
{meth}`~libtmux._internal.query_list.QueryList.get` returns exactly one match
(and raises if there are none or several) and
{meth}`~libtmux._internal.query_list.QueryList.filter` returns every match:

```python
>>> window = session.new_window(window_name="api")

>>> session.windows.get(window_name="api") == window
True

>>> len(session.windows.filter(window_name__startswith="a")) >= 1
True
```

Panes work the same way, keyed by any pane attribute. A pane's title is one
such attribute, set with {meth}`Pane.set_title() <libtmux.Pane.set_title>`:

```python
>>> window = session.new_window()

>>> second = window.split()

>>> second.set_title("worker")
Pane(...)

>>> window.panes.get(pane_title="worker") == second
True

>>> window.panes.filter(pane_title__startswith="wor") == [second]
True
```

A program running in the pane can rewrite its own title, so treat a title as
a hint, not an identity. The pane id (`%3`) is the stable handle: keep that,
and rebuild the object with {meth}`Pane.from_pane_id()
<libtmux.Pane.from_pane_id>`. {ref}`querylist-filtering` lists the lookup
suffixes.

## Find yourself instead of assuming one session

The habit: take `server.sessions[0]`, or the only session, and hope that is
where the code is running. It breaks as soon as a second session exists.

Code running inside a pane does not have to guess. tmux sets `$TMUX` and
`$TMUX_PANE` for it, and {meth}`Pane.from_env() <libtmux.Pane.from_env>`
reads them back:

```python
>>> socket_path = server.cmd(
...     "display-message", "-p", "-t", pane.pane_id, "#{socket_path}"
... ).stdout[0]

>>> env = {"TMUX": f"{socket_path},1,{session.session_id}", "TMUX_PANE": pane.pane_id}

>>> Pane.from_env(env).pane_id == pane.pane_id
True
```

Inside a real pane you call `Pane.from_env()` with no argument; the mapping is
only here because these docs do not run in a pane. {ref}`self-location` covers
the session, window and server versions and what happens outside tmux.
