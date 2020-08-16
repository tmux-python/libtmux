.. _Servers:

=======
Servers
=======

- identified by *socket path* and *socket name* 
- may have >1 servers running of tmux at the same time.
- hold :ref:`Sessions` (which hold :ref:`Windows`, which hold
  :ref:`Panes`)

In tmux, a server is automatically started on your behalf
when you first run tmux.

.. module:: libtmux

.. autoclass:: Server
    :noindex:
    :members:
    :inherited-members:
    :private-members:
    :show-inheritance:
    :member-order: bysource
