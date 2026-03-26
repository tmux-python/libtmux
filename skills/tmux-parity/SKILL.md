---
name: tmux-parity
description: This skill should be used when analyzing tmux/libtmux feature parity, comparing tmux C source against libtmux Python wrappers, implementing new tmux command wrappers, understanding "what commands are missing", "what does libtmux wrap", reviewing tmux command flags, or comparing tmux versions. Also relevant for queries about "parity", "coverage", "unwrapped commands", "missing features", "tmux source", or "implement command".
version: 0.1.0
---

# tmux/libtmux Feature Parity Analysis

Analyze and close feature parity gaps between the tmux terminal multiplexer (C source) and the libtmux Python wrapper library.

## Key Locations

| Resource | Path |
|----------|------|
| tmux source (HEAD) | `~/study/c/tmux/` |
| tmux version worktrees | `~/study/c/tmux-{0.8..3.6a}/` (41 versions) |
| libtmux source | `src/libtmux/` (relative to project root) |
| libtmux tests | `tests/` |
| Extraction scripts | `.claude-plugin/scripts/extract-tmux-commands.sh`, `.claude-plugin/scripts/extract-libtmux-methods.sh` |

## How tmux Commands Are Structured

Each tmux command is defined in a `cmd-{name}.c` file via a `cmd_entry` struct:

```c
const struct cmd_entry cmd_send_keys_entry = {
    .name = "send-keys",
    .alias = "send",
    .args = { "c:FHKlMN:Rt:X", 0, -1, NULL },  // getopt string
    .usage = "[-FHKlMRX] [-c target-client] ...",
    .target = { 't', CMD_FIND_PANE, 0 },          // target type
    .flags = CMD_AFTERHOOK|CMD_READONLY,
    .exec = cmd_send_keys_exec
};
```

Key fields:
- **`.args` getopt string**: Single char = boolean flag, char + `:` = flag with value
- **`.target`**: `CMD_FIND_PANE`, `CMD_FIND_WINDOW`, `CMD_FIND_SESSION`, `CMD_FIND_CLIENT`, or none
- **Command table**: All entries registered in `~/study/c/tmux/cmd.c` as `cmd_table[]`

## How libtmux Wraps Commands

libtmux methods call tmux via two patterns:

1. **Object method**: `self.cmd("command-name", *args)` — on Server/Session/Window/Pane, auto-adds `-t target`
2. **Standalone**: `tmux_cmd("command-name", *args)` — in mixins (EnvironmentMixin, etc.)

Class hierarchy mapping from tmux target types:
- `CMD_FIND_PANE` → `Pane` class (`src/libtmux/pane.py`)
- `CMD_FIND_WINDOW` → `Window` class (`src/libtmux/window.py`)
- `CMD_FIND_SESSION` → `Session` class (`src/libtmux/session.py`)
- No target / server-level → `Server` class (`src/libtmux/server.py`)
- Environment ops → `EnvironmentMixin` (`src/libtmux/common.py`)
- Option ops → `OptionsMixin` (`src/libtmux/options.py`)
- Hook ops → `HooksMixin` (`src/libtmux/hooks.py`)

## Current Coverage Summary

**~28 of ~88 tmux commands wrapped** (~32% coverage, approximate — run extraction scripts for current data). High-priority unwrapped commands include: `join-pane`, `swap-pane`, `swap-window`, `respawn-pane`, `respawn-window`, `run-shell`, `break-pane`, `move-pane`, `pipe-pane`, `display-popup`.

## Extraction Scripts

Run these for up-to-date data:

```bash
# All tmux commands with flags and target types
bash .claude-plugin/scripts/extract-tmux-commands.sh ~/study/c/tmux

# All tmux commands libtmux currently wraps
bash .claude-plugin/scripts/extract-libtmux-methods.sh
```

## Additional Resources

### Reference Files

For detailed data, consult:
- **`references/command-mapping.md`** — Complete mapping of all ~88 tmux commands to libtmux methods, with flag coverage
- **`references/libtmux-patterns.md`** — Implementation patterns for wrapping new commands (method signatures, doctests, logging, error handling)
- **`references/tmux-command-table.md`** — Guide to navigating tmux C source: cmd_entry fields, getopt format, target types, options-table.c, format.c

### Scripts

- **`.claude-plugin/scripts/extract-tmux-commands.sh`** — Parse all cmd-*.c files → `command|alias|getopt|target`
- **`.claude-plugin/scripts/extract-libtmux-methods.sh`** — Grep libtmux for tmux command invocations
