"""Tests for utility functions in libtmux."""

from __future__ import annotations

import re
import sys
import typing as t

import pytest

import libtmux
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
from libtmux.exc import BadSessionName, LibTmuxException, TmuxCommandNotFound

if t.TYPE_CHECKING:
    from libtmux.session import Session

version_regex = re.compile(r"([0-9]\.[0-9])|(master)")


def test_allows_master_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """Assert get_version() works with builds from git trunk."""

    class Hi:
        stdout: t.ClassVar = ["tmux master"]
        stderr = None

    def mock_tmux_cmd(*args: t.Any, **kwargs: t.Any) -> Hi:
        return Hi()

    monkeypatch.setattr(libtmux.common, "tmux_cmd", mock_tmux_cmd)

    assert has_minimum_version()
    assert has_gte_version(TMUX_MIN_VERSION)
    assert has_gt_version(TMUX_MAX_VERSION), "Greater than the max-supported version"
    assert get_version() == f"{TMUX_MAX_VERSION}-master", (
        "Is the latest supported version with -master appended"
    )


def test_allows_next_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """Assert get_version() supports next version."""
    TMUX_NEXT_VERSION = str(float(TMUX_MAX_VERSION) + 0.1)

    class Hi:
        stdout: t.ClassVar = [f"tmux next-{TMUX_NEXT_VERSION}"]
        stderr = None

    def mock_tmux_cmd(*args: t.Any, **kwargs: t.Any) -> Hi:
        return Hi()

    monkeypatch.setattr(libtmux.common, "tmux_cmd", mock_tmux_cmd)

    assert has_minimum_version()
    assert has_gte_version(TMUX_MIN_VERSION)
    assert has_gt_version(TMUX_MAX_VERSION), "Greater than the max-supported version"
    assert get_version() == TMUX_NEXT_VERSION


def test_get_version_openbsd(monkeypatch: pytest.MonkeyPatch) -> None:
    """Assert get_version() with OpenBSD versions."""

    class Hi:
        stderr: t.ClassVar = ["tmux: unknown option -- V"]

    def mock_tmux_cmd(*args: t.Any, **kwargs: t.Any) -> Hi:
        return Hi()

    monkeypatch.setattr(libtmux.common, "tmux_cmd", mock_tmux_cmd)
    monkeypatch.setattr(sys, "platform", "openbsd 5.2")
    assert has_minimum_version()
    assert has_gte_version(TMUX_MIN_VERSION)
    assert has_gt_version(TMUX_MAX_VERSION), "Greater than the max-supported version"
    assert get_version() == f"{TMUX_MAX_VERSION}-openbsd", (
        "Is the latest supported version with -openbsd appended"
    )


def test_get_version_too_low(monkeypatch: pytest.MonkeyPatch) -> None:
    """Assert get_version() raises if tmux version too low."""

    class Hi:
        stderr: t.ClassVar = ["tmux: unknown option -- V"]

    def mock_tmux_cmd(*args: t.Any, **kwargs: t.Any) -> Hi:
        return Hi()

    monkeypatch.setattr(libtmux.common, "tmux_cmd", mock_tmux_cmd)
    with pytest.raises(LibTmuxException) as exc_info:
        get_version()
    exc_info.match("is running tmux 1.3 or earlier")


def test_ignores_letter_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests version utilities ignores letters such as 1.8b.

    See ticket https://github.com/tmux-python/tmuxp/issues/55.

    In version 0.1.7 this is adjusted to use LooseVersion, in order to
    allow letters.

    """
    monkeypatch.setattr(libtmux.common, "TMUX_MIN_VERSION", "1.9a")
    result = has_minimum_version()
    assert result

    monkeypatch.setattr(libtmux.common, "TMUX_MIN_VERSION", "1.8a")
    result = has_minimum_version()
    assert result

    # Should not throw
    assert isinstance(has_version("1.8"), bool)
    assert isinstance(has_version("1.8a"), bool)
    assert isinstance(has_version("1.9a"), bool)


def test_error_version_less_1_7(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test raises if tmux version less than 1.7."""

    def mock_get_version() -> LooseVersion:
        return LooseVersion("1.7")

    monkeypatch.setattr(libtmux.common, "get_version", mock_get_version)
    with pytest.raises(LibTmuxException) as excinfo:
        has_minimum_version()
        excinfo.match(r"libtmux only supports")

    with pytest.raises(LibTmuxException) as excinfo:
        has_minimum_version()

        excinfo.match(r"libtmux only supports")


def test_has_version() -> None:
    """Test has_version()."""
    assert has_version(str(get_version()))


def test_tmux_cmd_raises_on_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify raises if tmux command not found."""
    monkeypatch.setenv("PATH", "")
    with pytest.raises(TmuxCommandNotFound):
        tmux_cmd("-V")


def test_tmux_cmd_unicode(session: Session) -> None:
    """Verify tmux commands with unicode."""
    session.cmd("new-window", "-t", 3, "-n", "юникод", "-F", "Ελληνικά")


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
        with pytest.raises(BadSessionName) as exc_info:
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
