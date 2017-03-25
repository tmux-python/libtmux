# -*- coding: utf-8 -*-
"""Helper methods and mixins.

libtmux.common
~~~~~~~~~~~~~~

"""
import collections
import logging
import os
import re
import sys
import subprocess
from distutils.version import StrictVersion, LooseVersion

from . import exc
from ._compat import console_to_str

logger = logging.getLogger(__name__)


class EnvironmentMixin(object):

    """Mixin class for managing session and server level environment
    variables in tmux.

    """

    _add_option = None

    def __init__(self, add_option=None):
        self._add_option = add_option

    def set_environment(self, name, value):
        """Set environment ``$ tmux set-environment <name> <value>``.

        :param name: the environment variable name. such as 'PATH'.
        :type option: string
        :param value: environment value.
        :type value: string

        """

        args = ['set-environment']
        if self._add_option:
            args += [self._add_option]

        args += [name, value]

        proc = self.cmd(*args)

        if proc.stderr:
            if isinstance(proc.stderr, list) and len(proc.stderr) == int(1):
                proc.stderr = proc.stderr[0]
            raise ValueError('tmux set-environment stderr: %s' % proc.stderr)

    def unset_environment(self, name):
        """Unset environment variable ``$ tmux set-environment -u <name>``.

        :param name: the environment variable name. such as 'PATH'.
        :type option: string
        """

        args = ['set-environment']
        if self._add_option:
            args += [self._add_option]
        args += ['-u', name]

        proc = self.cmd(*args)

        if proc.stderr:
            if isinstance(proc.stderr, list) and len(proc.stderr) == int(1):
                proc.stderr = proc.stderr[0]
            raise ValueError('tmux set-environment stderr: %s' % proc.stderr)

    def remove_environment(self, name):
        """Remove environment variable ``$ tmux set-environment -r <name>``.

        :param name: the environment variable name. such as 'PATH'.
        :type option: string
        """

        args = ['set-environment']
        if self._add_option:
            args += [self._add_option]
        args += ['-r', name]

        proc = self.cmd(*args)

        if proc.stderr:
            if isinstance(proc.stderr, list) and len(proc.stderr) == int(1):
                proc.stderr = proc.stderr[0]
            raise ValueError('tmux set-environment stderr: %s' % proc.stderr)

    def show_environment(self, name=None):
        """Show environment ``$tmux show-environment -t [session] <name>``.

        Return dict of environment variables for the session or the value of a
        specific variable if the name is specified.

        :param name: the environment variable name. such as 'PATH'.
        :type option: string
        """
        tmux_args = ['show-environment']
        if self._add_option:
            tmux_args += [self._add_option]
        if name:
            tmux_args += [name]
        vars = self.cmd(*tmux_args).stdout
        vars = [tuple(item.split('=', 1)) for item in vars]
        vars_dict = {}
        for t in vars:
            if len(t) == 2:
                vars_dict[t[0]] = t[1]
            elif len(t) == 1:
                vars_dict[t[0]] = True
            else:
                raise ValueError('unexpected variable %s', t)

        if name:
            return vars_dict.get(name)

        return vars_dict


class tmux_cmd(object):

    """:term:`tmux(1)` command via :py:mod:`subprocess`.

    Usage::

        proc = tmux_cmd('new-session', '-s%' % 'my session')

        if proc.stderr:
            raise exc.LibTmuxException(
                'Command: %s returned error: %s' % (proc.cmd, proc.stderr)
            )

        print('tmux command returned %s' % proc.stdout)

    Equivalent to:

    .. code-block:: bash

        $ tmux new-session -s my session

    :versionchanged: 0.8
        Renamed from ``tmux`` to ``tmux_cmd``.

    """

    def __init__(self, *args, **kwargs):
        cmd = [which('tmux')]
        cmd += args  # add the command arguments to cmd
        cmd = [str(c) for c in cmd]

        self.cmd = cmd

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.process.wait()
            stdout = self.process.stdout.read()
            self.process.stdout.close()
            stderr = self.process.stderr.read()
            self.process.stderr.close()
        except Exception as e:
            logger.error(
                'Exception for %s: \n%s' % (
                    subprocess.list2cmdline(cmd),
                    e
                )
            )

        self.stdout = console_to_str(stdout)
        self.stdout = self.stdout.split('\n')
        self.stdout = list(filter(None, self.stdout))  # filter empty values

        self.stderr = console_to_str(stderr)
        self.stderr = self.stderr.split('\n')
        self.stderr = list(filter(None, self.stderr))  # filter empty values

        if 'has-session' in cmd and len(self.stderr):
            if not self.stdout:
                self.stdout = self.stderr[0]

        logger.debug('self.stdout for %s: \n%s' %
                      (' '.join(cmd), self.stdout))


class TmuxMappingObject(collections.MutableMapping):

    """Base: :py:class:`collections.MutableMapping`.

    Convenience container. Base class for :class:`Pane`, :class:`Window`,
    :class:`Session` and :class:`Server`.

    Instance attributes for useful information :term:`tmux(1)` uses for
    Session, Window, Pane, stored :attr:`self._info`. For example, a
    :class:`Window` will have a ``window_id`` and ``window_name``.

    ================ ================================== ==============
    Object           formatter_prefix                   value
    ================ ================================== ==============
    :class:`Server`  n/a                                n/a
    :class:`Session` :attr:`Session.formatter_prefix`   session\_
    :class:`Window`  :attr:`Window.formatter_prefix`    window\_
    :class:`Pane`    :attr:`Pane.formatter_prefix`      pane\_
    ================ ================================== ==============
    """

    def __getitem__(self, key):
        return self._info[key]

    def __setitem__(self, key, value):
        self._info[key] = value
        self.dirty = True

    def __delitem__(self, key):
        del self._info[key]
        self.dirty = True

    def keys(self):
        """Return list of keys."""
        return self._info.keys()

    def __iter__(self):
        return self._info.__iter__()

    def __len__(self):
        return len(self._info.keys())

    def __getattr__(self, key):
        try:
            return self._info[self.formatter_prefix + key]
        except:
            raise AttributeError('%s has no property %s' %
                                 (self.__class__, key))


class TmuxRelationalObject(object):

    """Base Class for managing tmux object child entities.  .. # NOQA

    Manages collection of child objects  (a :class:`Server` has a collection of
    :class:`Session` objects, a :class:`Session` has collection of
    :class:`Window`)

    Children of :class:`TmuxRelationalObject` are going to have a
    ``self.children``, ``self.child_id_attribute``.

    ================ ========================= =================================
    Object           .children                 method
    ================ ========================= =================================
    :class:`Server`  :attr:`Server._sessions`  :meth:`Server.list_sessions`
    :class:`Session` :attr:`Sessions._windows` :meth:`Session.list_windows`
    :class:`Window`  :attr:`Windows._panes`    :meth:`Window.list_panes`
    :class:`Pane`    n/a                       n/a
    ================ ========================= =================================

    ================ ================================== ==============
    Object           child_id_attribute                 value
    ================ ================================== ==============
    :class:`Server`  :attr:`Server.child_id_attribute`  session_id
    :class:`Session` :attr:`Session.child_id_attribute` window_id
    :class:`Window`  :attr:`Window.child_id_attribute`  pane_id
    :class:`Pane`    n/a                                n/a
    ================ ================================== ==============
    """

    def find_where(self, attrs):
        """Return object on first match.

        :versionchanged: 0.4
            Renamed from ``.findWhere`` to ``.find_where``.

        """
        try:
            return self.where(attrs)[0]
        except IndexError:
            return None

    def where(self, attrs, first=False):
        """Return objects matching child objects properties.

        :param attrs: tmux properties to match
        :type attrs: dict
        :rtype: list

        """

        # from https://github.com/serkanyersen/underscore.py
        def by(val, *args):
            for key, value in attrs.items():
                try:
                    if attrs[key] != val[key]:
                        return False
                except KeyError:
                    return False
                return True

        if first:
            return list(filter(by, self.children))[0]
        else:
            return list(filter(by, self.children))

    def get_by_id(self, id):
        """Return object based on ``child_id_attribute``.

        Based on `.get()`_ from `backbone.js`_.

        .. _backbone.js: http://backbonejs.org/
        .. _.get(): http://backbonejs.org/#Collection-get

        :param id:
        :type id: string
        :rtype: object

        """
        for child in self.children:
            if child[self.child_id_attribute] == id:
                return child
            else:
                continue

        return None


def which(exe=None,
          default_paths=[
              '/bin', '/sbin', '/usr/bin', '/usr/sbin', '/usr/local/bin']
          ):
    """Return path of bin. Python clone of /usr/bin/which.

    from salt.util - https://www.github.com/saltstack/salt - license apache

    :param exe: Application to search PATHs for.
    :type exe: string
    :param default_path: Application to search PATHs for.
    :type default_path: list
    :rtype: string

    """
    def _is_executable_file_or_link(exe):
        # check for os.X_OK doesn't suffice because directory may executable
        return (os.access(exe, os.X_OK) and
                (os.path.isfile(exe) or os.path.islink(exe)))

    if _is_executable_file_or_link(exe):
        # executable in cwd or fullpath
        return exe

    # Enhance POSIX path for the reliability at some environments, when
    # $PATH is changing. This also keeps order, where 'first came, first
    # win' for cases to find optional alternatives
    search_path = os.environ.get('PATH') and \
        os.environ['PATH'].split(os.pathsep) or list()
    for default_path in default_paths:
        if default_path not in search_path:
            search_path.append(default_path)
    os.environ['PATH'] = os.pathsep.join(search_path)
    for path in search_path:
        full_path = os.path.join(path, exe)
        if _is_executable_file_or_link(full_path):
            return full_path
    logger.info(
        '\'{0}\' could not be found in the following search path: '
        '\'{1}\''.format(exe, search_path))

    return None


def is_version(version):
    """Return True if tmux version installed.

    :param version: version, '1.8'
    :param type: string
    :rtype: bool

    """
    if sys.platform.startswith("openbsd"):
        if LooseVersion(version) > LooseVersion('2.1'):
            return 'openbsd'
        else:
            return False

    proc = tmux_cmd('-V')

    if proc.stderr:
        raise exc.LibTmuxException(proc.stderr)

    installed_version = proc.stdout[0].split('tmux ')[1]

    return LooseVersion(installed_version) == LooseVersion(version)


def has_required_tmux_version(version=None):
    """Return if tmux meets version requirement. Version >1.8 or above.

    :versionchanged: 0.1.7
        Versions will now remove trailing letters per `Issue 55`_.

        .. _Issue 55: https://github.com/tony/tmuxp/issues/55.

    """

    if not version:
        if sys.platform.startswith("openbsd"):  # openbsd has no tmux -V
            return '2.3'

        proc = tmux_cmd('-V')

        if proc.stderr:
            if proc.stderr[0] == 'tmux: unknown option -- V':
                raise exc.LibTmuxException(
                    'libtmux supports tmux 1.8 and greater. This system'
                    ' is running tmux 1.3 or earlier.')
            raise exc.LibTmuxException(proc.stderr)

        version = proc.stdout[0].split('tmux ')[1]

    # Allow latest tmux HEAD
    if version == 'master':
        return version

    version = re.sub(r'[a-z]', '', version)

    if StrictVersion(version) <= StrictVersion("1.7"):
        raise exc.LibTmuxException(
            'libtmux only supports tmux 1.8 and greater. This system'
            ' has %s installed. Upgrade your tmux to use libtmux.' % version
        )
    return version


def session_check_name(session_name):
    """Raises exception session name invalid, modeled after tmux function.

    tmux(1) session names may not be empty, or include periods or colons.
    These delimiters are reserved for noting session, window and pane.

    :param session_name: name of session
    :type session_name: string
    :returns: void
    :raises: :exc:`exc.BadSessionName`
    """
    if not session_name or len(session_name) == 0:
        raise exc.BadSessionName("tmux session names may not be empty.")
    elif '.' in session_name:
        raise exc.BadSessionName(
            "tmux session name \"%s\" may not contain periods.", session_name)
    elif ':' in session_name:
        raise exc.BadSessionName(
            "tmux session name \"%s\" may not contain colons.", session_name)
