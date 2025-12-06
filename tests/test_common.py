"""Tests for utility functions in libtmux."""

from __future__ import annotations

import re
import sys
import typing as t

import pytest

import libtmux
from libtmux import exc
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

if t.TYPE_CHECKING:
    from libtmux.session import Session

version_regex = re.compile(r"([0-9]\.[0-9])|(master)")


def test_has_version() -> None:
    """Test has_version()."""
    assert has_version(str(get_version()))


def test_tmux_cmd_raises_on_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify raises if tmux command not found."""
    monkeypatch.setenv("PATH", "")
    with pytest.raises(exc.TmuxCommandNotFound):
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
        mock_stdout=["tmux next-3.7"],
        mock_stderr=None,
        mock_platform=None,
        expected_version="3.7",
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

        def mock_get_version() -> LooseVersion:
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
