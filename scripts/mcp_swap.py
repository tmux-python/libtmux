#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["tomlkit>=0.13"]
# ///
"""Swap MCP server configs across Claude / Codex / Cursor / Gemini / Grok / agy.

Use when you want every installed agent CLI to run a local checkout of an
MCP server (editable) instead of a pinned release. ``use-local`` rewrites
each CLI's config to invoke the checkout via ``uv --directory <repo> run
<entry>``, or a pull request's head via ``uvx`` with ``--pr``; ``revert``
restores from the timestamped backup the swap wrote.
Swapping a layer that is already swapped keeps that first backup rather
than taking a new one, so ``revert`` always lands on the pre-swap config.

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
$ uv run scripts/mcp_swap.py use-local --pr 115
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
- **Serialized mutations.** Concurrent ``use-local`` and ``revert``
  invocations share an advisory transaction lock, so config and recovery-state
  updates cannot overwrite one another.
"""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import fcntl
import functools
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
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
STATE_LOCK_NAME = "transaction.lock"

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


#: A ``--from`` argument pointing at a pull request's head commit.
#: GitHub publishes ``refs/pull/<n>/head`` on the *base* repository, so
#: one URL serves same-repo and fork pull requests alike.
PR_REF_RE = re.compile(r"git\+(?P<url>.+?)@refs/pull/(?P<number>\d+)/head")


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

    def pr_ref(self) -> tuple[str, int] | None:
        """Return ``(repo_url, pr_number)`` for a ``uvx`` pull-request spec."""
        if self.command != "uvx":
            return None
        for arg in self.args:
            match = PR_REF_RE.fullmatch(arg)
            if match:
                return match.group("url"), int(match.group("number"))
        return None


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
    #: Exact destination changed by the swap. ``config_path`` may be a
    #: symlink that is later repointed, so it is not sufficient recovery
    #: identity. Older state entries omit this field and fall back to
    #: ``config_path`` during revert.
    target_path: str | None = None


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


def _json_trailer(original: bytes) -> str:
    """Return the newline a rewritten JSON config should end with.

    Claude writes ``~/.claude.json`` without a trailing newline, so
    appending one unconditionally grows the file by a byte on every swap
    and shows as a diff hunk in a region the swap never touched. Empty
    bytes mean a file being seeded, which gets the conventional newline.
    """
    if not original:
        return "\n"
    return "\n" if original.endswith(b"\n") else ""


def dump_config_bytes(info: CLIInfo, config: t.Any, *, original: bytes) -> bytes:
    """Serialize an edited config back to bytes in its original format.

    ``original`` is the file's pre-edit bytes, or empty when seeding a
    new one. The parsed structure does not record the byte-level
    conventions of the file it came from, so they are carried over from
    the source instead. Required rather than defaulted: a caller that
    omitted it would silently start rewriting regions it never touched,
    which is the defect this parameter exists to prevent. tomlkit
    preserves those conventions itself; only the JSON writer needs it.
    """
    if info.fmt != "json":
        return tomlkit.dumps(config).encode()
    trailer = _json_trailer(original)
    # ensure_ascii would re-escape every non-ASCII character in the file,
    # including config text the swap never read.
    text = json.dumps(config, indent=2, ensure_ascii=False) + trailer
    try:
        return text.encode()
    except UnicodeEncodeError:
        # A lone surrogate — a JS writer slicing a string mid-pair — has no
        # UTF-8 encoding. Escaping the document is then the only form that
        # can be written at all.
        return (json.dumps(config, indent=2) + trailer).encode()


def atomic_write(path: pathlib.Path, data: bytes) -> None:
    """Write bytes to ``path`` without replacing a symlinked config.

    Parameters
    ----------
    path : pathlib.Path
        Destination path. A symlink resolves to its final target so the
        write preserves every link in the chain.
    data : bytes
        Bytes to write atomically.
    """
    target = path.resolve() if path.is_symlink() else path
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else None
    fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", dir=str(target.parent))
    tmp = pathlib.Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            if mode is not None:
                os.fchmod(fh.fileno(), mode)
            fh.write(data)
        tmp.replace(target)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def write_new_backup(base: pathlib.Path, data: bytes) -> pathlib.Path:
    """Write ``data`` to ``base``, or to ``base-1`` / ``base-2`` / … if taken.

    A backup is the only copy of the config as it stood before a swap, so
    clobbering one is unrecoverable data loss. The timestamp embedded in
    ``base`` has one-second granularity, which is not fine enough on its
    own: two swaps inside the same second derive the same path. Creation
    goes through ``O_CREAT | O_EXCL`` so the check and the claim are one
    atomic step and an existing file can never be truncated — the same
    exclusive-create discipline CPython's ``tempfile`` uses to hand out
    unique names.

    Parameters
    ----------
    base : pathlib.Path
        Preferred backup path.
    data : bytes
        Config bytes to preserve.

    Returns
    -------
    pathlib.Path
        Exclusively created backup path.

    Examples
    --------
    >>> with tempfile.TemporaryDirectory() as tmp_dir:
    ...     base = pathlib.Path(tmp_dir) / "config.bak"
    ...     first = write_new_backup(base, b"first")
    ...     second = write_new_backup(base, b"second")
    ...     (first.name, second.name, first.read_bytes(), second.read_bytes())
    ('config.bak', 'config.bak-1', b'first', b'second')
    """
    base.parent.mkdir(parents=True, exist_ok=True)
    candidate = base
    attempt = 0
    while True:
        try:
            fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            attempt += 1
            candidate = base.with_name(f"{base.name}-{attempt}")
            continue
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        return candidate


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
    if not isinstance(entry, dict):
        msg = f"expected server entry to be a mapping, got {type(entry).__name__}"
        raise TypeError(msg)
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
    server = (
        entry.removesuffix("-mcp") if entry.endswith("-mcp") else str(project["name"])
    )
    return server, entry


def build_local_spec(repo: pathlib.Path, entry: str) -> McpServerSpec:
    """Build the ``uv --directory <repo> run <entry>`` spec used by ``use-local``."""
    return McpServerSpec(
        command="uv",
        args=["--directory", str(repo.resolve()), "run", entry],
    )


def build_pr_spec(repo_url: str, pr: int, entry: str) -> McpServerSpec:
    """Build the ``uvx --from git+<url>@refs/pull/<n>/head <entry>`` spec.

    Nothing is checked out: ``uv`` resolves the ref itself, so a swap
    leaves no worktree to refresh or prune and ``revert`` needs no
    cleanup beyond restoring the config.
    """
    return McpServerSpec(
        command="uvx",
        args=["--from", f"git+{repo_url}@refs/pull/{pr}/head", entry],
    )


def _run_text(argv: list[str], cwd: pathlib.Path | None = None) -> str:
    """Run ``argv`` and return stdout, raising on a non-zero exit."""
    return subprocess.run(
        argv,
        cwd=None if cwd is None else str(cwd),
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def remote_https_url(repo: pathlib.Path, remote: str = "origin") -> str:
    """Return ``https://<host>/<owner>/<name>`` for a repo's git remote.

    Normalizes the spellings git accepts — ``git@host:owner/name.git``,
    an ``ssh://`` or ``git+ssh://`` scheme, an embedded user, a trailing
    ``.git`` — because the pull-request ref is fetched over https however
    the working copy was cloned.
    """
    try:
        raw = _run_text(["git", "-C", str(repo), "remote", "get-url", remote])
    except (OSError, subprocess.CalledProcessError) as exc:
        msg = f"cannot read git remote {remote!r} in {repo}"
        raise RuntimeError(msg) from exc
    return _normalize_remote_url(raw.strip())


def _normalize_remote_url(url: str) -> str:
    """Rewrite any git remote spelling as a plain https URL.

    Examples
    --------
    >>> _normalize_remote_url("git+ssh://git@github.com/o/n.git")
    'https://github.com/o/n'
    >>> _normalize_remote_url("git@github.com:o/n.git")
    'https://github.com/o/n'
    >>> _normalize_remote_url("https://github.com/o/n")
    'https://github.com/o/n'
    """
    url = url.removeprefix("git+")
    if url.startswith("ssh://"):
        url = "https://" + url.removeprefix("ssh://")
    elif "://" not in url and ":" in url:
        host, _, path = url.partition(":")
        url = f"https://{host}/{path}"
    scheme, sep, rest = url.partition("://")
    authority, slash, path = rest.partition("/")
    return f"{scheme}{sep}{authority.rpartition('@')[2]}{slash}{path}".removesuffix(
        ".git"
    )


def gh_pr_summary(repo: pathlib.Path, pr: int) -> dict[str, t.Any] | None:
    """Return ``gh``'s view of a pull request, or ``None`` when unreadable.

    Used to confirm the number exists and to label output. Resolution
    does not depend on it: the ref and URL come from git, so a missing
    or unauthenticated ``gh`` degrades to an unlabelled swap rather than
    a failure.
    """
    try:
        out = _run_text(
            [
                "gh",
                "pr",
                "view",
                str(pr),
                "--json",
                "number,title,state,headRefName,isCrossRepository",
            ],
            cwd=repo,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    try:
        loaded = json.loads(out)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


#: One MCP ``initialize`` request, newline-framed for stdio.
_INITIALIZE_FRAME = (
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "mcp_swap-preflight", "version": "1"},
            },
        }
    )
    + "\n"
)


def preflight_spec(spec: McpServerSpec, *, timeout: float = 300.0) -> str | None:
    """Launch ``spec`` and complete one MCP ``initialize`` round trip.

    Returns ``None`` when the server answered, otherwise a reason to
    show the operator. A pull-request spec resolves its dependencies at
    launch time, inside whichever agent starts it, so an unresolvable
    ref would otherwise land in every config and surface later as an
    opaque startup failure in each one.

    Closing stdin after the frame lets a well-behaved stdio server exit
    on its own, which keeps this free of signal handling.
    """
    try:
        proc = subprocess.Popen(
            [spec.command, *spec.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, **spec.env},
            text=True,
        )
    except OSError as exc:
        return f"could not launch {spec.command}: {exc}"

    try:
        out, err = proc.communicate(_INITIALIZE_FRAME, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return f"no MCP response within {timeout:.0f}s"

    for line in out.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict) and message.get("id") == 1 and "result" in message:
            return None

    tail = "\n".join(err.strip().splitlines()[-3:])
    return tail or "server exited without answering initialize"


# ---------------------------------------------------------------------------
# State file
# ---------------------------------------------------------------------------


def load_state() -> dict[tuple[CLIName, Scope], SwapEntry]:
    """Read the swap-state file, returning an empty mapping when absent.

    The state file's schema is internal — no compatibility contract —
    so this loader requires its canonical top-level shape. Invalid JSON
    and invalid containers raise ``RuntimeError`` so mutating commands
    cannot overwrite recovery metadata they failed to understand.
    Malformed individual keys and entries are dropped.
    """
    if not STATE_FILE.exists():
        return {}
    try:
        raw = json.loads(STATE_FILE.read_text())
    except (UnicodeError, json.JSONDecodeError) as exc:
        msg = f"recovery state is unreadable: {exc}"
        raise RuntimeError(msg) from exc
    if not isinstance(raw, dict):
        msg = (
            "recovery state is unreadable: expected a mapping, got "
            f"{type(raw).__name__}"
        )
        raise TypeError(msg)
    entries = raw.get("entries", {})
    if not isinstance(entries, dict):
        msg = (
            "recovery state is unreadable: expected 'entries' to be a mapping, "
            f"got {type(entries).__name__}"
        )
        raise TypeError(msg)
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


def _serialized_transaction(
    command: t.Callable[[argparse.Namespace], int],
) -> t.Callable[[argparse.Namespace], int]:
    """Serialize one config-and-recovery-state transaction across processes."""

    @functools.wraps(command)
    def locked(args: argparse.Namespace) -> int:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with (STATE_DIR / STATE_LOCK_NAME).open("a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                return command(args)
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    return locked


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
    had_error = 0
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
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            print(f"[{cli}] {exc}", file=sys.stderr)
            had_error = 1
            continue
    return had_error


def _describe_spec(spec: McpServerSpec, repo: pathlib.Path) -> str:
    """Return a short label classifying a spec (local/PR/pypi-pin/other)."""
    if spec.is_local_uv_directory():
        local = spec.local_repo_path()
        if local and local.resolve() == repo.resolve():
            return "local: this repo"
        return f"local: {local}"
    pr = spec.pr_ref()
    if pr is not None:
        # Checked before the pin branch below: a PR ref contains `@`,
        # which that branch would report as a version pin.
        return f"PR #{pr[1]}: {pr[0]}"
    if spec.command == "uvx":
        pinned = next((a for a in spec.args if "==" in a or "@" in a), None)
        return f"pypi pin: {pinned}" if pinned else "pypi (unpinned)"
    return "other"


def _points_at(current: McpServerSpec, target: McpServerSpec) -> bool:
    """Return True when ``current`` already runs what ``target`` describes.

    A pull-request target compares by ref so a re-swap onto the same
    number is a no-op while a different number is not. Everything else
    compares argv exactly: a local entry that names another ``--entry``
    still points at this repo, and treating that as "already local"
    would silently ignore the flag that asked for the change.
    """
    if target.pr_ref() is not None:
        return current.pr_ref() == target.pr_ref()
    return current.command == target.command and current.args == target.args


@_serialized_transaction
def cmd_use_local(args: argparse.Namespace) -> int:
    """Rewrite each target CLI's config to run the repo, or a pull request.

    Without ``--pr`` the entry runs the repo's checkout via ``uv``; with
    it, the pull request's head via ``uvx``.

    The optional ``--scope`` flag selects Claude's user-level fallback
    vs. per-project override; see :data:`Scope`. The flag is silently
    coerced to ``"user"`` for non-Claude CLIs by :func:`_normalize_scope`.
    """
    repo = pathlib.Path(args.repo).resolve()
    server, default_entry = resolve_repo_meta(repo)
    server = args.server or server
    entry = args.entry or default_entry
    extra_env = dict(args.env or [])

    pr = getattr(args, "pr", None)
    if pr is None:
        spec = build_local_spec(repo, entry)
    else:
        try:
            spec = build_pr_spec(remote_https_url(repo), pr, entry)
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return 1
        spec = dataclasses.replace(spec, env=dict(extra_env))
        summary = gh_pr_summary(repo, pr)
        if summary is None:
            print(f"PR #{pr}: gh could not read it — swapping anyway", file=sys.stderr)
        else:
            fork = " (fork)" if summary.get("isCrossRepository") else ""
            print(
                f"PR #{summary.get('number', pr)} [{summary.get('state', '?')}]"
                f"{fork} {summary.get('headRefName', '?')} — "
                f"{summary.get('title', '')}",
                file=sys.stderr,
            )

    hint = _naming_hint(repo, server)
    if hint:
        print(hint, file=sys.stderr)

    targets = args.cli or present_clis()
    if not targets:
        print("no CLIs detected — nothing to do", file=sys.stderr)
        return 1

    # Runs under --dry-run too: resolving the ref is the only signal a
    # dry run can give about whether the swap would actually start.
    if pr is not None and not args.no_preflight:
        print(f"preflight: {spec.command} {' '.join(spec.args)}", file=sys.stderr)
        failure = preflight_spec(spec)
        if failure is not None:
            print(f"preflight failed, nothing written:\n{failure}", file=sys.stderr)
            return 1

    ts = time.strftime("%Y%m%d%H%M%S")
    try:
        state = load_state()
    except (OSError, RuntimeError, TypeError) as exc:
        print(f"recovery state error: {exc}; no config changed", file=sys.stderr)
        return 1
    had_error = 0
    for cli in targets:
        scope = _normalize_scope(cli, args.scope)
        label = f"{cli}:{scope}" if cli == "claude" else cli
        info = CLIS[cli]
        if not info.config_path.exists():
            print(f"[{label}] skip — config not found at {info.config_path}")
            had_error = 1
            continue
        target_path = info.config_path.resolve()
        target_info = dataclasses.replace(info, config_path=target_path)
        # Treat read, parse, and shape errors as per-CLI failures so one
        # malformed target cannot strand earlier successful targets. A shape
        # this script rejects raises RuntimeError, an unparseable one raises
        # ValueError (JSON, TOML and UTF-8 decode errors all derive from it),
        # and an unopenable one raises OSError.
        try:
            original_bytes = target_path.read_bytes()
            config = load_config(target_info)
            current = get_server(cli, config, server, repo, scope=scope)
            state_key = (cli, scope)
            prior = state.get(state_key)
            prior_backup = (
                pathlib.Path(prior.backup_path) if prior is not None else None
            )
            if prior_backup is not None and not prior_backup.exists():
                print(
                    f"[{label}] recorded pre-swap backup is missing "
                    f"({prior_backup}); refusing to replace recovery state",
                    file=sys.stderr,
                )
                had_error = 1
                continue
            if (
                current
                and _points_at(current, spec)
                and all(current.env.get(k) == v for k, v in extra_env.items())
            ):
                where = "local (this repo)" if pr is None else f"PR #{pr}"
                print(f"[{label}] already {where} — no change")
                continue
            # Preserve the existing entry's env on replacement. ``build_local_spec``
            # writes an empty env, so without this merge a swap would silently drop
            # client-side settings (LIBTMUX_SAFETY, LIBTMUX_SOCKET, custom dev
            # knobs). Symmetric with ``_spec_from_entry`` which round-trips env on
            # the read side.
            base_env = dict(current.env) if current else {}
            base_env.update(extra_env)
            cli_spec = (
                dataclasses.replace(spec, env=base_env)
                if (current or extra_env)
                else spec
            )
            action = set_server(cli, config, server, cli_spec, repo, scope=scope)
            new_bytes = dump_config_bytes(info, config, original=original_bytes)
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
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

        # A repeated swap sees this script's earlier output, not the
        # user's pristine config. Keep the first backup and its ordering
        # metadata so revert still unwinds the layers it actually captured.
        if prior is not None:
            newer = sorted(
                (
                    (other_key, other_entry)
                    for other_key, other_entry in state.items()
                    if other_key != state_key
                    and other_entry.config_path == prior.config_path
                    and other_entry.seq_no > prior.seq_no
                ),
                key=lambda item: item[1].seq_no,
                reverse=True,
            )
            if newer:
                newer_labels = ", ".join(
                    f"{new_cli}:{new_scope}" if new_cli == "claude" else new_cli
                    for (new_cli, new_scope), _entry in newer
                )
                print(
                    f"[{label}] cannot update beneath newer whole-file layer(s) "
                    f"{newer_labels}; revert those layers first",
                    file=sys.stderr,
                )
                had_error = 1
                continue
        reused_prior_backup = False
        if prior_backup is not None:
            backup_path = prior_backup
            reused_prior_backup = True
            backup_note = f"pre-swap backup kept: {backup_path}"
        else:
            # Claude is the only CLI where two swaps (different scopes) can
            # touch the same config file in one second; embed the scope so
            # the two backups read distinctly. Non-Claude backup filenames
            # carry no scope suffix. Collisions past that are resolved by
            # ``write_new_backup``, which never overwrites.
            backup_suffix = f"{BACKUP_SUFFIX_PREFIX}{ts}"
            if cli == "claude":
                backup_suffix += f"-{scope}"
            # A backup that cannot be written must abort this CLI rather
            # than degrade into a swap with nothing to revert to — an
            # unwritable directory is the case that produces both.
            try:
                backup_path = write_new_backup(
                    info.config_path.with_suffix(
                        info.config_path.suffix + backup_suffix
                    ),
                    original_bytes,
                )
            except OSError as exc:
                print(f"[{label}] cannot write backup: {exc}", file=sys.stderr)
                had_error = 1
                continue
            backup_note = f"backup: {backup_path}"

        if prior is not None and reused_prior_backup:
            # ``swapped_at`` mirrors the timestamp in the backup filename
            # and ``seq_no`` fixes the backup's place in the unwind
            # stack; both describe the kept backup, not this run.
            seq_no, swapped_at = prior.seq_no, prior.swapped_at
        else:
            seq_no = max((e.seq_no for e in state.values()), default=-1) + 1
            swapped_at = ts
        recovery_entry = SwapEntry(
            config_path=str(info.config_path),
            backup_path=str(backup_path),
            server=server,
            action=action,
            swapped_at=swapped_at,
            seq_no=seq_no,
            target_path=str(target_path),
        )
        # Register recovery state before touching the config: a crash between
        # the two must leave a state entry pointing at a real backup, never a
        # swapped config no entry knows about.
        state[state_key] = recovery_entry
        try:
            save_state(state)
        except (OSError, TypeError, ValueError) as exc:
            if prior is None:
                state.pop(state_key)
            else:
                state[state_key] = prior
            cleanup_note = ""
            if not reused_prior_backup:
                try:
                    backup_path.unlink(missing_ok=True)
                except OSError as cleanup_exc:
                    cleanup_note = f"; backup cleanup failed ({cleanup_exc})"
            print(
                f"[{label}] recovery state write failed ({exc}){cleanup_note}",
                file=sys.stderr,
            )
            had_error = 1
            continue

        try:
            atomic_write(target_path, new_bytes)
            _revalidate(target_info)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            try:
                atomic_write(target_path, original_bytes)
                load_config(target_info)
            except (OSError, RuntimeError, TypeError, ValueError) as rollback_exc:
                print(
                    f"[{label}] write failed ({exc}); config rollback failed "
                    f"({rollback_exc}); recovery state and backup kept at "
                    f"{backup_path}",
                    file=sys.stderr,
                )
                had_error = 1
                continue

            if prior is None:
                state.pop(state_key)
            else:
                state[state_key] = prior
            try:
                if state:
                    save_state(state)
                else:
                    STATE_FILE.unlink(missing_ok=True)
            except (OSError, TypeError, ValueError) as rollback_exc:
                state[state_key] = recovery_entry
                print(
                    f"[{label}] write failed ({exc}); recovery state rollback "
                    f"failed ({rollback_exc}); backup kept at {backup_path}",
                    file=sys.stderr,
                )
                had_error = 1
                continue

            cleanup_note = ""
            if not reused_prior_backup:
                try:
                    backup_path.unlink(missing_ok=True)
                except OSError as cleanup_exc:
                    cleanup_note = f"; backup cleanup failed ({cleanup_exc})"
            print(
                f"[{label}] write failed ({exc}); config and state rolled back"
                f"{cleanup_note}",
                file=sys.stderr,
            )
            had_error = 1
            continue

        print(f"[{label}] {action}; {backup_note}")

    return had_error


def _revalidate(info: CLIInfo) -> None:
    """Re-parse the file after writing; raise on failure."""
    load_config(info)


@_serialized_transaction
def cmd_revert(args: argparse.Namespace) -> int:
    """Restore each target CLI's config from the backup recorded in the state file.

    Without ``--scope``, every recorded entry for the targeted CLIs is
    reverted (so a Claude install that has both user-scope and
    project-scope swaps gets both restored). With ``--scope``, only
    the matching scope is reverted; the parameter is silently coerced
    to ``"user"`` for non-Claude CLIs.
    """
    try:
        state = load_state()
    except (OSError, RuntimeError, TypeError) as exc:
        print(f"recovery state error: {exc}; no config changed", file=sys.stderr)
        return 1
    # Without --cli, revert every CLI that has any recorded swap.
    targets = list(args.cli) if args.cli else list({cli for cli, _scope in state})
    if not targets:
        print("no recorded swaps — nothing to revert", file=sys.stderr)
        return 1

    had_error = 0
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
        blocked = False
        if args.scope is not None:
            for key in cli_keys:
                entry = state[key]
                newer = sorted(
                    (
                        (other_key, other_entry)
                        for other_key, other_entry in state.items()
                        if other_key != key
                        and other_entry.config_path == entry.config_path
                        and other_entry.seq_no > entry.seq_no
                    ),
                    key=lambda item: item[1].seq_no,
                    reverse=True,
                )
                if not newer:
                    continue
                sc_cli, sc_scope = key
                label = f"{sc_cli}:{sc_scope}" if sc_cli == "claude" else sc_cli
                newer_labels = ", ".join(
                    f"{new_cli}:{new_scope}" if new_cli == "claude" else new_cli
                    for (new_cli, new_scope), _entry in newer
                )
                print(
                    f"[{label}] cannot revert before newer whole-file layer(s) "
                    f"{newer_labels}; revert those layers first",
                    file=sys.stderr,
                )
                had_error = 1
                blocked = True
        if blocked:
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
            # ``target_path`` is the file the swap actually wrote. A config
            # symlink repointed since then must not redirect recovery into
            # someone else's file; older entries have only ``config_path``.
            dest = pathlib.Path(entry.target_path or entry.config_path)
            if not backup.exists():
                print(f"[{label}] backup missing: {backup}", file=sys.stderr)
                had_error = 1
                break
            if args.dry_run:
                print(f"[{label}] would restore {dest} from {backup}")
                continue
            try:
                atomic_write(dest, backup.read_bytes())
            except OSError as exc:
                print(f"[{label}] restore failed ({exc})", file=sys.stderr)
                had_error = 1
                break

            # Checkpoint each completed layer before consuming its backup.
            # A later LIFO restore may fail, so deferring state cleanup until
            # the whole command finishes would leave a dead state entry that
            # points at an already-deleted backup.
            try:
                clear_state([key])
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                print(
                    f"[{label}] restored config but state checkpoint failed "
                    f"({exc}); backup kept at {backup}",
                    file=sys.stderr,
                )
                had_error = 1
                break
            state.pop(key)

            try:
                backup.unlink()
            except OSError as exc:
                print(
                    f"[{label}] restored from {backup}; backup cleanup failed ({exc})",
                    file=sys.stderr,
                )
                had_error = 1
                continue
            print(f"[{label}] restored from {backup}")

    return had_error


# ---------------------------------------------------------------------------
# doctor — read-only diagnostics
# ---------------------------------------------------------------------------

#: Env vars that, when set, override a CLI's stored subscription/login auth
#: with an API key — a frequent cause of "why is it billing / refusing?"
#: surprises when driving the CLI against a local server. Doctor only reports
#: presence; it never reads the value.
AUTH_ENV_VARS: dict[str, CLIName] = {
    "ANTHROPIC_API_KEY": "claude",
    "OPENAI_API_KEY": "codex",
    "GEMINI_API_KEY": "gemini",
    "GOOGLE_API_KEY": "gemini",
    "XAI_API_KEY": "grok",
    "GROK_API_KEY": "grok",
}


def _env_pair(raw: str) -> tuple[str, str]:
    """Parse a ``KEY=VALUE`` ``--env`` argument, or raise for argparse."""
    key, sep, value = raw.partition("=")
    if not sep or not key:
        msg = f"--env expects KEY=VALUE, got {raw!r}"
        raise argparse.ArgumentTypeError(msg)
    return key, value


def _pr_number(raw: str) -> int:
    """Parse a ``--pr`` argument as a pull-request number, or raise for argparse."""
    try:
        number = int(raw)
    except ValueError:
        msg = f"--pr expects a number, got {raw!r}"
        raise argparse.ArgumentTypeError(msg) from None
    if number < 1:
        msg = f"--pr expects a positive number, got {number}"
        raise argparse.ArgumentTypeError(msg)
    return number


def _config_present_clis() -> list[CLIName]:
    """CLIs whose config file exists — enough to *read* entries (no binary needed).

    Distinct from :func:`present_clis`, which also requires the binary on
    ``PATH``. Doctor and the naming hint only inspect config files, so a CLI
    whose binary is absent but whose config is present still has readable
    entries worth surfacing.
    """
    return [cli for cli in ALL_CLIS if CLIS[cli].config_path.exists()]


def _all_server_specs(
    cli: CLIName, config: t.Any, repo: pathlib.Path
) -> dict[str, McpServerSpec]:
    """Enumerate every MCP server entry visible in a CLI's config.

    Spans the scopes a CLI actually keys servers under: Claude's top-level
    user ``mcpServers`` plus this repo's per-project node, and the single
    ``mcpServers`` / ``mcp_servers`` table for the others. Used to detect the
    server-name footgun — the repo registered under a name other than the
    derived default — which a same-name-only lookup misses.
    """
    out: dict[str, McpServerSpec] = {}

    def _add(raw: t.Any) -> None:
        if not isinstance(raw, dict):
            return
        for name, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            out[str(name)] = _spec_from_entry(entry, fmt=CLIS[cli].fmt)

    if cli == "claude":
        _add(_claude_user_servers(config, create=False))
        node = _claude_project_node(config, repo, create=False)
        if node:
            _add(node.get("mcpServers"))
    elif cli in ("cursor", "gemini", "agy"):
        _add(config.get("mcpServers"))
    else:  # codex, grok
        _add(config.get("mcp_servers"))
    return out


def _repo_pointing_names(cli: CLIName, config: t.Any, repo: pathlib.Path) -> list[str]:
    """Server names in this CLI's config whose local checkout is ``repo``."""
    return sorted(
        name
        for name, spec in _all_server_specs(cli, config, repo).items()
        if spec.is_local_uv_directory() and spec.local_repo_path() == repo
    )


def _naming_hint(repo: pathlib.Path, server: str) -> str | None:
    """Suggest ``--server <name>`` when the repo is registered under another name.

    The derived default (the console-script entry minus ``-mcp``) often
    doesn't match the slug the CLIs were actually registered under (e.g.
    ``tmux`` vs the derived ``libtmux-engine``), so a bare run silently
    operates on a non-existent entry. Returns a one-line hint naming the real
    slug, or ``None`` when the derived name is already the registered one (or
    nothing points here).
    """
    names: set[str] = set()
    server_points = False
    for cli in _config_present_clis():
        try:
            config = load_config(CLIS[cli])
            pointing = _repo_pointing_names(cli, config, repo)
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            continue
        for name in pointing:
            if name == server:
                server_points = True
            else:
                names.add(name)
    if server_points or not names:
        return None
    pick = min(names)
    return (
        f"note: nothing is registered under server {server!r}, but this repo is "
        f"registered as {sorted(names)} — pass --server {pick} to target it"
    )


def _orphaned_backups(config_path: pathlib.Path) -> list[pathlib.Path]:
    """All ``mcp-swap`` backups sitting next to ``config_path`` (any timestamp)."""
    pattern = config_path.name + BACKUP_SUFFIX_PREFIX + "*"
    return sorted(config_path.parent.glob(pattern))


def cmd_doctor(args: argparse.Namespace) -> int:
    """Report the effective MCP-swap environment without changing anything.

    Read-only. Surfaces the footguns that swap/status don't: the repo
    registered under an unexpected server name, un-reverted swaps and orphaned
    backups accumulating on disk, a state entry whose backup has gone missing
    (so revert would fail), and auth-overriding env vars. It deliberately does
    NOT model each CLI's config-merge behaviour — that is CLI-version-specific
    and lives in documentation, not here.
    """
    repo = pathlib.Path(args.repo).resolve()
    server = args.server or resolve_repo_meta(repo)[0]
    print("mcp-swap doctor")
    print(f"  repo:   {repo}")
    print(f"  server: {server}  (derived default; override with --server)")

    print("  entries by CLI:")
    had_error = 0
    all_repo_names: set[str] = set()
    for cli in _config_present_clis():
        try:
            config = load_config(CLIS[cli])
            specs = _all_server_specs(cli, config, repo)
            pointing = _repo_pointing_names(cli, config, repo)
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            print(f"    [{cli}] config unreadable: {exc}")
            had_error = 1
            continue
        spec = specs.get(server)
        if spec is not None:
            print(f"    [{cli}] {server} = {_describe_spec(spec, repo)}")
        all_repo_names.update(pointing)
        for name in pointing:
            if name != server:
                print(f"    [{cli}] {name} = local: this repo  (other name)")
    if not all_repo_names:
        print("    (no CLI currently points at this repo)")

    if all_repo_names and server not in all_repo_names:
        pick = min(all_repo_names)
        print(
            f"  ! server name mismatch: this repo is registered as "
            f"{sorted(all_repo_names)}, not {server!r} — use --server {pick}"
        )

    try:
        state = load_state()
    except (OSError, RuntimeError, TypeError) as exc:
        print(f"  ! recovery state unreadable: {exc}")
        state = {}
        had_error = 1
    if state:
        print("  outstanding swaps (un-reverted):")
        for (cli, scope), entry in sorted(state.items(), key=lambda kv: kv[1].seq_no):
            flag = (
                ""
                if pathlib.Path(entry.backup_path).exists()
                else "  ! BACKUP MISSING — revert would fail for this entry"
            )
            print(f"    {cli}:{scope}  swapped_at={entry.swapped_at}{flag}")

    referenced = {e.backup_path for e in state.values()}
    orphans = [
        b
        for info in CLIS.values()
        for b in _orphaned_backups(info.config_path)
        if str(b) not in referenced
    ]
    if orphans:
        total = sum(b.stat().st_size for b in orphans if b.exists())
        print(
            f"  orphaned backups: {len(orphans)} file(s), {total} bytes not tracked "
            "by state — inspect before deleting: an untracked backup can be the "
            "only surviving pre-swap copy of a config"
        )

    auth_hits = [
        (var, cli) for var, cli in AUTH_ENV_VARS.items() if os.environ.get(var)
    ]
    if auth_hits:
        print("  auth-overriding env vars set:")
        for var, cli in auth_hits:
            print(
                f"    ! {var} overrides {cli}'s stored login — prefix with "
                f"`env -u {var}` to use the subscription/OAuth auth instead"
            )
    return had_error


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

    pu = sub.add_parser(
        "use-local", help="rewrite configs to run this checkout, or a pull request"
    )
    pu.add_argument("--repo", default=".", help="repo root (default: .)")
    pu.add_argument(
        "--pr",
        type=_pr_number,
        metavar="N",
        help=(
            "Point the CLIs at pull request N instead of the working copy. "
            "Writes 'uvx --from git+<remote>@refs/pull/N/head <entry>', so "
            "nothing is checked out and 'revert' needs no cleanup. The ref "
            "lives on the base repo, so fork PRs work unchanged."
        ),
    )
    pu.add_argument(
        "--no-preflight",
        action="store_true",
        help=(
            "Skip the MCP initialize round trip --pr runs before writing. "
            "The probe resolves the ref once so a bad PR fails here instead "
            "of inside every agent; skip it when offline or already warm."
        ),
    )
    pu.add_argument(
        "--server", help="MCP server name (default: derived from pyproject.toml)"
    )
    pu.add_argument(
        "--entry", help="uv run entry command (default: [project.scripts] first key)"
    )
    pu.add_argument(
        "--env",
        action="append",
        type=_env_pair,
        metavar="KEY=VALUE",
        help=(
            "Extra env var to write into the server entry (repeatable). "
            "Layered on top of any preserved existing env; explicit --env wins. "
            "Use to inject e.g. LIBTMUX_SOCKET without a manual post-edit."
        ),
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

    pd = sub.add_parser(
        "doctor", help="report the effective MCP-swap environment (read-only)"
    )
    pd.add_argument("--repo", default=".", help="repo root (default: .)")
    pd.add_argument(
        "--server", help="MCP server name (default: derived from pyproject.toml)"
    )
    pd.set_defaults(func=cmd_doctor)

    return p


def main(argv: list[str] | None = None) -> int:
    """Entry point — dispatches to the selected subcommand."""
    args = build_parser().parse_args(argv)
    return t.cast("int", args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
