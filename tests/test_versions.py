"""tmux version checks before ordinary public dispatch."""

from __future__ import annotations

import itertools
import pathlib
import shutil
import subprocess
import typing as t

import pytest

from libtmux import Server, Window, exc
from libtmux._internal import support
from libtmux._internal.query_list import QueryList
from libtmux._internal.support import versions
from libtmux.common import tmux_cmd


def _is_probe(argv: list[str]) -> bool:
    return argv[-3:-1] == ["run-shell", "-C"]


def _reply(argv: list[str], version: str) -> subprocess.CompletedProcess[str]:
    """Answer a version probe the way a live daemon does."""
    return subprocess.CompletedProcess(
        argv, 1, "", f"unknown command: {argv[-1].replace('#{version}', version)}\n"
    )


SUPPORTED = [
    "3.3a",
    "3.3b",
    "3.4",
    "3.7d",
    "3.8",
    "3.10",
    "4.0",
    "3.4-rc",
    "3.8-rc",
    "3.8-rc2",
    "next-3.4",
    "next-3.9",
]
BELOW_FLOOR = ["3.3", "3.2a", "3.3-rc", "3.2-rc5", "next-3.3"]
UNPARSEABLE = [
    "master",
    "openbsd-7.6",
    "",
    "3",
    "garbage",
    "3.3a garbage",
    "3.3a\n3.7",
    "3.3a-master",
    "3.3a-dev",
    "next-3.3a",
    "next-3.9-master",
    "next-3.9a",
    "3.3a-rc",
    "3.3a-rc1",
    "03.3a",
    "3.03a",
    "3.3A",
    "3.3aa",
    "3.3a ",
    "\u0663.\u0663a",
]


@pytest.mark.parametrize("version", SUPPORTED)
def test_checked_release(version: str) -> None:
    """Every form tmux reports at or above the floor is supported."""
    versions.require_version(version)


@pytest.mark.parametrize("version", [*BELOW_FLOOR, *UNPARSEABLE])
def test_refused_release(version: str) -> None:
    """Older and unparseable reports are never supported."""
    with pytest.raises(exc.VersionTooLow, match=r"3\.3a"):
        versions.require_version(version)


@pytest.mark.parametrize(
    "ascending",
    [
        ["next-3.7", "3.7-rc", "3.7-rc3", "3.7", "3.7a"],
        ["next-3.4", "3.4-rc", "3.4"],
        ["3.9", "3.10"],
        ["3.3", "3.3a", "3.3b"],
    ],
)
def test_release_order(ascending: list[str]) -> None:
    """Development builds precede candidates, which precede the release."""
    for lower, higher in itertools.pairwise(ascending):
        assert versions.is_at_least(higher, lower)
        assert not versions.is_at_least(lower, higher)


@pytest.mark.parametrize(
    ("version", "allowed"),
    [
        ("3.8-rc2", True),
        ("next-3.8", True),
        ("next-3.7", False),
        ("3.7-rc2", False),
        ("3.7", True),
    ],
)
def test_candidates_rank_against_a_feature_floor(version: str, allowed: bool) -> None:
    """A build below a release does not inherit that release's features."""
    assert versions.is_at_least(version, "3.7") is allowed


@pytest.mark.parametrize(
    "route",
    [
        "raw-read",
        "raw-write",
        "raw-batch",
        "server",
        "alive",
        "raise-if-dead",
        "kill",
        "sessions",
        "clients",
        "attached-sessions",
        "linked-sessions",
        "query",
    ],
)
def test_older_daemon_refused_before_dispatch(
    monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    """Synthetic version reports let the test assert zero requested effects."""
    probes: list[list[str]] = []

    def probe(argv: list[str]) -> subprocess.CompletedProcess[str]:
        probes.append(argv)
        return _reply(argv, "3.3")

    def dispatch(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        pytest.fail("requested process started below the minimum")

    monkeypatch.setattr(versions, "_run", probe)
    monkeypatch.setattr(subprocess, "Popen", dispatch)
    server = Server(tmux_bin="/test/tmux", socket_path="/private/socket")
    with pytest.raises(exc.VersionTooLow, match=r"3\.3"):
        if route == "raw-read":
            tmux_cmd("-S", "/private/socket", "list-sessions", tmux_bin="/test/tmux")
        elif route == "raw-write":
            tmux_cmd("set-option", "-g", "@probe", "changed", tmux_bin="/test/tmux")
        elif route == "raw-batch":
            tmux_cmd(
                "set-option",
                "-g",
                "@probe",
                "changed",
                ";",
                "list-sessions",
                tmux_bin="/test/tmux",
            )
        elif route == "alive":
            server.is_alive()
        elif route == "kill":
            server.kill()
        elif route == "raise-if-dead":
            server.raise_if_dead()
        elif route == "sessions":
            _ = server.sessions
        elif route == "clients":
            _ = server.clients
        elif route == "attached-sessions":
            _ = server.attached_sessions
        elif route == "linked-sessions":
            _ = Window(server=server, window_id="@1").linked_sessions
        elif route == "query":
            QueryList([server]).filter(sessions__noeq=[])
        else:
            server.cmd("new-session", "-d")
    assert len(probes) == 1
    assert probes[0][-4:-1] == ["-N", "run-shell", "-C"]
    assert probes[0][-1].endswith("#{version}")


def test_version_check_fires_no_user_hooks(server: Server) -> None:
    """The version probe has no side effects a user's hooks can observe."""
    from libtmux.test.retry import retry_until

    server.new_session("versioned", window_command="sleep 300")
    version = server._get_version()
    has_command_error = True
    try:
        versions.require_version(version, "3.5")
    except exc.VersionTooLow:
        has_command_error = False
    server.cmd(
        "set-hook", "-g", "after-display-message", "set-option -ag @probe-after x"
    )
    if has_command_error:
        server.cmd("set-hook", "-g", "command-error", "set-option -ag @probe-error y")

    binary, selectors = server._version_endpoint()
    assert versions.live_version(binary, selectors) == version
    versions.prepare([binary, *selectors, "list-sessions"])
    server.cmd("list-sessions")

    # Hooks run in order, so a control firing after the probes proves that no
    # earlier probe left a mark: each sentinel holds exactly one letter.
    server.cmd("display-message", "-p", "control")
    if has_command_error:
        assert server.cmd("kill-session", "-t", "=missing").returncode != 0

    def settled() -> bool:
        after = server.cmd("show-option", "-gqv", "@probe-after").stdout
        error = server.cmd("show-option", "-gqv", "@probe-error").stdout
        return after == ["x"] and (error == ["y"] or not has_command_error)

    assert retry_until(settled, seconds=5, raises=False)
    assert server.cmd("show-option", "-gqv", "@probe-after").stdout == ["x"]
    if has_command_error:
        assert server.cmd("show-option", "-gqv", "@probe-error").stdout == ["y"]


def test_feature_flags_follow_the_daemon_not_the_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A newer client executable cannot select flags an older daemon rejects."""
    monkeypatch.setattr(versions, "_run", lambda argv: _reply(argv, "3.3a"))
    monkeypatch.setattr("libtmux.common.has_gte_version", lambda *args, **kwargs: True)
    server = Server(tmux_bin="/test/newer-client")
    assert server._has_gte_version("3.3a")
    assert not server._has_gte_version("3.4")
    assert not server._has_gte_version("3.7")


def test_prefix_preserves_native_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep native argv and batch separators after the version fence."""
    monkeypatch.setattr(versions, "_run", lambda argv: _reply(argv, "3.3a"))
    original = [
        "/tmux",
        "-Lodd;socket",
        "set-option",
        "-g",
        "@value",
        "literal\\;",
        ";",
        "list-sessions",
    ]
    guarded, marker = versions.prepare(original)
    assert guarded[:3] == ["/tmux", "-L", "odd;socket"]
    assert guarded[-6:] == original[-6:]
    assert guarded[3:8] == ["-N", "if-shell", "-F", "#{==:#{version},3.3a}", ""]
    assert guarded[8] == marker


def test_changed_daemon_is_explicit() -> None:
    """The native false branch identifies refusal before requested commands."""
    with pytest.raises(exc.VersionTooLow, match="changed before dispatch"):
        versions.check_result("unknown command: private-marker\n", "private-marker")


@pytest.mark.parametrize("option", ["-L", "-S", "-f"])
def test_no_start_flag_distinguishes_option_values(
    monkeypatch: pytest.MonkeyPatch, option: str
) -> None:
    """A literal option value cannot disable daemon restart protection."""
    monkeypatch.setattr(versions, "_run", lambda argv: _reply(argv, "3.3a"))
    guarded, _ = versions.prepare(["/tmux", option, "-N", "new-session", "-d"])
    assert guarded[:4] == ["/tmux", option, "-N", "-N"]


def test_probe_error_is_not_a_cold_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Permission and protocol failures never authorize server creation."""
    calls: list[list[str]] = []

    def probe(argv: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, "", "permission denied")

    monkeypatch.setattr(versions, "_run", probe)
    with pytest.raises(exc.LibTmuxException, match="permission denied"):
        versions.prepare(["/tmux", "new-session", "-d"])
    assert len(calls) == 1


@pytest.mark.parametrize(
    "floor_report", ["3.3a", "3.3a-master", "3.3a-dev", "next-3.3b"]
)
def test_format_version_uses_tmux_release_order(floor_report: str) -> None:
    """Patch letters qualify the core but keep the release's format tokens."""
    from libtmux.neo import get_output_format

    fields, _ = get_output_format("list-panes", "3.7d")
    assert "pane_floating_flag" in fields
    fields, _ = get_output_format("list-panes", floor_report)
    assert "pane_dead_signal" in fields
    assert "pane_floating_flag" not in fields


def test_native_prefix_refuses_a_changed_report(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A native mismatch aborts every requested command in the same batch."""
    server.new_session("versioned")
    server._version_cache.clear()
    run = versions._run

    def changed(argv: list[str]) -> subprocess.CompletedProcess[str]:
        result = run(argv)
        if _is_probe(argv) and result.returncode == 1:
            return _reply(argv, "3.99")
        return result

    with monkeypatch.context() as scoped:
        scoped.setattr(versions, "_run", changed)
        with pytest.raises(exc.VersionTooLow, match="changed before dispatch"):
            server.cmd(
                "set-option",
                "-g",
                "@version-first",
                "changed",
                ";",
                "set-option",
                "-g",
                "@version-second",
                "changed",
            )
    assert server.cmd("show-option", "-gqv", "@version-first").stdout == []
    assert server.cmd("show-option", "-gqv", "@version-second").stdout == []


def _count_probes(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    probes: list[list[str]] = []
    run = versions._run

    def counted(argv: list[str]) -> subprocess.CompletedProcess[str]:
        if _is_probe(argv):
            probes.append(argv)
        return run(argv)

    monkeypatch.setattr(versions, "_run", counted)
    return probes


def test_checked_release_is_probed_once_per_endpoint(
    server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Later commands and flag decisions reuse the release the fence guards."""
    server.new_session("versioned", window_command="sleep 300")
    server._version_cache.clear()
    probes = _count_probes(monkeypatch)
    for _ in range(3):
        assert server.cmd("list-sessions").returncode == 0
    _ = server.sessions
    assert server._has_gte_version("3.3a")
    assert len(probes) == 1


def test_stale_cached_release_is_refused_and_forgotten(
    server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A daemon that no longer matches the cached release fails the fence."""
    server.new_session("versioned", window_command="sleep 300")
    server.cmd("list-sessions")
    binary, selectors = server._version_endpoint()
    server._version_cache.put(binary, selectors, "3.99")
    with pytest.raises(exc.VersionTooLow, match="changed before dispatch"):
        server.cmd("set-option", "-g", "@stale-effect", "ran")
    assert not server._version_cache
    probes = _count_probes(monkeypatch)
    assert server.cmd("show-option", "-gqv", "@stale-effect").stdout == []
    assert server.cmd("list-sessions").returncode == 0
    assert len(probes) == 1


def test_cached_release_survives_daemon_loss_without_a_stale_refusal(
    server: Server,
) -> None:
    """A vanished daemon is detected, and the next command checks again."""
    server.new_session("versioned", window_command="sleep 300")
    server.cmd("list-sessions")
    assert server._version_cache
    binary, selectors = server._version_endpoint()
    stop = subprocess.run(
        [binary, "-N", *selectors, "kill-server"], capture_output=True, check=False
    )
    assert stop.returncode == 0
    assert not server.is_alive()
    assert not server._version_cache
    created = server.new_session("returned", window_command="sleep 300")
    assert created.session_name == "returned"
    assert server.is_alive()


def test_kill_reads_liveness_afresh(
    server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Server.kill() probes even with a cached release, then forgets it."""
    server.new_session("versioned", window_command="sleep 300")
    server.cmd("list-sessions")
    assert server._version_cache
    probes = _count_probes(monkeypatch)
    server.kill()
    assert len(probes) == 1
    assert not server._version_cache
    assert not server.is_alive()


def test_absent_cleanup_never_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    """An absent endpoint stays untouched even when its binary is too old."""
    calls: list[list[str]] = []

    def absent(argv: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, "", "no server running")

    def dispatch(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        pytest.fail("absent cleanup dispatched a process")

    monkeypatch.setattr(versions, "_run", absent)
    monkeypatch.setattr(subprocess, "Popen", dispatch)
    Server(socket_name="absent", tmux_bin="/test/old-tmux").kill()
    assert len(calls) == 1
    assert _is_probe(calls[0])


def test_checked_daemon_disappearance_never_restarts(
    server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Losing a checked daemon cannot start the configured executable."""
    server.new_session("versioned", window_command="sleep 300")
    server._version_cache.clear()
    run = versions._run

    def disappear(argv: list[str]) -> subprocess.CompletedProcess[str]:
        result = run(argv)
        if _is_probe(argv) and result.returncode == 1:
            assert run([*argv[:-4], "kill-server"]).returncode == 0
        return result

    with monkeypatch.context() as scoped:
        scoped.setattr(versions, "_run", disappear)
        result = server.cmd(
            "new-session", "-d", "-s", "unexpected-restart", "sleep 300"
        )
    assert result.returncode != 0, "dispatch restarted the checked daemon"
    binary, selectors = server._version_endpoint()
    assert versions.live_version(binary, selectors) is None


@pytest.mark.parametrize("name", ["renamed-tmux", "tmux with spaces", "tmux\udcff"])
def test_named_33a_executable_can_create(tmp_path: pathlib.Path, name: str) -> None:
    """The native 3.3a banner includes the configured executable basename."""
    binary = shutil.which("tmux")
    assert binary is not None
    report = subprocess.run(
        [binary, "-V"], capture_output=True, check=True, timeout=5
    ).stdout
    if report != b"tmux 3.3a\n":
        pytest.skip("requires native tmux 3.3a")
    renamed = tmp_path / name
    renamed.symlink_to(binary)
    socket = tmp_path / "s"
    server = Server(
        tmux_bin=str(renamed), socket_path=str(socket), config_file="/dev/null"
    )
    try:
        session = server.new_session(
            "named-executable", window_command="exec sleep 123"
        )
        assert session.session_id is not None
        assert server._get_version() == "3.3a"
    finally:
        subprocess.run(
            [binary, "-N", "-S", str(socket), "kill-server"],
            capture_output=True,
            check=False,
            timeout=5,
        )


@pytest.mark.parametrize(
    ("banner", "accepted"),
    [
        ("tmux 3.3a\n", True),
        ("custom tmux 3.3a\n", True),
        ("unrelated 3.3a\n", False),
        ("custom tmux-suffix 3.3a\n", False),
        ("custom tmux 3.3a extra\n", False),
        ("custom tmux 3.3\n", False),
    ],
)
def test_executable_report_uses_its_exact_name(
    monkeypatch: pytest.MonkeyPatch, banner: str, accepted: bool
) -> None:
    """An executable's native name cannot relax the complete release token."""
    monkeypatch.setattr(
        versions,
        "_run",
        lambda argv: subprocess.CompletedProcess(argv, 0, banner, ""),
    )
    if accepted:
        assert versions._binary_version("/test/custom tmux") == "3.3a"
    else:
        with pytest.raises(exc.VersionTooLow):
            support._binary_version("/test/custom tmux")
