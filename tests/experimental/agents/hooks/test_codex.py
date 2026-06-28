"""Tests for the Codex hook installer."""

from __future__ import annotations

import pathlib
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[import-not-found]

from libtmux.experimental.agents.hooks.codex import CodexHook


def test_install_writes_event_hooks(tmp_path: pathlib.Path) -> None:
    """Round-trip: absent → install → installed (non-clobber) → uninstall → absent."""
    config = tmp_path / "config.toml"
    config.write_text('model = "o4"\n')  # pre-existing unrelated config
    hook = CodexHook(config_path=config)

    assert hook.status() == "absent"
    hook.install()
    assert hook.status() == "installed"

    text = config.read_text()
    # All four Codex events and their states are present.
    assert "user_prompt_submit" in text
    assert "libtmux-agent-emit running" in text
    assert "permission_request" in text
    assert "libtmux-agent-emit awaiting_input" in text
    assert "stop" in text
    assert "session_start" in text
    assert "libtmux-agent-emit idle" in text
    assert 'model = "o4"' in text  # untouched

    # File must parse as valid TOML after install
    parsed = tomllib.loads(text)
    assert isinstance(parsed, dict)
    assert parsed["model"] == "o4"

    # Installing again exercises the in-place-replace branch: still installed,
    # and the marker block appears exactly once (no duplication).
    hook.install()
    assert hook.status() == "installed"
    assert config.read_text().count("# >>> libtmux-agent-state >>>") == 1

    hook.uninstall()
    assert hook.status() == "absent"
    assert 'model = "o4"' in config.read_text()


def test_install_collapses_duplicate_marker_blocks(tmp_path: pathlib.Path) -> None:
    """install() over a file with two marker blocks collapses to exactly one."""
    config = tmp_path / "config.toml"
    hook = CodexHook(config_path=config)
    block = hook._build_block()
    # Seed the file with two copies of the marker block
    config.write_text(f'model = "o4"\n\n{block}\n{block}')
    assert config.read_text().count("# >>> libtmux-agent-state >>>") == 2

    hook.install()

    text = config.read_text()
    assert text.count("# >>> libtmux-agent-state >>>") == 1
    assert hook.status() == "installed"
    assert 'model = "o4"' in text


def test_status_outdated_when_block_is_stale(tmp_path: pathlib.Path) -> None:
    """status() returns 'outdated' when marker block is present but content differs."""
    config = tmp_path / "config.toml"
    hook = CodexHook(config_path=config)
    hook.install()

    # Mutate one of the emit commands inside the block to make it stale
    text = config.read_text()
    stale = text.replace(
        'command = "libtmux-agent-emit running"',
        'command = "libtmux-agent-emit STALE"',
    )
    assert stale != text, "replacement must differ"
    config.write_text(stale)

    assert hook.status() == "outdated"
