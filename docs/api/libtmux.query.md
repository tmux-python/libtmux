# QueryList

Import {class}`~libtmux.QueryList` from the package root. It is the same list
subclass returned by session, window and pane listings. Iteration, slicing and
comprehensions keep their existing Python list behavior.

```python
>>> from libtmux import QueryList
>>> values = QueryList([1, 2, 3])
>>> values.filter(lambda value: value > 1)
[2, 3]
>>> values.get(2)
2
>>> values.get(9, default="missing")
'missing'
```

`get()` without a default returns the element type or raises
{class}`~libtmux.exc.ObjectDoesNotExist`. Supplying a default adds that default's
type to the return type. Both forms raise
{class}`~libtmux.exc.MultipleObjectsReturned` for an ambiguous match. Filtering
and lookup perform no I/O; obtaining `server.sessions` still performs a live
read with classic libtmux's listing behavior.

```{eval-rst}
.. autoclass:: libtmux.QueryList
   :members:
```
