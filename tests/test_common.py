"""Tests for utility functions in libtmux."""

from __future__ import annotations

import inspect
import locale
import logging
import os
import pathlib
import re
import signal
import stat
import subprocess
import sys
import typing as t

import pytest

import libtmux
from libtmux import common, exc
from libtmux._compat import LooseVersion
from libtmux.common import (
    TMUX_MAX_VERSION,
    TMUX_MIN_VERSION,
    get_libtmux_version,
    get_version,
    has_gt_version,
    has_gte_version,
    has_lt_version,
    has_lte_version,
    has_minimum_version,
    has_version,
    session_check_name,
    tmux_cmd,
)
from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    from libtmux.server import Server
    from libtmux.session import Session

version_regex = re.compile(r"([0-9]\.[0-9])|(master)")


def test_has_version() -> None:
    """Test has_version()."""
    assert has_version(str(get_version()))


def test_get_version_is_memoized_for_same_tmux_bin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two calls with the same tmux_bin fork tmux -V once.

    Validates the @functools.cache contract: identical-arg calls hit the
    cache after the first miss.
    """
    call_count = {"n": 0}

    class _MockProc:
        stdout: t.ClassVar[list[str]] = ["tmux 3.6a"]
        stderr: t.ClassVar[list[str]] = []

    def _mock_tmux_cmd(*args: t.Any, **kwargs: t.Any) -> _MockProc:
        call_count["n"] += 1
        return _MockProc()

    monkeypatch.setattr(libtmux.common, "tmux_cmd", _mock_tmux_cmd)
    get_version.cache_clear()

    v1 = get_version()
    v2 = get_version()

    assert v1 == v2
    assert call_count["n"] == 1


def test_get_version_cache_keyed_by_tmux_bin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Different tmux_bin args cache independently; same arg revisits hit."""
    call_count = {"n": 0}
    versions = {"/path/a/tmux": "tmux 3.4", "/path/b/tmux": "tmux 3.6a"}

    class _MockProc:
        def __init__(self, line: str) -> None:
            self.stdout = [line]
            self.stderr: list[str] = []

    def _mock_tmux_cmd(*args: t.Any, **kwargs: t.Any) -> _MockProc:
        call_count["n"] += 1
        return _MockProc(versions[kwargs["tmux_bin"]])

    monkeypatch.setattr(libtmux.common, "tmux_cmd", _mock_tmux_cmd)
    get_version.cache_clear()

    a1 = get_version(tmux_bin="/path/a/tmux")
    b1 = get_version(tmux_bin="/path/b/tmux")
    a2 = get_version(tmux_bin="/path/a/tmux")

    assert a1 != b1
    assert a1 == a2
    assert call_count["n"] == 2  # /a once, /b once, /a hits cache


def test_get_version_cache_clear_invalidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cache_clear() forces a fresh subprocess on the next call."""
    call_count = {"n": 0}

    class _MockProc:
        stdout: t.ClassVar[list[str]] = ["tmux 3.6a"]
        stderr: t.ClassVar[list[str]] = []

    def _mock_tmux_cmd(*args: t.Any, **kwargs: t.Any) -> _MockProc:
        call_count["n"] += 1
        return _MockProc()

    monkeypatch.setattr(libtmux.common, "tmux_cmd", _mock_tmux_cmd)
    get_version.cache_clear()

    get_version()
    get_version()
    assert call_count["n"] == 1

    get_version.cache_clear()
    get_version()
    assert call_count["n"] == 2


def test_get_version_binary_swap_requires_explicit_cache_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Documents the sticky-cache trap when tmux_bin=None and PATH changes.

    Simulates a user upgrading tmux mid-process: two consecutive
    ``get_version()`` calls with ``tmux_bin=None`` see different
    underlying binaries, but the cache pins the first answer. The
    escape hatch is ``get_version.cache_clear()`` — this test asserts
    the trap is real and the escape hatch works.
    """
    versions = ["tmux 3.2a", "tmux 3.6a"]
    call_count = {"n": 0}

    class _MockProc:
        def __init__(self, line: str) -> None:
            self.stdout = [line]
            self.stderr: list[str] = []

    def _mock_tmux_cmd(*args: t.Any, **kwargs: t.Any) -> _MockProc:
        proc = _MockProc(versions[call_count["n"]])
        call_count["n"] += 1
        return proc

    monkeypatch.setattr(libtmux.common, "tmux_cmd", _mock_tmux_cmd)
    get_version.cache_clear()

    first = get_version()
    assert str(first) == "3.2"

    # "Binary swap" — PATH changed, but cache is sticky.
    second = get_version()
    assert str(second) == "3.2"  # Stale: still the cached 3.2a.
    assert call_count["n"] == 1  # No fresh subprocess.

    # Escape hatch.
    get_version.cache_clear()
    third = get_version()
    assert str(third) == "3.6"  # Fresh lookup.
    assert call_count["n"] == 2


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


class VersionComparisonFixture(t.NamedTuple):
    """Test fixture for version comparison functions."""

    test_id: str
    version: str
    comparison_type: t.Literal["gt", "gte", "lt", "lte"]
    expected: bool


VERSION_COMPARISON_FIXTURES: list[VersionComparisonFixture] = [
    # Greater than tests
    VersionComparisonFixture(
        test_id="gt_older_version",
        version="1.6",
        comparison_type="gt",
        expected=True,
    ),
    VersionComparisonFixture(
        test_id="gt_older_version_with_letter",
        version="1.6b",
        comparison_type="gt",
        expected=True,
    ),
    VersionComparisonFixture(
        test_id="gt_newer_version",
        version="4.0",
        comparison_type="gt",
        expected=False,
    ),
    VersionComparisonFixture(
        test_id="gt_newer_version_with_letter",
        version="4.0b",
        comparison_type="gt",
        expected=False,
    ),
    # Greater than or equal tests
    VersionComparisonFixture(
        test_id="gte_older_version",
        version="1.6",
        comparison_type="gte",
        expected=True,
    ),
    VersionComparisonFixture(
        test_id="gte_older_version_with_letter",
        version="1.6b",
        comparison_type="gte",
        expected=True,
    ),
    VersionComparisonFixture(
        test_id="gte_current_version",
        version=str(get_version()),
        comparison_type="gte",
        expected=True,
    ),
    VersionComparisonFixture(
        test_id="gte_newer_version",
        version="4.0",
        comparison_type="gte",
        expected=False,
    ),
    VersionComparisonFixture(
        test_id="gte_newer_version_with_letter",
        version="4.0b",
        comparison_type="gte",
        expected=False,
    ),
    # Less than tests
    VersionComparisonFixture(
        test_id="lt_newer_version_with_letter",
        version="4.0a",
        comparison_type="lt",
        expected=True,
    ),
    VersionComparisonFixture(
        test_id="lt_newer_version",
        version="4.0",
        comparison_type="lt",
        expected=True,
    ),
    VersionComparisonFixture(
        test_id="lt_older_version",
        version="1.7",
        comparison_type="lt",
        expected=False,
    ),
    VersionComparisonFixture(
        test_id="lt_current_version",
        version=str(get_version()),
        comparison_type="lt",
        expected=False,
    ),
    # Less than or equal tests
    VersionComparisonFixture(
        test_id="lte_newer_version_with_letter",
        version="4.0a",
        comparison_type="lte",
        expected=True,
    ),
    VersionComparisonFixture(
        test_id="lte_newer_version",
        version="4.0",
        comparison_type="lte",
        expected=True,
    ),
    VersionComparisonFixture(
        test_id="lte_current_version",
        version=str(get_version()),
        comparison_type="lte",
        expected=True,
    ),
    VersionComparisonFixture(
        test_id="lte_older_version",
        version="1.7",
        comparison_type="lte",
        expected=False,
    ),
    VersionComparisonFixture(
        test_id="lte_older_version_with_letter",
        version="1.7b",
        comparison_type="lte",
        expected=False,
    ),
]


@pytest.mark.parametrize(
    list(VersionComparisonFixture._fields),
    VERSION_COMPARISON_FIXTURES,
    ids=[test.test_id for test in VERSION_COMPARISON_FIXTURES],
)
def test_version_comparison(
    test_id: str,
    version: str,
    comparison_type: t.Literal["gt", "gte", "lt", "lte"],
    expected: bool,
) -> None:
    """Test version comparison functions."""
    comparison_funcs = {
        "gt": has_gt_version,
        "gte": has_gte_version,
        "lt": has_lt_version,
        "lte": has_lte_version,
    }
    assert comparison_funcs[comparison_type](version) == expected


class VersionParsingFixture(t.NamedTuple):
    """Test fixture for version parsing and validation."""

    test_id: str
    mock_stdout: list[str] | None
    mock_stderr: list[str] | None
    mock_platform: str | None
    expected_version: str | None
    raises: bool
    exc_msg_regex: str | None


VERSION_PARSING_FIXTURES: list[VersionParsingFixture] = [
    VersionParsingFixture(
        test_id="master_version",
        mock_stdout=["tmux master"],
        mock_stderr=None,
        mock_platform=None,
        expected_version=f"{TMUX_MAX_VERSION}-master",
        raises=False,
        exc_msg_regex=None,
    ),
    VersionParsingFixture(
        test_id="next_version",
        mock_stdout=["tmux next-3.8"],
        mock_stderr=None,
        mock_platform=None,
        expected_version="3.8",
        raises=False,
        exc_msg_regex=None,
    ),
    VersionParsingFixture(
        test_id="release_candidate",
        mock_stdout=["tmux 3.8-rc"],
        mock_stderr=None,
        mock_platform=None,
        expected_version="3.8",
        raises=False,
        exc_msg_regex=None,
    ),
    VersionParsingFixture(
        test_id="numbered_release_candidate",
        mock_stdout=["tmux 3.8-rc3"],
        mock_stderr=None,
        mock_platform=None,
        expected_version="3.8",
        raises=False,
        exc_msg_regex=None,
    ),
    VersionParsingFixture(
        test_id="openbsd_version",
        mock_stdout=None,
        mock_stderr=["tmux: unknown option -- V"],
        mock_platform="openbsd 5.2",
        expected_version=f"{TMUX_MAX_VERSION}-openbsd",
        raises=False,
        exc_msg_regex=None,
    ),
    VersionParsingFixture(
        test_id="too_low_version",
        mock_stdout=None,
        mock_stderr=["tmux: unknown option -- V"],
        mock_platform=None,
        expected_version=None,
        raises=True,
        exc_msg_regex="does not meet the minimum tmux version requirement",
    ),
]


@pytest.mark.parametrize(
    list(VersionParsingFixture._fields),
    VERSION_PARSING_FIXTURES,
    ids=[test.test_id for test in VERSION_PARSING_FIXTURES],
)
def test_version_parsing(
    monkeypatch: pytest.MonkeyPatch,
    test_id: str,
    mock_stdout: list[str] | None,
    mock_stderr: list[str] | None,
    mock_platform: str | None,
    expected_version: str | None,
    raises: bool,
    exc_msg_regex: str | None,
) -> None:
    """Test version parsing and validation."""

    class MockTmuxOutput:
        stdout = mock_stdout
        stderr = mock_stderr

    def mock_tmux_cmd(*args: t.Any, **kwargs: t.Any) -> MockTmuxOutput:
        return MockTmuxOutput()

    monkeypatch.setattr(libtmux.common, "tmux_cmd", mock_tmux_cmd)
    if mock_platform is not None:
        monkeypatch.setattr(sys, "platform", mock_platform)

    if raises:
        with pytest.raises(exc.LibTmuxException) as exc_info:
            get_version()
        if exc_msg_regex is not None:
            exc_info.match(exc_msg_regex)
    else:
        assert get_version() == expected_version
        assert has_minimum_version()
        assert has_gte_version(TMUX_MIN_VERSION)
        assert has_gt_version(TMUX_MAX_VERSION)


class VersionValidationFixture(t.NamedTuple):
    """Test fixture for version validation tests."""

    test_id: str
    mock_min_version: str | None
    mock_version: str | None
    check_type: t.Literal["min_version", "has_version", "type_check"]
    raises: bool
    exc_msg_regex: str | None


VERSION_VALIDATION_FIXTURES: list[VersionValidationFixture] = [
    # Letter version tests
    VersionValidationFixture(
        test_id="accepts_letter_in_min_version_1_9a",
        mock_min_version="1.9a",
        mock_version=None,
        check_type="min_version",
        raises=False,
        exc_msg_regex=None,
    ),
    VersionValidationFixture(
        test_id="accepts_letter_in_min_version_1_8a",
        mock_min_version="1.8a",
        mock_version=None,
        check_type="min_version",
        raises=False,
        exc_msg_regex=None,
    ),
    VersionValidationFixture(
        test_id="accepts_version_1_8",
        mock_min_version=None,
        mock_version="1.8",
        check_type="type_check",
        raises=False,
        exc_msg_regex=None,
    ),
    VersionValidationFixture(
        test_id="accepts_version_1_8a",
        mock_min_version=None,
        mock_version="1.8a",
        check_type="type_check",
        raises=False,
        exc_msg_regex=None,
    ),
    VersionValidationFixture(
        test_id="accepts_version_1_9a",
        mock_min_version=None,
        mock_version="1.9a",
        check_type="type_check",
        raises=False,
        exc_msg_regex=None,
    ),
    # Version too low tests
    VersionValidationFixture(
        test_id="rejects_version_1_7",
        mock_min_version=None,
        mock_version="1.7",
        check_type="min_version",
        raises=True,
        exc_msg_regex=r"libtmux only supports",
    ),
    # Additional test cases for version validation
    VersionValidationFixture(
        test_id="accepts_master_version",
        mock_min_version=None,
        mock_version="master",
        check_type="type_check",
        raises=False,
        exc_msg_regex=None,
    ),
    VersionValidationFixture(
        test_id="accepts_next_version",
        mock_min_version=None,
        mock_version="next-3.4",
        check_type="type_check",
        raises=False,
        exc_msg_regex=None,
    ),
    VersionValidationFixture(
        test_id="accepts_openbsd_version",
        mock_min_version=None,
        mock_version="3.3-openbsd",
        check_type="type_check",
        raises=False,
        exc_msg_regex=None,
    ),
    VersionValidationFixture(
        test_id="accepts_dev_version",
        mock_min_version=None,
        mock_version="3.3-dev",
        check_type="type_check",
        raises=False,
        exc_msg_regex=None,
    ),
    VersionValidationFixture(
        test_id="accepts_rc_version",
        mock_min_version=None,
        mock_version="3.3-rc2",
        check_type="type_check",
        raises=False,
        exc_msg_regex=None,
    ),
]


@pytest.mark.parametrize(
    list(VersionValidationFixture._fields),
    VERSION_VALIDATION_FIXTURES,
    ids=[test.test_id for test in VERSION_VALIDATION_FIXTURES],
)
def test_version_validation(
    monkeypatch: pytest.MonkeyPatch,
    test_id: str,
    mock_min_version: str | None,
    mock_version: str | None,
    check_type: t.Literal["min_version", "has_version", "type_check"],
    raises: bool,
    exc_msg_regex: str | None,
) -> None:
    """Test version validation."""
    if mock_min_version is not None:
        monkeypatch.setattr(libtmux.common, "TMUX_MIN_VERSION", mock_min_version)

    if mock_version is not None:

        def mock_get_version(tmux_bin: str | None = None) -> LooseVersion:
            return LooseVersion(mock_version)

        monkeypatch.setattr(libtmux.common, "get_version", mock_get_version)

    if check_type == "min_version":
        if raises:
            with pytest.raises(exc.LibTmuxException) as exc_info:
                has_minimum_version()
            if exc_msg_regex is not None:
                exc_info.match(exc_msg_regex)
        else:
            assert has_minimum_version()
    elif check_type == "type_check":
        assert mock_version is not None  # For type checker
        assert isinstance(has_version(mock_version), bool)


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

    tmux_version = str(get_version(tmux_bin=server.tmux_bin))
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


@pytest.mark.parametrize("locale_name", ["C", "POSIX"])
def test_tmux_cmd_listings_survive_non_utf8_client_locale(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
    locale_name: str,
) -> None:
    """A non-UTF-8 locale in the environment must not alter tmux's output.

    Without ``-u`` tmux rewrites every non-ASCII character in format output
    to ``_``: ``FORMAT_SEPARATOR`` first, so listings fail to parse, then
    any non-ASCII name or title. ``LC_ALL`` wins over ``LC_CTYPE``, so
    setting the latter does not help.
    """
    monkeypatch.setenv("LC_ALL", locale_name)
    monkeypatch.delenv("LC_CTYPE", raising=False)
    monkeypatch.delenv("LANG", raising=False)

    session = server.new_session(session_name="locale", window_name="café")

    assert [s.session_name for s in server.sessions] == ["locale"]
    assert session.active_window.window_name == "café"


class InteractiveArgvFixture(t.NamedTuple):
    """One tmux argv and whether ``tmux_cmd`` may pass ``-u`` to it."""

    test_id: str
    args: tuple[str, ...]
    expect_u: bool


INTERACTIVE_ARGV_FIXTURES: list[InteractiveArgvFixture] = [
    InteractiveArgvFixture("list_sessions", ("list-sessions",), True),
    InteractiveArgvFixture("version", ("-V",), True),
    InteractiveArgvFixture("detached_new_session", ("new-session", "-d", "-P"), True),
    InteractiveArgvFixture("combined_detach_flag", ("new-session", "-dP"), True),
    InteractiveArgvFixture("attach_session", ("attach-session",), False),
    InteractiveArgvFixture("attach_alias", ("attach", "-t", "s"), False),
    InteractiveArgvFixture(
        "attach_behind_socket_flags",
        ("-Lsock", "-f", "tmux.conf", "attach-session", "-t", "s"),
        False,
    ),
    InteractiveArgvFixture("foreground_new_session", ("new-session", "-s", "x"), False),
    InteractiveArgvFixture("new_alias", ("-L", "sock", "new", "-s", "x"), False),
    InteractiveArgvFixture("d_as_a_flag_value", ("new-session", "-s", "-d"), False),
    InteractiveArgvFixture("bare_tmux", (), False),
]


class StdinCase(t.NamedTuple):
    """Fixture for test_tmux_cmd_input_round_trip()."""

    test_id: str
    payload: str | bytes


STDIN_CASES: list[StdinCase] = [
    StdinCase("text", "hello"),
    StdinCase("leading_dash_and_semicolon", "-x;\n"),
    StdinCase("unicode", "юникод Ελληνικά"),
    StdinCase("non_utf8_bytes", b"\xff\xfe\x00\x80 binary\n"),
    StdinCase("esc_and_cr", b"\x1b[31mred\x1b[0m\r\n"),
    StdinCase("over_16_kib_text", "-line;\n" * 10_000),
    StdinCase("over_16_kib_bytes", bytes(range(256)) * 600),
]


@pytest.mark.parametrize(
    InteractiveArgvFixture._fields,
    INTERACTIVE_ARGV_FIXTURES,
    ids=[fixture.test_id for fixture in INTERACTIVE_ARGV_FIXTURES],
)
def test_tmux_cmd_passes_u_except_to_interactive_clients(
    monkeypatch: pytest.MonkeyPatch,
    test_id: str,
    args: tuple[str, ...],
    expect_u: bool,
) -> None:
    """``-u`` rides on every command but those that run an interactive client.

    An interactive client reads its terminal's encoding itself; forcing
    ``-u`` on ``attach-session`` would override that. The argv is captured
    at ``Popen``, so no tmux server is involved.
    """
    assert test_id
    argvs: list[list[str]] = []

    class FakePopen:
        returncode = 0

        def __init__(self, cmd: list[str], **kwargs: t.Any) -> None:
            argvs.append(cmd)

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            return "", ""

    monkeypatch.setattr("libtmux.common.subprocess.Popen", FakePopen)

    tmux_cmd(*args, tmux_bin="tmux")

    assert argvs == [["tmux", *(["-u"] if expect_u else []), *args]]


def test_tmux_cmd_timeout_kills_and_reaps_the_child(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A timed-out tmux process is killed, reaped, and its pipes closed.

    :meth:`subprocess.Popen.communicate` leaves the child running when its
    timeout expires, so an unhandled expiry leaks one tmux process per call.
    The recorder wraps :class:`subprocess.Popen` because the exception path
    never hands the caller the ``tmux_cmd`` holding the process.
    """
    spawned: list[subprocess.Popen[t.Any]] = []
    real_popen = subprocess.Popen

    def record_popen(*args: t.Any, **kwargs: t.Any) -> subprocess.Popen[t.Any]:
        process = real_popen(*args, **kwargs)
        spawned.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", record_popen)

    with pytest.raises(exc.TmuxTimeout):
        session.server.cmd("wait-for", "libtmux_reap_channel", timeout=0.5)

    assert spawned, "no tmux subprocess was spawned"
    process = spawned[-1]

    assert process.returncode is not None, "child was left running"
    assert process.returncode == -signal.SIGKILL, "child was not killed"

    with pytest.raises(ChildProcessError):
        os.waitpid(process.pid, os.WNOHANG)

    assert process.stdout is not None
    assert process.stdout.closed, "stdout pipe leaked"
    assert process.stderr is not None
    assert process.stderr.closed, "stderr pipe leaked"


def test_tmux_cmd_timeout_that_is_not_reached_returns_normally(
    session: Session,
) -> None:
    """A command that finishes inside its bound parses its output as usual."""
    proc = tmux_cmd(
        f"-L{session.server.socket_name}",
        "display-message",
        "-p",
        "ok",
        timeout=60,
    )

    assert proc.stdout == ["ok"]
    assert proc.returncode == 0
    assert proc.stderr == []


def test_timeout_defaults_to_none_at_every_entry_point() -> None:
    """Existing callers must not start timing out.

    ``None`` is the only default that keeps today's unbounded behavior, and
    keyword-only is what lets the parameter be added without disturbing the
    positional ``*args`` every one of these entry points forwards to tmux.
    """
    entry_points = (
        tmux_cmd.__init__,
        libtmux.Server.cmd,
        libtmux.Session.cmd,
        libtmux.Window.cmd,
        libtmux.Pane.cmd,
    )

    for func in entry_points:
        parameter = inspect.signature(func).parameters["timeout"]

        assert parameter.default is None, f"{func.__qualname__} defaults to a bound"
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


@pytest.mark.parametrize(
    list(StdinCase._fields),
    STDIN_CASES,
    ids=[case.test_id for case in STDIN_CASES],
)
def test_tmux_cmd_input_round_trip(
    session: Session,
    tmp_path: pathlib.Path,
    test_id: str,
    payload: str | bytes,
) -> None:
    """``input`` reaches the tmux client's stdin byte for byte."""
    server = session.server
    expected = payload.encode() if isinstance(payload, str) else payload
    out = tmp_path / "buffer.bin"

    proc = server.cmd("load-buffer", "-b", "stdin_rt", "-", input=payload)
    assert not proc.stderr
    server.cmd("save-buffer", "-b", "stdin_rt", str(out))

    assert out.read_bytes() == expected


def test_tmux_cmd_input_free_standing(session: Session) -> None:
    """``tmux_cmd`` takes ``input`` directly, not only through ``Server.cmd``."""
    server = session.server
    proc = tmux_cmd(
        f"-L{server.socket_name}",
        "load-buffer",
        "-b",
        "stdin_direct",
        "-",
        input="direct",
        tmux_bin=server.tmux_bin,
    )
    assert proc.returncode == 0
    assert server.show_buffer(buffer_name="stdin_direct") == "direct"


def test_tmux_cmd_input_rejects_unencodable_text(server: Server) -> None:
    """Text that UTF-8 cannot encode raises instead of being altered."""
    with pytest.raises(UnicodeEncodeError):
        server.cmd("load-buffer", "-", input="lone surrogate \ud800")


def test_tmux_cmd_input_tmux_refusal_is_reported(server: Server) -> None:
    """A tmux that exits without reading stdin reports its error, not a pipe error."""
    proc = server.cmd("no-such-command", input=b"x" * 1_000_000)
    assert proc.returncode != 0
    assert proc.stderr


def test_tmux_cmd_without_input_leaves_stdin_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ``input`` the Popen call keeps its original arguments.

    ``subprocess.Popen`` is replaced to read its keyword arguments: stdin must
    stay inherited (``attach-session`` needs the terminal) and decoding must stay
    text mode.
    """
    seen: dict[str, t.Any] = {}
    real_popen = subprocess.Popen

    def spy(*args: t.Any, **kwargs: t.Any) -> subprocess.Popen[t.Any]:
        seen.update(kwargs)
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", spy)
    tmux_cmd("-V")

    assert "stdin" not in seen
    assert seen["text"] is True
    assert seen["encoding"] == "utf-8"
    assert seen["errors"] == "backslashreplace"


@pytest.fixture
def echo_stdin_bin(tmp_path: pathlib.Path) -> str:
    """Return a fake ``tmux`` that prints its stdin, to observe forwarding."""
    script = tmp_path / "fake-tmux"
    script.write_text("#!/bin/sh\ncat\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


@pytest.mark.parametrize("level", ["server", "session", "window", "pane"])
def test_cmd_forwards_input_at_every_level(
    session: Session,
    echo_stdin_bin: str,
    monkeypatch: pytest.MonkeyPatch,
    level: str,
) -> None:
    """``Server``, ``Session``, ``Window`` and ``Pane`` ``cmd`` pass ``input``."""
    obj = {
        "server": session.server,
        "session": session,
        "window": session.active_window,
        "pane": session.active_pane,
    }[level]
    assert obj is not None
    monkeypatch.setattr(session.server, "tmux_bin", echo_stdin_bin)

    proc = obj.cmd("ignored", input="via stdin")

    assert proc.stdout == ["via stdin"]


def test_tmux_cmd_timeout_applies_when_input_is_given(session: Session) -> None:
    """``timeout`` bounds a command whose stdin is fed from ``input``.

    ``input`` takes a separate binary-mode ``Popen`` path; the bound must
    reach it too, and it must kill and reap the child like the text path.
    """
    with pytest.raises(exc.TmuxTimeout):
        session.server.cmd("run-shell", "sleep 5", input=b"payload", timeout=0.25)


def _debug_argvs(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        str(record.tmux_cmd)
        for record in caplog.records
        if record.name == "libtmux.common" and hasattr(record, "tmux_cmd")
    ]


def test_logged_argv_masks_environment_values_by_default(
    server: Server,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify an ``environment=`` secret never reaches a log record."""
    with caplog.at_level(logging.DEBUG, logger="libtmux.common"):
        session = server.new_session(
            session_name="redact_env",
            environment={"API_KEY": "sekrit-value"},
        )
        session.new_window(environment={"OTHER": "sekrit-two"})
        session.set_environment("THIRD", "sekrit-three")

    argvs = _debug_argvs(caplog)
    assert any("API_KEY=***" in argv for argv in argvs)
    assert any("OTHER=***" in argv for argv in argvs)
    assert any("THIRD" in argv for argv in argvs)
    assert not any("sekrit" in argv for argv in argvs)
    assert "sekrit" not in caplog.text


def test_set_argv_redactor_masks_send_keys_and_resets(
    server: Server,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify a custom redactor applies, and ``None`` restores the default."""
    pane = server.new_session(session_name="redact_keys").active_pane
    assert pane is not None

    common.set_argv_redactor(
        lambda argv: common.redact_send_keys(common.redact_env_values(argv)),
    )
    try:
        with caplog.at_level(logging.DEBUG, logger="libtmux.common"):
            pane.send_keys("echo typed-secret")
        assert not any("typed-secret" in a for a in _debug_argvs(caplog))
    finally:
        common.set_argv_redactor(None)

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="libtmux.common"):
        pane.send_keys("echo typed-visible")
    assert any("typed-visible" in a for a in _debug_argvs(caplog))


def test_redaction_does_not_change_the_argv_tmux_receives(server: Server) -> None:
    """Verify the pane still gets the real environment value."""
    session = server.new_session(
        session_name="redact_real",
        environment={"API_KEY": "sekrit-value"},
    )
    pane = session.active_pane
    assert pane is not None
    pane.send_keys("echo $API_KEY")

    def printed() -> bool:
        return "sekrit-value" in "\n".join(pane.capture_pane())

    assert retry_until(printed)


def test_timeout_log_and_message_redact_environment_values(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A timed-out command does not leak ``-e NAME=value`` into logs or the error.

    The timeout path logs and raises the argv itself, so it has to go
    through the same redactor as the DEBUG dispatch log.
    """

    class FakePopen:
        returncode = None
        stdout = None
        stderr = None

        def __init__(self, cmd: list[str], **kwargs: t.Any) -> None:
            self.cmd = cmd

        def communicate(self, *args: t.Any, timeout: float | None = None) -> t.Any:
            raise subprocess.TimeoutExpired(self.cmd, timeout or 0)

        def kill(self) -> None:
            pass

        def wait(self) -> int:
            return -9

    monkeypatch.setattr("libtmux.common.subprocess.Popen", FakePopen)

    with (
        caplog.at_level(logging.DEBUG, logger="libtmux.common"),
        pytest.raises(exc.TmuxTimeout) as excinfo,
    ):
        tmux_cmd("new-window", "-e", "TOKEN=hunter2", tmux_bin="tmux", timeout=1)

    assert "hunter2" not in str(excinfo.value)
    assert "hunter2" not in caplog.text
    assert "TOKEN=***" in str(excinfo.value)
    assert excinfo.value.cmd[-1] == "TOKEN=hunter2"
