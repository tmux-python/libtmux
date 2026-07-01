---
description: Compare tmux features across versions using source worktrees
argument-hint: "<version1> <version2> [command-name] — e.g., '3.0 3.6a' or '3.0 3.6a send-keys'"
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash
---

# Version Diff

Compare tmux features between two versions using the source worktrees at `~/study/c/tmux-{version}/`.

## Parse Arguments

Extract `version1`, `version2`, and optional `command-name` from `$ARGUMENTS`.

If no arguments provided, list available versions:

```console
$ ls -d ~/study/c/tmux-*/ | sed 's|.*/tmux-||;s|/$||' | sort -V
```

Then ask the user which two versions to compare.

## Validate Worktrees

Verify both worktrees exist:

```console
$ ls -d ~/study/c/tmux-{version1}/ ~/study/c/tmux-{version2}/ 2>/dev/null
```

## Single Command Comparison (when command-name given)

1. Check if the command file exists in both versions:
   ```bash
   ls ~/study/c/tmux-{v1}/cmd-{command}.c ~/study/c/tmux-{v2}/cmd-{command}.c 2>/dev/null
   ```
   If missing in v1, the command was introduced between v1 and v2.

2. Read both `cmd_entry` structs and compare:
   - Name/alias changes
   - Getopt string differences (new flags, removed flags)
   - Usage string changes
   - Target type changes
   - Flag changes

3. Diff the exec function to identify behavioral changes:
   ```bash
   diff ~/study/c/tmux-{v1}/cmd-{command}.c ~/study/c/tmux-{v2}/cmd-{command}.c
   ```

4. Report:
   ```
   ## send-keys: v3.0 → v3.6a

   ### Flag Changes
   | Flag | v3.0 | v3.6a | Notes |
   | -K   | No   | Yes   | Added: ... |

   ### Behavioral Changes
   - [description of exec function changes]
   ```

## Broad Version Comparison (no command filter)

1. **List cmd-*.c files in each version**:
   ```bash
   ls ~/study/c/tmux-{v1}/cmd-*.c | xargs -n1 basename | sort > /tmp/tmux-v1-cmds.txt
   ls ~/study/c/tmux-{v2}/cmd-*.c | xargs -n1 basename | sort > /tmp/tmux-v2-cmds.txt
   ```

2. **Identify new and removed command files**:
   ```bash
   comm -23 /tmp/tmux-v2-cmds.txt /tmp/tmux-v1-cmds.txt  # New in v2
   comm -23 /tmp/tmux-v1-cmds.txt /tmp/tmux-v2-cmds.txt  # Removed in v2
   ```

3. **For shared commands, compare getopt strings**:
   Run `.claude-plugin/scripts/extract-tmux-commands.sh` on both versions and diff the output.

4. **Compare options-table.c** (if it exists in both versions):
   ```bash
   diff ~/study/c/tmux-{v1}/options-table.c ~/study/c/tmux-{v2}/options-table.c
   ```

5. **Report**:
   ```
   ## tmux Version Diff: v{v1} → v{v2}

   ### New Commands
   | Command | Alias | Getopt | Target |

   ### Removed Commands
   ...

   ### Modified Commands (Flag Changes)
   | Command | Added Flags | Removed Flags |

   ### New Options
   | Option | Scope | Type | Default |

   ### Impact on libtmux
   - Commands libtmux wraps that changed: [list]
   - New commands worth wrapping: [recommendations]
   - Minimum version implications: [notes]
   ```
