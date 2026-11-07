"""Tests for utility functions in libtmux."""

from __future__ import annotations

import locale
import logging
import re
import subprocess
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
    from libtmux.server import Server
    from libtmux.session import Session

version_regex = re.compile(r"([0-9]\.[0-9])|(master)")


def test_command_deadline_reaps_only_its_client(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Observe the real child because raising alone does not prove it was reaped."""
    processes: list[subprocess.Popen[str]] = []
    spawn = subprocess.Popen

    def record(*args: t.Any, **kwargs: t.Any) -> subprocess.Popen[str]:
        process = spawn(*args, **kwargs)
        processes.append(process)
        return process

    server.new_session(session_name="survives-deadline")
    monkeypatch.setattr(subprocess, "Popen", record)
    with pytest.raises(Exception, match="tmux command timed out") as caught:
        tmux_cmd(f"-L{server.socket_name}", "wait-for", "never-signalled", timeout=0.03)
    assert isinstance(caught.value, exc.TmuxTimeout)
    assert caught.value.timeout == 0.03
    assert caught.value.cmd[-2:] == ["wait-for", "never-signalled"]
    assert len(processes) == 1
    process = processes[0]
    assert process.returncode is not None
    assert process.stdout is not None and process.stdout.closed
    assert process.stderr is not None and process.stderr.closed
    assert server.is_alive()


@pytest.mark.parametrize("scope", ["server", "session", "window", "pane"])
def test_object_command_accepts_optional_deadline(session: Session, scope: str) -> None:
    """Each command facade preserves its result and selected endpoint."""
    window = session.active_window
    assert window is not None
    pane = window.active_pane
    assert pane is not None
    target = {
        "server": session.server,
        "session": session,
        "window": window,
        "pane": pane,
    }[scope]
    result = target.cmd("display-message", "-p", "deadline-result", timeout=0.5)
    assert result.stdout == ["deadline-result"]
    assert result.returncode == 0


@pytest.mark.parametrize("scope", ["session", "window", "pane"])
@pytest.mark.parametrize("dispatch", ["instance", "class", "subclass"])
def test_object_deadline_refuses_custom_dispatch(
    monkeypatch: pytest.MonkeyPatch, scope: str, dispatch: str
) -> None:
    """A dispatcher accepting arbitrary keywords cannot silently discard a bound."""
    calls: list[dict[str, t.Any]] = []
    result = t.cast("tmux_cmd", object())

    def custom(*_args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        calls.append(kwargs)
        return result

    server: libtmux.Server
    if dispatch == "subclass":

        class RoutedServer(libtmux.Server):
            cmd = custom

        server = RoutedServer(
            socket_name="custom-deadline", tmux_bin="/not-an-executable"
        )
    else:
        server = libtmux.Server(
            socket_name="custom-deadline", tmux_bin="/not-an-executable"
        )
        monkeypatch.setattr(
            server if dispatch == "instance" else type(server), "cmd", custom
        )

    target = {
        "session": libtmux.Session(server=server, session_id="$0"),
        "window": libtmux.Window(server=server, window_id="@0"),
        "pane": libtmux.Pane(server=server, pane_id="%0"),
    }[scope]
    assert target.cmd("display-message", "-p", "unbounded", timeout=None) is result
    assert len(calls) == 1
    assert "timeout" not in calls[0]
    calls.clear()

    with pytest.raises(NotImplementedError, match="custom"):
        target.cmd("new-window", timeout=0.03)
    assert not calls


def test_command_deadline_refuses_an_injected_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An injected backend must not silently fall back to a local client."""
    server = libtmux.Server(
        socket_name="custom-deadline", tmux_bin="/not-an-executable"
    )
    backend = object()
    monkeypatch.setattr(server, "_engine", backend, raising=False)
    with pytest.raises(NotImplementedError, match="custom"):
        server.cmd("new-session", "-d", timeout=0.03)
    assert getattr(server, "_engine", None) is backend


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_deadline_refuses_before_effects(
    server: Server, timeout: float
) -> None:
    """An invalid bound must not create the requested session."""
    with pytest.raises(ValueError, match="timeout"):
        server.cmd("new-session", "-d", "-s", "invalid-deadline", timeout=timeout)
    assert not server.is_alive()


def test_deadline_does_not_undo_an_accepted_mutation(server: Server) -> None:
    """An accepted mutation remains when a later command blocks its reply."""
    server.new_session(session_name="accepted-mutation")
    with pytest.raises(exc.TmuxTimeout):
        server.cmd(
            "set-option",
            "-g",
            "@deadline-mutated",
            "1",
            ";",
            "wait-for",
            "never-replied",
            timeout=0.05,
        )
    assert server.cmd("show-options", "-gv", "@deadline-mutated").stdout == ["1"]


def test_has_version() -> None:
    """Test has_version()."""
    assert has_version(str(get_version()))


@pytest.mark.parametrize("timeout", [1e10, sys.float_info.max])
def test_large_finite_deadline_keeps_native_wait_in_range(
    server: Server,
    timeout: float,
) -> None:
    """A valid large deadline must not overflow the OS wait after spawning."""
    server.new_session(session_name="large-deadline")
    result = server.cmd("display-message", "-p", "large-result", timeout=timeout)
    assert result.stdout == ["large-result"]


def test_deadline_wait_slices_keep_one_client_and_its_output(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Force one native slice expiry while the original command remains alive."""
    server.new_session(session_name="sliced-wait")
    spawn = subprocess.Popen
    calls = 0
    clients: list[subprocess.Popen[str]] = []

    def control(*args: str) -> None:
        child = spawn(
            ["tmux", f"-L{server.socket_name}", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _, error = child.communicate(timeout=0.5)
        assert child.returncode == 0, error

    def record(*args: t.Any, **kwargs: t.Any) -> subprocess.Popen[str]:
        process = spawn(*args, **kwargs)
        clients.append(process)
        communicate = process.communicate

        def sliced(
            input: t.Any = None,  # noqa: A002 - mirrors subprocess.communicate's keyword.
            timeout: float | None = None,
        ) -> tuple[str, str]:
            nonlocal calls
            calls += 1
            if calls == 1:
                control("wait-for", "slice-ready")
                try:
                    return communicate(input, timeout=0)
                except subprocess.TimeoutExpired:
                    control("wait-for", "-S", "slice-release")
                    raise
            return communicate(input, timeout=timeout)

        monkeypatch.setattr(process, "communicate", sliced)
        return process

    monkeypatch.setattr(subprocess, "Popen", record)
    result = tmux_cmd(
        f"-L{server.socket_name}",
        "display-message",
        "-p",
        "early",
        ";",
        "wait-for",
        "-S",
        "slice-ready",
        ";",
        "wait-for",
        "slice-release",
        ";",
        "display-message",
        "-p",
        "late",
        timeout=0.5,
    )
    assert result.stdout == ["early", "late"]
    assert calls >= 2
    assert len(clients) == 1


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
