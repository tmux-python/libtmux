"""Tests for tmux-resurrect style process restore policies."""

from __future__ import annotations

from libtmux.resurrect.processes import ProcessRestorePolicy, ProcessRestoreRule


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
