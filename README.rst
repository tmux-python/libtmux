libtmux - scripting library for tmux

|pypi| |docs| |build-status| |coverage| |license|

libtmux is the tool behind `tmuxp`_, a tmux workspace manager in python.

it builds upon tmux' `target`_ and `formats`_ to create an object
mappings to traverse, inspect and interact with live tmux sesssions.

view the `documentation`_ homepage,  `API`_ information and `architectural
details`_.

install
-------

.. code-block:: sh

    $ [sudo] pip install libtmux

open a tmux session
-------------------

session name ``foo``, window name ``bar``

.. code-block:: sh

    $ tmux new-session -s foo -n bar

pilot your tmux session via python
----------------------------------

.. code-block:: sh

   $ python

   # or for nice autocomplete and syntax highlighting
   $ pip install ptpython
   $ ptpython

.. code-block:: python

    >>> import libtmux
    >>> server = libtmux.Server()
    >>> server
    <libtmux.server.Server object at 0x7fbd622c1dd0>

list sessions::

    >>> server.list_sessions()
    [Session($3 foo), Session($1 libtmux)]

find session::

    >>> server.get_by_id('$3')
    Session($3 foo)

find session by dict lookup::

    >>> server.find_where({ "session_name": "foo" })
    Session($3 foo)

assign session to ``session``::

    >>> session = server.find_where({ "session_name": "foo" })

play with session::

    >>> session.new_window(attach=False, window_name="ha in the bg")
    Window(@8 2:ha in the bg, Session($3 foo))
    >>> session.kill_window("ha in")

create new window in the background (don't switch to it)::

    >>> w = session.new_window(attach=False, window_name="ha in the bg")
    Window(@11 3:ha in the bg, Session($3 foo))

kill window object directly::

    >>> w.kill_window()

grab remaining tmux window::

    >>> window = session.attached_window()
    >>> window.split_window(attach=False)
    Pane(%23 Window(@10 1:bar, Session($3 foo)))

rename window::

    >>> window.rename_window('libtmuxower')
    Window(@10 1:libtmuxower, Session($3 foo))

create panes by splitting window::

    >>> pane = window.split_window()
    >>> pane = window.split_window(attach=False)
    >>> pane.select_pane()
    >>> window = session.new_window(attach=False, window_name="test")
    >>> pane = window.split_window(attach=False)

send key strokes to panes::

    >>> pane.send_keys('echo hey send now')

    >>> pane.send_keys('echo hey', enter=False)
    >>> pane.enter()

grab the output of pane::

    >>> pane.clear()  # clear the pane
    >>> pane.send_keys('cowsay hello')
    >>> print('\n'.join(pane.cmd('capture-pane', '-p').stdout))
    sh-3.2$ cowsay 'hello'
     _______
    < hello >
     -------
            \   ^__^
             \  (oo)\_______
                (__)\       )\/\
                    ||----w |
                    ||     ||

powerful traversal features::

    >>> pane.window
    Window(@10 1:libtmuxower, Session($3 foo))
    >>> pane.window.session
    Session($3 foo)

.. _BSD: http://opensource.org/licenses/BSD-3-Clause
.. _developing and testing: http://libtmux.readthedocs.io/developing.html
.. _tmuxp: https://github.com/tony/tmuxp
.. _documentation: https://libtmux.readthedocs.io/
.. _API: https://libtmux.readthedocs.io/api.html
.. _architectural details: https://libtmux.readthedocs.io/internals.html
.. _formats: http://man.openbsd.org/OpenBSD-5.9/man1/tmux.1#FORMAT
.. _target: http://man.openbsd.org/OpenBSD-5.9/man1/tmux.1#COMMANDS

Project details
---------------

==============  ==========================================================
tmux support    1.8, 1.9a, 2.0, 2.1, 2.2
python support  2.6, 2.7, >= 3.3
Source          https://github.com/tony/libtmux
Docs            http://libtmux.rtfd.org
API             http://libtmux.readthedocs.io/api.html
Changelog       http://libtmux.readthedocs.io/history.html
Issues          https://github.com/tony/libtmux/issues
Travis          http://travis-ci.org/tony/libtmux
Test Coverage   https://coveralls.io/r/tony/libtmux
pypi            https://pypi.python.org/pypi/libtmux
Open Hub        https://www.openhub.net/p/libtmux
License         `BSD`_.
git repo        .. code-block:: bash

                    $ git clone https://github.com/tony/libtmux.git
install stable  .. code-block:: bash

                    $ sudo pip install libtmux
install dev     .. code-block:: bash

                    $ git clone https://github.com/tony/libtmux.git libtmux
                    $ cd ./libtmux
                    $ virtualenv .venv
                    $ source .venv/bin/activate
                    $ pip install -e .

                See the `developing and testing`_ page in the docs for
                more.
tests           .. code-block:: bash

                    $ make test
==============  ==========================================================

.. |pypi| image:: https://img.shields.io/pypi/v/libtmux.svg
    :alt: Python Package
    :target: http://badge.fury.io/py/libtmux

.. |build-status| image:: https://img.shields.io/travis/tony/libtmux.svg
   :alt: Build Status
   :target: https://travis-ci.org/tony/libtmux

.. |coverage| image:: https://img.shields.io/coveralls/tony/libtmux.svg
    :alt: Code Coverage
    :target: https://coveralls.io/r/tony/libtmux?branch=master
    
.. |license| image:: https://img.shields.io/github/license/tony/libtmux.svg
    :alt: License 

.. |docs| image:: https://readthedocs.org/projects/libtmux/badge/?version=latest
    :alt: Documentation Status
    :scale: 100%
    :target: https://readthedocs.org/projects/libtmux/
