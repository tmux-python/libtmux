(windows)=

# Windows

- Exist inside {ref}`Sessions`
- Contain {ref}`Panes`
- Identified by `@`, e.g. `@313`

```{module} libtmux
:no-index:
```

`width_cells` and `height_cells` return captured dimensions as `int | None`.
`is_active` returns the captured active flag within the session as `bool | None`.
These properties perform no I/O; `None` means the field was unavailable.
The raw `window_*` fields and existing string-valued dimension aliases remain
unchanged. Invalid manually assigned numeric text raises `ValueError` when
decoded.

```{eval-rst}
.. autoclass:: Window
    :members:
    :inherited-members:
    :private-members:
    :show-inheritance:
    :member-order: bysource
```
