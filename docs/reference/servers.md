(servers)=

# Servers

- Identified by _socket path_ and _socket name_
- May have >1 servers running of tmux at the same time.
- Contain {ref}`Sessions` (which contain {ref}`Windows`, which contain
  {ref}`Panes`)

tmux initializes a server on automatically on first running (e.g. executing `tmux`)

```{eval-rst}
.. autoclass:: libtmux.Server
    :members:
    :inherited-members:
    :private-members:
    :show-inheritance:
    :member-order: bysource
```
