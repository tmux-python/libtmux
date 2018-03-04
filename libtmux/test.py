# -*- coding: utf-8 -*-
"""Helper methods for libtmux and downstream libtmux libraries."""

from __future__ import absolute_import, unicode_literals, with_statement

import contextlib
import logging
import os
import tempfile
import time

logger = logging.getLogger(__name__)

TEST_SESSION_PREFIX = 'libtmux_'
RETRY_TIMEOUT_SECONDS = int(os.getenv('RETRY_TIMEOUT_SECONDS', 8))

namer = tempfile._RandomNameSequence()
current_dir = os.path.abspath(os.path.dirname(__file__))
example_dir = os.path.abspath(os.path.join(current_dir, '..', 'examples'))
fixtures_dir = os.path.realpath(os.path.join(current_dir, 'fixtures'))


def retry(seconds=RETRY_TIMEOUT_SECONDS):
    """Retry a block of code until a time limit or ``break``.

    .. code-block:: python

        while retry():
            p = w.attached_pane
            p.server._update_panes()
            if p.current_path == pane_path:
                break


    :param seconds: Seconds to retry, defaults to ``RETRY_TIMEOUT_SECONDS``,
        which is configurable via environmental variables.
    :type seconds: int
    :rtype: void
    """
    return (lambda: time.time() < time.time() + seconds)()


def get_test_session_name(server, prefix=TEST_SESSION_PREFIX):
    """Faker to create a session name that doesn't exist.

    :param server: libtmux server
    :type server: :class:`libtmux.Server`
    :param prefix: prefix for sessions (e.g. libtmux_). Defaults to
        ``TEST_SESSION_PREFIX``.
    :type prefix: string
    :rtype: string
    :returns: Random session name guaranteed to not collide with current ones
    """
    while True:
        session_name = prefix + next(namer)
        if not server.has_session(session_name):
            break
    return session_name


def get_test_window_name(session, prefix=TEST_SESSION_PREFIX):
    """Faker to create a window name that doesn't exist.

    :param session: libtmux session
    :type session: :class:`libtmux.Session`
    :param prefix: prefix for sessions (e.g. libtmux_). Defaults to
        ``TEST_SESSION_PREFIX``. ATM we reuse the test session prefix here.
    :type prefix: string
    :rtype: string
    :returns: Random window name guaranteed to not collide with current ones
    """
    while True:
        window_name = prefix + next(namer)
        if not session.find_where(window_name=window_name):
            break
    return window_name


@contextlib.contextmanager
def temp_session(server, *args, **kwargs):
    """Return a context manager with a temporary session.

    e.g.::

        with temp_session(server) as session:
            session.new_window(window_name='my window')

    The session will destroy itself upon closing with :meth:`Session.
    kill_session()`.

    If no ``session_name`` is entered, :func:`get_test_session_name` will make
    an unused session name.

    :args: Same arguments as :meth:`Server.new_session`
    :yields: Temporary session
    :rtype: :class:`Session`
    """

    if 'session_name' in kwargs:
        session_name = kwargs.pop('session_name')
    else:
        session_name = get_test_session_name(server)

    session = server.new_session(session_name, *args, **kwargs)

    try:
        yield session
    finally:
        if server.has_session(session_name):
            session.kill_session()
    return


@contextlib.contextmanager
def temp_window(session, *args, **kwargs):
    """Return a context manager with a temporary window.

    e.g.::

        with temp_window(session) as window:
            my_pane = window.split_window()

    The window will destroy itself upon closing with :meth:`window.
    kill_window()`.

    If no ``window_name`` is entered, :func:`get_test_window_name` will make
    an unused window name.

    :args: Same arguments as :meth:`Session.new_window`
    :yields: Temporary window
    :rtype: :class:`Window`
    """

    if 'window_name' not in kwargs:
        window_name = get_test_window_name(session)
    else:
        window_name = kwargs.pop('window_name')

    window = session.new_window(window_name, *args, **kwargs)

    # Get ``window_id`` before returning it, it may be killed within context.
    window_id = window.get('window_id')

    try:
        yield session
    finally:
        if session.findWhere(window_id=window_id):
            window.kill_window()
    return


class EnvironmentVarGuard(object):

    """Class to help protect the environment variable properly.  Can be used as
    a context manager.
      Vendorize to fix issue with Anaconda Python 2 not
      including test module, see #121.
    """

    def __init__(self):
        self._environ = os.environ
        self._unset = set()
        self._reset = dict()

    def set(self, envvar, value):
        if envvar not in self._environ:
            self._unset.add(envvar)
        else:
            self._reset[envvar] = self._environ[envvar]
        self._environ[envvar] = value

    def unset(self, envvar):
        if envvar in self._environ:
            self._reset[envvar] = self._environ[envvar]
            del self._environ[envvar]

    def __enter__(self):
        return self

    def __exit__(self, *ignore_exc):
        for envvar, value in self._reset.items():
            self._environ[envvar] = value
        for unset in self._unset:
            del self._environ[unset]
