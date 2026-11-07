"""Tests for utility functions in libtmux."""

from __future__ import annotations

import locale
import logging
import re
import sys
import typing as t

import pytest

import libtmux
from libtmux import exc
from libtmux._compat import LooseVersion
from libtmux.common import (
    get_libtmux_version,
    session_check_name,
    tmux_cmd,
)

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session

version_regex = re.compile(r"([0-9]\.[0-9])|(master)")


def test_tmux_cmd_raises_on_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify raises if tmux command not found."""
    monkeypatch.setenv("PATH", "")
    with pytest.raises(exc.TmuxCommandNotFound):
        tmux_cmd("-V")


def test_tmux_cmd_unicode(session: Session) -> None:
    """Verify tmux commands with unicode."""
    session.cmd("new-window", "-n", "юникод", "-F", "Ελληνικά", target=3)


class SessionCheckName(t.NamedTuple):
    """Test fixture for test_session_check_name()."""

    test_id: str
    session_name: str | None
    raises: bool
    exc_msg_regex: str | None


SESSION_CHECK_NAME_FIXTURES: list[SessionCheckName] = [
    SessionCheckName(
        test_id="empty_string",
        session_name="",
        raises=True,
        exc_msg_regex="empty",
    ),
    SessionCheckName(
        test_id="none_value",
        session_name=None,
        raises=True,
        exc_msg_regex="empty",
    ),
    SessionCheckName(
        test_id="contains_period",
        session_name="my great session.",
        raises=True,
        exc_msg_regex="contains periods",
    ),
    SessionCheckName(
        test_id="contains_colon",
        session_name="name: great session",
        raises=True,
        exc_msg_regex="contains colons",
    ),
    SessionCheckName(
        test_id="valid_name",
        session_name="new great session",
        raises=False,
        exc_msg_regex=None,
    ),
    SessionCheckName(
        test_id="valid_with_special_chars",
        session_name="ajf8a3fa83fads,,,a",
        raises=False,
        exc_msg_regex=None,
    ),
]


@pytest.mark.parametrize(
    list(SessionCheckName._fields),
    SESSION_CHECK_NAME_FIXTURES,
    ids=[test.test_id for test in SESSION_CHECK_NAME_FIXTURES],
)
def test_session_check_name(
    test_id: str,
    session_name: str | None,
    raises: bool,
    exc_msg_regex: str | None,
) -> None:
    """Verify session_check_name()."""
    if raises:
        with pytest.raises(exc.BadSessionName) as exc_info:
            session_check_name(session_name)
        if exc_msg_regex is not None:
            assert exc_info.match(exc_msg_regex)
    else:
        session_check_name(session_name)


def test_get_libtmux_version() -> None:
    """Verify get_libtmux_version()."""
    from libtmux.__about__ import __version__

    version = get_libtmux_version()
    assert isinstance(version, LooseVersion)
    assert LooseVersion(__version__) == version


def test_tmux_cmd_pre_execution_logging(
    caplog: pytest.LogCaptureFixture,
    server: Server,
) -> None:
    """Verify tmux_cmd logs command before execution."""
    with caplog.at_level(logging.DEBUG, logger="libtmux.common"):
        server.cmd("list-sessions")
    running_records = [
        r
        for r in caplog.records
        if hasattr(r, "tmux_cmd") and not hasattr(r, "tmux_exit_code")
    ]
    assert len(running_records) > 0
    assert "list-sessions" in running_records[0].tmux_cmd


def test_libtmux_exception_subcommand_default_none() -> None:
    """Backward-compat: existing call sites (no kwarg) get subcommand=None."""
    err = exc.LibTmuxException(["no last window"])
    assert err.subcommand is None
    # str(err) reproduces only the args, preserving pre-0.57 shape.
    assert "no last window" in str(err)
    assert not str(err).startswith(":")


def test_libtmux_exception_subcommand_tags_str() -> None:
    """When ``subcommand`` is set, str(exc) prefixes ``"<subcommand>: …"``."""
    err = exc.LibTmuxException(["no last window"], subcommand="last-window")
    assert err.subcommand == "last-window"
    assert str(err).startswith("last-window:")
    assert "no last window" in str(err)


def test_raise_if_stderr_no_stderr_is_noop(session: libtmux.Session) -> None:
    """``raise_if_stderr`` returns silently when proc.stderr is empty."""
    from libtmux.common import raise_if_stderr

    proc = session.cmd("display-message", "-p", "#{version}")
    raise_if_stderr(proc, "display-message")  # must not raise


def test_raise_if_stderr_raises_with_subcommand_tag(
    session: libtmux.Session,
) -> None:
    """``raise_if_stderr`` raises ``LibTmuxException`` tagged with subcommand."""
    from libtmux.common import raise_if_stderr

    # Provoke a tmux stderr: ask list-clients with a non-existent target.
    proc = session.server.cmd("list-clients", "-t", "$nonexistent_session_id_for_test")
    assert proc.stderr  # sanity check the fixture

    with pytest.raises(exc.LibTmuxException) as excinfo:
        raise_if_stderr(proc, "list-clients")

    assert excinfo.value.subcommand == "list-clients"
    assert str(excinfo.value).startswith("list-clients:")


def test_raise_if_stderr_str_shape_exact(session: libtmux.Session) -> None:
    """Lock down ``str(exc)`` and ``exc.args[0]`` against future drift.

    The breaking-change documentation promises a flat string in
    ``str(exc)`` and a flat string in ``exc.args[0]``. If a future change
    re-introduces a list-shaped ``proc.stderr`` into ``LibTmuxException``,
    this test catches it where ``startswith`` / substring matches won't.
    """
    from libtmux.common import raise_if_stderr

    proc = session.cmd("last-window")
    assert proc.stderr == ["no last window"]

    with pytest.raises(exc.LibTmuxException) as excinfo:
        raise_if_stderr(proc, "last-window")

    assert str(excinfo.value) == "last-window: no last window"
    assert excinfo.value.args == ("no last window",)
    assert excinfo.value.subcommand == "last-window"


@pytest.mark.skipif(
    sys.flags.utf8_mode != 0,
    reason="PYTHONUTF8 mode forces UTF-8, masking the locale bug",
)
def test_tmux_cmd_format_separator_survives_non_utf8_locale(
    session: Session,
) -> None:
    """FORMAT_SEPARATOR must survive a non-UTF-8 locale round-trip through tmux_cmd.

    Regression test for the encoding bug introduced in commit 1a5e69a2
    (``tmux_cmd: Remove console_to_str(), use text=True``). When
    ``subprocess.Popen`` receives ``text=True`` without an explicit
    ``encoding="utf-8"``, CPython falls back to the process locale encoding. On
    a ``C`` locale the FORMAT_SEPARATOR character U+241E (UTF-8 bytes
    ``e2 90 9e``) is decoded as escaped bytes, corrupting every
    ``parse_output()`` call downstream.

    This test guards the explicit ``encoding="utf-8"`` passed to
    ``subprocess.Popen`` in ``tmux_cmd.__init__``.
    """
    from libtmux.formats import FORMAT_SEPARATOR
    from libtmux.neo import get_output_format, parse_output

    server = session.server

    tmux_version = server._get_version()
    _fields, fmt_str = get_output_format("list-sessions", tmux_version)

    old_lc_ctype = locale.setlocale(locale.LC_CTYPE)
    try:
        locale.setlocale(locale.LC_CTYPE, "C")
        proc = server.cmd("list-sessions", f"-F{fmt_str}")
    finally:
        locale.setlocale(locale.LC_CTYPE, old_lc_ctype)
    assert proc.stdout

    line = proc.stdout[0]

    assert FORMAT_SEPARATOR in line, (
        f"FORMAT_SEPARATOR U+241E not found in output; "
        f"got {line[:80]!r}... (likely decoded with wrong encoding)"
    )

    result = parse_output(line, "list-sessions", tmux_version)
    assert isinstance(result, dict)
    assert "session_id" in result
