(servers)=

# Servers

- identified by _socket path_ and _socket name_
- may have >1 servers running of tmux at the same time.
- hold {ref}`Sessions` (which hold {ref}`Windows`, which hold
  {ref}`Panes`)

In tmux, a server is automatically started on your behalf
when you first run tmux.

```{eval-rst}
.. autoclass:: Server
    :noindex:
    :members:
    :inherited-members:
    :private-members:
    :show-inheritance:
    :member-order: bysource
```
