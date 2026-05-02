# Navigating tmux C Source

## Command Table (cmd.c)

File: `~/study/c/tmux/cmd.c`

The `cmd_table[]` array lists all registered commands as `extern const struct cmd_entry` references. Each entry is defined in the corresponding `cmd-*.c` file.

Some cmd-*.c files define multiple commands:
- `cmd-send-keys.c`: `send-keys` + `send-prefix`
- `cmd-new-session.c`: `new-session` + `has-session`
- `cmd-capture-pane.c`: `capture-pane` + `clear-history`
- `cmd-choose-tree.c`: `choose-tree` + `choose-client` + `choose-buffer` + `customize-mode`
- `cmd-copy-mode.c`: `copy-mode` + `clock-mode`
- `cmd-detach-client.c`: `detach-client` + `suspend-client`
- `cmd-display-menu.c`: `display-menu` + `display-popup`
- `cmd-set-option.c`: `set-option` + `set-window-option`
- `cmd-show-options.c`: `show-options` + `show-window-options`

## cmd_entry Struct Fields

| Field | Type | Description |
|-------|------|-------------|
| `.name` | `const char *` | Full command name (e.g., `"new-session"`) |
| `.alias` | `const char *` | Short alias (e.g., `"new"`) or `NULL` |
| `.args` | `struct args_parse` | `{ getopt_string, min_args, max_args, NULL }` |
| `.usage` | `const char *` | Human-readable usage string |
| `.target` | `struct cmd_find_target` | `{ flag_char, CMD_FIND_TYPE, flags }` |
| `.flags` | `int` | Behavior flags (bitfield) |
| `.exec` | `enum cmd_retval (*)(struct cmd *, struct cmdq_item *)` | Implementation |

## Getopt String Format

The first element of `.args` is a `getopt(3)` option string:
- Single char = boolean flag: `d` means `-d` is a boolean toggle
- Char followed by `:` = flag with argument: `t:` means `-t <value>`
- Example: `"Ac:dDe:EF:f:n:Ps:t:x:Xy:"` means:
  - Boolean: `-A`, `-d`, `-D`, `-E`, `-P`, `-X`
  - With value: `-c val`, `-e val`, `-F val`, `-f val`, `-n val`, `-s val`, `-t val`, `-x val`, `-y val`

## Target Types

| Constant | Meaning | libtmux Class |
|----------|---------|---------------|
| `CMD_FIND_PANE` | Targets a pane (`-t pane_id`) | `Pane` |
| `CMD_FIND_WINDOW` | Targets a window (`-t window_id`) | `Window` |
| `CMD_FIND_SESSION` | Targets a session (`-t session_id`) | `Session` |
| `CMD_FIND_CLIENT` | Targets a client (`-c client`) | (no direct class) |
| (none) | No target required | `Server` |

## Command Flags

| Flag | Meaning |
|------|---------|
| `CMD_STARTSERVER` | Command starts server if not running |
| `CMD_READONLY` | Command doesn't modify state |
| `CMD_AFTERHOOK` | Command triggers after-hooks |
| `CMD_CLIENT_CFLAG` | Uses `-c` for client targeting |
| `CMD_CLIENT_CANFAIL` | Client lookup failure is non-fatal |

## options-table.c

File: `~/study/c/tmux/options-table.c`

Defines all tmux options. Each entry specifies:
- **name**: Option name (e.g., `"status-style"`)
- **type**: `OPTIONS_TABLE_STRING`, `OPTIONS_TABLE_NUMBER`, `OPTIONS_TABLE_FLAG`, etc.
- **scope**: `OPTIONS_TABLE_SERVER`, `OPTIONS_TABLE_SESSION`, `OPTIONS_TABLE_WINDOW`, `OPTIONS_TABLE_PANE`
- **default**: Default value
- **minimum/maximum**: For numeric options

Search pattern: `grep '\.name = "' ~/study/c/tmux/options-table.c`

## format.c

File: `~/study/c/tmux/format.c`

Registers all format variables (`#{variable_name}`) used in `-F` format strings.

Search for registrations: `grep 'format_add\|format_add_cb' ~/study/c/tmux/format.c`

Compare against libtmux: `src/libtmux/formats.py`

## Version Worktrees

41 versions available at `~/study/c/tmux-{version}/`:
- 0.8, 0.9
- 1.0 through 1.9, 1.9a
- 2.0 through 2.9, 2.9a
- 3.0, 3.0a, 3.1 through 3.1c, 3.2, 3.2a, 3.3, 3.3a, 3.4, 3.5, 3.5a, 3.6, 3.6a

To check if a command exists in a version (not-found = added later):

```console
$ ls ~/study/c/tmux-3.0/cmd-display-popup.c 2>/dev/null
```

```console
$ ls ~/study/c/tmux-3.3/cmd-display-popup.c 2>/dev/null
```

To diff a command across versions:

```console
$ diff ~/study/c/tmux-3.0/cmd-send-keys.c ~/study/c/tmux-3.6a/cmd-send-keys.c
```
