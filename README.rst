libtmux - library for managing tmux workspaces

|pypi| |docs| |build-status| |coverage| |license|

libtmux is the library that powers `tmuxp`_, a tool that helps tmux users
manage their workspaces.

Take control of tmux via python.

View the `documentation`_ homepage,  `API`_ information and `architectural 
details`_.

.. _tmuxp: https://github.com/tony/tmuxp
.. _documentation: https://libtmux.readthedocs.io/
.. _API: https://libtmux.readthedocs.io/api.html
.. _architectural details: https://libtmux.readthedocs.io/internals.html

install
-------

.. code-block:: sh

    $ [sudo] pip install libtmux

open a tmux session
-------------------

.. code-block:: sh

    $ tmux new-session -n libtmux_wins -s a_libtmux_session

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
    [Session($3 a_libtmux_session), Session($1 libtmux)]

find session::

    >>> server.getById('$3')
    Session($3 a_libtmux_session)

find session by dict lookup::

    >>> server.findWhere({ "session_name": "a_libtmux_session" })
    Session($3 a_libtmux_session)

assign session to ``session``::

    >>> session = server.findWhere({ "session_name": "a_libtmux_session" })

play with session::

    >>> session.new_window(attach=False, window_name="ha in the bg")
    Window(@8 2:ha in the bg, Session($3 a_libtmux_session))
    >>> session.kill_window("ha in")
    >>> session.new_window(attach=False, window_name="ha in the bg")
    Window(@11 3:ha in the bg, Session($3 a_libtmux_session))
    >>> session.kill_window('@12')
    >>> window = session.new_window(attach=False, window_name="check this out")
    >>> window.kill_window()

grab remaining tmux window::

    >>> window = session.attached_window()
    >>> window.split_window(attach=False)
    Pane(%23 Window(@10 1:libtmux_wins, Session($3 a_libtmux_session)))

rename window::

    >>> window.rename_window('libtmuxower')
    Window(@10 1:libtmuxower, Session($3 a_libtmux_session))

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

powerful traversal features::

    >>> pane.window
    Window(@10 1:libtmuxower, Session($3 a_libtmux_session))
    >>> pane.window.session
    Session($3 a_libtmux_session)

Project details
---------------

==============  ==========================================================
tmux support    1.8, 1.9a, 2.0, 2.1, 2.2
python support  2.6, 2.7, >= 3.3
Source          https://github.com/tony/libtmux
Docs            http://libtmux.rtfd.org
API             http://libtmux.readthedocs.io/en/latest/api.html
Changelog       http://libtmux.readthedocs.io/en/latest/history.html
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

.. _BSD: http://opensource.org/licenses/BSD-3-Clause
.. _developing and testing: http://libtmux.readthedocs.io/en/latest/developing.html
.. _installing bash completion: http://libtmux.readthedocs.io/en/latest/quickstart.html#bash-completion
.. _Developing and Testing: http://libtmux.readthedocs.io/en/latest/developing.html
.. _Issues tracker: https://github.com/tony/libtmux/issues

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
