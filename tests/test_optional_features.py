"""Optional operations preserve the ordinary 3.3a support boundary."""

from __future__ import annotations

import shlex
import subprocess
import typing as t

import pytest

from libtmux import Pane, Server, Session, exc
from libtmux._internal.support import versions
from libtmux.common import tmux_cmd

if t.TYPE_CHECKING:
    import pathlib


def _reply(argv: list[str], version: str) -> subprocess.CompletedProcess[str]:
    """Answer a version probe the way a live daemon does."""
    return subprocess.CompletedProcess(
        argv, 1, "", f"unknown command: {argv[-1].replace('#{version}', version)}\n"
    )


@pytest.mark.parametrize("verb", ["select-layout", "selectl", "select-l"])
def test_malformed_layout_is_refused_before_any_batch_effect(
    session: Session, tmp_path: pathlib.Path, verb: str
) -> None:
    """Refuse the 3.3a layout error path before the batch prefix runs."""
    server = session.server
    marker = tmp_path / "layout-prefix-effect"
    command = (
        "run-shell",
        f": > {shlex.quote(str(marker))}",
        ";",
        verb,
        "-t",
        session.active_window.window_id,
        "not-a-layout",
    )
    if server._get_version() == "3.3a":
        with pytest.raises(ValueError, match="layout"):
            server.cmd(*command)
        assert not marker.exists()
    else:
        result = server.cmd(*command)
        assert result.returncode != 0
        assert marker.exists()
    assert server.is_alive()


def test_33a_layout_validation_retains_native_safe_forms(session: Session) -> None:
    """Preset prefixes, serialized forms and ignored operands stay available."""
    server = session.server
    if server._get_version() != "3.3a":
        pytest.skip("the narrow layout error guard applies to tmux 3.3a")
    target = session.active_window.window_id
    for flag in ("-n", "-p", "-E"):
        assert server.cmd("selectl", flag, "-t", target, "not-a-layout").returncode == 0
    assert server.cmd("select-layout", "-t", target, "even-h").returncode == 0
    layout = server.cmd(
        "display-message", "-p", "-t", target, "#{window_layout}"
    ).stdout[0]
    assert server.cmd("select-layout", "-t", target, layout).returncode == 0
    assert server.cmd("select-layout", "-o", "-t", target, layout).returncode == 0
    assert server.cmd("select-layout", "-o", "-t", target).returncode == 0
    invalid = server.cmd("select-layout", "-t", target, "0000,not-a-layout")
    assert invalid.returncode != 0
    with pytest.raises(ValueError, match="layout"):
        server.cmd("select-layout", "-o", "-t", target, "tiled")
    assert server.is_alive()


@pytest.mark.parametrize("window_name", [None, "sole-after-break"])
@pytest.mark.parametrize("stale_window", [False, True])
def test_single_pane_break_returns_the_actual_window(
    session: Session, window_name: str | None, stale_window: bool
) -> None:
    """Old sole-pane relinking succeeds without printing its requested ID."""
    window = session.active_window
    window.rename_window("sole-before-break")
    pane = window.active_pane
    assert pane is not None
    before = window.window_id
    expected_name = "sole-before-break"
    if stale_window:
        peer = session.new_window(window_name="actual-before-break")
        peer_pane = peer.active_pane
        assert peer_pane is not None
        swapped = session.server.cmd(
            "swap-pane", "-d", "-s", pane.pane_id, "-t", peer_pane.pane_id
        )
        assert swapped.returncode == 0
        before = peer.window_id
        expected_name = "actual-before-break"
    if session.server._get_version() == "3.7" and window_name is None:
        with pytest.raises(exc.VersionTooLow, match="unnamed break-pane"):
            pane.break_pane()
        pane.refresh()
        assert pane.window.window_id == before
        assert pane.window.window_name == expected_name
        return
    result = pane.break_pane(window_name=window_name)
    assert result.window_id == before
    assert result.window_name == (window_name or expected_name)
    assert [item.pane_id for item in result.panes] == [pane.pane_id]


@pytest.mark.parametrize(
    ("version", "arguments", "reason"),
    [
        ("3.3a", ["delete-buffer", "-b", "missing"], "deletion"),
        ("3.3a", ["deleteb", "-bmissing"], "deletion"),
        ("3.3a", ["delete-bu", "-b", ""], "deletion"),
        ("3.3a", ["set-buffer", "-bmissing", "-n", "new"], "rename"),
        ("3.3a", ["setb", "-abmissing", "-nnew"], "rename"),
        ("3.3a", ["set-b", "-t", "-n", "-bmissing", "-nnew"], "rename"),
        (
            "3.3a",
            ["set-option", "-g", "@probe", "changed;", "deleteb", "-bmissing"],
            "deletion",
        ),
        ("3.4", ["split-window", "-p25"], "percentage"),
        ("3.4", ["splitw", "-dp", "25"], "percentage"),
        ("3.7", ["break-pane", "-s", "%1"], "break-pane"),
        ("3.7", ["breakp", "-n", "requested", "-s", "%1"], "break-pane"),
        ("3.7", ["break-p", "-nrequested", "-s%1"], "break-pane"),
    ],
)
def test_refused_native_feature_has_no_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    version: str,
    arguments: list[str],
    reason: str,
) -> None:
    """Direct aliases, abbreviations and flat batches share one version check."""
    monkeypatch.setattr(
        versions,
        "_run",
        lambda argv: _reply(argv, version),
    )

    def unexpected(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        pytest.fail("requested feature process started before refusal")

    monkeypatch.setattr(subprocess, "Popen", unexpected)
    with pytest.raises(exc.VersionTooLow, match=reason):
        tmux_cmd(*arguments, tmux_bin="/test/tmux")


@pytest.mark.parametrize(
    ("version", "arguments"),
    [
        ("3.3a", ["set", "-g", "status", "off"]),
        ("3.3a", ["setw", "-g", "mode-keys", "vi"]),
        ("3.3a", ["delete-buffer"]),
        ("3.3a", ["set-buffer", "-b", "name", "data"]),
        ("3.3a", ["set-buffer", "-n", "new"]),
        ("3.3a", ["paste-buffer", "-bmissing", "-d"]),
        ("3.3a", ["display-message", "-p", "delete-buffer", "-bmissing"]),
        ("3.3a", ["run-shell", "printf native-output"]),
        ("3.3a", ["if-shell", "true", "delete-buffer -b missing", ""]),
        ("3.3a", ["display-message", "-p", "literal\\;", "delete-buffer"]),
        ("3.4", ["delete-buffer", "-bmissing"]),
        ("3.4", ["set-buffer", "-bmissing", "-nnew"]),
        ("3.4", ["split-window", "-l25%"]),
        ("3.5", ["split-window", "-p25"]),
        ("3.6", ["break-pane", "-s%1"]),
        ("3.7a", ["break-pane", "-s%1"]),
    ],
)
def test_native_feature_scope_preserves_arguments(
    monkeypatch: pytest.MonkeyPatch, version: str, arguments: list[str]
) -> None:
    """Keep ordinary commands and opaque programs in their native form."""
    monkeypatch.setattr(
        versions,
        "_run",
        lambda argv: _reply(argv, version),
    )
    guarded, _ = versions.prepare(["/test/tmux", *arguments])
    assert guarded[-len(arguments) :] == arguments


@pytest.mark.parametrize("control", ["-C", "-CC"])
def test_raw_control_requires_owned_control_helper(control: str) -> None:
    """Synchronous raw dispatch cannot own a pinned control client's lifetime."""
    with pytest.raises(exc.LibTmuxException, match="use ControlMode"):
        versions.prepare(["/test/tmux", control, "attach-session"])


def test_capture_refusal_uses_actual_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    """A modern configured executable cannot qualify older job stdout."""
    monkeypatch.setattr(
        versions,
        "_run",
        lambda argv: (
            subprocess.CompletedProcess(argv, 0, "tmux 3.7d\n", "")
            if "-V" in argv
            else _reply(argv, "3.3a")
        ),
    )

    def unexpected(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        pytest.fail("captured job started on an ineligible daemon")

    monkeypatch.setattr(subprocess, "Popen", unexpected)
    server = Server(tmux_bin="/test/tmux")
    assert not server._has_gte_version("3.4")
    with pytest.raises(exc.VersionTooLow, match=r"3\.5"):
        server.run_shell("touch /must-not-exist")


def test_unnamed_exact_37_break_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse before topology-dependent native naming or a NULL dereference."""
    monkeypatch.setattr(
        versions,
        "_run",
        lambda argv: _reply(argv, "3.7"),
    )
    pane = Pane(server=Server(tmux_bin="/test/tmux"), pane_id="%1")
    with pytest.raises(exc.VersionTooLow, match="provide window_name"):
        pane.break_pane()


def test_capability_selection_cannot_cross_daemon_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new probe cannot silently accept flags selected for another release."""
    monkeypatch.setattr(
        versions,
        "_run",
        lambda argv: _reply(argv, "3.3a"),
    )
    with pytest.raises(exc.VersionTooLow, match="selecting"):
        versions.prepare(
            ["/test/tmux", "run-shell", "-b", "true"], expected_version="3.7d"
        )


@pytest.mark.parametrize("multiple_panes", [False, True])
def test_exact_37_break_names(session: Session, multiple_panes: bool) -> None:
    """Both native topology branches preserve refusals and explicit names."""
    server = session.server
    if server._get_version() != "3.7":
        pytest.skip("exact tmux 3.7 regression")
    window = session.new_window(window_name="original", window_shell="exec sleep 123")
    pane = window.active_pane
    assert pane is not None
    if multiple_panes:
        pane = pane.split(shell="exec sleep 123")
    before = [(item.window_id, item.window_name) for item in session.windows]
    with pytest.raises(exc.VersionTooLow, match="provide window_name"):
        pane.break_pane()
    with pytest.raises(exc.VersionTooLow, match="raw break-pane"):
        server.cmd("breakp", "-nignored", "-s", pane.pane_id)
    assert [(item.window_id, item.window_name) for item in session.windows] == before
    broken = pane.break_pane(window_name="requested")
    assert broken.window_name == "requested"


def test_option_aliases_keep_native_meaning(session: Session) -> None:
    """Exact aliases take precedence over buffer-command prefixes."""
    server = session.server
    assert server.cmd("set", "-g", "@optional_alias", "server-value").returncode == 0
    assert server.cmd("setw", "-g", "mode-keys", "vi").returncode == 0
    assert server.cmd("show-options", "-gqv", "@optional_alias").stdout == [
        "server-value"
    ]
    assert server.cmd("show-window-options", "-gv", "mode-keys").stdout == ["vi"]
