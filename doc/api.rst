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


.. autodata:: libtmux.common.TMUX_MIN_VERSION

.. autodata:: libtmux.common.TMUX_MAX_VERSION

.. autoclass:: libtmux.common.TmuxRelationalObject
    :members:

.. autoclass:: libtmux.common.TmuxMappingObject
    :members:

.. autoclass:: libtmux.common.EnvironmentMixin
    :members:

.. autoclass:: libtmux.common.tmux_cmd

.. automethod:: libtmux.common.which

.. automethod:: libtmux.common.has_version

.. automethod:: libtmux.common.has_gt_version

.. automethod:: libtmux.common.has_gte_version

.. automethod:: libtmux.common.has_lt_version

.. automethod:: libtmux.common.has_lte_version

.. automethod:: libtmux.common.has_minimum_version

.. automethod:: libtmux.common.handle_option_error

Exceptions
----------

.. autoexception:: libtmux.exc.LibTmuxException

.. autoexception:: libtmux.exc.TmuxCommandNotFound

.. autoexception:: libtmux.exc.VersionTooLow

.. autoexception:: libtmux.exc.TmuxSessionExists

.. autoexception:: libtmux.exc.BadSessionName

.. autoexception:: libtmux.exc.OptionError

.. autoexception:: libtmux.exc.UnknownOption

.. autoexception:: libtmux.exc.InvalidOption

.. autoexception:: libtmux.exc.AmbiguousOption

Test tools
----------

.. automethod:: libtmux.test.get_test_session_name

.. automethod:: libtmux.test.get_test_window_name

.. automethod:: libtmux.test.temp_session

.. automethod:: libtmux.test.temp_window
