(traversal)=

# Traverse the tmux hierarchy

The object hierarchy mirrors tmux: a {class}`~libtmux.Server` contains
{class}`~libtmux.Session` objects, sessions contain
{class}`~libtmux.Window` objects, and windows contain
{class}`~libtmux.Pane` objects. Every object retains enough identity to move
back toward its parents.

## When to use it

Use traversal when you already have one object and need a directly related
object. It is the shortest path for common work such as finding a session's
active pane or moving from a pane back to its server.

Child accessors such as {attr}`~libtmux.Session.windows` and
{attr}`~libtmux.Window.panes` query tmux each time. Bind the returned collection
when several operations should share one view.

## Tutorial

### Happy path

Create a window, take its active pane, then move down and back up the hierarchy:

```python
>>> query_window = session.new_window(window_name="query-hierarchy")
>>> query_pane = query_window.active_pane
>>> query_pane is not None
True
>>> query_pane.session.session_id == session.session_id
True
>>> any(item.window_id == query_window.window_id for item in session.windows)
True
```

### Sad path

A Python object retains its identifier after another actor removes the tmux
object. Refreshing that stale point object reports disappearance explicitly:

```python
>>> from libtmux import exc
>>> stale_window = session.new_window(window_name="query-stale")
>>> stale_window.kill()
>>> try:
...     stale_window.refresh()
... except exc.TmuxObjectDoesNotExist:
...     print("window is stale")
window is stale
```

If you only need the current children, read the parent collection again. If you
need to validate a retained point object, call its `refresh()` method and handle
{exc}`~libtmux.exc.TmuxObjectDoesNotExist`.

## API reference

The styled API entries below expose the hierarchy accessors and point-object
refresh behavior:

```{eval-rst}
.. autoattribute:: libtmux.Server.sessions
   :no-index:

.. autoattribute:: libtmux.Server.windows
   :no-index:

.. autoattribute:: libtmux.Server.panes
   :no-index:

.. autoattribute:: libtmux.Session.windows
   :no-index:

.. autoattribute:: libtmux.Session.active_window
   :no-index:

.. autoattribute:: libtmux.Session.active_pane
   :no-index:

.. autoattribute:: libtmux.Window.panes
   :no-index:

.. autoattribute:: libtmux.Window.active_pane
   :no-index:

.. autoattribute:: libtmux.Window.session
   :no-index:

.. autoattribute:: libtmux.Pane.window
   :no-index:

.. autoattribute:: libtmux.Pane.session
   :no-index:

.. automethod:: libtmux.Window.refresh
   :no-index:

.. automethod:: libtmux.Pane.refresh
   :no-index:
```

## Related topics

- [QueryList filtering](query-list.md) narrows a fetched child collection.
- [Locating yourself](../self_location.md) starts traversal from the current
  tmux process environment.
- [Architecture](../architecture.md) explains object identity and targets.
