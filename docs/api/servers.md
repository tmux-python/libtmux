(servers)=

# Servers

- Identified by _socket path_ and _socket name_
- May have >1 servers running of tmux at the same time.
- Contain {ref}`Sessions` (which contain {ref}`Windows`, which contain
  {ref}`Panes`)

tmux initializes a server automatically on first running (e.g. executing `tmux`)

## Async Methods

Server provides async versions of key methods for use in async applications:

- {meth}`~Server.ahas_session` - Check if session exists asynchronously
- {meth}`~Server.anew_session` - Create new session asynchronously

See {ref}`async` for comprehensive async documentation.

## API Reference

```{eval-rst}
.. autoclass:: libtmux.Server
    :members:
    :inherited-members:
    :private-members:
    :show-inheritance:
    :member-order: bysource
```
