"""Version admission before ordinary public dispatch."""

from __future__ import annotations

import subprocess
import typing as t

import pytest

from libtmux import Server, exc
from libtmux._internal import support
from libtmux.common import tmux_cmd


@pytest.mark.parametrize(
    "version",
    ["3.3a", "3.3b", "3.4", "3.10", "4.0", "3.3a-master", "next-3.8"],
)
def test_admitted_release(version: str) -> None:
    """Keep patch letters and numeric minor ordering at the floor."""
    support.require_version(version)


@pytest.mark.parametrize(
    "version",
    [
        "3.2a",
        "3.3",
        "3.3rc1",
        "3.3a-rc1",
        "next-3.3",
        "next-3.3a",
        "",
        "unknown",
        "master",
        "3.3alpha",
        "3.3a\n3.7",
    ],
)
def test_refused_release(version: str) -> None:
    """Unknown and pre-floor reports cannot inherit admission."""
    with pytest.raises(exc.VersionTooLow, match=r"3\.3a"):
        support.require_version(version)


@pytest.mark.parametrize(
    "route",
    ["raw-read", "raw-write", "raw-batch", "server", "alive", "raise-if-dead", "kill"],
)
def test_older_daemon_refused_before_dispatch(
    monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    """Synthetic version reports let the test assert zero requested effects."""
    probes: list[list[str]] = []

    def probe(argv: list[str]) -> subprocess.CompletedProcess[str]:
        probes.append(argv)
        return subprocess.CompletedProcess(argv, 0, "3.3\n", "")

    def dispatch(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        pytest.fail("requested process started below the minimum")

    monkeypatch.setattr(support, "_run", probe)
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
        else:
            server.cmd("new-session", "-d")
    assert len(probes) == 1
    assert probes[0][-3:] == ["display-message", "-p", "#{version}"]


def test_prefix_preserves_native_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep native argv and batch separators after the admission prefix."""
    monkeypatch.setattr(
        support, "_run", lambda argv: subprocess.CompletedProcess(argv, 0, "3.3a\n", "")
    )
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
    guarded, marker = support.prepare(original)
    assert guarded[:3] == ["/tmux", "-L", "odd;socket"]
    assert guarded[-6:] == original[-6:]
    assert guarded[3:8] == ["-N", "if-shell", "-F", "#{==:#{version},3.3a}", ""]
    assert guarded[8] == marker


def test_changed_daemon_is_explicit() -> None:
    """The native false branch identifies refusal before requested commands."""
    with pytest.raises(exc.VersionTooLow, match="changed before dispatch"):
        support.check_result("unknown command: private-marker\n", "private-marker")


@pytest.mark.parametrize("option", ["-L", "-S", "-f"])
def test_no_start_flag_distinguishes_option_values(
    monkeypatch: pytest.MonkeyPatch, option: str
) -> None:
    """A literal option value cannot disable daemon restart protection."""
    monkeypatch.setattr(
        support, "_run", lambda argv: subprocess.CompletedProcess(argv, 0, "3.3a\n", "")
    )
    guarded, _ = support.prepare(["/tmux", option, "-N", "new-session", "-d"])
    assert guarded[:4] == ["/tmux", option, "-N", "-N"]


def test_probe_error_is_not_a_cold_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Permission and protocol failures never authorize server creation."""
    calls: list[list[str]] = []

    def probe(argv: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, "", "permission denied")

    monkeypatch.setattr(support, "_run", probe)
    with pytest.raises(exc.LibTmuxException, match="permission denied"):
        support.prepare(["/tmux", "new-session", "-d"])
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
    server.new_session("admission")
    run = support._run

    def changed(argv: list[str]) -> subprocess.CompletedProcess[str]:
        result = run(argv)
        if result.returncode == 0 and argv[-1] == "#{version}":
            return subprocess.CompletedProcess(argv, 0, "3.99\n", "")
        return result

    with monkeypatch.context() as scoped:
        scoped.setattr(support, "_run", changed)
        with pytest.raises(exc.VersionTooLow, match="changed before dispatch"):
            server.cmd(
                "set-option",
                "-g",
                "@admission-first",
                "changed",
                ";",
                "set-option",
                "-g",
                "@admission-second",
                "changed",
            )
    assert server.cmd("show-option", "-gqv", "@admission-first").stdout == []
    assert server.cmd("show-option", "-gqv", "@admission-second").stdout == []


def test_absent_cleanup_never_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    """An absent endpoint stays untouched even when its binary is too old."""
    calls: list[list[str]] = []

    def absent(argv: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, "", "no server running")

    def dispatch(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        pytest.fail("absent cleanup dispatched a process")

    monkeypatch.setattr(support, "_run", absent)
    monkeypatch.setattr(subprocess, "Popen", dispatch)
    Server(socket_name="absent", tmux_bin="/test/old-tmux").kill()
    assert len(calls) == 1
    assert calls[0][-1] == "#{version}"


def test_admitted_daemon_disappearance_never_restarts(
    server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Losing an admitted daemon cannot start the configured executable."""
    server.new_session("admission", window_command="sleep 300")
    run = support._run

    def disappear(argv: list[str]) -> subprocess.CompletedProcess[str]:
        result = run(argv)
        if result.returncode == 0 and argv[-1] == "#{version}":
            assert run([*argv[:-4], "kill-server"]).returncode == 0
        return result

    with monkeypatch.context() as scoped:
        scoped.setattr(support, "_run", disappear)
        result = server.cmd(
            "new-session", "-d", "-s", "unexpected-restart", "sleep 300"
        )
    assert result.returncode != 0, "dispatch restarted the admitted daemon"
    binary, selectors = server._version_endpoint()
    assert support.live_version(binary, selectors) is None
