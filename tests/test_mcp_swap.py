"""The ported ``scripts/mcp_swap.py`` dev tool resolves this repo's identity.

``mcp_swap`` swaps MCP server configs across agent CLIs to point at a local
checkout. The only port-specific change is the slug derivation: this repo's
package is ``libtmux`` but its MCP console script is ``libtmux-engine-mcp``, so
the slug must come from the *entry* (yielding ``libtmux-engine``) to stay
distinct from a sibling ``libtmux`` server. These tests lock that in, plus the
packaging wiring that makes the server runnable.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import pathlib
import sys
import threading
import types
import typing as t

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
_SCRIPT = _REPO / "scripts" / "mcp_swap.py"


def _load_mcp_swap() -> t.Any:
    """Import the PEP 723 script as a module (registered so dataclasses resolve)."""
    spec = importlib.util.spec_from_file_location("mcp_swap", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["mcp_swap"] = module
    spec.loader.exec_module(module)
    return module


def test_console_script_registered() -> None:
    """The ``libtmux-engine-mcp`` console script points at a loadable entry."""
    scripts = importlib.metadata.entry_points(group="console_scripts")
    entry = next((ep for ep in scripts if ep.name == "libtmux-engine-mcp"), None)
    assert entry is not None
    assert entry.value == "libtmux.experimental.mcp:main"


def test_resolve_repo_meta_derives_engine_identity() -> None:
    """Slug derives from the entry (``libtmux-engine``), not project.name."""
    pytest.importorskip("tomlkit")
    mcp_swap = _load_mcp_swap()
    server, entry = mcp_swap.resolve_repo_meta(_REPO)
    assert server == "libtmux-engine"
    assert entry == "libtmux-engine-mcp"


def test_build_local_spec_uv_directory() -> None:
    """``use-local`` writes a ``uv --directory <repo> run <entry>`` invocation."""
    pytest.importorskip("tomlkit")
    mcp_swap = _load_mcp_swap()
    _, entry = mcp_swap.resolve_repo_meta(_REPO)
    spec = mcp_swap.build_local_spec(_REPO, entry)
    assert spec.command == "uv"
    assert spec.args == ["--directory", str(_REPO), "run", "libtmux-engine-mcp"]
    assert spec.is_local_uv_directory()


def test_grok_and_agy_registered() -> None:
    """The grok and agy CLIs join the registry with their config shapes."""
    pytest.importorskip("tomlkit")
    mcp_swap = _load_mcp_swap()
    assert "grok" in mcp_swap.ALL_CLIS
    assert "agy" in mcp_swap.ALL_CLIS
    assert mcp_swap.CLIS["grok"].fmt == "toml"
    assert mcp_swap.CLIS["grok"].config_path.name == "config.toml"
    assert mcp_swap.CLIS["agy"].fmt == "json"
    assert mcp_swap.CLIS["agy"].config_path.name == "mcp_config.json"


def test_grok_set_get_delete_roundtrip() -> None:
    """The grok CLI reads/writes the TOML ``[mcp_servers]`` table like codex."""
    tomlkit = pytest.importorskip("tomlkit")
    mcp_swap = _load_mcp_swap()
    config = tomlkit.parse("")
    spec = mcp_swap.McpServerSpec(
        command="uv", args=["--directory", str(_REPO), "run", "x"]
    )
    assert mcp_swap.set_server("grok", config, "tmux", spec, _REPO) == "added"
    assert "mcp_servers" in config  # TOML table, not the JSON "mcpServers"
    got = mcp_swap.get_server("grok", config, "tmux", _REPO)
    assert got is not None
    assert got.is_local_uv_directory()
    assert mcp_swap.set_server("grok", config, "tmux", spec, _REPO) == "replaced"
    assert mcp_swap.delete_server("grok", config, "tmux", _REPO)
    assert mcp_swap.get_server("grok", config, "tmux", _REPO) is None


def test_agy_set_get_delete_roundtrip() -> None:
    """The agy CLI reads/writes the JSON ``mcpServers`` map like cursor/gemini."""
    pytest.importorskip("tomlkit")
    mcp_swap = _load_mcp_swap()
    config: dict[str, t.Any] = {}
    spec = mcp_swap.McpServerSpec(
        command="uv", args=["--directory", str(_REPO), "run", "x"]
    )
    assert mcp_swap.set_server("agy", config, "tmux", spec, _REPO) == "added"
    # JSON (non-Claude) shape: no Claude-style "type", no empty "env"
    assert "type" not in config["mcpServers"]["tmux"]
    assert "env" not in config["mcpServers"]["tmux"]
    got = mcp_swap.get_server("agy", config, "tmux", _REPO)
    assert got is not None
    assert got.is_local_uv_directory()
    assert mcp_swap.delete_server("agy", config, "tmux", _REPO)
    assert mcp_swap.get_server("agy", config, "tmux", _REPO) is None


def test_load_config_tolerates_empty_json(tmp_path: pathlib.Path) -> None:
    """An empty JSON config (Antigravity's initial mcp_config.json) loads as {}."""
    pytest.importorskip("tomlkit")
    mcp_swap = _load_mcp_swap()
    cfg = tmp_path / "mcp_config.json"
    cfg.write_text("")
    info = mcp_swap.CLIInfo(
        name="agy",
        binary="agy",
        config_path=cfg,
        fmt="json",
        container=("mcpServers",),
        dialect="standard",
    )
    assert mcp_swap.load_config(info) == {}


# ---------------------------------------------------------------------------
# Fixtures for the doctor / --env / naming-hint ports
# ---------------------------------------------------------------------------
#
# The upstream ``mcp_swap`` tests use a module-level import plus ``fake_home``
# / ``fake_repo`` fixtures. This file loads the PEP 723 script fresh per test
# (tomlkit-gated) via ``_load_mcp_swap``, so ``mcp_swap`` is a fixture — passed
# by name into the ported tests, which reference ``mcp_swap.<attr>`` unchanged.


@pytest.fixture
def mcp_swap() -> t.Any:
    """Load the swap script as a fresh module per test (tomlkit-gated)."""
    pytest.importorskip("tomlkit")
    return _load_mcp_swap()


@pytest.fixture
def fake_home(
    mcp_swap: t.Any, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> pathlib.Path:
    """Redirect every config path and the state file the script touches into tmp."""
    monkeypatch.setattr(
        mcp_swap,
        "CLIS",
        {
            "claude": mcp_swap.CLIInfo(
                name="claude",
                binary="claude",
                config_path=tmp_path / ".claude.json",
                fmt="json",
                container=("mcpServers",),
                dialect="claude",
            ),
            "codex": mcp_swap.CLIInfo(
                name="codex",
                binary="codex",
                config_path=tmp_path / ".codex" / "config.toml",
                fmt="toml",
                container=("mcp_servers",),
                dialect="standard",
            ),
            "cursor": mcp_swap.CLIInfo(
                name="cursor",
                binary="cursor-agent",
                config_path=tmp_path / ".cursor" / "mcp.json",
                fmt="json",
                container=("mcpServers",),
                dialect="standard",
            ),
            "gemini": mcp_swap.CLIInfo(
                name="gemini",
                binary="gemini",
                config_path=tmp_path / ".gemini" / "settings.json",
                fmt="json",
                container=("mcpServers",),
                dialect="standard",
            ),
            "grok": mcp_swap.CLIInfo(
                name="grok",
                binary="grok",
                config_path=tmp_path / ".grok" / "config.toml",
                fmt="toml",
                container=("mcp_servers",),
                dialect="standard",
            ),
            "agy": mcp_swap.CLIInfo(
                name="agy",
                binary="agy",
                config_path=tmp_path / ".gemini" / "config" / "mcp_config.json",
                fmt="json",
                container=("mcpServers",),
                dialect="standard",
            ),
            "opencode": mcp_swap.CLIInfo(
                name="opencode",
                binary="opencode",
                config_path=tmp_path / ".config" / "opencode" / "opencode.jsonc",
                fmt="jsonc",
                container=("mcp",),
                dialect="opencode",
            ),
            "pi": mcp_swap.CLIInfo(
                name="pi",
                binary="pi",
                config_path=tmp_path / ".pi" / "agent" / "mcp.json",
                fmt="jsonc",
                container=("mcpServers",),
                dialect="standard",
            ),
        },
    )
    state_dir = tmp_path / "state"
    monkeypatch.setattr(mcp_swap, "STATE_DIR", state_dir)
    monkeypatch.setattr(mcp_swap, "STATE_FILE", state_dir / "state.json")
    return tmp_path


@pytest.fixture
def fake_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal pyproject.toml matching libtmux's engine-mcp wiring.

    The console-script entry is ``libtmux-engine-mcp`` (as in the real
    pyproject), so the derived server slug is ``libtmux-engine``.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        "[project]\n"
        'name = "libtmux"\n'
        "[project.scripts]\n"
        'libtmux-engine-mcp = "libtmux.experimental.mcp:main"\n'
    )
    return repo


def _write_json(path: pathlib.Path, data: dict[str, t.Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _local_entry(repo: pathlib.Path) -> dict[str, t.Any]:
    """Return a local ``uv --directory <repo> run <entry>`` JSON entry."""
    return {
        "command": "uv",
        "args": ["--directory", str(repo.resolve()), "run", "libtmux-engine-mcp"],
    }


def _pinned_entry() -> dict[str, t.Any]:
    """Return a released-pin JSON entry, the shape a swap replaces."""
    return {"command": "uvx", "args": ["libtmux==0.63.0"]}


def _pinned_claude_entry() -> dict[str, t.Any]:
    """Return the same pin in Claude's extended entry shape."""
    return {
        "type": "stdio",
        "command": "uvx",
        "args": ["libtmux==0.63.0"],
        "env": {},
    }


# ---------------------------------------------------------------------------
# use-local --env injection
# ---------------------------------------------------------------------------


def test_use_local_env_flag_injects_into_entry(
    mcp_swap: t.Any, fake_home: pathlib.Path, fake_repo: pathlib.Path
) -> None:
    """``--env KEY=VALUE`` lands in the written server entry's ``env``.

    The isolation workflow needs to point the server at a scratch socket
    without a manual post-edit; ``--env`` writes that env at swap time.
    """
    info = mcp_swap.CLIS["cursor"]
    _write_json(info.config_path, {"mcpServers": {}})

    args = mcp_swap.build_parser().parse_args(
        [
            "use-local",
            "--repo",
            str(fake_repo),
            "--cli",
            "cursor",
            "--env",
            "LIBTMUX_SOCKET=mcp-target",
        ]
    )
    assert mcp_swap.cmd_use_local(args) == 0

    entry = json.loads(info.config_path.read_text())["mcpServers"]["libtmux-engine"]
    assert entry["env"] == {"LIBTMUX_SOCKET": "mcp-target"}


def test_use_local_env_flag_wins_over_preserved_env(
    mcp_swap: t.Any, fake_home: pathlib.Path, fake_repo: pathlib.Path
) -> None:
    """Explicit ``--env`` overrides a preserved key; other preserved keys survive."""
    info = mcp_swap.CLIS["cursor"]
    _write_json(
        info.config_path,
        {
            "mcpServers": {
                "libtmux-engine": {
                    "command": "uvx",
                    "args": ["libtmux==0.63.0"],
                    "env": {"LIBTMUX_SAFETY": "readonly", "KEEP": "me"},
                }
            }
        },
    )

    args = mcp_swap.build_parser().parse_args(
        [
            "use-local",
            "--repo",
            str(fake_repo),
            "--cli",
            "cursor",
            "--env",
            "LIBTMUX_SAFETY=destructive",
        ]
    )
    assert mcp_swap.cmd_use_local(args) == 0

    entry = json.loads(info.config_path.read_text())["mcpServers"]["libtmux-engine"]
    assert entry["env"] == {"LIBTMUX_SAFETY": "destructive", "KEEP": "me"}


def test_use_local_env_written_on_already_local_entry(
    mcp_swap: t.Any, fake_home: pathlib.Path, fake_repo: pathlib.Path
) -> None:
    """``--env`` still writes when the entry already points at this repo."""
    info = mcp_swap.CLIS["cursor"]
    _write_json(
        info.config_path,
        {"mcpServers": {"libtmux-engine": _local_entry(fake_repo)}},
    )

    args = mcp_swap.build_parser().parse_args(
        [
            "use-local",
            "--repo",
            str(fake_repo),
            "--cli",
            "cursor",
            "--env",
            "LIBTMUX_SOCKET=mcp-target",
        ]
    )
    assert mcp_swap.cmd_use_local(args) == 0

    entry = json.loads(info.config_path.read_text())["mcpServers"]["libtmux-engine"]
    assert entry["env"] == {"LIBTMUX_SOCKET": "mcp-target"}


def test_use_local_entry_updates_already_local_entry(
    mcp_swap: t.Any, fake_home: pathlib.Path, fake_repo: pathlib.Path
) -> None:
    """An explicit entry change is not mistaken for an already-local no-op."""
    info = mcp_swap.CLIS["cursor"]
    _write_json(
        info.config_path,
        {"mcpServers": {"libtmux-engine": _local_entry(fake_repo)}},
    )

    args = mcp_swap.build_parser().parse_args(
        [
            "use-local",
            "--repo",
            str(fake_repo),
            "--cli",
            "cursor",
            "--entry",
            "alternate-mcp",
        ]
    )
    assert mcp_swap.cmd_use_local(args) == 0

    entry = json.loads(info.config_path.read_text())["mcpServers"]["libtmux-engine"]
    assert entry["args"][-1] == "alternate-mcp"


def test_env_pair_rejects_malformed(mcp_swap: t.Any) -> None:
    """``--env`` without ``=`` is an argparse error, not a silent skip."""
    with pytest.raises(SystemExit):
        mcp_swap.build_parser().parse_args(["use-local", "--env", "NOEQUALS"])


# ---------------------------------------------------------------------------
# naming hint
# ---------------------------------------------------------------------------


def test_naming_hint_points_at_registered_alias(
    mcp_swap: t.Any, fake_home: pathlib.Path, fake_repo: pathlib.Path
) -> None:
    """Hint names the real slug when the repo uses a non-default server name.

    A bare run would otherwise no-op on a missing entry, so the hint points
    at the name the CLIs were actually registered under.
    """
    _write_json(
        mcp_swap.CLIS["cursor"].config_path,
        {"mcpServers": {"tmux": _local_entry(fake_repo)}},
    )
    hint = mcp_swap._naming_hint(fake_repo.resolve(), "libtmux-engine")
    assert hint is not None
    assert "--server tmux" in hint


def test_naming_hint_none_when_derived_name_matches(
    mcp_swap: t.Any, fake_home: pathlib.Path, fake_repo: pathlib.Path
) -> None:
    """No hint when the repo is already registered under the derived name."""
    _write_json(
        mcp_swap.CLIS["cursor"].config_path,
        {"mcpServers": {"libtmux-engine": _local_entry(fake_repo)}},
    )
    assert mcp_swap._naming_hint(fake_repo.resolve(), "libtmux-engine") is None


def test_naming_hint_none_when_derived_and_alias_both_point_here(
    mcp_swap: t.Any, fake_home: pathlib.Path, fake_repo: pathlib.Path
) -> None:
    """An alias does not hide that the requested server already points here."""
    _write_json(
        mcp_swap.CLIS["cursor"].config_path,
        {
            "mcpServers": {
                "libtmux-engine": _local_entry(fake_repo),
                "tmux": _local_entry(fake_repo),
            }
        },
    )
    assert mcp_swap._naming_hint(fake_repo.resolve(), "libtmux-engine") is None


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def test_doctor_reports_name_mismatch_and_auth_env(
    mcp_swap: t.Any,
    fake_home: pathlib.Path,
    fake_repo: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Doctor surfaces the server-name mismatch and auth-overriding env vars."""
    _write_json(
        mcp_swap.CLIS["cursor"].config_path,
        {"mcpServers": {"tmux": _local_entry(fake_repo)}},
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    args = mcp_swap.build_parser().parse_args(["doctor", "--repo", str(fake_repo)])
    assert mcp_swap.cmd_doctor(args) == 0
    out = capsys.readouterr().out
    assert "server name mismatch" in out
    assert "--server tmux" in out
    assert "OPENAI_API_KEY" in out and "codex" in out


def test_doctor_flags_missing_backup_and_orphans(
    mcp_swap: t.Any,
    fake_home: pathlib.Path,
    fake_repo: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Doctor flags a state entry whose backup vanished, and untracked backups."""
    info = mcp_swap.CLIS["cursor"]
    _write_json(
        info.config_path, {"mcpServers": {"libtmux-engine": _local_entry(fake_repo)}}
    )
    # A recorded swap whose backup file does not exist -> revert would fail.
    mcp_swap.save_state(
        {
            ("cursor", "user"): mcp_swap.SwapEntry(
                config_path=str(info.config_path),
                backup_path=str(info.config_path) + ".bak.mcp-swap-20200101000000",
                server="libtmux-engine",
                action="replaced",
                swapped_at="20200101000000",
                seq_no=0,
            )
        }
    )
    # An orphaned backup on disk not referenced by state.
    orphan = info.config_path.parent / (
        info.config_path.name + ".bak.mcp-swap-20190101000000"
    )
    orphan.write_text("stale")

    args = mcp_swap.build_parser().parse_args(["doctor", "--repo", str(fake_repo)])
    assert mcp_swap.cmd_doctor(args) == 0
    out = capsys.readouterr().out
    assert "BACKUP MISSING" in out
    assert "orphaned backups" in out


def test_orphaned_backups_matches_swap_pattern(
    mcp_swap: t.Any,
    fake_home: pathlib.Path,
) -> None:
    """``_orphaned_backups`` finds swap backups and ignores the live config."""
    info = mcp_swap.CLIS["cursor"]
    info.config_path.parent.mkdir(parents=True, exist_ok=True)
    info.config_path.write_text("{}\n")
    b1 = info.config_path.parent / (
        info.config_path.name + ".bak.mcp-swap-20260101000000"
    )
    b1.write_text("x")
    found = mcp_swap._orphaned_backups(info.config_path)
    assert b1 in found
    assert info.config_path not in found


def test_doctor_does_not_call_orphaned_backups_safe_to_delete(
    mcp_swap: t.Any,
    fake_home: pathlib.Path,
    fake_repo: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Doctor treats an untracked backup as possible recovery data."""
    info = mcp_swap.CLIS["cursor"]
    _write_json(
        info.config_path,
        {"mcpServers": {"libtmux-engine": _local_entry(fake_repo)}},
    )
    referenced = info.config_path.parent / (
        info.config_path.name + ".bak.mcp-swap-20200101000000"
    )
    referenced.write_text("tracked")
    mcp_swap.save_state(
        {
            ("cursor", "user"): mcp_swap.SwapEntry(
                config_path=str(info.config_path),
                backup_path=str(referenced),
                server="libtmux-engine",
                action="replaced",
                swapped_at="20200101000000",
                seq_no=0,
            )
        }
    )
    orphan = info.config_path.parent / (
        info.config_path.name + ".bak.mcp-swap-20190101000000"
    )
    orphan.write_text("pristine")

    args = mcp_swap.build_parser().parse_args(["doctor", "--repo", str(fake_repo)])
    assert mcp_swap.cmd_doctor(args) == 0
    out = capsys.readouterr().out
    assert "orphaned backups: 1 file(s)" in out
    assert "safe to delete" not in out
    assert "inspect before deleting" in out


def test_doctor_ignores_scalar_server_entries(
    mcp_swap: t.Any,
    fake_home: pathlib.Path,
    fake_repo: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A malformed sibling entry does not hide valid diagnostic output."""
    _write_json(
        mcp_swap.CLIS["cursor"].config_path,
        {
            "mcpServers": {
                "broken": "not a mapping",
                "libtmux-engine": _local_entry(fake_repo),
            }
        },
    )

    args = mcp_swap.build_parser().parse_args(["doctor", "--repo", str(fake_repo)])
    assert mcp_swap.cmd_doctor(args) == 0
    assert "[cursor] libtmux-engine = local: this repo" in capsys.readouterr().out


def test_status_reports_scalar_selected_server_entry(
    mcp_swap: t.Any,
    fake_home: pathlib.Path,
    fake_repo: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A malformed selected entry is a clean status error, not a traceback."""
    info = mcp_swap.CLIS["cursor"]
    _write_json(
        info.config_path,
        {"mcpServers": {"libtmux-engine": "not a mapping"}},
    )
    args = mcp_swap.build_parser().parse_args(
        ["status", "--repo", str(fake_repo), "--cli", "cursor"]
    )

    assert mcp_swap.cmd_status(args) == 1
    assert "expected server entry to be a mapping" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Repeat swaps
# ---------------------------------------------------------------------------


def _freeze_timestamps(
    mcp_swap: t.Any,
    monkeypatch: pytest.MonkeyPatch,
    stamps: list[str],
) -> None:
    """Make the script's timestamp source yield ``stamps`` in order."""
    remaining = list(stamps)

    def fake_strftime(*_args: object) -> str:
        return remaining.pop(0) if remaining else stamps[-1]

    monkeypatch.setattr(
        mcp_swap,
        "time",
        types.SimpleNamespace(strftime=fake_strftime),
    )


@pytest.mark.parametrize(
    "stamps",
    [
        ["20260101000000", "20260101000000"],
        ["20260101000000", "20260101000001"],
    ],
    ids=["same-second", "different-second"],
)
def test_repeat_swap_then_revert_restores_pristine_config(
    mcp_swap: t.Any,
    fake_home: pathlib.Path,
    fake_repo: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    stamps: list[str],
) -> None:
    """A repeat swap keeps the first backup and reverts to pristine bytes."""
    info = mcp_swap.CLIS["cursor"]
    _write_json(
        info.config_path,
        {
            "mcpServers": {
                "libtmux-engine": {
                    "command": "uvx",
                    "args": ["libtmux==0.63.0"],
                }
            }
        },
    )
    original = info.config_path.read_bytes()
    _freeze_timestamps(mcp_swap, monkeypatch, stamps)
    parser = mcp_swap.build_parser()

    def swap(socket_name: str) -> None:
        args = parser.parse_args(
            [
                "use-local",
                "--repo",
                str(fake_repo),
                "--cli",
                "cursor",
                "--env",
                f"LIBTMUX_SOCKET={socket_name}",
            ]
        )
        assert mcp_swap.cmd_use_local(args) == 0

    swap("first")
    first_backup = pathlib.Path(mcp_swap.load_state()[("cursor", "user")].backup_path)
    assert first_backup.read_bytes() == original

    swap("second")

    live_entry = json.loads(info.config_path.read_text())["mcpServers"][
        "libtmux-engine"
    ]
    assert live_entry["env"]["LIBTMUX_SOCKET"] == "second"
    state_entry = mcp_swap.load_state()[("cursor", "user")]
    assert pathlib.Path(state_entry.backup_path) == first_backup
    assert first_backup.read_bytes() == original
    assert mcp_swap._orphaned_backups(info.config_path) == [first_backup]

    revert_args = parser.parse_args(["revert", "--cli", "cursor"])
    assert mcp_swap.cmd_revert(revert_args) == 0
    assert info.config_path.read_bytes() == original


def test_repeat_swap_refuses_to_cross_newer_claude_scope(
    mcp_swap: t.Any,
    fake_home: pathlib.Path,
    fake_repo: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An older whole-file layer cannot be mutated beneath a newer layer."""
    info = mcp_swap.CLIS["claude"]
    pinned = {
        "type": "stdio",
        "command": "uvx",
        "args": ["libtmux==0.63.0"],
        "env": {},
    }
    _write_json(
        info.config_path,
        {
            "mcpServers": {"libtmux-engine": pinned},
            "projects": {
                str(fake_repo.resolve()): {
                    "mcpServers": {"libtmux-engine": pinned},
                }
            },
        },
    )
    original = info.config_path.read_bytes()
    _freeze_timestamps(
        mcp_swap,
        monkeypatch,
        ["20260101000000", "20260101000001", "20260101000002"],
    )
    parser = mcp_swap.build_parser()

    def swap(scope: str, socket_name: str) -> int:
        args = parser.parse_args(
            [
                "use-local",
                "--repo",
                str(fake_repo),
                "--cli",
                "claude",
                "--scope",
                scope,
                "--env",
                f"LIBTMUX_SOCKET={socket_name}",
            ]
        )
        return t.cast(int, mcp_swap.cmd_use_local(args))

    assert swap("user", "first") == 0
    assert swap("project", "first") == 0
    before_rejected_swap = info.config_path.read_bytes()
    state_before = mcp_swap.load_state()
    backups = [pathlib.Path(entry.backup_path) for entry in state_before.values()]

    assert swap("user", "second") == 1
    assert info.config_path.read_bytes() == before_rejected_swap
    assert mcp_swap.load_state() == state_before
    assert all(backup.exists() for backup in backups)

    revert_args = parser.parse_args(["revert", "--cli", "claude"])
    assert mcp_swap.cmd_revert(revert_args) == 0
    assert info.config_path.read_bytes() == original


def test_missing_recorded_backup_blocks_repeat_and_revert(
    mcp_swap: t.Any,
    fake_home: pathlib.Path,
    fake_repo: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing pre-swap backup cannot be replaced with already-local bytes."""
    info = mcp_swap.CLIS["claude"]
    pinned = {
        "type": "stdio",
        "command": "uvx",
        "args": ["libtmux==0.63.0"],
        "env": {},
    }
    _write_json(
        info.config_path,
        {
            "mcpServers": {"libtmux-engine": pinned},
            "projects": {
                str(fake_repo.resolve()): {
                    "mcpServers": {"libtmux-engine": pinned},
                }
            },
        },
    )
    _freeze_timestamps(
        mcp_swap,
        monkeypatch,
        ["20260101000000", "20260101000000", "20260101000000"],
    )
    parser = mcp_swap.build_parser()

    def swap(scope: str, socket_name: str) -> int:
        args = parser.parse_args(
            [
                "use-local",
                "--repo",
                str(fake_repo),
                "--cli",
                "claude",
                "--scope",
                scope,
                "--env",
                f"LIBTMUX_SOCKET={socket_name}",
            ]
        )
        return t.cast(int, mcp_swap.cmd_use_local(args))

    assert swap("user", "first") == 0
    after_user_swap = info.config_path.read_bytes()
    state_before = mcp_swap.load_state()
    first_user_backup = pathlib.Path(state_before[("claude", "user")].backup_path)
    first_user_backup.unlink()

    assert swap("user", "first") == 1
    assert swap("user", "second") == 1
    assert info.config_path.read_bytes() == after_user_swap
    assert mcp_swap.load_state() == state_before
    assert not first_user_backup.exists()

    revert_args = parser.parse_args(["revert", "--cli", "claude"])
    assert mcp_swap.cmd_revert(revert_args) == 1
    assert info.config_path.read_bytes() == after_user_swap
    assert mcp_swap.load_state() == state_before


def test_write_new_backup_never_overwrites(
    mcp_swap: t.Any,
    tmp_path: pathlib.Path,
) -> None:
    """A claimed backup path forces an exclusive suffixed write."""
    base = tmp_path / "config.toml.bak.mcp-swap-20260101000000"
    first = mcp_swap.write_new_backup(base, b"pristine\n")
    second = mcp_swap.write_new_backup(base, b"later\n")
    third = mcp_swap.write_new_backup(base, b"latest\n")

    assert first == base
    assert second == base.with_name(base.name + "-1")
    assert third == base.with_name(base.name + "-2")
    assert first.read_bytes() == b"pristine\n"
    assert second.read_bytes() == b"later\n"
    assert third.read_bytes() == b"latest\n"


# ---------------------------------------------------------------------------
# Recovery transaction ordering
# ---------------------------------------------------------------------------


def test_use_local_persists_state_before_config_write_and_rolls_it_back(
    mcp_swap: t.Any,
    fake_home: pathlib.Path,
    fake_repo: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed config write sees durable recovery state, then restores cleanly."""
    info = mcp_swap.CLIS["cursor"]
    _write_json(
        info.config_path,
        {
            "mcpServers": {
                "libtmux-engine": {
                    "command": "uvx",
                    "args": ["libtmux==0.63.0"],
                }
            }
        },
    )
    original = info.config_path.read_bytes()
    real_atomic_write = mcp_swap.atomic_write
    state_was_durable = False
    config_write_error = OSError("injected config write failure")

    def fail_config_write(path: pathlib.Path, data: bytes) -> None:
        nonlocal state_was_durable
        if path == info.config_path and data != original:
            state = mcp_swap.load_state()
            state_was_durable = ("cursor", "user") in state
            raise config_write_error
        real_atomic_write(path, data)

    monkeypatch.setattr(mcp_swap, "atomic_write", fail_config_write)
    args = mcp_swap.build_parser().parse_args(
        ["use-local", "--repo", str(fake_repo), "--cli", "cursor"]
    )

    assert mcp_swap.cmd_use_local(args) == 1
    assert state_was_durable
    assert info.config_path.read_bytes() == original
    assert mcp_swap.load_state() == {}
    assert not mcp_swap.STATE_FILE.exists()
    assert mcp_swap._orphaned_backups(info.config_path) == []


def test_use_local_revalidation_failure_rolls_back_config_and_state(
    mcp_swap: t.Any,
    fake_home: pathlib.Path,
    fake_repo: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A post-write parse failure restores the config and removes recovery state."""
    info = mcp_swap.CLIS["cursor"]
    _write_json(
        info.config_path,
        {
            "mcpServers": {
                "libtmux-engine": {
                    "command": "uvx",
                    "args": ["libtmux==0.63.0"],
                }
            }
        },
    )
    original = info.config_path.read_bytes()
    revalidation_error = ValueError("injected revalidation failure")

    def fail_revalidation(_info: object) -> None:
        raise revalidation_error

    monkeypatch.setattr(mcp_swap, "_revalidate", fail_revalidation)
    args = mcp_swap.build_parser().parse_args(
        ["use-local", "--repo", str(fake_repo), "--cli", "cursor"]
    )

    assert mcp_swap.cmd_use_local(args) == 1
    assert info.config_path.read_bytes() == original
    assert mcp_swap.load_state() == {}
    assert not mcp_swap.STATE_FILE.exists()
    assert mcp_swap._orphaned_backups(info.config_path) == []


def test_use_local_state_failure_prevents_config_mutation(
    mcp_swap: t.Any,
    fake_home: pathlib.Path,
    fake_repo: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure to register recovery state leaves the live config untouched."""
    info = mcp_swap.CLIS["cursor"]
    _write_json(
        info.config_path,
        {
            "mcpServers": {
                "libtmux-engine": {
                    "command": "uvx",
                    "args": ["libtmux==0.63.0"],
                }
            }
        },
    )
    original = info.config_path.read_bytes()
    state_write_error = OSError("injected state write failure")

    def fail_save_state(_entries: object) -> None:
        raise state_write_error

    monkeypatch.setattr(mcp_swap, "save_state", fail_save_state)
    args = mcp_swap.build_parser().parse_args(
        ["use-local", "--repo", str(fake_repo), "--cli", "cursor"]
    )

    assert mcp_swap.cmd_use_local(args) == 1
    assert info.config_path.read_bytes() == original
    assert not mcp_swap.STATE_FILE.exists()
    assert mcp_swap._orphaned_backups(info.config_path) == []


def test_use_local_keeps_earlier_target_recoverable_when_later_backup_fails(
    mcp_swap: t.Any,
    fake_home: pathlib.Path,
    fake_repo: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later target failure cannot discard an earlier target's recovery state."""
    cursor = mcp_swap.CLIS["cursor"]
    gemini = mcp_swap.CLIS["gemini"]
    pinned = {
        "mcpServers": {
            "libtmux-engine": {
                "command": "uvx",
                "args": ["libtmux==0.63.0"],
            }
        }
    }
    _write_json(cursor.config_path, pinned)
    _write_json(gemini.config_path, pinned)
    cursor_original = cursor.config_path.read_bytes()
    gemini_original = gemini.config_path.read_bytes()
    real_write_new_backup = t.cast(
        t.Callable[[pathlib.Path, bytes], pathlib.Path],
        mcp_swap.write_new_backup,
    )
    backup_error = OSError("injected backup failure")

    def fail_gemini_backup(base: pathlib.Path, data: bytes) -> pathlib.Path:
        if base.parent == gemini.config_path.parent:
            raise backup_error
        return real_write_new_backup(base, data)

    monkeypatch.setattr(mcp_swap, "write_new_backup", fail_gemini_backup)
    args = mcp_swap.build_parser().parse_args(
        [
            "use-local",
            "--repo",
            str(fake_repo),
            "--cli",
            "cursor",
            "--cli",
            "gemini",
        ]
    )

    assert mcp_swap.cmd_use_local(args) == 1
    state = mcp_swap.load_state()
    assert set(state) == {("cursor", "user")}
    cursor_backup = pathlib.Path(state[("cursor", "user")].backup_path)
    assert cursor_backup.read_bytes() == cursor_original
    assert cursor.config_path.read_bytes() != cursor_original
    assert gemini.config_path.read_bytes() == gemini_original
    assert mcp_swap._orphaned_backups(gemini.config_path) == []


def test_concurrent_swaps_preserve_both_recovery_entries(
    mcp_swap: t.Any,
    fake_home: pathlib.Path,
    fake_repo: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The transaction lock prevents concurrent state read-modify-write loss."""
    cursor = mcp_swap.CLIS["cursor"]
    gemini = mcp_swap.CLIS["gemini"]
    pinned = {
        "mcpServers": {
            "libtmux-engine": {
                "command": "uvx",
                "args": ["libtmux==0.63.0"],
            }
        }
    }
    _write_json(cursor.config_path, pinned)
    _write_json(gemini.config_path, pinned)
    cursor_waiting = threading.Event()
    release_cursor = threading.Event()
    gemini_reached_state_write = threading.Event()
    real_save_state = mcp_swap.save_state

    def pause_first_state_write(entries: t.Any) -> None:
        keys = set(entries)
        if keys == {("cursor", "user")} and not cursor_waiting.is_set():
            cursor_waiting.set()
            assert release_cursor.wait(timeout=5)
        if ("gemini", "user") in keys:
            gemini_reached_state_write.set()
        real_save_state(entries)

    monkeypatch.setattr(mcp_swap, "save_state", pause_first_state_write)
    parser = mcp_swap.build_parser()
    outcomes: dict[str, int] = {}

    def swap(cli: str) -> None:
        args = parser.parse_args(["use-local", "--repo", str(fake_repo), "--cli", cli])
        outcomes[cli] = mcp_swap.cmd_use_local(args)

    cursor_thread = threading.Thread(target=swap, args=("cursor",))
    gemini_thread = threading.Thread(target=swap, args=("gemini",))
    cursor_thread.start()
    assert cursor_waiting.wait(timeout=5)
    gemini_thread.start()
    overlapped = gemini_reached_state_write.wait(timeout=0.5)
    release_cursor.set()
    cursor_thread.join(timeout=5)
    gemini_thread.join(timeout=5)

    assert not cursor_thread.is_alive()
    assert not gemini_thread.is_alive()
    assert not overlapped
    assert outcomes == {"cursor": 0, "gemini": 0}
    assert set(mcp_swap.load_state()) == {
        ("cursor", "user"),
        ("gemini", "user"),
    }


def test_use_local_reports_unreadable_config_without_mutation(
    mcp_swap: t.Any,
    fake_home: pathlib.Path,
    fake_repo: pathlib.Path,
) -> None:
    """A malformed target config is a per-target error, not an uncaught failure."""
    info = mcp_swap.CLIS["cursor"]
    info.config_path.parent.mkdir(parents=True, exist_ok=True)
    info.config_path.write_text("{not json")
    original = info.config_path.read_bytes()
    args = mcp_swap.build_parser().parse_args(
        ["use-local", "--repo", str(fake_repo), "--cli", "cursor"]
    )

    assert mcp_swap.cmd_use_local(args) == 1
    assert info.config_path.read_bytes() == original
    assert mcp_swap.load_state() == {}


@pytest.mark.parametrize(
    "raw_state",
    (
        pytest.param("{", id="invalid_json"),
        pytest.param("[]", id="top_level_list"),
        pytest.param('{"entries": []}', id="entries_list"),
        pytest.param('{"entries": null}', id="entries_null"),
    ),
)
def test_use_local_refuses_malformed_recovery_state(
    mcp_swap: t.Any,
    fake_home: pathlib.Path,
    fake_repo: pathlib.Path,
    raw_state: str,
) -> None:
    """Corrupt recovery metadata cannot be overwritten by a new config swap."""
    info = mcp_swap.CLIS["cursor"]
    _write_json(
        info.config_path,
        {
            "mcpServers": {
                "libtmux-engine": {
                    "command": "uvx",
                    "args": ["libtmux==0.63.0"],
                }
            }
        },
    )
    original = info.config_path.read_bytes()
    mcp_swap.STATE_FILE.parent.mkdir(parents=True)
    mcp_swap.STATE_FILE.write_text(raw_state)
    args = mcp_swap.build_parser().parse_args(
        ["use-local", "--repo", str(fake_repo), "--cli", "cursor"]
    )

    with pytest.raises((RuntimeError, TypeError), match="recovery state"):
        mcp_swap.load_state()
    assert mcp_swap.cmd_use_local(args) == 1
    assert info.config_path.read_bytes() == original
    assert mcp_swap.STATE_FILE.read_text() == raw_state
    assert mcp_swap._orphaned_backups(info.config_path) == []


def test_revert_and_doctor_report_malformed_recovery_state(
    mcp_swap: t.Any,
    fake_home: pathlib.Path,
    fake_repo: pathlib.Path,
) -> None:
    """Recovery commands return errors instead of tracing back on corrupt state."""
    mcp_swap.STATE_FILE.parent.mkdir(parents=True)
    mcp_swap.STATE_FILE.write_text('{"entries": null}')
    parser = mcp_swap.build_parser()

    revert_args = parser.parse_args(["revert", "--cli", "cursor"])
    doctor_args = parser.parse_args(["doctor", "--repo", str(fake_repo)])

    assert mcp_swap.cmd_revert(revert_args) == 1
    assert mcp_swap.cmd_doctor(doctor_args) == 1
    assert mcp_swap.STATE_FILE.read_text() == '{"entries": null}'


def test_revert_checkpoints_each_layer_before_a_later_restore_failure(
    mcp_swap: t.Any,
    fake_home: pathlib.Path,
    fake_repo: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed LIFO layer stays cleared when the next restore fails."""
    info = mcp_swap.CLIS["claude"]
    pinned = {
        "type": "stdio",
        "command": "uvx",
        "args": ["libtmux==0.63.0"],
        "env": {},
    }
    _write_json(
        info.config_path,
        {
            "mcpServers": {"libtmux-engine": pinned},
            "projects": {
                str(fake_repo.resolve()): {
                    "mcpServers": {"libtmux-engine": pinned},
                }
            },
        },
    )
    original = info.config_path.read_bytes()
    parser = mcp_swap.build_parser()

    def swap(scope: str) -> None:
        args = parser.parse_args(
            [
                "use-local",
                "--repo",
                str(fake_repo),
                "--cli",
                "claude",
                "--scope",
                scope,
            ]
        )
        assert mcp_swap.cmd_use_local(args) == 0

    swap("user")
    after_user_swap = info.config_path.read_bytes()
    swap("project")
    before_revert = mcp_swap.load_state()
    user_backup = pathlib.Path(before_revert[("claude", "user")].backup_path)
    project_backup = pathlib.Path(before_revert[("claude", "project")].backup_path)
    real_atomic_write = mcp_swap.atomic_write
    config_writes = 0
    restore_error = OSError("injected later restore failure")

    def fail_second_config_restore(path: pathlib.Path, data: bytes) -> None:
        nonlocal config_writes
        if path == info.config_path:
            config_writes += 1
            if config_writes == 2:
                raise restore_error
        real_atomic_write(path, data)

    monkeypatch.setattr(mcp_swap, "atomic_write", fail_second_config_restore)
    revert_args = parser.parse_args(["revert", "--cli", "claude"])

    assert mcp_swap.cmd_revert(revert_args) == 1
    assert info.config_path.read_bytes() == after_user_swap
    state = mcp_swap.load_state()
    assert set(state) == {("claude", "user")}
    assert user_backup.exists()
    assert not project_backup.exists()

    assert mcp_swap.cmd_revert(revert_args) == 0
    assert info.config_path.read_bytes() == original
    assert not mcp_swap.STATE_FILE.exists()


def test_revert_keeps_backup_when_state_checkpoint_fails(
    mcp_swap: t.Any,
    fake_home: pathlib.Path,
    fake_repo: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A restored layer retains its backup until state removal is durable."""
    info = mcp_swap.CLIS["claude"]
    pinned = {
        "type": "stdio",
        "command": "uvx",
        "args": ["libtmux==0.63.0"],
        "env": {},
    }
    _write_json(
        info.config_path,
        {
            "mcpServers": {"libtmux-engine": pinned},
            "projects": {
                str(fake_repo.resolve()): {
                    "mcpServers": {"libtmux-engine": pinned},
                }
            },
        },
    )
    original = info.config_path.read_bytes()
    parser = mcp_swap.build_parser()
    for scope in ("user", "project"):
        args = parser.parse_args(
            [
                "use-local",
                "--repo",
                str(fake_repo),
                "--cli",
                "claude",
                "--scope",
                scope,
            ]
        )
        assert mcp_swap.cmd_use_local(args) == 0

    state = mcp_swap.load_state()
    project_backup = pathlib.Path(state[("claude", "project")].backup_path)
    real_save_state = mcp_swap.save_state
    checkpoint_error = OSError("injected checkpoint failure")

    def fail_checkpoint(_entries: object) -> None:
        raise checkpoint_error

    monkeypatch.setattr(mcp_swap, "save_state", fail_checkpoint)
    revert_args = parser.parse_args(["revert", "--cli", "claude"])

    assert mcp_swap.cmd_revert(revert_args) == 1
    assert set(mcp_swap.load_state()) == {
        ("claude", "user"),
        ("claude", "project"),
    }
    assert project_backup.exists()

    monkeypatch.setattr(mcp_swap, "save_state", real_save_state)
    assert mcp_swap.cmd_revert(revert_args) == 0
    assert info.config_path.read_bytes() == original


def test_scoped_revert_refuses_to_cross_newer_whole_file_layer(
    mcp_swap: t.Any,
    fake_home: pathlib.Path,
    fake_repo: pathlib.Path,
) -> None:
    """A scoped Claude revert preserves whole-file backup LIFO ordering."""
    info = mcp_swap.CLIS["claude"]
    pinned = {
        "type": "stdio",
        "command": "uvx",
        "args": ["libtmux==0.63.0"],
        "env": {},
    }
    _write_json(
        info.config_path,
        {
            "mcpServers": {"libtmux-engine": pinned},
            "projects": {
                str(fake_repo.resolve()): {
                    "mcpServers": {"libtmux-engine": pinned},
                }
            },
        },
    )
    original = info.config_path.read_bytes()
    parser = mcp_swap.build_parser()
    for scope in ("user", "project"):
        swap_args = parser.parse_args(
            [
                "use-local",
                "--repo",
                str(fake_repo),
                "--cli",
                "claude",
                "--scope",
                scope,
            ]
        )
        assert mcp_swap.cmd_use_local(swap_args) == 0

    fully_swapped = info.config_path.read_bytes()
    state = mcp_swap.load_state()
    backups = {key: pathlib.Path(entry.backup_path) for key, entry in state.items()}

    user_revert = parser.parse_args(["revert", "--cli", "claude", "--scope", "user"])
    assert mcp_swap.cmd_revert(user_revert) == 1
    assert info.config_path.read_bytes() == fully_swapped
    assert mcp_swap.load_state() == state
    assert all(backup.exists() for backup in backups.values())

    project_revert = parser.parse_args(
        ["revert", "--cli", "claude", "--scope", "project"]
    )
    assert mcp_swap.cmd_revert(project_revert) == 0
    assert mcp_swap.cmd_revert(user_revert) == 0
    assert info.config_path.read_bytes() == original
    assert not mcp_swap.STATE_FILE.exists()


# ---------------------------------------------------------------------------
# Pull-request targeting
# ---------------------------------------------------------------------------


class RemoteURLFixture(t.NamedTuple):
    """One git remote spelling and the https URL it normalizes to.

    Attributes
    ----------
    test_id : str
        Identifier shown in the parametrized test name.
    remote : str
        A URL as ``git remote get-url`` may report it.
    expected : str
        The https form the pull-request ref is fetched from.
    """

    test_id: str
    remote: str
    expected: str


REMOTE_URL_FIXTURES: list[RemoteURLFixture] = [
    RemoteURLFixture(
        "git_ssh_scheme", "git+ssh://git@github.com/o/n.git", "https://github.com/o/n"
    ),
    RemoteURLFixture(
        "ssh_scheme", "ssh://git@github.com/o/n.git", "https://github.com/o/n"
    ),
    RemoteURLFixture(
        "scp_shorthand", "git@github.com:o/n.git", "https://github.com/o/n"
    ),
    RemoteURLFixture(
        "https_dotgit", "https://github.com/o/n.git", "https://github.com/o/n"
    ),
    RemoteURLFixture("https_plain", "https://github.com/o/n", "https://github.com/o/n"),
    RemoteURLFixture(
        "self_hosted",
        "git@git.example.com:team/n.git",
        "https://git.example.com/team/n",
    ),
]


@pytest.mark.parametrize(
    RemoteURLFixture._fields,
    REMOTE_URL_FIXTURES,
    ids=[f.test_id for f in REMOTE_URL_FIXTURES],
)
def test_normalize_remote_url(
    mcp_swap: t.Any, test_id: str, remote: str, expected: str
) -> None:
    """Every spelling git accepts resolves to the same https URL.

    This repo's own ``origin`` is spelled ``git+ssh://``, so the
    normalizer is what makes ``--pr`` work here at all.
    """
    assert test_id
    assert mcp_swap._normalize_remote_url(remote) == expected


def test_build_pr_spec_round_trips_through_pr_ref(mcp_swap: t.Any) -> None:
    """A built pull-request spec is recognized by the reader that parses it."""
    spec = mcp_swap.build_pr_spec(
        "https://github.com/tmux-python/libtmux", 114, "libtmux-engine-mcp"
    )

    assert spec.command == "uvx"
    assert spec.args == [
        "--from",
        "git+https://github.com/tmux-python/libtmux@refs/pull/114/head",
        "libtmux-engine-mcp",
    ]
    assert spec.pr_ref() == ("https://github.com/tmux-python/libtmux", 114)
    assert spec.is_local_uv_directory() is False


def test_pr_ref_ignores_non_pr_specs(mcp_swap: t.Any) -> None:
    """A local checkout, a version pin and a branch are not pull requests."""
    local = mcp_swap.McpServerSpec(
        command="uv", args=["--directory", "/tmp", "run", "x"]
    )
    pinned = mcp_swap.McpServerSpec(command="uvx", args=["libtmux==0.63.0"])
    branch = mcp_swap.McpServerSpec(
        command="uvx", args=["--from", "git+https://github.com/o/n@main", "x"]
    )

    assert local.pr_ref() is None
    assert pinned.pr_ref() is None
    assert branch.pr_ref() is None


def test_describe_spec_labels_a_pr_before_the_version_pin_branch(
    mcp_swap: t.Any, tmp_path: pathlib.Path
) -> None:
    """A pull-request ref is described as a PR, not as a version pin.

    The ref carries an ``@``, which the pin branch would otherwise report
    as ``pypi pin: git+...@refs/pull/114/head``.
    """
    spec = mcp_swap.build_pr_spec("https://github.com/o/n", 114, "libtmux-engine-mcp")

    assert mcp_swap._describe_spec(spec, tmp_path) == "PR #114: https://github.com/o/n"


def test_points_at_distinguishes_pr_numbers(
    mcp_swap: t.Any, tmp_path: pathlib.Path
) -> None:
    """A swap to one pull request is not treated as already pointing at another."""
    target = mcp_swap.build_pr_spec("https://github.com/o/n", 114, "x")
    same = mcp_swap.build_pr_spec("https://github.com/o/n", 114, "x")
    other = mcp_swap.build_pr_spec("https://github.com/o/n", 115, "x")
    local = mcp_swap.build_local_spec(tmp_path, "x")

    assert mcp_swap._points_at(same, target) is True
    assert mcp_swap._points_at(other, target) is False
    assert mcp_swap._points_at(local, target) is False
    assert mcp_swap._points_at(local, local) is True


def test_points_at_rejects_a_local_entry_with_another_entry_command(
    mcp_swap: t.Any, tmp_path: pathlib.Path
) -> None:
    """``--entry`` changes argv, so the same repo is not "already local".

    Both specs point at this checkout; only an exact argv comparison sees
    that the console script differs, which is what keeps ``--entry`` from
    being silently ignored.
    """
    target = mcp_swap.build_local_spec(tmp_path, "libtmux-engine-mcp")
    other_entry = mcp_swap.build_local_spec(tmp_path, "alternate-mcp")

    assert mcp_swap._points_at(other_entry, target) is False


def test_preflight_accepts_a_server_that_answers_initialize(
    mcp_swap: t.Any, tmp_path: pathlib.Path
) -> None:
    """A stdio server that replies to ``initialize`` passes preflight."""
    server = tmp_path / "server.py"
    server.write_text(
        "import json, sys\n"
        "line = sys.stdin.readline()\n"
        "req = json.loads(line)\n"
        'print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {}}))\n',
        encoding="utf-8",
    )
    spec = mcp_swap.McpServerSpec(command=sys.executable, args=[str(server)])

    assert mcp_swap.preflight_spec(spec, timeout=60) is None


def test_preflight_reports_stderr_when_the_server_never_answers(
    mcp_swap: t.Any, tmp_path: pathlib.Path
) -> None:
    """A server that dies is reported with the tail of its stderr."""
    server = tmp_path / "server.py"
    server.write_text(
        'import sys\nsys.stderr.write("could not resolve ref\\n")\nsys.exit(1)\n',
        encoding="utf-8",
    )
    spec = mcp_swap.McpServerSpec(command=sys.executable, args=[str(server)])

    assert mcp_swap.preflight_spec(spec, timeout=60) == "could not resolve ref"


def test_preflight_reports_a_command_that_cannot_launch(mcp_swap: t.Any) -> None:
    """A missing binary is named rather than raising."""
    spec = mcp_swap.McpServerSpec(command="mcp-swap-no-such-binary", args=[])

    failure = mcp_swap.preflight_spec(spec, timeout=60)

    assert failure is not None
    assert "mcp-swap-no-such-binary" in failure


def test_preflight_passes_spec_env_to_the_process(
    mcp_swap: t.Any, tmp_path: pathlib.Path
) -> None:
    """``spec.env`` reaches the launched server.

    ``LIBTMUX_SAFETY`` and ``LIBTMUX_SOCKET`` travel this way, so a
    preflight that dropped the env would reject a spec that works in an
    agent.
    """
    server = tmp_path / "server.py"
    server.write_text(
        "import json, os, sys\n"
        "req = json.loads(sys.stdin.readline())\n"
        'if os.environ.get("MCP_SWAP_PROBE") != "1":\n'
        "    sys.exit(2)\n"
        'print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {}}))\n',
        encoding="utf-8",
    )
    spec = mcp_swap.McpServerSpec(
        command=sys.executable, args=[str(server)], env={"MCP_SWAP_PROBE": "1"}
    )

    assert mcp_swap.preflight_spec(spec, timeout=60) is None


@pytest.mark.parametrize("raw", ["0", "-5", "notanumber", "1.5", ""])
def test_pr_number_rejects_what_is_not_a_pull_request(
    mcp_swap: t.Any, raw: str
) -> None:
    """``--pr`` takes a positive integer and nothing else."""
    with pytest.raises(argparse.ArgumentTypeError):
        mcp_swap._pr_number(raw)


def test_pr_number_accepts_a_pull_request_number(mcp_swap: t.Any) -> None:
    """A plain positive number parses to an int."""
    assert mcp_swap._pr_number("115") == 115


@pytest.mark.parametrize("raw", ["0", "-5", "notanumber"])
def test_parser_rejects_a_bad_pr_argument(mcp_swap: t.Any, raw: str) -> None:
    """The parser surfaces the rejection instead of swapping onto a bad ref."""
    with pytest.raises(SystemExit):
        mcp_swap.build_parser().parse_args(["use-local", "--pr", raw])


# ---------------------------------------------------------------------------
# JSON writer fidelity
#
# The swap edits one entry inside a file the user owns, so bytes it did
# not set out to change must survive the rewrite. ``load_config`` ->
# ``dump_config_bytes`` is the whole write path, so an unmodified config
# has to come back byte-identical.
#
# Out of scope, and normalized rather than preserved: indent width, CRLF,
# `\/` and `\uXXXX` escapes of characters that need none, duplicate keys,
# and number spelling (`1e5` -> `100000.0`). None appear in what the JSON
# CLIs write — they all emit `JSON.stringify(x, null, 2)` — and none
# change what a CLI reads, only the bytes a dotfile diff shows.
# ---------------------------------------------------------------------------


class JSONFidelityCase(t.NamedTuple):
    """A JSON config body whose exact bytes survive a no-op rewrite.

    Attributes
    ----------
    test_id : str
        Identifier shown in the parametrized test name.
    body : str
        The config file's text, written to disk verbatim.
    """

    test_id: str
    body: str


PRESERVED_JSON: list[JSONFidelityCase] = [
    JSONFidelityCase(
        "mcp_servers_block",
        '{\n  "mcpServers": {\n    "libtmux-engine": {\n      "command": "uvx",\n'
        '      "args": [\n        "libtmux==0.63.0"\n      ]\n    }\n  }\n}\n',
    ),
    JSONFidelityCase(
        "non_ascii_model_label",
        '{\n  "model": "Fable 5 · Most capable…",\n  "mcpServers": {}\n}\n',
    ),
    JSONFidelityCase(
        "emoji_and_cjk", '{\n  "history": [\n    "🙂 日本語 café"\n  ]\n}\n'
    ),
    JSONFidelityCase("escaped_lone_surrogate", '{\n  "truncated": "\\ud800"\n}\n'),
    JSONFidelityCase("unsorted_keys", '{\n  "zeta": 1,\n  "alpha": 2\n}\n'),
    JSONFidelityCase(
        "claude_shape_without_trailing_newline",
        '{\n  "model": "Fable 5 · Most capable…",\n  "projects": {\n'
        '    "/home/someone/repo": {\n      "mcpServers": {}\n    }\n  }\n}',
    ),
]


def _json_config(
    mcp_swap: t.Any, tmp_path: pathlib.Path, body: str
) -> tuple[t.Any, bytes]:
    """Write ``body`` verbatim and return its ``CLIInfo`` and exact bytes."""
    path = tmp_path / "config.json"
    raw = body.encode()
    path.write_bytes(raw)
    info = mcp_swap.CLIInfo(
        name="cursor",
        binary="cursor-agent",
        config_path=path,
        fmt="json",
        container=("mcpServers",),
        dialect="standard",
    )
    return info, raw


@pytest.mark.parametrize(
    JSONFidelityCase._fields,
    PRESERVED_JSON,
    ids=[c.test_id for c in PRESERVED_JSON],
)
def test_untouched_json_config_round_trips_byte_identical(
    mcp_swap: t.Any, tmp_path: pathlib.Path, test_id: str, body: str
) -> None:
    """Parsing a config and writing it back unmodified changes nothing.

    Every case is a shape the JavaScript agent CLIs actually emit:
    two-space indent, literal non-ASCII, escapes only below ``0x20`` plus
    lone surrogates, and no terminating newline.
    """
    assert test_id
    info, raw = _json_config(mcp_swap, tmp_path, body)

    assert (
        mcp_swap.dump_config_bytes(info, mcp_swap.load_config(info), original=raw)
        == raw
    )


def test_dump_config_bytes_ends_a_seeded_file_with_a_newline(
    mcp_swap: t.Any, tmp_path: pathlib.Path
) -> None:
    """With no original to match, a JSON config gets the conventional newline."""
    info, _ = _json_config(mcp_swap, tmp_path, "")

    assert (
        mcp_swap.dump_config_bytes(info, {"mcpServers": {}}, original=b"")
        == b'{\n  "mcpServers": {}\n}\n'
    )


def test_dump_config_bytes_escapes_a_config_it_cannot_encode(
    mcp_swap: t.Any, tmp_path: pathlib.Path
) -> None:
    r"""A lone surrogate has no UTF-8 form, so the document is escaped instead.

    JavaScript writes a string sliced through a surrogate pair as
    ``"\ud800"``, which parses to a Python string ``str.encode`` rejects.
    Escaping the whole document is what keeps the file writable at all.
    """
    config = {"truncated": "\ud800", "label": "café"}

    with pytest.raises(UnicodeEncodeError):
        json.dumps(config, indent=2, ensure_ascii=False).encode()

    info, _ = _json_config(mcp_swap, tmp_path, "")
    written = mcp_swap.dump_config_bytes(info, config, original=b"")

    assert written == b'{\n  "truncated": "\\ud800",\n  "label": "caf\\u00e9"\n}\n'
    assert json.loads(written.decode()) == config


def test_swap_leaves_non_ascii_elsewhere_in_the_config_alone(
    mcp_swap: t.Any, fake_home: pathlib.Path, fake_repo: pathlib.Path
) -> None:
    """A real swap does not re-escape config text it never read.

    Claude stores model labels and prompt history alongside the MCP
    entries, so escaping on write turns a one-entry edit into a diff
    spanning the file.
    """
    info = mcp_swap.CLIS["claude"]
    label = "Fable 5 · Most capable…"
    _write_json(
        info.config_path,
        {
            "model": label,
            "projects": {
                str(fake_repo.resolve()): {
                    "mcpServers": {"libtmux-engine": _pinned_claude_entry()},
                    "history": ["café ☕"],
                }
            },
        },
    )
    args = mcp_swap.build_parser().parse_args(
        ["use-local", "--repo", str(fake_repo), "--cli", "claude"]
    )

    assert mcp_swap.cmd_use_local(args) == 0

    after = info.config_path.read_text()
    assert f'"model": "{label}"' in after
    assert '"café ☕"' in after
    assert "\\u" not in after


def test_swap_does_not_append_a_newline_the_cli_never_wrote(
    mcp_swap: t.Any, fake_home: pathlib.Path, fake_repo: pathlib.Path
) -> None:
    """Claude's config has no trailing newline, and swapping must not add one."""
    info = mcp_swap.CLIS["claude"]
    body = json.dumps(
        {
            "projects": {
                str(fake_repo.resolve()): {
                    "mcpServers": {"libtmux-engine": _pinned_claude_entry()}
                }
            }
        },
        indent=2,
    )
    info.config_path.parent.mkdir(parents=True, exist_ok=True)
    info.config_path.write_text(body)

    args = mcp_swap.build_parser().parse_args(
        ["use-local", "--repo", str(fake_repo), "--cli", "claude"]
    )
    assert mcp_swap.cmd_use_local(args) == 0

    assert not info.config_path.read_bytes().endswith(b"\n")


# ---------------------------------------------------------------------------
# Atomic writes through symlinked configs
# ---------------------------------------------------------------------------


def _build_symlink_chain(
    root: pathlib.Path, hops: int
) -> tuple[pathlib.Path, pathlib.Path, list[pathlib.Path]]:
    """Create ``hops`` links ending at an existing config file.

    Parameters
    ----------
    root : pathlib.Path
        Empty directory where the link and target trees are created.
    hops : int
        Number of links in the chain.

    Returns
    -------
    tuple of pathlib.Path, pathlib.Path, list of pathlib.Path
        Entry path, final target, and each link in the chain.
    """
    target = root / "dotfiles" / "mcp.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"original\n")
    link_dir = root / "home"
    link_dir.mkdir()
    links: list[pathlib.Path] = []
    entry = target
    for hop in range(hops):
        link = link_dir / f"hop-{hop}.json"
        link.symlink_to(entry)
        links.append(link)
        entry = link
    return entry, target, links


@pytest.mark.parametrize("hops", [1, 3], ids=["single", "chain"])
def test_atomic_write_updates_the_symlink_target(
    mcp_swap: t.Any, tmp_path: pathlib.Path, hops: int
) -> None:
    """The final target receives the bytes and every link survives."""
    entry, target, links = _build_symlink_chain(tmp_path, hops)

    mcp_swap.atomic_write(entry, b"swapped\n")

    assert all(link.is_symlink() for link in links)
    assert target.read_bytes() == b"swapped\n"
    assert entry.read_bytes() == b"swapped\n"


def test_atomic_write_stages_beside_the_symlink_target(
    mcp_swap: t.Any, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The temp file shares the final target's filesystem for atomic rename."""
    entry, target, _links = _build_symlink_chain(tmp_path, 1)
    real_mkstemp = mcp_swap.tempfile.mkstemp
    staged_in: list[str | None] = []

    def recording_mkstemp(*args: t.Any, **kwargs: t.Any) -> tuple[int, str]:
        staged_in.append(kwargs.get("dir"))
        return t.cast("tuple[int, str]", real_mkstemp(*args, **kwargs))

    monkeypatch.setattr(mcp_swap.tempfile, "mkstemp", recording_mkstemp)

    mcp_swap.atomic_write(entry, b"swapped\n")

    assert staged_in == [str(target.parent)]


def test_atomic_write_preserves_the_target_mode(
    mcp_swap: t.Any, tmp_path: pathlib.Path
) -> None:
    """Replacing a config does not silently narrow its permission bits."""
    target = tmp_path / "mcp.json"
    target.write_bytes(b"original\n")
    target.chmod(0o640)

    mcp_swap.atomic_write(target, b"swapped\n")

    assert target.stat().st_mode & 0o777 == 0o640


def test_symlinked_config_swap_and_revert_round_trip(
    mcp_swap: t.Any, fake_home: pathlib.Path, fake_repo: pathlib.Path
) -> None:
    """Swap and revert update the target without replacing the config link."""
    info = mcp_swap.CLIS["cursor"]
    target = fake_home / "dotfiles" / "cursor" / "mcp.json"
    _write_json(target, {"mcpServers": {"libtmux-engine": _pinned_entry()}})
    original = target.read_bytes()
    info.config_path.parent.mkdir(parents=True)
    info.config_path.symlink_to(target)
    parser = mcp_swap.build_parser()

    swap = parser.parse_args(["use-local", "--repo", str(fake_repo), "--cli", "cursor"])
    assert mcp_swap.cmd_use_local(swap) == 0
    state = mcp_swap.load_state()["cursor", "user"]
    backup = pathlib.Path(state.backup_path)
    assert info.config_path.is_symlink()
    assert backup.parent == info.config_path.parent
    entry = json.loads(target.read_text())["mcpServers"]["libtmux-engine"]
    assert entry["command"] == "uv"

    assert mcp_swap.cmd_revert(parser.parse_args(["revert", "--cli", "cursor"])) == 0
    assert info.config_path.is_symlink()
    assert target.read_bytes() == original
    assert not backup.exists()


@pytest.mark.parametrize("replacement_kind", ["symlink", "file"])
def test_revert_uses_the_original_target_when_a_config_link_is_replaced(
    mcp_swap: t.Any,
    fake_home: pathlib.Path,
    fake_repo: pathlib.Path,
    replacement_kind: str,
) -> None:
    """Repointing or replacing a link cannot redirect recovery into a new file."""
    info = mcp_swap.CLIS["cursor"]
    original_target = fake_home / "dotfiles" / "original.json"
    new_target = fake_home / "dotfiles" / "replacement.json"
    _write_json(original_target, {"mcpServers": {"libtmux-engine": _pinned_entry()}})
    _write_json(new_target, {"sentinel": "leave me alone"})
    original = original_target.read_bytes()
    replacement = new_target.read_bytes()
    info.config_path.parent.mkdir(parents=True)
    info.config_path.symlink_to(original_target)
    parser = mcp_swap.build_parser()

    swap = parser.parse_args(["use-local", "--repo", str(fake_repo), "--cli", "cursor"])
    assert mcp_swap.cmd_use_local(swap) == 0
    info.config_path.unlink()
    if replacement_kind == "symlink":
        info.config_path.symlink_to(new_target)
        replacement_path = new_target
    else:
        info.config_path.write_bytes(replacement)
        replacement_path = info.config_path

    assert mcp_swap.cmd_revert(parser.parse_args(["revert", "--cli", "cursor"])) == 0
    assert original_target.read_bytes() == original
    assert replacement_path.read_bytes() == replacement


# ---------------------------------------------------------------------------
# Fixture invariant
# ---------------------------------------------------------------------------


def test_fake_home_covers_every_registered_cli(
    mcp_swap: t.Any, fake_home: pathlib.Path
) -> None:
    """``fake_home`` replaces ``CLIS`` wholesale, so it must list every CLI.

    Regression guard rather than a behavior test. ``_config_present_clis``
    iterates ``ALL_CLIS`` while indexing ``CLIS``, so a CLI added to the
    registry but not to this fixture raises ``KeyError`` from half a dozen
    unrelated doctor and naming-hint tests. Naming the invariant here turns
    that into one obvious failure.
    """
    assert set(mcp_swap.CLIS) == set(mcp_swap.ALL_CLIS)


# ---------------------------------------------------------------------------
# opencode and pi
#
# These two exercise axes the first six never did. opencode is the first
# JSONC config, the first container key that is not ``mcpServers`` or
# ``mcp_servers``, and the first entry dialect that packs argv into one
# array; pi is the first CLI whose config is read by an extension rather
# than by the agent itself. The comment-fidelity cases are the point of
# the JSONC codec, so they are asserted on bytes, not on parsed values.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["relcfg", "", "  ", "./cfg"])
def test_relative_xdg_config_home_is_ignored(
    mcp_swap: t.Any, raw: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: a relative XDG_CONFIG_HOME resolved against the cwd.

    The spec requires these to be absolute and to be ignored otherwise.
    Honouring a relative one made opencode's config -- and the backup path
    recorded for it -- depend on where the swap was run from, so revert
    from any other directory reported the backup missing for good.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", raw)
    assert mcp_swap._xdg_config_home() == pathlib.Path.home() / ".config"


def test_absolute_xdg_config_home_is_honoured(
    mcp_swap: t.Any, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Opencode resolves XDG the way its own loader does."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert mcp_swap._xdg_config_home() == tmp_path


def test_opencode_and_pi_registered(mcp_swap: t.Any) -> None:
    """Both new CLIs are first-class ``--cli`` choices with their own shapes."""
    assert "opencode" in mcp_swap.ALL_CLIS
    assert "pi" in mcp_swap.ALL_CLIS
    opencode = mcp_swap.CLIS["opencode"]
    assert opencode.fmt == "jsonc"
    assert opencode.config_path.name == "opencode.jsonc"
    assert opencode.container == ("mcp",)
    assert opencode.dialect == "opencode"
    pi = mcp_swap.CLIS["pi"]
    assert pi.fmt == "jsonc"
    assert pi.config_path.name == "mcp.json"
    assert pi.container == ("mcpServers",)
    assert pi.dialect == "standard"
    parser = mcp_swap.build_parser()
    assert parser.parse_args(["status", "--cli", "opencode"]).cli == ["opencode"]
    assert parser.parse_args(["status", "--cli", "pi"]).cli == ["pi"]


@pytest.mark.parametrize("cli", ["opencode", "pi"])
def test_new_cli_set_get_delete_roundtrip(
    mcp_swap: t.Any, cli: str, fake_repo: pathlib.Path
) -> None:
    """Each new CLI's four container branches agree with one another.

    Proves the name was threaded through ``get_server``, ``set_server``,
    ``delete_server`` and ``_all_server_specs`` rather than falling through
    to another CLI's container key.
    """
    config: dict[str, t.Any] = {}
    spec = mcp_swap.McpServerSpec(
        command="uv",
        args=["--directory", str(fake_repo), "run", "libtmux-engine-mcp"],
    )
    server = "libtmux-engine"
    assert mcp_swap.set_server(cli, config, server, spec, fake_repo) == "added"
    assert mcp_swap.CLIS[cli].container[0] in config
    got = mcp_swap.get_server(cli, config, server, fake_repo)
    assert got is not None
    assert got.is_local_uv_directory()
    assert got.local_repo_path() == fake_repo
    assert mcp_swap.set_server(cli, config, server, spec, fake_repo) == "replaced"
    assert mcp_swap._all_server_specs(cli, config, fake_repo).keys() == {server}
    assert mcp_swap.delete_server(cli, config, server, fake_repo)
    assert mcp_swap.get_server(cli, config, server, fake_repo) is None


def test_opencode_entry_packs_argv_into_one_command_array(mcp_swap: t.Any) -> None:
    """The opencode dialect uses one argv array and the key ``environment``.

    A scalar ``command`` is a decode error that stops opencode starting at
    all, and an ``env`` key is dropped without a warning, so both spellings
    are pinned here rather than left to the round-trip tests.
    """
    spec = mcp_swap.McpServerSpec(
        command="uv", args=["--directory", "/repo", "run"], env={"A": "b"}
    )
    entry = spec.to_entry_dict("opencode")
    assert entry["type"] == "local"
    assert entry["command"] == ["uv", "--directory", "/repo", "run"]
    assert entry["environment"] == {"A": "b"}
    assert "args" not in entry
    assert "env" not in entry


def test_opencode_array_entry_reads_back_as_command_plus_args(mcp_swap: t.Any) -> None:
    """An array ``command`` normalizes to the portable scalar-plus-args spec.

    Regression: without the split, ``command`` becomes the ``str()`` of a
    Python list, ``is_local_uv_directory`` is False for a correct entry, and
    the "already local — no change" short-circuit never fires, so every run
    rewrites a config that needed no change.
    """
    info = mcp_swap.CLIS["opencode"]
    spec = mcp_swap._spec_from_entry(
        {
            "type": "local",
            "command": ["uv", "--directory", "/repo", "run", "libtmux-engine-mcp"],
            "environment": {"A": "b"},
        },
        info=info,
    )
    assert spec.command == "uv"
    assert spec.args == ["--directory", "/repo", "run", "libtmux-engine-mcp"]
    assert spec.env == {"A": "b"}
    assert spec.is_local_uv_directory()
    assert spec.local_repo_path() == pathlib.Path("/repo")


def test_opencode_array_entry_round_trips_a_pr_spec(mcp_swap: t.Any) -> None:
    """``pr_ref`` still recognises a pull-request spec in the array shape."""
    info = mcp_swap.CLIS["opencode"]
    spec = mcp_swap.build_pr_spec(
        "https://github.com/tmux-python/libtmux", 115, "libtmux-engine-mcp"
    )
    decoded = mcp_swap._spec_from_entry(spec.to_entry_dict("opencode"), info=info)
    assert decoded.pr_ref() == ("https://github.com/tmux-python/libtmux", 115)


def _opencode_config(mcp_swap: t.Any, body: str) -> t.Any:
    """Write ``body`` to the fake opencode config and return its ``CLIInfo``."""
    info = mcp_swap.CLIS["opencode"]
    info.config_path.parent.mkdir(parents=True, exist_ok=True)
    info.config_path.write_text(body)
    return info


def _swap_opencode(mcp_swap: t.Any, fake_repo: pathlib.Path) -> int:
    """Run ``use-local`` against opencode only."""
    args = mcp_swap.build_parser().parse_args(
        ["use-local", "--repo", str(fake_repo), "--cli", "opencode"]
    )
    return int(mcp_swap.cmd_use_local(args))


def test_opencode_swap_preserves_jsonc_comments(
    mcp_swap: t.Any, fake_home: pathlib.Path, fake_repo: pathlib.Path
) -> None:
    """Line comments, block comments and sibling servers survive a swap."""
    info = _opencode_config(
        mcp_swap,
        "{\n"
        "  // header comment\n"
        '  "$schema": "https://opencode.ai/config.json",\n'
        "  /* a block comment\n"
        "     spanning lines */\n"
        '  "model": "openrouter/x",\n'
        '  "mcp": {\n'
        '    "other": { "type": "local", "command": ["echo", "keep"] }\n'
        "  }\n"
        "}\n",
    )
    assert _swap_opencode(mcp_swap, fake_repo) == 0
    text = info.config_path.read_text()
    assert "// header comment" in text
    assert "/* a block comment" in text
    assert "spanning lines */" in text
    doc = mcp_swap._jsonc_loads(text)
    assert doc["model"] == "openrouter/x"
    assert doc["mcp"]["other"]["command"] == ["echo", "keep"]
    assert doc["mcp"]["libtmux-engine"]["command"][0] == "uv"


def test_opencode_comment_inside_the_replaced_entry_survives(
    mcp_swap: t.Any, fake_home: pathlib.Path, fake_repo: pathlib.Path
) -> None:
    """A comment attached to the entry being rewritten is not collateral.

    The case a whole-entry rewrite loses and a field-level splice keeps.
    Real opencode configs carry the rationale for a pinned ``command``
    directly above it, which is exactly the text a swap would destroy.
    """
    info = _opencode_config(
        mcp_swap,
        "{\n"
        '  "mcp": {\n'
        '    "libtmux-engine": {\n'
        '      "type": "local",\n'
        "      // Pinned deliberately; this rationale must outlive the swap.\n"
        '      "command": ["uvx", "libtmux==0.63.0"],\n'
        '      "environment": { "KEEP": "me" }\n'
        "    }\n"
        "  }\n"
        "}\n",
    )
    assert _swap_opencode(mcp_swap, fake_repo) == 0
    text = info.config_path.read_text()
    assert "// Pinned deliberately; this rationale must outlive the swap." in text
    entry = mcp_swap._jsonc_loads(text)["mcp"]["libtmux-engine"]
    assert entry["command"][0] == "uv"
    assert entry["environment"] == {"KEEP": "me"}


def test_opencode_swap_and_revert_round_trip_is_byte_identical(
    mcp_swap: t.Any, fake_home: pathlib.Path, fake_repo: pathlib.Path
) -> None:
    """Revert restores a commented JSONC config byte for byte."""
    body = (
        "{\n"
        "  // keep me\n"
        '  "model": "m",\n'
        '  "mcp": {\n'
        '    "libtmux-engine": {\n'
        '      "type": "local",\n'
        '      "command": ["uvx", "libtmux==0.63.0"]\n'
        "    }\n"
        "  }\n"
        "}\n"
    )
    info = _opencode_config(mcp_swap, body)
    original = info.config_path.read_bytes()
    assert _swap_opencode(mcp_swap, fake_repo) == 0
    assert info.config_path.read_bytes() != original
    revert = mcp_swap.build_parser().parse_args(["revert", "--cli", "opencode"])
    assert mcp_swap.cmd_revert(revert) == 0
    assert info.config_path.read_bytes() == original


def test_opencode_second_swap_reports_no_change(
    mcp_swap: t.Any, fake_home: pathlib.Path, fake_repo: pathlib.Path
) -> None:
    """The idempotence check fires for the array command shape.

    Depends on ``_spec_from_entry`` splitting the array; without it the
    config is rewritten on every invocation.
    """
    info = _opencode_config(mcp_swap, '{\n  "mcp": {}\n}\n')
    assert _swap_opencode(mcp_swap, fake_repo) == 0
    after_first = info.config_path.read_bytes()
    assert _swap_opencode(mcp_swap, fake_repo) == 0
    assert info.config_path.read_bytes() == after_first


def test_opencode_seeds_schema_into_an_empty_config(
    mcp_swap: t.Any, fake_home: pathlib.Path, fake_repo: pathlib.Path
) -> None:
    """Seeding an empty file writes ``$schema`` alongside the server entry."""
    info = _opencode_config(mcp_swap, "")
    assert _swap_opencode(mcp_swap, fake_repo) == 0
    doc = mcp_swap._jsonc_loads(info.config_path.read_text())
    assert doc["$schema"] == mcp_swap.OPENCODE_SCHEMA_URL
    assert doc["mcp"]["libtmux-engine"]["type"] == "local"


def test_opencode_symlinked_config_swap_updates_target_not_link(
    mcp_swap: t.Any, fake_home: pathlib.Path, fake_repo: pathlib.Path
) -> None:
    """A JSONC config symlinked into a dotfiles tree keeps its link."""
    info = mcp_swap.CLIS["opencode"]
    target = fake_home / "dotfiles" / "opencode.jsonc"
    target.parent.mkdir(parents=True)
    target.write_text('{\n  // linked\n  "mcp": {}\n}\n')
    info.config_path.parent.mkdir(parents=True)
    info.config_path.symlink_to(target)

    assert _swap_opencode(mcp_swap, fake_repo) == 0
    assert info.config_path.is_symlink()
    assert info.config_path.readlink() == target
    text = target.read_text()
    assert "// linked" in text
    assert mcp_swap._jsonc_loads(text)["mcp"]["libtmux-engine"]["command"][0] == "uv"


def test_pi_config_with_comments_is_readable(
    mcp_swap: t.Any, fake_home: pathlib.Path, fake_repo: pathlib.Path
) -> None:
    """Regression: pi's adapter accepts JSONC, so strict JSON rejected it.

    ``pi-mcp-adapter`` reads the file through ``strip-json-comments`` with
    trailing commas allowed. Parsing it as strict JSON made ``status`` and
    ``use-local`` report a config the adapter reads fine as unreadable.
    """
    info = mcp_swap.CLIS["pi"]
    info.config_path.parent.mkdir(parents=True)
    info.config_path.write_text(
        '{\n  // the adapter allows comments\n  "mcpServers": {\n'
        '    "keep": { "command": "echo", "args": ["hi"] },\n  }\n}\n'
    )
    args = mcp_swap.build_parser().parse_args(
        ["use-local", "--repo", str(fake_repo), "--cli", "pi"]
    )
    assert mcp_swap.cmd_use_local(args) == 0
    text = info.config_path.read_text()
    assert "// the adapter allows comments" in text
    servers = mcp_swap._jsonc_loads(text)["mcpServers"]
    assert servers["keep"]["command"] == "echo"
    assert servers["libtmux-engine"]["command"] == "uv"


def test_detect_reports_the_pi_adapter_prerequisite(
    mcp_swap: t.Any,
    fake_home: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``detect`` says why a pi swap will not take effect on its own.

    pi ships no MCP client, so the file this script writes is read only by
    the ``pi-mcp-adapter`` extension. Reporting pi as swappable without
    that caveat would be the one thing this script must never do: claim an
    agent will run something it will not.
    """
    monkeypatch.setattr(mcp_swap, "PI_ADAPTER_DIR", fake_home / "absent")
    monkeypatch.setattr(mcp_swap.shutil, "which", lambda _binary: "/usr/bin/stub")
    info = mcp_swap.CLIS["pi"]
    info.config_path.parent.mkdir(parents=True)
    info.config_path.write_text('{"mcpServers": {}}\n')

    assert mcp_swap.cmd_detect(mcp_swap.build_parser().parse_args(["detect"])) == 0
    out = capsys.readouterr().out
    assert mcp_swap.PI_ADAPTER_HINT in out

    monkeypatch.setattr(mcp_swap, "PI_ADAPTER_DIR", fake_home)
    assert mcp_swap.cmd_detect(mcp_swap.build_parser().parse_args(["detect"])) == 0
    assert mcp_swap.PI_ADAPTER_HINT not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# JSONC writer fidelity
#
# The JSON writer reserializes the whole document, so it can only promise
# to preserve values. The JSONC writer splices text and therefore promises
# bytes: anything it did not deliberately change must come back identical,
# including the comments, the trailing comma, the indent width and the
# absence of a final newline. The string cases exist because a
# comment-stripper that is not string-aware corrupts a URL or a Windows
# path silently, which is the worst failure this codec could have.
# ---------------------------------------------------------------------------


PRESERVED_JSONC: list[JSONFidelityCase] = [
    JSONFidelityCase("line_comment", '{\n  // note\n  "mcp": {}\n}\n'),
    JSONFidelityCase("block_comment", '{\n  /* note\n     more */\n  "mcp": {}\n}\n'),
    JSONFidelityCase("comment_after_last_member", '{\n  "mcp": {}\n  // tail\n}\n'),
    JSONFidelityCase("trailing_comma", '{\n  "mcp": {},\n}\n'),
    JSONFidelityCase("no_trailing_newline", '{\n  "mcp": {}\n}'),
    JSONFidelityCase("four_space_indent", '{\n    "mcp": {}\n}\n'),
    JSONFidelityCase("url_containing_double_slash", '{\n  "a": "https://x/y//z"\n}\n'),
    JSONFidelityCase("block_marker_inside_string", '{\n  "a": "/* not one */"\n}\n'),
    JSONFidelityCase("windows_path", '{\n  "a": "C:\\\\tmp\\\\x"\n}\n'),
    JSONFidelityCase("literal_backslash_u", '{\n  "a": "C:\\\\u0041"\n}\n'),
    JSONFidelityCase("emoji_and_cjk", '{\n  "a": "🙂 日本語 café"\n}\n'),
    JSONFidelityCase("empty_object", "{}\n"),
    JSONFidelityCase("comment_only_object", '{\n  "mcp": {\n    // none yet\n  }\n}\n'),
    JSONFidelityCase(
        "comment_before_the_delimiter", '{\n  "a": 1 /* x */,\n  "b": 2\n}\n'
    ),
]


def _jsonc_config(
    mcp_swap: t.Any, tmp_path: pathlib.Path, body: str
) -> tuple[t.Any, bytes]:
    """Write ``body`` verbatim and return its ``CLIInfo`` and exact bytes."""
    path = tmp_path / "opencode.jsonc"
    path.write_text(body)
    info = mcp_swap.CLIInfo(
        name="opencode",
        binary="opencode",
        config_path=path,
        fmt="jsonc",
        container=("mcp",),
        dialect="opencode",
    )
    return info, path.read_bytes()


@pytest.mark.parametrize(
    JSONFidelityCase._fields,
    PRESERVED_JSONC,
    ids=[c.test_id for c in PRESERVED_JSONC],
)
def test_untouched_jsonc_config_round_trips_byte_identical(
    mcp_swap: t.Any, test_id: str, body: str, tmp_path: pathlib.Path
) -> None:
    """Loading and rewriting an unmodified JSONC config changes no byte."""
    assert test_id
    info, raw = _jsonc_config(mcp_swap, tmp_path, body)
    config = mcp_swap.load_config(info)
    assert mcp_swap.dump_config_bytes(info, config, original=raw) == raw


@pytest.mark.parametrize(
    JSONFidelityCase._fields,
    PRESERVED_JSONC,
    ids=[c.test_id for c in PRESERVED_JSONC],
)
def test_jsonc_values_match_stdlib_json(
    mcp_swap: t.Any, test_id: str, body: str, tmp_path: pathlib.Path
) -> None:
    r"""JSONC parsing agrees with stdlib json wherever stdlib can parse.

    Escape handling is the standard library's, not a reimplementation's.
    The rejected ``json-five`` dependency failed exactly here: it raised on
    ``"C:\\x"`` and decoded a literal ``\\u0041`` to ``"A"``.
    """
    assert test_id
    try:
        expected = json.loads(body)
    except json.JSONDecodeError:
        pytest.skip("comment or trailing comma — stdlib cannot parse it")
    assert mcp_swap._jsonc_loads(body) == expected


def test_jsonc_config_is_not_written_through_the_toml_writer(
    mcp_swap: t.Any, tmp_path: pathlib.Path
) -> None:
    """A jsonc config comes back as JSON text, not TOML.

    Regression: ``dump_config_bytes`` branched on ``fmt != "json"``, so any
    third format reached ``tomlkit.dumps`` and put TOML bytes in a JSON
    file. The dispatch is on the exact format now.
    """
    info, raw = _jsonc_config(mcp_swap, tmp_path, '{\n  "mcp": {}\n}\n')
    out = mcp_swap.dump_config_bytes(
        info, {"mcp": {"x": {"type": "local"}}}, original=raw
    )
    text = out.decode()
    assert text.lstrip().startswith("{")
    assert mcp_swap._jsonc_loads(text)["mcp"]["x"]["type"] == "local"


class JsoncDeletionCase(t.NamedTuple):
    """A member removal whose exact resulting text is pinned.

    Attributes
    ----------
    test_id : str
        Identifier shown in the parametrized test name.
    body : str
        The config text before the merge.
    data : dict[str, t.Any]
        The reconciled data the merge is driven with.
    expected : str
        The exact text the merge must produce.
    """

    test_id: str
    body: str
    data: dict[str, t.Any]
    expected: str


JSONC_DELETIONS: list[JsoncDeletionCase] = [
    JsoncDeletionCase(
        "first_member",
        '{\n  "a": 1,\n  "b": 2\n}\n',
        {"b": 2},
        '{\n  "b": 2\n}\n',
    ),
    JsoncDeletionCase(
        "middle_member",
        '{\n  "a": 1,\n  "b": 2,\n  "c": 3\n}\n',
        {"a": 1, "c": 3},
        '{\n  "a": 1,\n  "c": 3\n}\n',
    ),
    JsoncDeletionCase(
        "last_member",
        '{\n  "a": 1,\n  "b": 2\n}\n',
        {"a": 1},
        '{\n  "a": 1\n}\n',
    ),
    JsoncDeletionCase(
        "comma_hidden_behind_a_comment",
        '{\n  "a": 1 /* x, y */,\n  "b": 2\n}\n',
        {"b": 2},
        '{\n  "b": 2\n}\n',
    ),
]


@pytest.mark.parametrize(
    JsoncDeletionCase._fields,
    JSONC_DELETIONS,
    ids=[c.test_id for c in JSONC_DELETIONS],
)
def test_jsonc_merge_removing_a_member_takes_exactly_one_comma(
    mcp_swap: t.Any,
    test_id: str,
    body: str,
    data: dict[str, t.Any],
    expected: str,
) -> None:
    """Regression: a removal took the comma on both sides of the member.

    Deleting a member between two others left its neighbours undelimited,
    so the next merge pass raised ``JSONDecodeError`` and the swap reported
    the config unreadable. ``comma_hidden_behind_a_comment`` covers the
    partner defect: the delimiter scan read the raw text, where a comma
    inside a comment passes for the separator.
    """
    assert test_id
    assert mcp_swap._jsonc_merge(body, data, ensure_ascii=False) == expected


@pytest.mark.parametrize(
    "name", ["back\\slash", 'quo"te', "new\nline", "tab\tbed", "unicode\u00e9"]
)
def test_jsonc_merge_escapes_an_inserted_key(mcp_swap: t.Any, name: str) -> None:
    """Regression: an inserted key was written raw, so a swap could not converge.

    ``--server`` takes an arbitrary string. Written unescaped, a backslash or
    quote in it emitted text that would not parse back, so the member was
    never found again and the merge re-inserted it until the pass ceiling --
    spinning while holding the swap lock and then failing.
    """
    src = '{\n  "mcp": {}\n}\n'
    data = mcp_swap._jsonc_loads(src)
    data["mcp"][name] = {"type": "local"}
    out = mcp_swap._jsonc_merge(src, data, ensure_ascii=False)
    assert mcp_swap._jsonc_loads(out)["mcp"][name] == {"type": "local"}


def test_jsonc_merge_removing_a_middle_member_stays_parseable(
    mcp_swap: t.Any,
) -> None:
    """The shape that surfaced it: an opencode entry losing optional fields."""
    src = (
        '{\n  "mcp": {\n    "tmux": {\n      "type": "local",\n'
        '      "enabled": true,\n      "timeout": 5000,\n'
        '      "command": ["uvx", "old"]\n    }\n  }\n}\n'
    )
    data = mcp_swap._jsonc_loads(src)
    data["mcp"]["tmux"] = {"type": "local", "command": ["uv", "run", "x"]}
    out = mcp_swap._jsonc_merge(src, data, ensure_ascii=False)
    assert mcp_swap._jsonc_loads(out) == data


def test_jsonc_merge_inserting_into_a_comment_only_object_keeps_the_comment(
    mcp_swap: t.Any,
) -> None:
    """Regression: blanking made a documented object look empty.

    The emptiness guard reads the comment-blanked text, where a comment is
    indistinguishable from whitespace, so insertion used to splice over the
    whole interior and take the comment with it.
    """
    src = '{\n  "mcp": {\n    // why there are no servers yet\n  }\n}\n'
    data = mcp_swap._jsonc_loads(src)
    data["mcp"]["tmux"] = {"type": "local", "command": ["uv"]}
    out = mcp_swap._jsonc_merge(src, data, ensure_ascii=False)
    assert out == (
        '{\n  "mcp": {\n    // why there are no servers yet\n'
        '    "tmux": {\n      "type": "local",\n      "command": [\n'
        '        "uv"\n      ]\n    }\n  }\n}\n'
    )


def test_jsonc_merge_inserting_into_a_comment_only_document_keeps_the_comment(
    mcp_swap: t.Any,
) -> None:
    """The same splice at the root, where there is no enclosing member."""
    src = "{\n  // root rationale\n}\n"
    data = mcp_swap._jsonc_loads(src)
    data["mcp"] = {}
    out = mcp_swap._jsonc_merge(src, data, ensure_ascii=False)
    assert out == '{\n  // root rationale\n  "mcp": {}\n}\n'


@pytest.mark.parametrize(
    "body",
    ["{}\n", "{ }\n", '{\n  "mcp": {}\n}\n', '{\n  "mcp": {\n  }\n}\n'],
)
def test_jsonc_merge_inserting_into_an_empty_object_is_unchanged(
    mcp_swap: t.Any, body: str
) -> None:
    """A genuinely empty interior still collapses to the old splice point."""
    data = mcp_swap._jsonc_loads(body)
    data.setdefault("mcp", {})["tmux"] = {"type": "local"}
    out = mcp_swap._jsonc_merge(body, data, ensure_ascii=False)
    assert mcp_swap._jsonc_loads(out)["mcp"]["tmux"] == {"type": "local"}
    assert out.rstrip().endswith("}")


def test_jsonc_comment_blanking_preserves_offsets(mcp_swap: t.Any) -> None:
    """Blanking a comment must not move the bytes around it.

    Offsets are what let a span found in the blanked text address the same
    bytes in the original; if blanking changed the length, every splice
    would land in the wrong place.
    """
    src = '{\n  // note\n  "a": 1, /* x */\n  "b": "//not a comment"\n}\n'
    blanked = mcp_swap._jsonc_blank_comments(src)
    assert len(blanked) == len(src)
    assert "//not a comment" in blanked
    assert "note" not in blanked
    assert blanked.count("\n") == src.count("\n")
