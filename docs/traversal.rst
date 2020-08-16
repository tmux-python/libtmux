.. _Traversal:

=========
Traversal
=========

libtmux convenient access to move around the hierachy of sessions,
windows and panes in tmux.

this is done by libtmux's object abstraction of `target`\_s (the ``-t``
command) and the permanent internal ID's tmux gives to objects.

open two terminals:

terminal one: start tmux in a seperate terminal::

    $ tmux

.. NOTE::

    Make sure you have :ref:`libtmux installed <installation>`::

       $ pip install libtmux

    To upgrade::

       $ pip install -U libtmux

terminal two, ``python`` or ``ptpython`` if you have it::

    $ python

import tmux::

   import tmux

attach default tmux :class:`libtmux.Server` to ``t``::

   >>> t = libtmux.Server();
   >>> t
   <libtmux.server.Server object at 0x10edd31d0>

get first session :class:`Session` to `session`::

    >>> session = t.sessions[0]
    >>> session
    Session($0 libtmux)

get a list of sessions::

    >>> t.sessions
    [Session($0 libtmux), Session($1 tmuxp)]

iterate through sessions in a server::

    >>> for sess in t.sessions:
    ...     print(sess)

    Session($0 libtmux)
    Session($1 tmuxp)

grab a :class:`Window` from a session::

    >>> session.windows[0]
    Window(@1 1:libtmux, Session($0 libtmux))

grab the currently focused window from session:

    >>> session.attached_window
    Window(@2 2:docs, Session($0 libtmux))

grab the currently focused :class:`Pane` from session::

    >>> session.attached_pane
    Pane(%5 Window(@2 2:docs, Session($0 libtmux)))

assign the attached pane to ``p``::

    >>> p = session.attached_pane

access the window/server of a pane::

    >>> p.window
    Window(@2 2:docs, Session($0 libtmux))

    >>> p.server
    <libtmux.server.Server object at 0x104191a10>

.. _target: http://man.openbsd.org/OpenBSD-5.9/man1/tmux.1#COMMANDS
