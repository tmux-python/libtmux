# Contributing

Thanks for looking. Bug reports with a reproduction, and notes on where
the documentation misled you, are the most useful things right now.

How this project writes prose — README, `CHANGES`, release notes,
commit messages, docstrings, and source comments — is set out
separately in [WRITING.md](WRITING.md). Read that before changing
any of it. The constraints every change is held to, and the map of
what is where, are in [AGENTS.md](../AGENTS.md).

## Getting set up

Install [git] and [uv].

```console
$ git clone https://github.com/tmux-python/libtmux.git
```

```console
$ cd libtmux
```

```console
$ uv sync --all-extras --dev
```

This project uses Python 3.10+, [uv] for dependency management, [ruff]
for linting and formatting, [mypy] for type checking, and [pytest] for
testing (with [pytest-watcher] for continuous runs).

[git]: https://git-scm.com/
[uv]: https://github.com/astral-sh/uv
[ruff]: https://github.com/astral-sh/ruff
[mypy]: https://mypy-lang.org/
[pytest]: https://docs.pytest.org/
[pytest-watcher]: https://github.com/olzhasar/pytest-watcher

## The gates

Format:

```console
$ uv run ruff format .
```

Lint:

```console
$ uv run ruff check . --fix --show-fixes
```

Type-check:

```console
$ uv run mypy
```

Test:

```console
$ uv run pytest
```

Documentation is a gate, not a courtesy. Examples in docstrings,
documentation pages, and `README.md` are executed by `pytest`; the
doctest flags live in `pyproject.toml`, so there is no separate doctest
step and a green `pytest` is the proof. Which blocks qualify, and the
one mistake that silently removes a test, are in
[WRITING.md](WRITING.md#documented-examples-that-run).

Before claiming a test or a gate works, show it failing. A gate that
has never been red is an assumption.

### Code style

Standard library imports are namespace imports —
`import pathlib`, not `from pathlib import Path` — except
`dataclasses`, which may use `from dataclasses import dataclass, field`
for the decorator syntax. Third-party packages may use `from X import
Y` freely. For `typing`, `import typing as t` and access members via
the namespace (`t.NamedTuple`, `t.Optional`, …). Every file starts with
`from __future__ import annotations`; ruff's isort `required-imports`
enforces it.

Docstring conventions, including the NumPy style all public functions
and methods use, are in
[WRITING.md](WRITING.md#docstrings).

## Tests

The suite needs a real `tmux` binary on `PATH` — there is no mock
backend, and `uv run pytest --reruns=2` (set in `addopts`) absorbs the
occasional flake from timing against a live tmux server.

libtmux's own pytest plugin (`src/libtmux/pytest_plugin.py`) is the
source of truth for the fixtures it registers. Two are ready to use
directly:

- `server`: a tmux server on an isolated, uniquely named socket
- `session`: a tmux session on that server

Both are torn down automatically, including killing the tmux daemon and
unlinking its socket file. Derive windows and panes from the `session`
fixture (`session.new_window(...)`, `window.active_pane`) rather than
asking for `window` or `pane` fixtures — those two names exist only in
the `doctest_namespace` documented in
[WRITING.md](WRITING.md#documented-examples-that-run), not as pytest
fixtures.

Write tests as standalone functions, not `class TestFoo:` groupings —
descriptive function names and file organization carry the structure
instead. Prefer the `server` and `session` fixtures over `monkeypatch`
and `MagicMock` when one covers the case; when you do reach for a mock,
say why in the test's docstring. Elsewhere, prefer `tmp_path`
(`pathlib.Path`) over `tempfile`, and `monkeypatch` over
`unittest.mock`.

Run the suite continuously during development:

```console
$ uv run ptw .
```

Include doctests in the watch loop:

```console
$ uv run ptw . --now --doctest-modules
```

## Debugging

Stuck in a debugging loop: pause and acknowledge it rather than trying
another variation of the same fix. Strip the change back to a minimal
reproduction, removing debugging cruft and experimental code, and write
down what you have ruled out so a fresh attempt does not repeat it. If
that writeup itself contains a fenced code block, wrap the whole thing
in four backticks so the nested fence still renders.

## Documentation

Build once:

```console
$ just build-docs
```

Serve with live reload while editing (default: http://localhost:8023):

```console
$ just start-docs
```

`just build-docs` is also how a broken cross-reference or MyST role
surfaces — the doctests do not catch it. Nothing under `docs/_build/`
is hand-edited; it is the build's own output and is not tracked. The
prose voice, cross-reference conventions, and doctest rules for pages
under `docs/` are in [WRITING.md](WRITING.md).

## Releasing

Never create tags. Never push tags. The owner handles tagging and tag
pushes, because a tag triggers the publish workflow. See
[Release commits](WRITING.md#release-commits).

libtmux is pre-1.0: a minor version bump may include breaking API
changes, so downstream projects should pin `>=0.x,<0.y`.

1. Add the release's entries to `CHANGES`, following
   [The changelog](WRITING.md#the-changelog).
2. Bump the version in both `pyproject.toml` and
   `src/libtmux/__about__.py` — neither is derived from the other.
3. Commit as `Tag v<version>` (see
   [Release commits](WRITING.md#release-commits)).
4. The owner tags (`git tag v<version>`) and pushes the tag. CI then
   builds and publishes to PyPI via OIDC trusted publishing —
   there is no manual upload step.

## Pull requests

One subject per pull request. Unrelated cleanup found along the way
belongs in its own commit, and usually in its own pull request.

Discuss a substantial change via an issue before making it.

Update the docs when a change touches the public interface.

A pull request merges once it has the sign-off of one other developer.
If you don't have permission to merge it yourself, ask a maintainer to
merge it for you.

Commit format is in [WRITING.md](WRITING.md#commits).

## Decorum

- Participants will be tolerant of opposing views.
- Participants must ensure that their language and actions are free of
  personal attacks and disparaging personal remarks.
- When interpreting the words and actions of others, participants
  should always assume good intentions.
- Behaviour which can be reasonably considered harassment will not be
  tolerated.

Based on [Ruby's Community Conduct Guideline](https://www.ruby-lang.org/en/conduct/).

## Security

Please do not open a public issue for a vulnerability. Report it
privately via
[GitHub Security Advisories](https://github.com/tmux-python/libtmux/security/advisories/new).
