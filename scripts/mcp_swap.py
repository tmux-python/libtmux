#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["tomlkit>=0.13"]
# ///
"""Swap MCP server configs across Claude / Codex / Cursor / Gemini / Grok / agy.

Use when you want every installed agent CLI to run a local checkout of an
MCP server (editable) instead of a pinned release. ``use-local`` rewrites
each CLI's config to invoke the checkout via ``uv --directory <repo> run
<entry>``; ``revert`` restores from the timestamped backup the swap wrote.

Defaults are derived from the current repo's ``pyproject.toml``:

- entry command = first key of ``[project.scripts]``
- server name = that entry with a trailing ``-mcp`` stripped
  (``libtmux-engine-mcp`` -> ``libtmux-engine``), falling back to
  ``project.name`` when the entry has no ``-mcp`` suffix. Deriving the
  slug from the entry (not ``project.name``) keeps this repo's server
  key distinct from a sibling package whose ``project.name`` differs
  from its console-script name.

Examples
--------
```console
$ uv run scripts/mcp_swap.py detect
$ uv run scripts/mcp_swap.py status
$ uv run scripts/mcp_swap.py use-local --dry-run
$ uv run scripts/mcp_swap.py use-local
$ uv run scripts/mcp_swap.py revert
```

Scope
-----
This script is best-effort and intentionally narrow:

- **Global configs only.** Writes to ``~/.cursor/mcp.json``,
  ``~/.claude.json``, ``~/.codex/config.toml``,
  ``~/.gemini/settings.json``, ``~/.grok/config.toml`` (TOML
  ``mcp_servers``, same shape as Codex), and
  ``~/.gemini/config/mcp_config.json`` (agy / Antigravity CLI, JSON
  ``mcpServers`` — the shared-config file the CLI reads, sibling to the
  ``config.json`` it loads at startup). Workspace / project-local configs
  (``$PWD/.cursor/mcp.json``, ``$PWD/.gemini/settings.json``,
  per-project ``projects.<abs>.mcpServers`` entries inside
  ``~/.claude.json`` *are* recognised for Claude only) are NOT
  walked — workspace files for Cursor/Gemini are silently ignored.
  When workspace precedence matters, run the CLI's own
  ``cursor mcp add ...`` / ``gemini mcp add ...`` directly.

- **Claude scope.** ``use-local`` and ``revert`` accept
  ``--scope {user,project}``. The default ``project`` writes the
  per-project entry under ``projects[<abs-repo>].mcpServers`` —
  only the current repo's directory sees the swap, matching
  pre-flag behaviour. ``--scope user`` writes Claude's top-level
  ``mcpServers`` fallback so every project that has no per-project
  override picks up the swap; useful when QA-ing a branch across
  many directories. Codex, Cursor, Gemini, Grok, and agy have no per-project
  layer in their config files; the flag is silently coerced to
  ``user`` for them. Both Claude scopes can coexist with
  independent backups; full ``revert`` unwinds in LIFO order.
- **Simple binary detection.** Probing is ``shutil.which(<binary>)``
  plus ``<config_path>.exists()``. Custom install locations
  (Homebrew, npm prefixes, ``~/.npm-global/bin``,
  ``~/.claude/local/claude``, ``~/.gemini/local/gemini``) are picked
  up only if the binary is on ``PATH``. FastMCP's installer probes
  these locations directly; this script does not.
- **Single config shape per CLI.** No fallback paths, no merge of
  multiple sources. If your setup deviates from the defaults above,
  use the CLI's native ``mcp`` subcommand instead.
"""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
import typing as t

import tomlkit
import tomlkit.items

CLIName = t.Literal["claude", "codex", "cursor", "gemini", "grok", "agy"]
ALL_CLIS: tuple[CLIName, ...] = ("claude", "codex", "cursor", "gemini", "grok", "agy")

#: Claude config scope: ``"user"`` targets the user/system-level top-level
#: ``mcpServers`` fallback that applies to every project without its own
#: override; ``"project"`` targets the project-level per-project
#: ``projects.<abs>.mcpServers`` node. Non-Claude CLIs have no
#: per-project scope in their config files, so for those CLIs the scope
#: is always normalised to ``"user"`` regardless of what was passed.
Scope = t.Literal["user", "project"]
ALL_SCOPES: tuple[Scope, ...] = ("user", "project")


def _normalize_scope(cli: CLIName, scope: Scope | None) -> Scope:
    """Coerce ``scope`` to the value that actually applies to ``cli``.

    Non-Claude CLIs have no per-project config layer — every write to
    them is necessarily user-level — so the flag is silently coerced to
    ``"user"`` for those. For Claude, ``None`` defaults to ``"project"``
    to preserve pre-flag behaviour where the script always wrote the
    per-project entry.
    """
    if cli != "claude":
        return "user"
    return scope if scope is not None else "project"


def _state_key(cli: CLIName, scope: Scope) -> str:
    """Compose the ``cli:scope`` key used inside the state file."""
    return f"{cli}:{scope}"


def _parse_state_key(key: str) -> tuple[CLIName, Scope] | None:
    """Decode a ``cli:scope`` state key, returning ``None`` for malformed input.

    The script declares no compatibility contract for its state file —
    schema is internal — so this only accepts the canonical
    ``f"{cli}:{scope}"`` form. Hand-edited or unrecognised keys return
    ``None`` so ``load_state`` can drop them without crashing.
    """
    if ":" not in key:
        return None
    cli_str, _, scope_str = key.partition(":")
    if cli_str in ALL_CLIS and scope_str in ALL_SCOPES:
        return cli_str, scope_str
    return None


def _parse_state_entry(v: dict[str, t.Any]) -> SwapEntry | None:
    """Build a :class:`SwapEntry` from a raw state-file dict, or ``None``.

    Validates at the trust boundary so a hand-edited ``state.json`` can't
    crash later code paths — particularly :func:`cmd_revert`'s LIFO sort,
    which compares ``SwapEntry.seq_no`` and would raise ``TypeError`` on a
    mixed ``int``/``str`` ordering. ``seq_no`` is coerced via ``int()``;
    any ``KeyError`` (missing required field), ``ValueError`` (non-numeric
    string), or ``TypeError`` (wrong shape, extra keys for the dataclass)
    drops the entry silently. Same drop-on-malformed posture as
    :func:`_parse_state_key`.

    Mirrors CPython's ``Lib/sched.py`` discipline: validate at the
    counter's *origin* (``enterabs`` for sched, ``load_state`` here), not
    at sort time. State-file schema is internal — no compatibility
    contract — so silent drop is the right failure mode.
    """
    try:
        v = {**v, "seq_no": int(v["seq_no"])}
        return SwapEntry(**v)
    except (KeyError, TypeError, ValueError):
        return None


def _xdg_state_home() -> pathlib.Path:
    """Resolve ``$XDG_STATE_HOME`` per the XDG Base Directory spec.

    Defaults to ``~/.local/state`` when the env var is unset or empty.
    State is the right XDG bucket here (vs. cache / config / data): the
    file is machine-written, must persist across runs so ``revert`` can
    locate the right backup, but is not safely deletable like cache nor
    user-edited like config.
    """
    env = os.environ.get("XDG_STATE_HOME")
    if env:
        return pathlib.Path(env)
    return pathlib.Path.home() / ".local" / "state"


# ``-dev`` suffix in the namespace makes it loud that this is dev-only
# tooling state, distinct from the runtime ``libtmux`` package and from
# any sibling ``libtmux-mcp-dev`` swap state.
STATE_DIR = _xdg_state_home() / "libtmux-engine-mcp-dev" / "swap"
STATE_FILE = STATE_DIR / "state.json"

BACKUP_SUFFIX_PREFIX = ".bak.mcp-swap-"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class CLIInfo:
    """Static descriptor for a CLI's config file and discovery heuristics."""

    name: CLIName
    binary: str
    config_path: pathlib.Path
    fmt: t.Literal["json", "toml"]


CLIS: dict[CLIName, CLIInfo] = {
    "claude": CLIInfo(
        name="claude",
        binary="claude",
        config_path=pathlib.Path.home() / ".claude.json",
        fmt="json",
    ),
    "codex": CLIInfo(
        name="codex",
        binary="codex",
        config_path=pathlib.Path.home() / ".codex" / "config.toml",
        fmt="toml",
    ),
    "cursor": CLIInfo(
        name="cursor",
        binary="cursor-agent",
        config_path=pathlib.Path.home() / ".cursor" / "mcp.json",
        fmt="json",
    ),
    "gemini": CLIInfo(
        name="gemini",
        binary="gemini",
        config_path=pathlib.Path.home() / ".gemini" / "settings.json",
        fmt="json",
    ),
    "grok": CLIInfo(
        name="grok",
        binary="grok",
        config_path=pathlib.Path.home() / ".grok" / "config.toml",
        fmt="toml",
    ),
    # Antigravity (the ``agy`` CLI). Its MCP config is the standard JSON
    # ``mcpServers`` shape (same as Cursor / Gemini). The CLI reads
    # ``~/.gemini/config/mcp_config.json`` — its shared-config dir,
    # sibling to the ``config.json`` it loads at startup. The file may
    # start empty until a server is added; ``load_config`` tolerates a
    # 0-byte JSON file as ``{}``.
    "agy": CLIInfo(
        name="agy",
        binary="agy",
        config_path=(pathlib.Path.home() / ".gemini" / "config" / "mcp_config.json"),
        fmt="json",
    ),
}


@dataclasses.dataclass
class McpServerSpec:
    """The portable shape shared across CLI configs."""

    command: str
    args: list[str] = dataclasses.field(default_factory=list)
    env: dict[str, str] = dataclasses.field(default_factory=dict)

    def to_json_dict(self, *, include_stdio_type: bool = False) -> dict[str, t.Any]:
        """Serialize to the JSON shape (Claude-extended when ``include_stdio_type``)."""
        # Claude's format always includes ``type`` and ``env`` (even when empty);
        # Cursor/Gemini omit both. include_stdio_type selects Claude shape.
        if include_stdio_type:
            return {
                "type": "stdio",
                "command": self.command,
                "args": list(self.args),
                "env": dict(self.env),
            }
        out: dict[str, t.Any] = {"command": self.command, "args": list(self.args)}
        if self.env:
            out["env"] = dict(self.env)
        return out

    def is_local_uv_directory(self) -> bool:
        """Return True for a ``uv --directory <repo> run <entry>`` shape."""
        return (
            self.command == "uv" and "--directory" in self.args and "run" in self.args
        )

    def local_repo_path(self) -> pathlib.Path | None:
        """Extract the ``--directory`` argument, if any."""
        try:
            i = self.args.index("--directory")
        except ValueError:
            return None
        if i + 1 >= len(self.args):
            return None
        return pathlib.Path(self.args[i + 1])


@dataclasses.dataclass
class SwapEntry:
    """One CLI's bookkeeping for a swap, written to the state file."""

    config_path: str
    backup_path: str
    server: str
    action: t.Literal["replaced", "added"]
    #: ``YYYYMMDDHHMMSS`` registration timestamp, human-readable for
    #: anyone inspecting ``state.json`` directly. Sort order is enforced
    #: separately via :attr:`seq_no` so this field stays purely
    #: descriptive.
    swapped_at: str
    #: Monotonic registration counter — the primary LIFO sort key for
    #: ``cmd_revert``. ``cmd_use_local`` computes the next value as
    #: ``max(existing seq_nos, default=-1) + 1`` so it strictly
    #: increases per swap regardless of wall-clock collisions or dict
    #: iteration order. Same explicit-counter pattern CPython's
    #: ``Lib/sched.py`` uses to break ties on ``Event(time, priority,
    #: sequence, …)``.
    seq_no: int


# ---------------------------------------------------------------------------
# Config IO — per format
# ---------------------------------------------------------------------------


def load_config(info: CLIInfo) -> t.Any:
    """Parse a CLI's config file (JSON or TOML) into an editable structure.

    Empty JSON files are treated as empty objects so first-run MCP configs can
    be seeded with their initial server entry.
    """
    raw = info.config_path.read_bytes()
    if info.fmt == "json":
        text = raw.decode().strip()
        return json.loads(text) if text else {}
    return tomlkit.parse(raw.decode())


def dump_config_bytes(info: CLIInfo, config: t.Any) -> bytes:
    """Serialize an edited config back to bytes in its original format."""
    if info.fmt == "json":
        return (json.dumps(config, indent=2) + "\n").encode()
    return tomlkit.dumps(config).encode()


def atomic_write(path: pathlib.Path, data: bytes) -> None:
    """Write bytes to ``path`` via tempfile + ``os.replace`` to avoid partial writes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    tmp = pathlib.Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# Per-CLI get / set / delete (the only CLI-specific logic)
# ---------------------------------------------------------------------------


@t.overload
def _claude_project_node(
    config: dict[str, t.Any],
    repo: pathlib.Path,
    *,
    create: t.Literal[True],
) -> dict[str, t.Any]: ...


@t.overload
def _claude_project_node(
    config: dict[str, t.Any],
    repo: pathlib.Path,
    *,
    create: t.Literal[False],
) -> dict[str, t.Any] | None: ...


def _claude_project_node(
    config: dict[str, t.Any], repo: pathlib.Path, *, create: bool
) -> dict[str, t.Any] | None:
    """Return (or create) the ``projects.<abs-repo>`` node Claude keys per-project.

    With ``create=True``, the node is unconditionally created if missing
    and the return type is statically narrowed to ``dict[str, t.Any]``;
    callers can drop runtime ``assert node is not None`` defensiveness.
    With ``create=False``, the absence of the node is a real return value
    and the type stays ``dict[str, t.Any] | None``.

    Raises ``RuntimeError`` if Claude's config layout is not the
    expected ``projects.<abs>.mcpServers`` mapping shape — the layout
    is undocumented Claude Code internal state, so a clear error before
    the atomic write beats a silent partial mutation that the backup
    defense would be asked to recover from.
    """
    key = str(repo.resolve())
    projects_node = config.get("projects")
    if projects_node is not None and not isinstance(projects_node, dict):
        msg = (
            "Claude config layout appears to have changed; expected "
            f"'projects' to be a mapping but got "
            f"{type(projects_node).__name__}"
        )
        raise RuntimeError(msg)
    projects = (
        config.setdefault("projects", {}) if create else config.get("projects", {})
    )
    raw_node = projects.get(key)
    node: dict[str, t.Any] | None = None
    if isinstance(raw_node, dict):
        node = raw_node
    elif raw_node is not None:
        msg = (
            "Claude config layout appears to have changed; expected "
            f"'projects[{key!r}]' to be a mapping but got "
            f"{type(raw_node).__name__}"
        )
        raise RuntimeError(msg)
    if node is None and create:
        node = {"allowedTools": [], "mcpContextUris": [], "mcpServers": {}, "env": {}}
        projects[key] = node
    return node


@t.overload
def _claude_user_servers(
    config: dict[str, t.Any], *, create: t.Literal[True]
) -> dict[str, t.Any]: ...


@t.overload
def _claude_user_servers(
    config: dict[str, t.Any], *, create: t.Literal[False]
) -> dict[str, t.Any] | None: ...


def _claude_user_servers(
    config: dict[str, t.Any], *, create: bool
) -> dict[str, t.Any] | None:
    """Return (or create) the top-level ``mcpServers`` dict — Claude user scope.

    Mirrors :func:`_claude_project_node` for the user-scope path so the
    shape guard is centralised once and reused across read / write /
    delete instead of duplicated at each call site (or worse, missing
    on read and delete the way the inline write-side guard left them).
    Same reasoning applies as for the project-scope helper: Claude's
    config shape is undocumented internal state, so a clear
    ``RuntimeError`` before the atomic write beats an opaque
    ``AttributeError`` from ``.setdefault()`` on a non-dict.

    With ``create=True`` the dict is initialised when missing and the
    return type narrows to ``dict[str, t.Any]``. With ``create=False``
    a missing key returns ``None``.
    """
    raw = config.get("mcpServers")
    existing: dict[str, t.Any] | None = None
    if isinstance(raw, dict):
        existing = raw
    elif raw is not None:
        msg = (
            "Claude config layout appears to have changed; expected "
            f"'mcpServers' to be a mapping but got "
            f"{type(raw).__name__}"
        )
        raise RuntimeError(msg)
    if existing is None and create:
        existing = {}
        config["mcpServers"] = existing
    return existing


def get_server(
    cli: CLIName,
    config: t.Any,
    name: str,
    repo: pathlib.Path,
    *,
    scope: Scope = "project",
) -> McpServerSpec | None:
    """Fetch the MCP server entry for ``name`` from a CLI's config, if present.

    ``scope`` only affects Claude (see :data:`Scope` for the layered shape
    of ``~/.claude.json``); for Codex / Cursor / Gemini the parameter is
    accepted-but-ignored because their config has no per-project layer.
    """
    if cli == "claude":
        if scope == "user":
            servers = _claude_user_servers(config, create=False)
            entry = servers.get(name) if servers else None
        else:
            node = _claude_project_node(config, repo, create=False)
            if not node:
                return None
            entry = node.get("mcpServers", {}).get(name)
    elif cli in ("cursor", "gemini", "agy"):
        entry = config.get("mcpServers", {}).get(name)
    else:  # cli in ("codex", "grok") — TOML "mcp_servers" table
        entry = config.get("mcp_servers", {}).get(name)
    if entry is None:
        return None
    return _spec_from_entry(entry, fmt=CLIS[cli].fmt)


def set_server(
    cli: CLIName,
    config: t.Any,
    name: str,
    spec: McpServerSpec,
    repo: pathlib.Path,
    *,
    scope: Scope = "project",
) -> t.Literal["replaced", "added"]:
    """Write ``spec`` under ``name`` in a CLI's config, returning replaced/added.

    ``scope == "user"`` for Claude writes the top-level ``mcpServers``
    fallback used by every project that has no per-project override;
    ``"project"`` (the default, preserving pre-flag behaviour) writes
    under ``projects[abs(repo)].mcpServers``. The parameter is silently
    ignored for non-Claude CLIs.
    """
    if cli == "claude":
        if scope == "user":
            servers = _claude_user_servers(config, create=True)
            had = name in servers
            servers[name] = spec.to_json_dict(include_stdio_type=True)
            return "replaced" if had else "added"
        node = _claude_project_node(config, repo, create=True)
        servers = node.setdefault("mcpServers", {})
        had = name in servers
        servers[name] = spec.to_json_dict(include_stdio_type=True)
        return "replaced" if had else "added"
    if cli in ("cursor", "gemini", "agy"):
        servers = config.setdefault("mcpServers", {})
        had = name in servers
        servers[name] = spec.to_json_dict()
        return "replaced" if had else "added"
    if cli in ("codex", "grok"):
        # tomlkit: top-level tables are accessed via dict protocol too.
        mcp_servers = config.get("mcp_servers")
        if mcp_servers is None:
            mcp_servers = tomlkit.table()
            config["mcp_servers"] = mcp_servers
        had = name in mcp_servers
        table = tomlkit.table()
        table["command"] = spec.command
        table["args"] = list(spec.args)
        if spec.env:
            env_tbl = tomlkit.table()
            for k, v in spec.env.items():
                env_tbl[k] = v
            table["env"] = env_tbl
        mcp_servers[name] = table
        return "replaced" if had else "added"
    msg = f"unreachable: unknown CLI {cli!r}"
    raise AssertionError(msg)


def delete_server(
    cli: CLIName,
    config: t.Any,
    name: str,
    repo: pathlib.Path,
    *,
    scope: Scope = "project",
) -> bool:
    """Remove the entry for ``name`` from a CLI's config; return whether it existed.

    See :func:`set_server` for the meaning of ``scope`` — the parameter
    is honoured for Claude and ignored for the other CLIs.
    """
    if cli == "claude":
        if scope == "user":
            servers = _claude_user_servers(config, create=False)
            if servers is not None and name in servers:
                del servers[name]
                return True
            return False
        node = _claude_project_node(config, repo, create=False)
        if not node:
            return False
        servers = node.get("mcpServers", {})
        return servers.pop(name, None) is not None
    if cli in ("cursor", "gemini", "agy"):
        return config.get("mcpServers", {}).pop(name, None) is not None
    if cli in ("codex", "grok"):
        mcp_servers = config.get("mcp_servers")
        if mcp_servers is None:
            return False
        if name in mcp_servers:
            del mcp_servers[name]
            return True
        return False
    msg = f"unreachable: unknown CLI {cli!r}"
    raise AssertionError(msg)


def _spec_from_entry(entry: t.Any, *, fmt: t.Literal["json", "toml"]) -> McpServerSpec:
    """Convert a raw config entry (dict or tomlkit Table) into an McpServerSpec."""
    # tomlkit items quack like dicts/lists; coerce to plain Python for our spec.
    if fmt == "toml":
        entry = (
            tomlkit.items.Table.unwrap(entry)
            if isinstance(entry, tomlkit.items.Table)
            else dict(entry)
        )
    command = str(entry.get("command", ""))
    raw_args = entry.get("args", [])
    args = [str(a) for a in raw_args] if raw_args else []
    raw_env = entry.get("env") or {}
    env = {str(k): str(v) for k, v in dict(raw_env).items()}
    return McpServerSpec(command=command, args=args, env=env)


# ---------------------------------------------------------------------------
# Repo metadata
# ---------------------------------------------------------------------------


def resolve_repo_meta(repo: pathlib.Path) -> tuple[str, str]:
    """Derive (server_name, entry_command) from the repo's pyproject.toml.

    The server name is the registration slug used as the config-file key
    (``mcpServers.<slug>`` in JSON, ``[mcp_servers.<slug>]`` in TOML).
    Default: the first ``[project.scripts]`` entry with a trailing
    ``-mcp`` stripped (``libtmux-engine-mcp`` → ``libtmux-engine``),
    falling back to ``project.name`` when the entry has no ``-mcp``
    suffix. Deriving the slug from the entry rather than ``project.name``
    keeps this repo's server key (``libtmux-engine``) distinct from a
    sibling package whose ``project.name`` is ``libtmux`` — both can be
    registered side by side. Pass ``--server <name>`` to override.
    """
    pyproject = repo / "pyproject.toml"
    doc = tomlkit.parse(pyproject.read_text())
    project = doc.get("project")
    if project is None:
        msg = f"{pyproject} has no [project] table"
        raise RuntimeError(msg)
    scripts = project.get("scripts") or {}
    if not scripts:
        msg = f"{pyproject} has no [project.scripts] — cannot derive entry"
        raise RuntimeError(msg)
    entry = next(iter(scripts))
    server = entry[: -len("-mcp")] if entry.endswith("-mcp") else str(project["name"])
    return server, entry


def build_local_spec(repo: pathlib.Path, entry: str) -> McpServerSpec:
    """Build the ``uv --directory <repo> run <entry>`` spec used by ``use-local``."""
    return McpServerSpec(
        command="uv",
        args=["--directory", str(repo.resolve()), "run", entry],
    )


# ---------------------------------------------------------------------------
# State file
# ---------------------------------------------------------------------------


def load_state() -> dict[tuple[CLIName, Scope], SwapEntry]:
    """Read the swap-state file, returning an empty mapping when absent.

    The state file's schema is internal — no compatibility contract —
    so this loader assumes a single canonical shape. Malformed keys
    (those that don't parse as ``cli:scope``) and entries with a
    non-coercible ``seq_no`` or missing required fields are dropped
    silently so a hand-edited file cannot crash the script.
    """
    if not STATE_FILE.exists():
        return {}
    raw = json.loads(STATE_FILE.read_text())
    entries = raw.get("entries", {})
    out: dict[tuple[CLIName, Scope], SwapEntry] = {}
    for k, v in entries.items():
        parsed = _parse_state_key(k)
        if parsed is None:
            continue
        entry = _parse_state_entry(v)
        if entry is None:
            continue
        out[parsed] = entry
    return out


def save_state(entries: dict[tuple[CLIName, Scope], SwapEntry]) -> None:
    """Write the swap-state file atomically."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "entries": {
            _state_key(cli, scope): dataclasses.asdict(v)
            for (cli, scope), v in entries.items()
        },
    }
    atomic_write(STATE_FILE, (json.dumps(payload, indent=2) + "\n").encode("utf-8"))


def clear_state(keys: t.Iterable[tuple[CLIName, Scope]]) -> None:
    """Remove the given ``(cli, scope)`` keys; delete the file if empty."""
    current = load_state()
    for key in keys:
        current.pop(key, None)
    if current:
        save_state(current)
    elif STATE_FILE.exists():
        STATE_FILE.unlink()


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Presence:
    """Detection outcome for a CLI: binary on PATH and config file present."""

    cli: CLIName
    binary_found: bool
    config_found: bool

    @property
    def present(self) -> bool:
        """Return True only when both the binary and the config file were found."""
        return self.binary_found and self.config_found


def detect_clis() -> list[Presence]:
    """Probe all supported CLIs and return their detection results."""
    return [
        Presence(
            cli=info.name,
            binary_found=shutil.which(info.binary) is not None,
            config_found=info.config_path.exists(),
        )
        for info in CLIS.values()
    ]


def present_clis() -> list[CLIName]:
    """Return the list of CLIs that have both a binary and a config present."""
    return [p.cli for p in detect_clis() if p.present]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_detect(args: argparse.Namespace) -> int:
    """Print detection results for every supported CLI."""
    for p in detect_clis():
        flag = "yes" if p.present else " no"
        extra = []
        if not p.binary_found:
            extra.append("binary missing")
        if not p.config_found:
            extra.append(f"config missing: {CLIS[p.cli].config_path}")
        suffix = f"  ({', '.join(extra)})" if extra else ""
        print(f"  [{flag}] {p.cli:<7}{suffix}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Print the current MCP server entry per detected CLI.

    For Claude, prints separate lines for the user-level fallback
    (``[claude:user]``) and the per-project override
    (``[claude:project]``) when both exist; if only one exists, only
    that line shows. ``args.scope`` (when set) restricts Claude output
    to the matching layer only. Other CLIs print a single line as
    ``[<cli>]`` since their config has no scope concept and ignore
    ``args.scope``.
    """
    repo = pathlib.Path(args.repo).resolve()
    server = args.server or resolve_repo_meta(repo)[0]
    scope_filter: Scope | None = args.scope
    for cli in args.cli or present_clis():
        info = CLIS[cli]
        if not info.config_path.exists():
            print(f"[{cli}] (no config at {info.config_path})")
            continue
        # Wrap the read + shape-guarded queries in try/except RuntimeError
        # so a malformed Claude config surfaces as a clean per-CLI error
        # instead of aborting status output for the rest of the CLIs.
        try:
            config = load_config(info)
            if cli == "claude":
                # Lazy reads: skip the get_server call entirely for the
                # filtered-out scope so a malformed projects node doesn't
                # raise when the user only asked about user scope.
                user_spec = (
                    get_server(cli, config, server, repo, scope="user")
                    if scope_filter in (None, "user")
                    else None
                )
                project_spec = (
                    get_server(cli, config, server, repo, scope="project")
                    if scope_filter in (None, "project")
                    else None
                )
                shown = False
                if user_spec is not None:
                    tag = _describe_spec(user_spec, repo)
                    print(
                        f"[claude:user] {server} = {user_spec.command} "
                        f"{' '.join(user_spec.args)}  ({tag})"
                    )
                    shown = True
                if project_spec is not None:
                    tag = _describe_spec(project_spec, repo)
                    print(
                        f"[claude:project] {server} = {project_spec.command} "
                        f"{' '.join(project_spec.args)}  ({tag})"
                    )
                    shown = True
                if not shown:
                    label = f"claude:{scope_filter}" if scope_filter else "claude"
                    print(f"[{label}] no entry for {server!r}")
            else:
                spec = get_server(cli, config, server, repo)
                if spec is None:
                    print(f"[{cli}] no entry for {server!r}")
                    continue
                tag = _describe_spec(spec, repo)
                print(
                    f"[{cli}] {server} = {spec.command} {' '.join(spec.args)}  ({tag})"
                )
        except RuntimeError as exc:
            print(f"[{cli}] {exc}", file=sys.stderr)
            continue
    return 0


def _describe_spec(spec: McpServerSpec, repo: pathlib.Path) -> str:
    """Return a short label classifying a spec (local/pypi-pin/other)."""
    if spec.is_local_uv_directory():
        local = spec.local_repo_path()
        if local and local.resolve() == repo.resolve():
            return "local: this repo"
        return f"local: {local}"
    if spec.command == "uvx":
        pinned = next((a for a in spec.args if "==" in a or "@" in a), None)
        return f"pypi pin: {pinned}" if pinned else "pypi (unpinned)"
    return "other"


def cmd_use_local(args: argparse.Namespace) -> int:
    """Rewrite each target CLI's config to run the repo's checkout via ``uv``.

    The optional ``--scope`` flag selects Claude's user-level fallback
    vs. per-project override; see :data:`Scope`. The flag is silently
    coerced to ``"user"`` for non-Claude CLIs by :func:`_normalize_scope`.
    """
    repo = pathlib.Path(args.repo).resolve()
    server, default_entry = resolve_repo_meta(repo)
    server = args.server or server
    entry = args.entry or default_entry
    spec = build_local_spec(repo, entry)

    targets = args.cli or present_clis()
    if not targets:
        print("no CLIs detected — nothing to do", file=sys.stderr)
        return 1

    ts = time.strftime("%Y%m%d%H%M%S")
    state = load_state()
    had_error = 0
    for cli in targets:
        scope = _normalize_scope(cli, args.scope)
        label = f"{cli}:{scope}" if cli == "claude" else cli
        info = CLIS[cli]
        if not info.config_path.exists():
            print(f"[{label}] skip — config not found at {info.config_path}")
            continue
        # Wrap the read + shape-guarded mutation in try/except RuntimeError
        # so a malformed Claude config (top-level mcpServers / projects not a
        # mapping) surfaces as a clean per-CLI error instead of an uncaught
        # traceback. Same per-CLI continuation pattern the inner write-failure
        # handler below uses.
        try:
            original_bytes = info.config_path.read_bytes()
            config = load_config(info)
            current = get_server(cli, config, server, repo, scope=scope)
            if (
                current
                and current.is_local_uv_directory()
                and current.local_repo_path() == repo
            ):
                print(f"[{label}] already local (this repo) — no change")
                continue
            # Preserve the existing entry's env on replacement. ``build_local_spec``
            # writes an empty env, so without this merge a swap would silently drop
            # client-side settings (LIBTMUX_SAFETY, LIBTMUX_SOCKET, custom dev
            # knobs). Symmetric with ``_spec_from_entry`` which round-trips env on
            # the read side.
            cli_spec = (
                dataclasses.replace(spec, env={**current.env}) if current else spec
            )
            action = set_server(cli, config, server, cli_spec, repo, scope=scope)
            new_bytes = dump_config_bytes(info, config)
        except RuntimeError as exc:
            print(f"[{label}] {exc}", file=sys.stderr)
            had_error = 1
            continue

        if args.dry_run:
            print(f"--- {info.config_path} (current)")
            print(f"+++ {info.config_path} (proposed)")
            diff = difflib.unified_diff(
                original_bytes.decode(errors="replace").splitlines(keepends=True),
                new_bytes.decode(errors="replace").splitlines(keepends=True),
                lineterm="",
            )
            sys.stdout.writelines(diff)
            continue

        # Claude is the only CLI where two swaps (different scopes) can
        # touch the same config file in one second; embed the scope so
        # the second backup doesn't overwrite the first. Non-Claude
        # backup filenames carry no scope suffix.
        backup_suffix = f"{BACKUP_SUFFIX_PREFIX}{ts}"
        if cli == "claude":
            backup_suffix += f"-{scope}"
        backup_path = info.config_path.with_suffix(
            info.config_path.suffix + backup_suffix
        )
        backup_path.write_bytes(original_bytes)
        try:
            atomic_write(info.config_path, new_bytes)
            _revalidate(info)
        except Exception as exc:
            atomic_write(info.config_path, original_bytes)
            print(
                f"[{label}] write failed ({exc}); backup at {backup_path}",
                file=sys.stderr,
            )
            had_error = 1
            continue
        next_seq = max((e.seq_no for e in state.values()), default=-1) + 1
        state[(cli, scope)] = SwapEntry(
            config_path=str(info.config_path),
            backup_path=str(backup_path),
            server=server,
            action=action,
            swapped_at=ts,
            seq_no=next_seq,
        )
        print(f"[{label}] {action}; backup: {backup_path}")

    if not args.dry_run:
        save_state(state)
    return had_error


def _revalidate(info: CLIInfo) -> None:
    """Re-parse the file after writing; raise on failure."""
    load_config(info)


def cmd_revert(args: argparse.Namespace) -> int:
    """Restore each target CLI's config from the backup recorded in the state file.

    Without ``--scope``, every recorded entry for the targeted CLIs is
    reverted (so a Claude install that has both user-scope and
    project-scope swaps gets both restored). With ``--scope``, only
    the matching scope is reverted; the parameter is silently coerced
    to ``"user"`` for non-Claude CLIs.
    """
    state = load_state()
    # Without --cli, revert every CLI that has any recorded swap.
    targets = list(args.cli) if args.cli else list({cli for cli, _scope in state})
    if not targets:
        print("no recorded swaps — nothing to revert", file=sys.stderr)
        return 1

    reverted: list[tuple[CLIName, Scope]] = []
    for cli in targets:
        if args.scope is not None:
            wanted_scopes: tuple[Scope, ...] = (_normalize_scope(cli, args.scope),)
        else:
            wanted_scopes = ALL_SCOPES
        cli_keys = [
            (sc_cli, sc_scope)
            for (sc_cli, sc_scope) in state
            if sc_cli == cli and sc_scope in wanted_scopes
        ]
        if not cli_keys:
            label = f"{cli}:{args.scope}" if args.scope and cli == "claude" else cli
            print(f"[{label}] no state entry — skip")
            continue
        # Unwind in reverse-registration order (LIFO) — sort by the
        # explicit ``SwapEntry.seq_no`` counter so order is independent
        # of JSON parse order, dict iteration, and wall-clock
        # collisions. ``seq_no`` is coerced to ``int`` at load time by
        # ``_parse_state_entry``; entries with a non-coercible value
        # are dropped before they reach this sort, so the comparison
        # is always int vs int. When two scopes back the same physical
        # file (Claude user + project), the later swap's backup
        # contains the earlier swap's modifications, so each backup
        # must restore its own layer before the prior one is restored.
        # Same explicit counter pattern CPython's ``Lib/sched.py`` uses
        # to break ties on ``Event(time, priority, sequence, …)``.
        cli_keys.sort(key=lambda k: state[k].seq_no, reverse=True)
        for key in cli_keys:
            sc_cli, sc_scope = key
            entry = state[key]
            label = f"{sc_cli}:{sc_scope}" if sc_cli == "claude" else sc_cli
            backup = pathlib.Path(entry.backup_path)
            dest = pathlib.Path(entry.config_path)
            if not backup.exists():
                print(f"[{label}] backup missing: {backup}", file=sys.stderr)
                continue
            if args.dry_run:
                print(f"[{label}] would restore {dest} from {backup}")
                continue
            atomic_write(dest, backup.read_bytes())
            # Backup served its purpose; LIFO unwind for this layer is
            # complete. Delete on success, keep on error — same idiom
            # CPython's ``tempfile.NamedTemporaryFile`` uses
            # (Lib/tempfile.py:614-618). If ``atomic_write`` had raised,
            # this line wouldn't run and the backup would survive for
            # post-mortem; on success the backup is redundant and would
            # otherwise accumulate forever across swap/revert cycles.
            backup.unlink()
            print(f"[{label}] restored from {backup}")
            reverted.append(key)

    if not args.dry_run and reverted:
        clear_state(reverted)
    return 0


# ---------------------------------------------------------------------------
# argparse glue
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Construct the ``argparse`` parser for ``mcp_swap``."""
    p = argparse.ArgumentParser(prog="mcp_swap", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser(
        "detect", help="list installed CLIs and their config presence"
    ).set_defaults(func=cmd_detect)

    ps = sub.add_parser("status", help="show the current MCP server entry per CLI")
    ps.add_argument("--repo", default=".", help="repo root (default: .)")
    ps.add_argument(
        "--server", help="MCP server name (default: derived from pyproject.toml)"
    )
    ps.add_argument(
        "--cli", action="append", choices=ALL_CLIS, help="limit to one or more CLIs"
    )
    ps.add_argument(
        "--scope",
        choices=ALL_SCOPES,
        default=None,
        help=(
            "Limit Claude output to one scope: 'user' shows only the "
            "top-level mcpServers fallback, 'project' shows only the "
            "projects.<abs>.mcpServers entry. Without this flag, both "
            "Claude scopes print when both have an entry. No-op for "
            "non-Claude CLIs (their config has no per-project layer)."
        ),
    )
    ps.set_defaults(func=cmd_status)

    pu = sub.add_parser("use-local", help="rewrite configs to run this checkout")
    pu.add_argument("--repo", default=".", help="repo root (default: .)")
    pu.add_argument(
        "--server", help="MCP server name (default: derived from pyproject.toml)"
    )
    pu.add_argument(
        "--entry", help="uv run entry command (default: [project.scripts] first key)"
    )
    pu.add_argument("--cli", action="append", choices=ALL_CLIS)
    pu.add_argument(
        "--scope",
        choices=ALL_SCOPES,
        default=None,
        help=(
            "Claude config scope: 'user' rewrites the top-level mcpServers "
            "fallback (every project without an override picks it up), "
            "'project' rewrites projects.<abs>.mcpServers under this repo. "
            "Default 'project'. Silently coerced to 'user' for non-Claude CLIs."
        ),
    )
    pu.add_argument("--dry-run", action="store_true")
    pu.set_defaults(func=cmd_use_local)

    pr = sub.add_parser("revert", help="restore each CLI's config from its swap backup")
    pr.add_argument("--cli", action="append", choices=ALL_CLIS)
    pr.add_argument(
        "--scope",
        choices=ALL_SCOPES,
        default=None,
        help=(
            "Limit revert to one Claude scope. Without this flag, every "
            "recorded scope for the targeted CLIs is reverted."
        ),
    )
    pr.add_argument("--dry-run", action="store_true")
    pr.set_defaults(func=cmd_revert)

    return p


def main(argv: list[str] | None = None) -> int:
    """Entry point — dispatches to the selected subcommand."""
    args = build_parser().parse_args(argv)
    return t.cast("int", args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
