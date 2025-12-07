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
make test
# or directly with pytest
uv run pytest

# Run a single test file
uv run pytest tests/test_pane.py

# Run a specific test
uv run pytest tests/test_pane.py::test_send_keys

# Run tests with test watcher
make start
# or
uv run ptw .

# Run tests with doctests
uv run ptw . --now --doctest-modules
```

### Linting and Type Checking

```bash
# Run ruff for linting
make ruff
# or directly
uv run ruff check .

# Format code with ruff
make ruff_format
# or directly
uv run ruff format .

# Run ruff linting with auto-fixes
uv run ruff check . --fix --show-fixes

# Run mypy for type checking
make mypy
# or directly
uv run mypy src tests

# Watch mode for linting (using entr)
make watch_ruff
make watch_mypy
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
make build_docs

# Start documentation server with auto-reload
make start_docs

# Update documentation CSS/JS
make design_docs
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

1. **Use existing fixtures over mocks**
   - Use fixtures from conftest.py instead of `monkeypatch` and `MagicMock` when available
   - For libtmux, use provided fixtures: `server`, `session`, `window`, and `pane`
   - Document in test docstrings why standard fixtures weren't used for exceptional cases

2. **Preferred pytest patterns**
   - Use `tmp_path` (pathlib.Path) fixture over Python's `tempfile`
   - Use `monkeypatch` fixture over `unittest.mock`

3. **Running tests continuously**
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

### Doctest Guidelines

1. **Use narrative descriptions** for test sections rather than inline comments
2. **Move complex examples** to dedicated test files at `tests/examples/<path_to_module>/test_<example>.py`
3. **Keep doctests simple and focused** on demonstrating usage
4. **Add blank lines between test sections** for improved readability

### Git Commit Standards

Format commit messages as:
```
Component/File(commit-type[Subcomponent/method]): Concise description

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
- **ai(rules[LLM type])**: AI Rule Updates

Example:
```
Pane(feat[send_keys]): Add support for literal flag

why: Enable sending literal characters without tmux interpretation
what:
- Add literal parameter to send_keys method
- Update send_keys to pass -l flag when literal=True
- Add tests for literal key sending
```

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

## References

- Documentation: https://libtmux.git-pull.com/
- API Reference: https://libtmux.git-pull.com/api.html
- Architecture: https://libtmux.git-pull.com/about.html
- tmux man page: http://man.openbsd.org/OpenBSD-current/man1/tmux.1
- tmuxp (workspace manager): https://tmuxp.git-pull.com/
