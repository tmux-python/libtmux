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

connect to a live tmux session:

.. code-block:: python

    >>> import libtmux
    >>> server = libtmux.Server()
    >>> server
    <libtmux.server.Server object at 0x7fbd622c1dd0>

list sessions:

.. code-block:: python

    >>> server.list_sessions()
    [Session($3 foo), Session($1 libtmux)]

find session:

.. code-block:: python

    >>> server.get_by_id('$3')
    Session($3 foo)

find session by dict lookup:

.. code-block:: python

    >>> server.find_where({ "session_name": "foo" })
    Session($3 foo)

assign session to ``session``:

.. code-block:: python

    >>> session = server.find_where({ "session_name": "foo" })

play with session:

.. code-block:: python

    >>> session.new_window(attach=False, window_name="ha in the bg")
    Window(@8 2:ha in the bg, Session($3 foo))
    >>> session.kill_window("ha in")

create new window in the background (don't switch to it):

.. code-block:: python

    >>> w = session.new_window(attach=False, window_name="ha in the bg")
    Window(@11 3:ha in the bg, Session($3 foo))

kill window object directly:

.. code-block:: python

    >>> w.kill_window()

grab remaining tmux window:

.. code-block:: python

    >>> window = session.attached_window
    >>> window.split_window(attach=False)
    Pane(%23 Window(@10 1:bar, Session($3 foo)))

rename window:

.. code-block:: python

    >>> window.rename_window('libtmuxower')
    Window(@10 1:libtmuxower, Session($3 foo))

create panes by splitting window:

.. code-block:: python

    >>> pane = window.split_window()
    >>> pane = window.split_window(attach=False)
    >>> pane.select_pane()
    >>> window = session.new_window(attach=False, window_name="test")
    >>> pane = window.split_window(attach=False)

send key strokes to panes:

.. code-block:: python

    >>> pane.send_keys('echo hey send now')

    >>> pane.send_keys('echo hey', enter=False)
    >>> pane.enter()

grab the output of pane:

.. code-block:: python

    >>> pane.clear()  # clear the pane
    >>> pane.send_keys('cowsay hello')
    >>> print('\n'.join(pane.cmd('capture-pane', '-p').stdout))

::

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
.. _developing and testing: http://libtmux.git-pull.com/developing.html
.. _tmuxp: https://github.com/tony/tmuxp
.. _documentation: https://libtmux.git-pull.com/
.. _API: https://libtmux.git-pull.com/api.html
.. _architectural details: https://libtmux.git-pull.com/about.html
.. _formats: http://man.openbsd.org/OpenBSD-5.9/man1/tmux.1#FORMATS
.. _target: http://man.openbsd.org/OpenBSD-5.9/man1/tmux.1#COMMANDS

Donations
---------

Your donations fund development of new features, testing and support.
Your money will go directly to maintenance and development of the project.
If you are an individual, feel free to give whatever feels right for the
value you get out of the project.

See donation options at https://git-pull.com/support.html.

Project details
---------------

==============  ==========================================================
tmux support    1.8, 1.9a, 2.0, 2.1, 2.2, 2.3
python support  2.6, 2.7, >= 3.3
Source          https://github.com/tony/libtmux
Docs            http://libtmux.git-pull.com
API             http://libtmux.git-pull.com/api.html
Changelog       http://libtmux.git-pull.com/history.html
Issues          https://github.com/tony/libtmux/issues
Travis          http://travis-ci.org/tony/libtmux
Test Coverage   https://coveralls.io/r/tony/libtmux
pypi            https://pypi.python.org/pypi/libtmux
Open Hub        https://www.openhub.net/p/libtmux-python
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

.. |coverage| image:: https://codecov.io/gh/tony/libtmux/branch/master/graph/badge.svg
    :alt: Code Coverage
    :target: https://codecov.io/gh/tony/libtmux
    
.. |license| image:: https://img.shields.io/github/license/tony/libtmux.svg
    :alt: License 

.. |docs| image:: https://readthedocs.org/projects/libtmux/badge/?version=latest
    :alt: Documentation Status
    :scale: 100%
    :target: https://readthedocs.org/projects/libtmux/
