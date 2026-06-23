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
