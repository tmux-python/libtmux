---
description: Guide implementing a new tmux command wrapper in libtmux
argument-hint: "<tmux-command-name> — e.g., 'break-pane', 'join-pane', 'swap-window'"
allowed-tools:
  - Read
  - Write
  - Edit
  - Grep
  - Glob
  - Bash
  - AskUserQuestion
  - Agent
---

# Implement Command

Guide wrapping a tmux command in libtmux, following project coding standards from CLAUDE.md.

Load the `tmux-parity` skill first for reference data and implementation patterns.

If `$ARGUMENTS` is empty, ask the user which tmux command to wrap. Consult `skills/tmux-parity/references/command-mapping.md` for the "Not Wrapped" list to suggest candidates.

## Phase 1: Analyze the tmux Command

1. Read `~/study/c/tmux/cmd-{command}.c` fully
2. Extract from the `cmd_entry` struct:
   - **name** and **alias**
   - **getopt string** — enumerate all flags, which take values, which are boolean
   - **usage string** — human-readable flag descriptions
   - **target type** — `CMD_FIND_PANE`, `CMD_FIND_WINDOW`, `CMD_FIND_SESSION`, or none
   - **command flags** — `CMD_READONLY`, `CMD_AFTERHOOK`, etc.
3. Read the `exec` function to understand:
   - What arguments it processes
   - What side effects it has (creates objects, modifies state, produces output)
   - What it returns or prints
   - Error conditions

4. Present a summary to the user:
   ```
   ## tmux command: {name} ({alias})
   Target: {pane|window|session|none} → libtmux class: {Pane|Window|Session|Server}
   Flags: {table of flags with descriptions}
   Behavior: {what the command does}
   ```

## Phase 2: Determine libtmux Placement

Map the target type to libtmux class:
| Target | Primary Class | File |
|--------|--------------|------|
| `CMD_FIND_PANE` | `Pane` | `src/libtmux/pane.py` |
| `CMD_FIND_WINDOW` | `Window` | `src/libtmux/window.py` |
| `CMD_FIND_SESSION` | `Session` | `src/libtmux/session.py` |
| none | `Server` | `src/libtmux/server.py` |

Some commands may also get convenience methods on parent classes. Ask the user if they want additional convenience methods.

## Phase 3: Find a Similar Implementation

Search libtmux for a wrapped command with similar characteristics:
- Same target type
- Similar flag pattern (boolean flags, value flags, creates objects, etc.)
- Read that method as a template

Consult `skills/tmux-parity/references/libtmux-patterns.md` for the five implementation patterns.

## Phase 4: Design the Method Signature

Present a proposed method signature to the user before implementing. Include:
- Method name (snake_case, derived from tmux command name)
- Parameters mapped from tmux flags (with Python-friendly names and types)
- Return type
- Which flags to include (not all flags need wrapping — ask user about ambiguous ones)

**This is a good point to ask the user to write the method signature and core logic (5-10 lines).** Present the trade-offs:
- Which flags to expose (all vs. commonly used)?
- Return type (Self vs. new object vs. None)?
- Naming conventions for parameters?

## Phase 5: Implement

Follow CLAUDE.md coding standards strictly:

1. **Imports**: `from __future__ import annotations`, `import typing as t`
2. **Method**: Add to the appropriate class file
3. **Docstring**: NumPy format with Parameters, Returns, Examples sections
4. **Doctests**: Working doctests using `doctest_namespace` fixtures (`server`, `session`, `window`, `pane`)
   - Use `# doctest: +ELLIPSIS` for variable output
   - NEVER use `# doctest: +SKIP`
5. **Logging**: `logger.info("descriptive msg", extra={"tmux_subcommand": "...", ...})`
6. **Error handling**: Check `proc.stderr`, raise `exc.LibTmuxException`

## Phase 6: Create Tests

Add tests in `tests/test_{class}.py` (or a new file if warranted):

1. **Functional tests only** — no test classes
2. **Use fixtures**: `server`, `session`, `window`, `pane` from conftest.py
3. **Test each parameter/flag** combination
4. **Test error cases** if applicable
5. **Use descriptive function names**: `test_{command}_{scenario}`

## Phase 7: Verify

Run the full verification workflow:

```console
$ uv run ruff format .
```

```console
$ uv run ruff check . --fix --show-fixes
```

```console
$ uv run mypy src tests
```

```console
$ uv run pytest tests/test_{class}.py -x -v
```

```console
$ uv run pytest --doctest-modules src/libtmux/{class}.py -v
```

```console
$ uv run pytest
```

All must pass before considering the implementation complete.
