.. _api:

=============
API Reference
=============

.. seealso::
    :ref:`quickstart`.

.. module:: libtmux

Server Object
-------------

.. autoclass:: Server
    :members:
    :inherited-members:
    :private-members:
    :show-inheritance:
    :member-order: bysource

Session Object
--------------

.. autoclass:: Session
    :members:
    :inherited-members:
    :private-members:
    :show-inheritance:
    :member-order: bysource

Window Object
-------------

.. autoclass:: Window
    :members:
    :inherited-members:
    :private-members:
    :show-inheritance:
    :member-order: bysource

Pane Object
-----------

.. autoclass:: Pane
    :members:
    :inherited-members:
    :private-members:
    :show-inheritance:
    :member-order: bysource

Internals
---------

.. autoclass:: libtmux.common.TmuxRelationalObject
    :members:

.. autoclass:: libtmux.common.TmuxMappingObject
    :members:

.. autoclass:: libtmux.common.tmux_cmd

.. automethod:: libtmux.common.has_required_tmux_version

.. automethod:: libtmux.common.which

.. automethod:: libtmux.common.is_version

Exceptions
----------

.. autoexception:: libtmux.exc.LibTmuxException

.. autoexception:: libtmux.exc.TmuxSessionExists

Test tools
----------

.. automethod:: libtmux.test.get_test_session_name

.. automethod:: libtmux.test.get_test_window_name

.. automethod:: libtmux.test.temp_session

.. automethod:: libtmux.test.temp_window
