---
description: Generate a feature parity report between tmux commands and libtmux wrappers
argument-hint: "[command-name] — audit a specific command, or leave empty for full audit"
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash
  - Agent
---

# Parity Audit

Load the `tmux-parity` skill first to access reference data and domain knowledge.

## Single Command Audit (when $ARGUMENTS specifies a command name)

1. **Read the tmux C source** for the specified command:
   - Read `~/study/c/tmux/cmd-{command}.c` to find the `cmd_entry` struct
   - Extract: name, alias, getopt string, usage, target type, command flags
   - Parse the getopt string to enumerate all flags (boolean vs value-taking)
   - Read the `exec` function to understand behavior and return semantics

2. **Search libtmux source** for the command:
   - Grep `src/libtmux/*.py` for the command string (e.g., `"send-keys"`)
   - For each match, read the surrounding method to understand which flags are exposed as Python parameters
   - Check mixins: `src/libtmux/common.py` (EnvironmentMixin), `src/libtmux/options.py`, `src/libtmux/hooks.py`

3. **Produce a detailed report**:
   - Command name, alias, target type
   - Table of all tmux flags: flag | description (from usage string) | exposed in libtmux? | Python parameter name
   - Missing flags with notes on what they do
   - Recommendations for which missing flags to add

## Full Audit (when no arguments given)

1. **Run extraction scripts** for up-to-date data:
   ```bash
   bash .claude-plugin/scripts/extract-tmux-commands.sh ~/study/c/tmux
   bash .claude-plugin/scripts/extract-libtmux-methods.sh
   ```

2. **Cross-reference the results**:
   - Parse script output to classify each command: Wrapped, Not Wrapped
   - For wrapped commands, compare getopt strings against Python method signatures to find partially-covered commands

3. **Audit format variables** (optional, if specifically requested):
   - Read `~/study/c/tmux/format.c` and search for `format_add` calls to list all format variables
   - Compare against `src/libtmux/formats.py`
   - Report missing format variables

4. **Audit options table** (optional, if specifically requested):
   - Read `~/study/c/tmux/options-table.c` to list all options with their scopes
   - Compare against libtmux options handling
   - Report missing options

5. **Produce the full parity report**:

   ```
   ## tmux/libtmux Parity Report

   ### Summary
   - Commands: X/Y wrapped (Z%)
   - Partially wrapped: N commands (some flags missing)

   ### Coverage by Category
   | Category | Wrapped | Total | % |
   |----------|---------|-------|---|
   | Session mgmt | ... | ... | ... |
   | Window mgmt | ... | ... | ... |
   | Pane mgmt | ... | ... | ... |
   | ...

   ### Not Wrapped — High Priority
   | Command | Alias | Target | Why Important |

   ### Not Wrapped — Medium Priority
   ...

   ### Partially Wrapped (Missing Flags)
   | Command | libtmux Method | Missing Flags |
   ```

Consult `skills/tmux-parity/references/command-mapping.md` for the baseline mapping data. Run the extraction scripts for the most current data.
