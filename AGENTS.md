# AGENTS.md

libtmux is a typed Python API over [tmux](https://github.com/tmux/tmux):
object-oriented `Server` → `Session` → `Window` → `Pane` wrappers around
tmux's target and formats system. It also ships a pytest plugin that
gives other projects isolated tmux fixtures, and it is the library
[tmuxp](https://github.com/tmux-python/tmuxp) is built on.

Follow the conventions already in the tree, and keep a change scoped to
what was asked for.

## What is here

| Path | What it is |
| ---- | ---------- |
| `src/libtmux/server.py`, `session.py`, `window.py`, `pane.py` | The object hierarchy, one module per level |
| `src/libtmux/common.py` | Shared base classes and command execution |
| `src/libtmux/formats.py` | tmux format-string constants |
| `src/libtmux/neo.py` | Dataclass-based query interface |
| `src/libtmux/options.py`, `hooks.py` | tmux options and hooks abstractions |
| `src/libtmux/pytest_plugin.py` | The pytest plugin; see `src/libtmux/AGENTS.md` |
| `tests/` | Functional tests, one file per module under test |
| `docs/` | Sphinx/MyST site: `topics/` (concepts), `api/` (autodoc), `project/` (contributing, releasing, compatibility) |
| `README.md` | Doctested quickstart — every `>>> ` block is a real test |
| `CHANGES` | The changelog, rendered as a docs page |
| `MIGRATION` | Deprecation and migration notes |
| `conftest.py` | Root fixtures, including `doctest_namespace` seeding |

## Which policy applies

- Documentation, user-facing text, `CHANGES`, release notes, commit
  messages, docstrings, and source comments:
  [.github/WRITING.md](.github/WRITING.md)
- Environment, the gates, tests, documentation builds, releases, and
  pull requests: [.github/CONTRIBUTING.md](.github/CONTRIBUTING.md)

Each of those is the single home for its subject. Where a rule seems to
be stated twice, the file listed above is the one that governs.

## Change discipline

- Make the smallest coherent change that solves the verified problem;
  keep unrelated cleanup out of it.
- Reuse an existing file, helper, API, or test before adding a new one.
- Add a file only for a durable boundary — a distinct responsibility,
  independent reuse, or splitting an oversized module — not for a
  single-use helper or a one-line re-export.
- Keep new APIs private until a caller outside the module needs them.
- Add a test for every user-visible behaviour change, and a `CHANGES`
  entry for every change to the public API, CLI, configuration, or
  output.
- A passing gate is evidence only once it has been shown capable of
  failing. Pair a new test with a deliberate break that proves it bites.

tmux >= 3.2a is the compatibility floor (see `tests.yml`'s build
matrix). `Server.sessions`, `Server.clients`, and
`Server.attached_sessions` return an empty `QueryList` rather than
raising when the underlying tmux list command fails for any reason —
list-shaped accessors are lenient by default; `Server.is_alive()` and
`Server.raise_if_dead()` are the explicit, loud-failure primitives. See
`src/libtmux/AGENTS.md` for the full contract and this package's
logging conventions.

## References

- Documentation: https://libtmux.git-pull.com/
- API Reference: https://libtmux.git-pull.com/api/
- Architecture: https://libtmux.git-pull.com/topics/architecture/
- tmux man page: http://man.openbsd.org/OpenBSD-current/man1/tmux.1
- tmuxp (workspace manager): https://tmuxp.git-pull.com/
