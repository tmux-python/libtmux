# Query raw rows with Neo

{func}`~libtmux.neo.fetch_objs` and {func}`~libtmux.neo.fetch_obj` expose
fresh tmux format rows as dictionaries. They are the data boundary underneath
the object model and avoid constructing Session, Window, or Pane objects.

## When to use it

Use Neo when a consumer needs raw fields, custom object construction, or an
explicit distinction between a missing target and a dead server. Prefer the
object hierarchy when its relationships and methods are useful.

`fetch_objs()` runs one list command and returns every parsed row.
`fetch_obj()` requires an identity field and value and applies tmux's winlink
selection rules when a linked window produces several rows.

## Tutorial

### Happy path

Fetch a collection, then fetch one pane by its permanent identifier:

```python
>>> from libtmux.neo import fetch_obj, fetch_objs
>>> rows = fetch_objs(server=server, list_cmd="list-sessions")
>>> any(row["session_id"] == session.session_id for row in rows)
True
>>> pane_row = fetch_obj(
...     server=pane.server,
...     obj_key="pane_id",
...     obj_id=pane.pane_id,
...     list_cmd="list-panes",
...     list_extra_args=("-t", pane.pane_id),
... )
>>> pane_row["pane_id"] == pane.pane_id
True
```

### Sad path

A reachable server with no such target raises a specific point-lookup error:

```python
>>> from libtmux import exc
>>> from libtmux.neo import fetch_obj
>>> try:
...     fetch_obj(
...         server=server,
...         obj_key="pane_id",
...         obj_id="%99999",
...         list_cmd="list-panes",
...         list_extra_args=("-t", "%99999"),
...     )
... except exc.TmuxObjectDoesNotExist:
...     print("pane does not exist")
pane does not exist
```

Other command failures remain {exc}`~libtmux.exc.LibTmuxException`. This keeps
"target is gone" distinct from "tmux is unreachable."

## API reference

```{eval-rst}
.. autofunction:: libtmux.neo.fetch_objs
   :no-index:

.. autofunction:: libtmux.neo.fetch_obj
   :no-index:
```

## Related topics

- [Hierarchy traversal](hierarchy.md) wraps raw rows as relational objects.
- [tmux format queries](tmux-formats.md) shares the server-side `filter=`
  behavior.
- [Public versus internal APIs](../public-vs-internal.md) explains stability
  expectations.
