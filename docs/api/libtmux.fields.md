(api-fields)=

# Typed fields

- `obj.typed` reads a tmux object's numeric and flag fields as `int` and `bool`
- The dataclass fields keep tmux's text, so existing code is unchanged
- A field is optional when tmux leaves it empty for some live objects or the
  running tmux is too old to know it

```{eval-rst}
.. autoclass:: libtmux.fields.ObjFields
    :show-inheritance:

.. autoclass:: libtmux.fields.ClientFields
    :show-inheritance:
```

{exc}`~libtmux.exc.FieldNotReported` is raised when a required field is read
from an object that was never listed.
