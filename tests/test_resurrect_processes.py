"""Tests for tmux-resurrect style process restore policies."""

from __future__ import annotations

import pathlib
import typing as t

import pytest

import libtmux.resurrect.processes as resurrect_processes
from libtmux.resurrect.processes import (
    CompositeProcessCommandProvider,
    ProcessRestorePolicy,
    ProcessRestoreRule,
    ProcfsProcessCommandProvider,
    PsProcessCommandProvider,
    default_process_command_provider,
)


class _Provider:
    """Process command provider test double."""

    def __init__(self, command: str | None) -> None:
        self.command = command

    def capture(self, pid: int) -> str | None:
        """Return the configured command."""
        return self.command


class ProcfsEntry(t.NamedTuple):
    """Procfs process entry test fixture."""

    pid: int
    ppid: int
    pgrp: int
    tpgid: int
    command: tuple[str, ...]


class ProcfsCaptureCase(t.NamedTuple):
    """Case for procfs process command capture."""

    test_id: str
    pid: int
    entries: tuple[ProcfsEntry, ...]
    expected_command: str | None


class DefaultProviderFallbackCase(t.NamedTuple):
    """Case for default process provider fallback behavior."""

    test_id: str
    pid: int
    ps_command: str


PROCFS_CAPTURE_CASES = (
    ProcfsCaptureCase(
        test_id="direct_cmdline",
        pid=123,
        entries=(
            ProcfsEntry(
                pid=123,
                ppid=1,
                pgrp=123,
                tpgid=123,
                command=("python", "-m", "http.server"),
            ),
        ),
        expected_command="python -m http.server",
    ),
    ProcfsCaptureCase(
        test_id="foreground_child",
        pid=100,
        entries=(
            ProcfsEntry(
                pid=100,
                ppid=1,
                pgrp=100,
                tpgid=200,
                command=("-zsh",),
            ),
            ProcfsEntry(
                pid=200,
                ppid=100,
                pgrp=200,
                tpgid=200,
                command=("vim", "README.md"),
            ),
        ),
        expected_command="vim README.md",
    ),
    ProcfsCaptureCase(
        test_id="missing_pid",
        pid=456,
        entries=(),
        expected_command=None,
    ),
)

DEFAULT_PROVIDER_FALLBACK_CASES = (
    DefaultProviderFallbackCase(
        test_id="pane_shell_from_ps",
        pid=1234,
        ps_command="-zsh",
    ),
)


def _write_procfs_entry(proc_root: pathlib.Path, entry: ProcfsEntry) -> None:
    proc_dir = proc_root / str(entry.pid)
    proc_dir.mkdir()
    (proc_dir / "cmdline").write_bytes(
        b"\0".join(part.encode() for part in entry.command) + b"\0",
    )
    (proc_dir / "stat").write_text(
        (
            f"{entry.pid} ({entry.command[0]}) S {entry.ppid} {entry.pgrp} "
            f"0 34816 {entry.tpgid} 0 0 0 0 0 0 0 0 20 0 1 0 0\n"
        ),
        encoding="utf-8",
    )


def test_process_restore_policy_matches_defaults_and_inline_rules() -> None:
    """ProcessRestorePolicy parses tmux-resurrect-style process options."""
    default_policy = ProcessRestorePolicy.from_options(None)
    custom_policy = ProcessRestorePolicy.from_options(
        "'python->uv run python *' '~rails server->rails server *' 'git log'",
    )

    assert default_policy.resolve_command("vim pyproject.toml") == "vim pyproject.toml"
    assert default_policy.resolve_command("node server.js") is None
    assert custom_policy.resolve_command("python -m http.server 8000") == (
        "uv run python -m http.server 8000"
    )
    assert custom_policy.resolve_command("git log --oneline") == "git log --oneline"
    assert (
        custom_policy.resolve_command(
            "/rubies/bin/ruby script/rails server -p 3000",
        )
        == "rails server -p 3000"
    )
    assert (
        ProcessRestorePolicy.from_options(":all:").resolve_command(
            "node server.js",
        )
        == "node server.js"
    )
    assert ProcessRestorePolicy.from_options("false").resolve_command("vim") is None


def test_process_restore_rule_handles_unparseable_commands() -> None:
    """ProcessRestoreRule treats invalid shell syntax as a non-match."""
    rule = ProcessRestoreRule("vim")

    assert rule.matches('"unterminated') is False
    assert rule.resolve("vim notes.md") == "vim notes.md"


@pytest.mark.parametrize(
    "case",
    PROCFS_CAPTURE_CASES,
    ids=[case.test_id for case in PROCFS_CAPTURE_CASES],
)
def test_procfs_process_command_provider_reads_cmdline(
    case: ProcfsCaptureCase,
    tmp_path: pathlib.Path,
) -> None:
    """ProcfsProcessCommandProvider resolves pane PIDs to active commands."""
    for entry in case.entries:
        _write_procfs_entry(tmp_path, entry)

    provider = ProcfsProcessCommandProvider(tmp_path)

    assert provider.capture(case.pid) == case.expected_command
    assert provider.capture(0) is None


def test_composite_process_command_provider_uses_first_command() -> None:
    """CompositeProcessCommandProvider falls through missing providers."""
    provider = CompositeProcessCommandProvider(
        (
            _Provider(None),
            _Provider("vim README.md"),
        ),
    )

    assert provider.capture(123) == "vim README.md"


def test_default_process_command_provider_and_missing_ps() -> None:
    """Default providers are headless and tolerate unavailable ps binaries."""
    provider = default_process_command_provider()

    assert hasattr(provider, "capture")
    assert PsProcessCommandProvider(ps_bin="/missing-ps").capture(123) is None


@pytest.mark.parametrize(
    "case",
    DEFAULT_PROVIDER_FALLBACK_CASES,
    ids=[case.test_id for case in DEFAULT_PROVIDER_FALLBACK_CASES],
)
def test_default_process_command_provider_skips_ps_fallback(
    case: DefaultProviderFallbackCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """default_process_command_provider() does not archive ps shell fallback."""
    monkeypatch.setattr(
        resurrect_processes,
        "ProcfsProcessCommandProvider",
        lambda: _Provider(None),
    )
    monkeypatch.setattr(
        resurrect_processes,
        "PsProcessCommandProvider",
        lambda: _Provider(case.ps_command),
    )

    provider = default_process_command_provider()

    assert provider.capture(case.pid) is None
