# -*- coding: utf-8 -*-
"""Test for tmuxp Session object."""
from __future__ import absolute_import, unicode_literals, with_statement

import logging

import pytest

from libtmux import Pane, Session, Window, exc
from libtmux.common import has_gte_version
from libtmux.test import TEST_SESSION_PREFIX, namer

logger = logging.getLogger(__name__)


def test_has_session(server, session):
    """Server.has_session returns True if has session_name exists."""
    TEST_SESSION_NAME = session.get('session_name')
    assert server.has_session(TEST_SESSION_NAME)
    if has_gte_version('2.1'):
        assert not server.has_session(TEST_SESSION_NAME[:-2])
        assert server.has_session(TEST_SESSION_NAME[:-2], exact=False)
    assert not server.has_session('asdf2314324321')


def test_select_window(session):
    """Session.select_window moves window."""
    # get the current window_base_index, since different user tmux config
    # may start at 0 or 1, or whatever they want.
    window_base_index = int(
        session.attached_window.get('window_index')
    )

    session.new_window(window_name='test_window')
    window_count = len(session._windows)

    assert window_count >= 2  # 2 or more windows

    assert len(session._windows) == window_count

    # tmux selects a window, moves to it, shows it as attached_window
    selected_window1 = session.select_window(window_base_index)
    assert isinstance(selected_window1, Window)
    attached_window1 = session.attached_window

    assert selected_window1 == attached_window1
    assert selected_window1.__dict__ == attached_window1.__dict__

    # again: tmux selects a window, moves to it, shows it as
    # attached_window
    selected_window2 = session.select_window(window_base_index + 1)
    assert isinstance(selected_window2, Window)
    attached_window2 = session.attached_window

    assert selected_window2 == attached_window2
    assert selected_window2.__dict__ == attached_window2.__dict__

    # assure these windows were really different
    assert selected_window1 != selected_window2
    assert selected_window1.__dict__ != selected_window2.__dict__


def test_select_window_returns_Window(session):
    """Session.select_window returns Window object."""

    window_count = len(session._windows)
    assert len(session._windows) == window_count
    window_base_index = int(
        session.attached_window.get('window_index'))

    assert isinstance(
        session.select_window(window_base_index), Window
    )


def test_attached_window(session):
    """Session.attached_window returns Window."""
    assert isinstance(session.attached_window, Window)


def test_attached_pane(session):
    """Session.attached_pane returns Pane."""
    assert isinstance(session.attached_pane, Pane)


def test_session_rename(session):
    """Session.rename_session renames session."""
    TEST_SESSION_NAME = session.get('session_name')
    test_name = 'testingdis_sessname'
    session.rename_session(test_name)
    assert session.get('session_name') == test_name
    session.rename_session(TEST_SESSION_NAME)
    assert session.get('session_name') == TEST_SESSION_NAME


def test_new_session(server):
    """Server.new_session creates new session."""
    new_session_name = TEST_SESSION_PREFIX + next(namer)
    new_session = server.new_session(
        session_name=new_session_name, detach=True)

    assert isinstance(new_session, Session)
    assert new_session.get('session_name') == new_session_name


def test_show_options(session):
    """Session.show_options() returns dict."""

    options = session.show_options()
    assert isinstance(options, dict)


def test_set_show_options_single(session):
    """Set option then Session.show_options(key)."""

    session.set_option('history-limit', 20)
    assert session.show_options('history-limit') == 20

    session.set_option('history-limit', 40)
    assert session.show_options('history-limit') == 40

    assert session.show_options()['history-limit'] == 40


def test_set_show_option(session):
    """Set option then Session.show_option(key)."""
    session.set_option('history-limit', 20)
    assert session.show_option('history-limit') == 20

    session.set_option('history-limit', 40)

    assert session.show_option('history-limit') == 40


def test_empty_session_option_returns_None(session):
    assert session.show_option('default-shell') is None


def test_show_option_unknown(session):
    """Session.show_option raises UnknownOption for invalid option."""
    with pytest.raises(exc.UnknownOption):
        session.show_option('moooz')


def test_show_option_ambiguous(session):
    """Session.show_option raises AmbiguousOption for ambiguous option."""
    with pytest.raises(exc.AmbiguousOption):
        session.show_option('bell-')


def test_set_option_ambigous(session):
    """Session.set_option raises AmbiguousOption for invalid option."""
    with pytest.raises(exc.AmbiguousOption):
        session.set_option('bell-', 43)


def test_set_option_invalid(session):
    """Session.set_option raises UnknownOption for invalid option."""
    if has_gte_version('2.4'):
        with pytest.raises(exc.InvalidOption):
            session.set_option('afewewfew', 43)
    else:
        with pytest.raises(exc.UnknownOption):
            session.set_option('afewewfew', 43)


def test_show_environment(session):
    """Session.show_environment() returns dict."""

    _vars = session.show_environment()
    assert isinstance(_vars, dict)


def test_set_show_environment_single(session):
    """Set environment then Session.show_environment(key)."""

    session.set_environment('FOO', 'BAR')
    assert session.show_environment('FOO') == 'BAR'

    session.set_environment('FOO', 'DAR')
    assert session.show_environment('FOO') == 'DAR'

    assert session.show_environment()['FOO'] == 'DAR'


def test_show_environment_not_set(session):
    """Not set environment variable returns None."""
    assert session.show_environment('BAR') is None


def test_remove_environment(session):
    """Remove environment variable."""
    assert session.show_environment('BAM') is None
    session.set_environment('BAM', 'OK')
    assert session.show_environment('BAM') == 'OK'
    session.remove_environment('BAM')
    assert session.show_environment('BAM') is None


def test_unset_environment(session):
    """Unset environment variable."""
    assert session.show_environment('BAM') is None
    session.set_environment('BAM', 'OK')
    assert session.show_environment('BAM') == 'OK'
    session.unset_environment('BAM')
    assert session.show_environment('BAM') is None


@pytest.mark.parametrize("session_name,raises", [
    ('hey.period', True),
    ('hey:its a colon', True),
    ('hey moo', False),
])
def test_periods_raise_badsessionname(server, session, session_name, raises):
    new_name = session_name + 'moo'  # used for rename / switch
    if raises:
        with pytest.raises(exc.BadSessionName):
            session.rename_session(new_name)

        with pytest.raises(exc.BadSessionName):
            server.new_session(session_name)

        with pytest.raises(exc.BadSessionName):
            server.has_session(session_name)

        with pytest.raises(exc.BadSessionName):
            server.switch_client(new_name)

        with pytest.raises(exc.BadSessionName):
            server.attach_session(new_name)

    else:
        server.new_session(session_name)
        server.has_session(session_name)
        session.rename_session(new_name)
        with pytest.raises(exc.LibTmuxException):
            server.switch_client(new_name)


def test_cmd_inserts_sesion_id(session):
    current_session_id = session.id
    last_arg = 'last-arg'
    cmd = session.cmd('not-a-command', last_arg)
    assert '-t' in cmd.cmd
    assert current_session_id in cmd.cmd
    assert cmd.cmd[-1] == last_arg
