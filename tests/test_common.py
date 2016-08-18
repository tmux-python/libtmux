# -*- coding: utf-8 -*-
"""Tests for utility functions in tmux."""

import re

import pytest

from libtmux.common import has_required_tmux_version, which
from libtmux.exc import LibTmuxException

version_regex = re.compile(r'[0-9]\.[0-9]')


def test_no_arg_uses_tmux_version():
    """Test the :meth:`has_required_tmux_version`."""
    result = has_required_tmux_version()
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


def test_error_version_less_1_7():
    with pytest.raises(LibTmuxException) as excinfo:
        has_required_tmux_version('1.7')
        excinfo.match(r'tmuxp only supports')

    with pytest.raises(LibTmuxException) as excinfo:
        has_required_tmux_version('1.6a')

        excinfo.match(r'tmuxp only supports')

    has_required_tmux_version('1.9a')


def test_which_no_tmuxp_found(monkeypatch):
    monkeypatch.setenv("PATH", "/")
    which('tmuxp')
    which('tmuxp', '/')
