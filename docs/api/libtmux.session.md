(sessions)=

# Sessions

- Exist inside {ref}`Servers`
- Contain {ref}`Windows` (which contain {ref}`Panes`)
- Identified by `$`, e.g. `$313`

`attached_count` returns the captured number of attached clients as `int | None`
without performing I/O. `None` means the field was unavailable. The raw
`session_attached` string remains available; invalid manually assigned numeric
text raises `ValueError` when decoded.

```{eval-rst}
.. autoclass:: libtmux.Session
    :members:
    :inherited-members:
    :private-members:
    :show-inheritance:
    :member-order: bysource
```
