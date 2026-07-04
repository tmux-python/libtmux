"""Tests for tmux-resurrect style process restore policies."""

from __future__ import annotations

import pathlib

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


def test_procfs_process_command_provider_reads_cmdline(
    tmp_path: pathlib.Path,
) -> None:
    """ProcfsProcessCommandProvider reads null-delimited procfs cmdline files."""
    proc_dir = tmp_path / "123"
    proc_dir.mkdir()
    (proc_dir / "cmdline").write_bytes(b"python\0-m\0http.server\0")

    provider = ProcfsProcessCommandProvider(tmp_path)

    assert provider.capture(123) == "python -m http.server"
    assert provider.capture(0) is None
    assert provider.capture(456) is None


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
