(servers)=

# Servers

- identified by _socket path_ and _socket name_
- may have >1 servers running of tmux at the same time.
- contain {ref}`Sessions` (which contain {ref}`Windows`, which contain
  {ref}`Panes`)

In tmux, a server is automatically started on your behalf
when you first run tmux.

```{eval-rst}
.. autoapiclass:: libtmux.Server
    :members:
    :inherited-members:
    :private-members:
    :show-inheritance:
    :member-order: bysource
```
