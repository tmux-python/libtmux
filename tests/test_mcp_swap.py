"""The ported ``scripts/mcp_swap.py`` dev tool resolves this repo's identity.

``mcp_swap`` swaps MCP server configs across agent CLIs to point at a local
checkout. The only port-specific change is the slug derivation: this repo's
package is ``libtmux`` but its MCP console script is ``libtmux-engine-mcp``, so
the slug must come from the *entry* (yielding ``libtmux-engine``) to stay
distinct from a sibling ``libtmux`` server. These tests lock that in, plus the
packaging wiring that makes the server runnable.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import pathlib
import sys
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
    info = mcp_swap.CLIInfo(name="agy", binary="agy", config_path=cfg, fmt="json")
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
            ),
            "codex": mcp_swap.CLIInfo(
                name="codex",
                binary="codex",
                config_path=tmp_path / ".codex" / "config.toml",
                fmt="toml",
            ),
            "cursor": mcp_swap.CLIInfo(
                name="cursor",
                binary="cursor-agent",
                config_path=tmp_path / ".cursor" / "mcp.json",
                fmt="json",
            ),
            "gemini": mcp_swap.CLIInfo(
                name="gemini",
                binary="gemini",
                config_path=tmp_path / ".gemini" / "settings.json",
                fmt="json",
            ),
            "grok": mcp_swap.CLIInfo(
                name="grok",
                binary="grok",
                config_path=tmp_path / ".grok" / "config.toml",
                fmt="toml",
            ),
            "agy": mcp_swap.CLIInfo(
                name="agy",
                binary="agy",
                config_path=tmp_path / ".gemini" / "config" / "mcp_config.json",
                fmt="json",
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
