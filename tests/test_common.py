# -*- coding: utf-8 -*-
"""Tests for utility functions in tmux."""

import re

import pytest

from libtmux.common import (
    has_required_tmux_version, which, session_check_name, is_version, tmux_cmd
)
from libtmux.exc import LibTmuxException, BadSessionName, TmuxCommandNotFound

version_regex = re.compile(r'([0-9]\.[0-9])|(master)')


def test_no_arg_uses_tmux_version():
    """Test the :meth:`has_required_tmux_version`."""
    result = has_required_tmux_version()
    assert version_regex.match(result) is not None


def test_allows_master_version():
    result = has_required_tmux_version('master')
    assert version_regex.match(result) is not None


def test_ignores_letter_versions():
    """Ignore letters such as 1.8b.

    See ticket https://github.com/tony/tmuxp/issues/55.

    In version 0.1.7 this is adjusted to use LooseVersion, in order to
    allow letters.

    """
    result = has_required_tmux_version('1.9a')
    assert version_regex.match(result) is not None

    result = has_required_tmux_version('1.8a')
    assert result == r'1.8'

    # Should not throw
    assert type(is_version('1.8')) is bool
    assert type(is_version('1.8a')) is bool
    assert type(is_version('1.9a')) is bool


def test_error_version_less_1_7():
    with pytest.raises(LibTmuxException) as excinfo:
        has_required_tmux_version('1.7')
        excinfo.match(r'tmuxp only supports')

    with pytest.raises(LibTmuxException) as excinfo:
        has_required_tmux_version('1.6a')

        excinfo.match(r'tmuxp only supports')

    has_required_tmux_version('1.9a')


def test_which_no_bin_found(monkeypatch):
    monkeypatch.setenv("PATH", "/")
    assert which('top')
    assert which('top', default_paths=[])
    assert not which('top', default_paths=[], append_env_path=False)
    assert not which('top', default_paths=['/'], append_env_path=False)


def test_tmux_cmd_raises_on_not_found(monkeypatch):
    with pytest.raises(TmuxCommandNotFound):
        tmux_cmd('-V', tmux_search_paths=[], append_env_path=False)

    tmux_cmd('-V')


@pytest.mark.parametrize("session_name,raises,exc_msg_regex", [
    ('', True, 'may not be empty'),
    (None, True, 'may not be empty'),
    ("my great session.", True, 'may not contain periods'),
    ("name: great session", True, 'may not contain colons'),
    ("new great session", False, None),
    ("ajf8a3fa83fads,,,a", False, None),
])
def test_session_check_name(session_name, raises, exc_msg_regex):
    if raises:
        with pytest.raises(BadSessionName) as exc_info:
            session_check_name(session_name)
        assert exc_info.match(exc_msg_regex)
    else:
        session_check_name(session_name)
