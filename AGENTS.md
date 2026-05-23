# AGENTS.md

This file provides guidance to AI agents (including Claude Code, Cursor, and other LLM-powered tools) when working with code in this repository.

## CRITICAL REQUIREMENTS

### Test Success
- ALL tests MUST pass for code to be considered complete and working
- Never describe code as "working as expected" if there are ANY failing tests
- Even if specific feature tests pass, failing tests elsewhere indicate broken functionality
- Changes that break existing tests must be fixed before considering implementation complete
- A successful implementation must pass linting, type checking, AND all existing tests

## Project Overview

libtmux is a typed Python library that provides an Object-Relational Mapping (ORM) wrapper for interacting programmatically with [tmux](https://github.com/tmux/tmux), a terminal multiplexer.

Key features:
- Manage tmux servers, sessions, windows, and panes programmatically
- Typed Python API with full type hints
- Built on tmux's target and formats system
- Powers [tmuxp](https://github.com/tmux-python/tmuxp), a tmux workspace manager
- Provides pytest fixtures for testing with tmux

## Development Environment

This project uses:
- Python 3.10+
- [uv](https://github.com/astral-sh/uv) for dependency management
- [ruff](https://github.com/astral-sh/ruff) for linting and formatting
- [mypy](https://github.com/python/mypy) for type checking
- [pytest](https://docs.pytest.org/) for testing
  - [pytest-watcher](https://github.com/olzhasar/pytest-watcher) for continuous testing

## Common Commands

### Setting Up Environment

```bash
# Install dependencies
uv pip install --editable .
uv pip sync

# Install with development dependencies
uv pip install --editable . -G dev
```

### Running Tests

```bash
# Run all tests
just test
# or directly with pytest
uv run pytest

# Run a single test file
uv run pytest tests/test_pane.py

# Run a specific test
uv run pytest tests/test_pane.py::test_send_keys

# Run tests with test watcher
just start
# or
uv run ptw .

# Run tests with doctests
uv run ptw . --now --doctest-modules
```

### Linting and Type Checking

```bash
# Run ruff for linting
just ruff
# or directly
uv run ruff check .

# Format code with ruff
just ruff-format
# or directly
uv run ruff format .

# Run ruff linting with auto-fixes
uv run ruff check . --fix --show-fixes

# Run mypy for type checking
just mypy
# or directly
uv run mypy src tests

# Watch mode for linting (using entr)
just watch-ruff
just watch-mypy
```

### Development Workflow

Follow this workflow for code changes:

1. **Format First**: `uv run ruff format .`
2. **Run Tests**: `uv run pytest`
3. **Run Linting**: `uv run ruff check . --fix --show-fixes`
4. **Check Types**: `uv run mypy`
5. **Verify Tests Again**: `uv run pytest`

### Documentation

```bash
# Build documentation
just build-docs

# Start documentation server with auto-reload
just start-docs

# Update documentation CSS/JS
just design-docs
```

## Code Architecture

libtmux follows an object-oriented design that mirrors tmux's hierarchy:

```
Server (tmux server instance)
  └─ Session (tmux session)
      └─ Window (tmux window)
          └─ Pane (tmux pane)
```

### Core Modules

1. **Server** (`src/libtmux/server.py`)
   - Represents a tmux server instance
   - Manages sessions
   - Executes tmux commands via `tmux()` method
   - Entry point for most libtmux interactions

2. **Session** (`src/libtmux/session.py`)
   - Represents a tmux session
   - Manages windows within the session
   - Provides session-level operations (attach, kill, rename, etc.)

3. **Window** (`src/libtmux/window.py`)
   - Represents a tmux window
   - Manages panes within the window
   - Provides window-level operations (split, rename, move, etc.)

4. **Pane** (`src/libtmux/pane.py`)
   - Represents a tmux pane (terminal instance)
   - Provides pane-level operations (send-keys, capture, resize, etc.)
   - Core unit for command execution and output capture

5. **Common** (`src/libtmux/common.py`)
   - Base classes and shared functionality
   - `TmuxRelationalObject` and `TmuxMappingObject` base classes
   - Format handling and command execution

6. **Formats** (`src/libtmux/formats.py`)
   - Tmux format string constants
   - Used for querying tmux state

7. **Neo** (`src/libtmux/neo.py`)
   - Modern query interface and dataclass-based objects
   - Alternative to traditional ORM-style objects

8. **pytest Plugin** (`src/libtmux/pytest_plugin.py`)
   - Provides fixtures for testing with tmux
   - Creates temporary tmux sessions/windows/panes

## Testing Strategy

libtmux uses pytest for testing with custom fixtures. The pytest plugin (`pytest_plugin.py`) defines fixtures for creating temporary tmux objects for testing. These include:

- `server`: A tmux server instance for testing
- `session`: A tmux session for testing
- `window`: A tmux window for testing
- `pane`: A tmux pane for testing

These fixtures handle setup and teardown automatically, creating isolated test environments.

### Testing Guidelines

1. **Use functional tests only**: Write tests as standalone functions, not classes. Avoid `class TestFoo:` groupings - use descriptive function names and file organization instead.

2. **Use existing fixtures over mocks**
   - Use fixtures from conftest.py instead of `monkeypatch` and `MagicMock` when available
   - For libtmux, use provided fixtures: `server`, `session`, `window`, and `pane`
   - Document in test docstrings why standard fixtures weren't used for exceptional cases

3. **Preferred pytest patterns**
   - Use `tmp_path` (pathlib.Path) fixture over Python's `tempfile`
   - Use `monkeypatch` fixture over `unittest.mock`

4. **Running tests continuously**
   - Use pytest-watcher during development: `uv run ptw .`
   - For doctests: `uv run ptw . --now --doctest-modules`

### Example Fixture Usage

```python
def test_window_rename(window):
    """Test renaming a window."""
    # window is already a Window instance with a live tmux window
    window.rename_window('new_name')
    assert window.window_name == 'new_name'
```

## Coding Standards

Key highlights:

### Imports

- **Use namespace imports for standard library modules**: `import enum` instead of `from enum import Enum`
  - **Exception**: `dataclasses` module may use `from dataclasses import dataclass, field` for cleaner decorator syntax
  - This rule applies to Python standard library only; third-party packages may use `from X import Y`
- **For typing**, use `import typing as t` and access via namespace: `t.NamedTuple`, etc.
- **Use `from __future__ import annotations`** at the top of all Python files

### Docstrings

Follow NumPy docstring style for all functions and methods:

```python
"""Short description of the function or class.

Detailed description using reStructuredText format.

Parameters
----------
param1 : type
    Description of param1
param2 : type
    Description of param2

Returns
-------
type
    Description of return value
"""
```

### Doctests

**All functions and methods MUST have working doctests.** Doctests serve as both documentation and tests.

**CRITICAL RULES:**
- Doctests MUST actually execute - never comment out function calls or similar
- Doctests MUST NOT be converted to `.. code-block::` as a workaround (code-blocks don't run)
- If you cannot create a working doctest, **STOP and ask for help**

**Available tools for doctests:**
- `doctest_namespace` fixtures: `server`, `session`, `window`, `pane`, `Server`, `Session`, `Window`, `Pane`, `request`
- Ellipsis for variable output: `# doctest: +ELLIPSIS`
- Update `conftest.py` to add new fixtures to `doctest_namespace`

**`# doctest: +SKIP` is NOT permitted** - it's just another workaround that doesn't test anything. Use the fixtures properly - tmux is required to run tests anyway.

**Using fixtures in doctests:**
```python
>>> server.new_session(session_name='my_session')  # server from doctest_namespace
Session($... my_session)
>>> session.new_window(window_name='my_window')  # session from doctest_namespace
Window(@... ...:my_window, Session($... ...))
>>> pane.send_keys('echo hello')  # pane from doctest_namespace
>>> pane.capture_pane()  # doctest: +ELLIPSIS
[...'echo hello'...]
```

**When output varies, use ellipsis:**
```python
>>> window.window_id  # doctest: +ELLIPSIS
'@...'
>>> session.session_id  # doctest: +ELLIPSIS
'$...'
```

**Additional guidelines:**
1. **Use narrative descriptions** for test sections rather than inline comments
2. **Move complex examples** to dedicated test files at `tests/examples/<path_to_module>/test_<example>.py`
3. **Keep doctests simple and focused** on demonstrating usage
4. **Add blank lines between test sections** for improved readability

### Logging Standards

These rules guide future logging changes; existing code may not yet conform.

#### Logger setup

- Use `logging.getLogger(__name__)` in every module
- Add `NullHandler` in library `__init__.py` files
- Never configure handlers, levels, or formatters in library code — that's the application's job

#### Structured context via `extra`

Pass structured data on every log call where useful for filtering, searching, or test assertions.

**Core keys** (stable, scalar, safe at any log level):

| Key | Type | Context |
|-----|------|---------|
| `tmux_cmd` | `str` | tmux command line |
| `tmux_subcommand` | `str` | tmux subcommand (e.g. `new-session`) |
| `tmux_target` | `str` | tmux target specifier (e.g. `mysession:1.2`) |
| `tmux_exit_code` | `int` | tmux process exit code |
| `tmux_session` | `str` | session name |
| `tmux_window` | `str` | window name or index |
| `tmux_pane` | `str` | pane identifier |
| `tmux_option_key` | `str` | tmux option name |

**Heavy/optional keys** (DEBUG only, potentially large):

| Key | Type | Context |
|-----|------|---------|
| `tmux_stdout` | `list[str]` | tmux stdout lines (truncate or cap; `%(tmux_stdout)s` produces repr) |
| `tmux_stderr` | `list[str]` | tmux stderr lines (same caveats) |
| `tmux_stdout_len` | `int` | number of stdout lines |
| `tmux_stderr_len` | `int` | number of stderr lines |

Treat established keys as compatibility-sensitive — downstream users may build dashboards and alerts on them. Change deliberately.

#### Key naming rules

- `snake_case`, not dotted; `tmux_` prefix
- Prefer stable scalars; avoid ad-hoc objects
- Heavy keys (`tmux_stdout`, `tmux_stderr`) are DEBUG-only; consider companion `tmux_stdout_len` fields or hard truncation (e.g. `stdout[:100]`)

#### Lazy formatting

`logger.debug("msg %s", val)` not f-strings. Two rationales:
- Deferred string interpolation: skipped entirely when level is filtered
- Aggregator message template grouping: `"Running %s"` is one signature grouped ×10,000; f-strings make each line unique

When computing `val` itself is expensive, guard with `if logger.isEnabledFor(logging.DEBUG)`.

#### stacklevel for wrappers

Increment for each wrapper layer so `%(filename)s:%(lineno)d` and OTel `code.filepath` point to the real caller. Verify whenever call depth changes.

#### LoggerAdapter for persistent context

For objects with stable identity (Session, Window, Pane), use `LoggerAdapter` to avoid repeating the same `extra` on every call. Lead with the portable pattern (override `process()` to merge); `merge_extra=True` simplifies this on Python 3.13+.

#### Log levels

| Level | Use for | Examples |
|-------|---------|----------|
| `DEBUG` | Internal mechanics, tmux I/O | tmux command + stdout, format queries |
| `INFO` | Object lifecycle, user-visible operations | Session created, window added |
| `WARNING` | Recoverable issues, deprecation | Deprecated method, missing optional program |
| `ERROR` | Failures that stop an operation | tmux command failed, invalid target |

#### Message style

- Lowercase, past tense for events: `"session created"`, `"tmux command failed"`
- No trailing punctuation
- Keep messages short; put details in `extra`, not the message string

#### Exception logging

- Use `logger.exception()` only inside `except` blocks when you are **not** re-raising
- Use `logger.error(..., exc_info=True)` when you need the traceback outside an `except` block
- Avoid `logger.exception()` followed by `raise` — this duplicates the traceback. Either add context via `extra` that would otherwise be lost, or let the exception propagate

#### Testing logs

Assert on `caplog.records` attributes, not string matching on `caplog.text`:
- Scope capture: `caplog.at_level(logging.DEBUG, logger="libtmux.common")`
- Filter records rather than index by position: `[r for r in caplog.records if hasattr(r, "tmux_cmd")]`
- Assert on schema: `record.tmux_exit_code == 0` not `"exit code 0" in caplog.text`
- `caplog.record_tuples` cannot access extra fields — always use `caplog.records`

#### Avoid

- f-strings/`.format()` in log calls
- Unguarded logging in hot loops (guard with `isEnabledFor()`)
- Catch-log-reraise without adding new context
- `print()` for diagnostics
- Logging secret env var values (log key names only)
- Non-scalar ad-hoc objects in `extra`
- Requiring custom `extra` fields in format strings without safe defaults (missing keys raise `KeyError`)

### Git Commit Standards

Format commit messages as:
```
Scope(type[detail]): concise description

why: Explanation of necessity or impact.
what:
- Specific technical changes made
- Focused on a single topic
```

Common commit types:
- **feat**: New features or enhancements
- **fix**: Bug fixes
- **refactor**: Code restructuring without functional change
- **docs**: Documentation updates
- **chore**: Maintenance (dependencies, tooling, config)
- **test**: Test-related updates
- **style**: Code style and formatting
- **py(deps)**: Dependencies
- **py(deps[dev])**: Dev Dependencies
- **ai(rules[AGENTS])**: AI rule updates
- **ai(claude[rules])**: Claude Code rules (CLAUDE.md)
- **ai(claude[command])**: Claude Code command changes

Example:
```
Pane(feat[send_keys]): Add support for literal flag

why: Enable sending literal characters without tmux interpretation
what:
- Add literal parameter to send_keys method
- Update send_keys to pass -l flag when literal=True
- Add tests for literal key sending
```
#### Release commits

Never create tags. Never push tags. The user handles tagging and tag
pushes (tags trigger the CI publish workflow).

Release commit subjects are plain and short: `Tag v<version>`. Put
the detailed why/what in the commit body. Don't use the
`Scope(type[detail]):` format for releases — don't bury the lede.

For multi-line commits, use heredoc to preserve formatting:
```bash
git commit -m "$(cat <<'EOF'
feat(Component[method]) add feature description

why: Explanation of the change.
what:
- First change
- Second change
EOF
)"
```

## Documentation Standards

### Code Blocks in Documentation

When writing documentation (README, CHANGES, docs/), follow these rules for code blocks:

**One command per code block.** This makes commands individually copyable. For sequential commands, either use separate code blocks or chain them with `&&` or `;` and `\` continuations (keeping it one logical command).

**Put explanations outside the code block**, not as comments inside.

Good:

Run the tests:

```console
$ uv run pytest
```

Run with coverage:

```console
$ uv run pytest --cov
```

Bad:

```console
# Run the tests
$ uv run pytest

# Run with coverage
$ uv run pytest --cov
```

### Shell Command Formatting

These rules apply to shell commands in documentation (README, CHANGES, docs/), **not** to Python doctests.

**Use `console` language tag with `$ ` prefix.** This distinguishes interactive commands from scripts and enables prompt-aware copy in many terminals.

Good:

```console
$ uv run pytest
```

Bad:

```bash
uv run pytest
```

**Split long commands with `\` for readability.** Each flag or flag+value pair gets its own continuation line, indented. Positional parameters go on the final line.

Good:

```console
$ pipx install \
    --suffix=@next \
    --pip-args '\--pre' \
    --force \
    'libtmux'
```

Bad:

```console
$ pipx install --suffix=@next --pip-args '\--pre' --force 'libtmux'
```

### Changelog Conventions

These rules apply when authoring entries in `CHANGES`, which is rendered as the Sphinx changelog page. Modeled on Django's release-notes shape — deliverables get titles and prose, not bullets.

**Release entry boilerplate.** Every release header is `## libtmux X.Y.Z (YYYY-MM-DD)`. The file opens with a `## libtmux X.Y.Z (Yet to be released)` placeholder block fenced by `<!-- KEEP THIS PLACEHOLDER ... -->` and `<!-- END PLACEHOLDER ... -->` HTML comments — new release entries land immediately below the END marker, never above it.

**Open with a multi-sentence lead paragraph.** Plain prose, no italic. Open with the version as sentence subject (*"libtmux X.Y.Z ships …"*) so the lead is self-contained when excerpted. Two to four sentences telling the reader what shipped and who cares — user-visible takeaways, not internal mechanism. Cross-reference detail docs with `{ref}` to keep the lead compact.

**Each deliverable is a section, not a bullet.** Inside `### What's new`, every distinct deliverable gets a `#### Deliverable title (#NN)` heading naming it in user vocabulary, followed by 1-3 prose paragraphs explaining what shipped. Don't wrap a paragraph in `- ` — bullets are for enumerable lists, not paragraph containers. Cross-link detail docs (`See {ref}\`foo\` for details.`) so prose stays focused.

**The deliverable test.** Before writing an entry, ask: "What's the deliverable, in user vocabulary?" If you can't answer in one sentence, the entry isn't ready. Mechanism (helper internals, byte counters, schema-validation locations) belongs in PR descriptions and code comments, not the changelog.

**Fixed subheadings**, in this order when present: `### Breaking changes`, `### Dependencies`, `### What's new`, `### Fixes`, `### Documentation`, `### Development`. Dev tooling (helper scripts, internal automation) lives under `### Development`. For breaking changes, show the migration path with concrete inline code (e.g. a `# Before` / `# After` fenced code block). Dependency floor bumps use the form ``Minimum `pkg>=X.Y.Z` (was `>=X.Y.W`)``.

**PR refs `(#NN)`** sit in each deliverable's `####` heading.

**When bullets are appropriate.** Catch-all sections (`### Fixes`, occasionally `### Documentation`) with 3+ genuinely small items use bullets — one line each, never paragraphs. If a bullet swells past two lines, promote it to a `#### Title (#NN)` heading with prose body.

**Anti-patterns.**

- Fragile metrics: token ceilings, third-party version pins, percent benchmarks, exact byte counts. Describe the *capability*, not the math.
- Internal jargon: private symbols (leading-underscore identifiers), algorithm names exposed for the first time, backend scaffolding.
- Walls of text dressed up as bullets.
- Buried breaking changes — they get their own subheading at the top of the entry.

**Always link autodoc'd APIs.** Any class, method, function, exception, or attribute that has its own rendered page must be cited via the appropriate role (`{class}`, `{meth}`, `{func}`, `{exc}`, `{attr}`) — never with plain backticks. Doc pages without explicit ref labels use `{doc}`. Plain backticks are correct for code syntax, env vars, parameter names, and file paths that aren't doc pages — anything without an autodoc destination.

**MyST roles.** Class references use `{class}` (e.g. `{class}\`~libtmux.Pane\``), methods use `{meth}`, functions use `{func}`, exceptions use `{exc}`, attributes use `{attr}`, internal anchors use `{ref}`, doc-path links use `{doc}`.

**Summarization style.** When a user asks "what changed in the latest version?" or similar, lead with the entry's lead paragraph (paraphrased if needed), followed by each `####` deliverable heading under `### What's new` with a one-sentence summary. Cite `(#NN)` only if the user asks for source links. Don't invent versions, dates, or numbers not present in `CHANGES`. Don't quote line numbers or file offsets — those shift as the file evolves.

## Debugging Tips

When stuck in debugging loops:

1. **Pause and acknowledge the loop**
2. **Minimize to MVP**: Remove all debugging cruft and experimental code
3. **Document the issue** comprehensively for a fresh approach
4. **Format for portability** (using quadruple backticks)

## tmux-Specific Considerations

### tmux Command Execution

- All tmux commands go through the `cmd()` method on Server/Session/Window/Pane objects
- Commands return a `CommandResult` object with `stdout` and `stderr`
- Use tmux format strings to query object state (see `formats.py`)

### Format Strings

libtmux uses tmux's format system extensively:
- Defined in `src/libtmux/formats.py`
- Used to query session_id, window_id, pane_id, etc.
- Format: `#{format_name}` (e.g., `#{session_id}`, `#{window_name}`)

### Object Refresh

- Objects can become stale if tmux state changes externally
- Use refresh methods (e.g., `session.refresh()`) to update object state
- Alternative: use `neo.py` query interface for fresh data

### List-returning accessors: empty by default on tmux errors

`Server.sessions`, `Server.clients`, and `Server.attached_sessions`
return an empty `QueryList` when tmux's underlying list command fails
for any reason — no running daemon, a missing socket, a permission
error, a subprocess crash. This is a deliberate API contract:
list-shaped accessors are lenient by default. Callers that need to
distinguish "no rows" from "tmux unreachable" use the explicit
`Server.is_alive()` or `Server.raise_if_dead()` primitives.

When adding a new list-returning accessor, follow this convention. If
a future feature genuinely benefits from loud-failure semantics, expose
it as a scoped opt-in (e.g. a `Server.raise_server_errors()` context
manager) rather than changing the default contract of an existing
accessor or hard-coding raise-on-tmux-error into a new one.
Empty-on-tmux-error stays the default; raise is opt-in.

## References

- Documentation: https://libtmux.git-pull.com/
- API Reference: https://libtmux.git-pull.com/api/
- Architecture: https://libtmux.git-pull.com/topics/architecture/
- tmux man page: http://man.openbsd.org/OpenBSD-current/man1/tmux.1
- tmuxp (workspace manager): https://tmuxp.git-pull.com/

## Shipped vs. Branch-Internal Narrative

Long-running branches accumulate tactical decisions — renames,
refactors, attempts-then-reverts, intermediate states. Commit messages
and the diff hold *what changed* and *why*. Do not restate either in
artifacts the downstream reader holds: code, docstrings, README,
CHANGES, PR descriptions, release notes, migration guides.

When deciding what counts as branch-internal, use trunk or the parent
branch as the baseline — not intermediate states inside the current
branch.

**The Published-Release Test**

Before adding rename history, "previously" / "formerly" / "no longer
X" phrasing, "removed" / "moved" / "refactored" / "fixed" diff
paraphrases, or `### Fixes` entries to a user-facing surface, ask:

> Did users of the most recently published release ever experience
> this old name, old behavior, or bug?

If the answer is no, it is branch-internal narrative. Move it to the
commit message and describe only the current state in the artifact.

**Keep in shipped artifacts**

- Deprecations and migration guides for symbols that actually shipped.
- `### Fixes` entries for bugs that affected users of a published
  release.
- Comments explaining *why the current code looks this way* —
  invariants, platform quirks, upstream bug workarounds — that make
  sense to a reader who never saw the previous version.

**Default**: when in doubt, keep the artifact clean and put the story
in the commit.

### Cleanup in Hindsight

When applying this rule retroactively from inside a feature branch,
first establish scope by diffing against the parent branch (or trunk)
to identify which commits this branch actually introduced. Then:

- **Commits introduced in this branch** — prompt the user with two
  options: `fixup!` commits with `git rebase --autosquash` to address
  each causal commit at its source, or a single cleanup commit at
  branch tip. User chooses.
- **Commits already in trunk or a parent branch** — default to
  leaving them alone. Do not raise them as cleanup candidates; act
  only on explicit user instruction. If the user opts in, fold the
  cleanup into a single commit at branch tip and do not rewrite trunk
  or parent-branch history.
- **Scope guard** — if cleaning in-branch bleed would touch a
  colleague's in-flight work or expand the branch beyond its stated
  goal, default to staying in lane: protect the project's current
  goal, leave prior bleed alone, and don't introduce new bleed in the
  current change.
