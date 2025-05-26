# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

libtmux is a typed Python library providing an object-oriented wrapper for tmux. It enables programmatic control of tmux servers, sessions, windows, and panes through a hierarchical API: Server → Sessions → Windows → Panes.

## Development Commands

### Setup
```bash
# Install dependencies using uv (modern Python package manager)
uv sync --all-extras --dev
```

### Testing
```bash
# Run all tests
uv run pytest
# or
make test

# Run specific test file
uv run pytest tests/test_server.py

# Run specific test
uv run pytest tests/test_server.py::test_server_cmd

# Run with verbose output
uv run pytest -v

# Run doctests
uv run pytest --doctest-modules src/
```

### Code Quality
```bash
# Run linting
uv run ruff check .
# or
make ruff

# Format code
uv run ruff format .
# or
make ruff_format

# Type checking
uv run mypy .
# or
make mypy

# Run all checks
make watch_ruff  # Watches for changes
```

### Documentation
```bash
# Build and serve docs locally
make start_docs

# Build docs only
cd docs && make html
```

## Architecture

### Core Classes (src/libtmux/)
- **Server** (`server.py`): Represents tmux server, manages sessions
- **Session** (`session.py`): Manages windows within a session
- **Window** (`window.py`): Manages panes within a window
- **Pane** (`pane.py`): Individual terminal pane

### Key Modules
- **common.py**: Base classes, command execution (`tmux_cmd`, `AsyncTmuxCmd`)
- **exc.py**: Custom exceptions (e.g., `LibTmuxException`, `TmuxCommandNotFound`)
- **formats.py**: Format handling for tmux output
- **constants.py**: Tmux version constants and feature flags

### Command Execution Pattern
All tmux objects inherit from `TmuxCommonObject` which provides:
- `.cmd()` - Synchronous tmux command execution
- `.acmd()` - Asynchronous tmux command execution (new feature on asyncio branch)

Example:
```python
server.cmd('list-sessions', '-F', '#{session_name}')
await server.acmd('list-sessions', '-F', '#{session_name}')
```

### Testing Approach
- Tests require tmux to be installed
- Use pytest fixtures from `conftest.py` (e.g., `server`, `session`)
- Test helpers in `libtmux.test.*` for creating temporary sessions/windows
- Legacy API tests kept separate in `tests/legacy_api/`

### Current Development Focus
Currently on `asyncio` branch implementing async support:
- `AsyncTmuxCmd` class for async subprocess execution
- `.acmd()` methods added to all tmux objects
- Basic async tests in `test_async.py`

## Important Notes
- Supports tmux 1.8+ and Python 3.9+
- Uses numpy docstring convention
- Strict typing with mypy
- All new features should include tests and type hints
- Format strings use tmux's format syntax (e.g., `#{session_name}`)