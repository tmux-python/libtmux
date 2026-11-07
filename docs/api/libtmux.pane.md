(panes)=

# Panes

- Contain [pseudoterminal]s ([pty(4)][pty(4)])
- Exist inside {ref}`Windows`
- Identified by `%`, e.g. `%313`

[pseudoterminal]: https://en.wikipedia.org/wiki/Pseudoterminal
[pty(4)]: https://www.freebsd.org/cgi/man.cgi?query=pty&sektion=4

`width_cells` and `height_cells` return captured dimensions as `int | None`;
`is_active` and `is_dead` return captured flags as `bool | None`. These reads
perform no I/O and preserve `None` when a field was unavailable. The raw
`pane_*` fields and existing string-valued `width` and `height` aliases remain
available. Invalid manually assigned numeric text raises `ValueError` when
decoded.

```python
>>> isinstance(pane.width_cells, int)
True
>>> pane.width == pane.pane_width
True
>>> pane.is_dead
False
```

```{eval-rst}
.. autoclass:: libtmux.Pane
    :members:
    :inherited-members:
    :private-members:
    :show-inheritance:
    :member-order: bysource
```
