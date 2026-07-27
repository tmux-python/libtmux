(querylist-filtering)=

# Filter collections with QueryList

Collection accessors return
{class}`~libtmux._internal.query_list.QueryList`, a list subtype with
Django-style attribute lookups. Filtering happens in Python after tmux has
returned the rows and libtmux has built the objects.

## When to use it

Use {meth}`~libtmux._internal.query_list.QueryList.filter` for small, already
fetched collections and expressive Python lookups. Use
{meth}`~libtmux._internal.query_list.QueryList.get` only when zero or multiple
matches are both errors.

Common suffixes are `exact`, `iexact`, `contains`, `icontains`, `startswith`,
`istartswith`, `endswith`, `iendswith`, `in`, `nin`, `regex`, and `iregex`.
Multiple keyword arguments and chained filters combine with AND.

## Tutorial

### Happy path

Filter windows by a case-insensitive prefix, then use `get()` for an exact
point lookup:

```python
>>> _ = session.new_window(window_name="Query-API")
>>> _ = session.new_window(window_name="query-worker")
>>> matches = session.windows.filter(window_name__istartswith="query-")
>>> sorted(item.window_name for item in matches)
['Query-API', 'query-worker']
>>> matches.get(window_name="query-worker").window_name
'query-worker'
```

### Sad path

`get()` refuses to choose arbitrarily when more than one object matches:

```python
>>> from libtmux import exc
>>> _ = session.new_window(window_name="query-duplicate-one")
>>> _ = session.new_window(window_name="query-duplicate-two")
>>> try:
...     session.windows.get(window_name__startswith="query-duplicate")
... except exc.MultipleObjectsReturned:
...     print("query is ambiguous")
query is ambiguous
```

An absent match raises {exc}`~libtmux.exc.ObjectDoesNotExist`; pass
`default=None` only when absence is an expected value. A default never hides an
ambiguous match.

## API reference

```{eval-rst}
.. automethod:: libtmux._internal.query_list.QueryList.filter
   :no-index:

.. automethod:: libtmux._internal.query_list.QueryList.get
   :no-index:
```

## Related topics

- [Hierarchy traversal](hierarchy.md) explains where collections come from.
- [tmux format queries](tmux-formats.md) filters rows before object creation.
- {ref}`winlinks` explains why a server-wide window query can contain
  multiple rows for one window.

(winlinks)=

### Shared windows and ambiguity

Server-wide window and pane collections enumerate tmux winlinks: the edges from
sessions to windows. A window linked into two sessions therefore appears twice.
Use `filter()` when both relationships are meaningful; use
{meth}`~libtmux.Window.from_window_id` when a permanent window identifier should
resolve to one object.
