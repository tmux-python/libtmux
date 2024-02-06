"""Tests for utility functions in libtmux."""
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
    assert (
        get_version() == "%s-master" % TMUX_MAX_VERSION
    ), "Is the latest supported version with -master appended"


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
    assert (
        get_version() == "%s-openbsd" % TMUX_MAX_VERSION
    ), "Is the latest supported version with -openbsd appended"


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


def test_has_gt_version() -> None:
    """Test has_gt_version()."""
    assert has_gt_version("1.6")
    assert has_gt_version("1.6b")

    assert not has_gt_version("4.0")
    assert not has_gt_version("4.0b")


def test_has_gte_version() -> None:
    """Test has_gte_version()."""
    assert has_gte_version("1.6")
    assert has_gte_version("1.6b")
    assert has_gte_version(str(get_version()))

    assert not has_gte_version("4.0")
    assert not has_gte_version("4.0b")


def test_has_lt_version() -> None:
    """Test has_lt_version()."""
    assert has_lt_version("4.0a")
    assert has_lt_version("4.0")

    assert not has_lt_version("1.7")
    assert not has_lt_version(str(get_version()))


def test_has_lte_version() -> None:
    """Test has_lti_version()."""
    assert has_lte_version("4.0a")
    assert has_lte_version("4.0")
    assert has_lte_version(str(get_version()))

    assert not has_lte_version("1.7")
    assert not has_lte_version("1.7b")


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

    session_name: t.Optional[str]
    raises: bool
    exc_msg_regex: t.Optional[str]


@pytest.mark.parametrize(
    SessionCheckName._fields,
    [
        SessionCheckName("", True, "empty"),
        SessionCheckName(None, True, "empty"),
        SessionCheckName("my great session.", True, "contains periods"),
        SessionCheckName("name: great session", True, "contains colons"),
        SessionCheckName("new great session", False, None),
        SessionCheckName("ajf8a3fa83fads,,,a", False, None),
    ],
)
def test_session_check_name(
    session_name: t.Optional[str],
    raises: bool,
    exc_msg_regex: t.Optional[str],
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
