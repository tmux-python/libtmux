(sessions)=

# Sessions

- Exist inside {ref}`Servers`
- Contain {ref}`Windows` (which contain {ref}`Panes`)
- Identified by `$`, e.g. `$313`

## Async Methods

Session provides async versions of key methods for use in async applications:

- {meth}`~Session.anew_window` - Create new window asynchronously
- {meth}`~Session.arename_session` - Rename session asynchronously

See {ref}`async` for comprehensive async documentation.

## API Reference

```{eval-rst}
.. autoclass:: libtmux.Session
    :members:
    :inherited-members:
    :private-members:
    :show-inheritance:
    :member-order: bysource
```
