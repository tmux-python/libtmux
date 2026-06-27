"""Tests for the Claude Code hook installer."""

from __future__ import annotations

import json
import pathlib

from libtmux.experimental.agents.hooks.claude import ClaudeCodeHook


def test_install_status_uninstall_roundtrip(tmp_path: pathlib.Path) -> None:
    """Round-trip: absent → install → installed (non-clobber) → uninstall → absent."""
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {"hooks": [{"type": "command", "command": "echo user-owned"}]}
                    ]
                }
            }
        )
    )
    hook = ClaudeCodeHook(settings_path=settings)

    assert hook.status() == "absent"
    hook.install()
    assert hook.status() == "installed"

    data = json.loads(settings.read_text())
    stop_cmds = [h["command"] for grp in data["hooks"]["Stop"] for h in grp["hooks"]]
    assert any("libtmux-agent-emit awaiting_input" in c for c in stop_cmds)
    assert "echo user-owned" in stop_cmds  # never clobber the user's hook

    hook.uninstall()
    assert hook.status() == "absent"
    data = json.loads(settings.read_text())
    stop_cmds = [
        h["command"] for grp in data["hooks"].get("Stop", []) for h in grp["hooks"]
    ]
    assert "echo user-owned" in stop_cmds  # still there

    # Events we installed with no surviving user group are pruned entirely
    # (not left as empty arrays); Stop survives via the user's group.
    assert "UserPromptSubmit" not in data["hooks"]
    assert "Notification" not in data["hooks"]
    assert "SessionStart" not in data["hooks"]
    assert "Stop" in data["hooks"]


def test_install_is_idempotent(tmp_path: pathlib.Path) -> None:
    """Installing twice leaves exactly one copy of each our-entry per event."""
    settings = tmp_path / "settings.json"
    hook = ClaudeCodeHook(settings_path=settings)
    hook.install()
    hook.install()
    assert hook.status() == "installed"

    # Confirm no duplicate our-entries exist
    data = json.loads(settings.read_text())
    for event in ("UserPromptSubmit", "Notification", "Stop", "SessionStart"):
        groups = data["hooks"].get(event, [])
        our_cmds = [
            h["command"]
            for g in groups
            for h in g.get("hooks", [])
            if "libtmux-agent-emit" in h.get("command", "")
        ]
        assert len(our_cmds) == 1, f"duplicate our-entries under {event}: {our_cmds}"
