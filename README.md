<div align="center">
  <h1>⚙️ libtmux</h1>
  <p><strong>Drive tmux from Python: typed, object-oriented control over servers, sessions, windows, and panes.</strong></p>
  <p>
    <a href="https://libtmux.git-pull.com/"><img src="https://raw.githubusercontent.com/tmux-python/libtmux/master/docs/_static/img/libtmux.svg" alt="libtmux logo" height="120"></a>
  </p>
  <p>
    <a href="https://pypi.org/project/libtmux/"><img src="https://img.shields.io/pypi/v/libtmux.svg" alt="PyPI version"></a>
    <a href="https://libtmux.git-pull.com/"><img src="https://github.com/tmux-python/libtmux/workflows/docs/badge.svg" alt="Docs status"></a>
    <a href="https://github.com/tmux-python/libtmux/actions"><img src="https://github.com/tmux-python/libtmux/workflows/tests/badge.svg" alt="Tests status"></a>
    <a href="https://codecov.io/gh/tmux-python/libtmux"><img src="https://codecov.io/gh/tmux-python/libtmux/branch/master/graph/badge.svg" alt="Coverage"></a>
    <a href="https://github.com/tmux-python/libtmux/blob/master/LICENSE"><img src="https://img.shields.io/github/license/tmux-python/libtmux.svg" alt="License"></a>
  </p>
</div>

## 🐍 What is libtmux?

libtmux is a typed Python API over [tmux], the terminal multiplexer. Stop shelling out and parsing `tmux ls`. Instead, interact with real Python objects: `Server`, `Session`, `Window`, and `Pane`. The same API powers [tmuxp], so it stays battle-tested in real-world workflows.

### ✨ Features

- Typed, object-oriented control of tmux state
- Query and [traverse](https://libtmux.git-pull.com/topics/traversal.html) live sessions, windows, and panes
- Raw escape hatch via `.cmd(...)` on any object
- Works with multiple tmux sockets and servers
- [Context managers](https://libtmux.git-pull.com/topics/context_managers.html) for automatic cleanup
- [pytest plugin](https://libtmux.git-pull.com/pytest-plugin/index.html) for isolated tmux fixtures
- Proven in production via tmuxp and other tooling

## Requirements & support

- tmux: >= 3.2a
- Python: >= 3.10 (CPython and PyPy)

Maintenance-only backports (no new fixes):

- Python 2.x: [`v0.8.x`](https://github.com/tmux-python/libtmux/tree/v0.8.x)
- tmux 1.8-3.1c: [`v0.48.x`](https://github.com/tmux-python/libtmux/tree/v0.48.x)

## 📦 Installation

Stable release:

```bash
pip install libtmux
```

With pipx:

```bash
pipx install libtmux
```

With uv / uvx:

```bash
uv add libtmux
uvx --from "libtmux" python
```

From the main branch (bleeding edge):

```bash
pip install 'git+https://github.com/tmux-python/libtmux.git'
```

Tip: libtmux is pre-1.0. Pin a range in projects to avoid surprises:

requirements.txt:

```ini
libtmux==0.50.*
```

pyproject.toml:

```toml
libtmux = "0.50.*"
```

## 🚀 Quickstart

### Open a tmux session

First, start a tmux session to connect to:

```console
$ tmux new-session -s foo -n bar
```

### Pilot your tmux session via Python

Use [ptpython], [ipython], etc. for a nice REPL with autocompletions:

```console
$ pip install --user ptpython
$ ptpython
```

Connect to a live tmux session:

```python
>>> import libtmux
>>> svr = libtmux.Server()
>>> svr
Server(socket_path=/tmp/tmux-.../default)
```

**Tip:** You can also use [tmuxp]'s [`tmuxp shell`] to drop straight into your
current tmux server / session / window / pane.

[ptpython]: https://github.com/prompt-toolkit/ptpython
[ipython]: https://ipython.org/
[`tmuxp shell`]: https://tmuxp.git-pull.com/cli/shell.html

### Run any tmux command

Every object has a `.cmd()` escape hatch that honors socket name and path:

```python
>>> server = Server(socket_name='libtmux_doctest')
>>> server.cmd('display-message', 'hello world')
<libtmux...>
```

Create a new session:

```python
>>> server.cmd('new-session', '-d', '-P', '-F#{session_id}').stdout[0]
'$...'
```

### List and filter sessions

[**Learn more about Filtering**](https://libtmux.git-pull.com/topics/filtering.html)

```python
>>> server.sessions
[Session($... ...), ...]
```

Filter by attribute:

```python
>>> server.sessions.filter(history_limit='2000')
[Session($... ...), ...]
```

Direct lookup:

```python
>>> server.sessions.get(session_id=session.session_id)
Session($... ...)
```

### Control sessions and windows

[**Learn more about Workspace Setup**](https://libtmux.git-pull.com/topics/workspace_setup.html)

```python
>>> session.rename_session('my-session')
Session($... my-session)
```

Create new window in the background (don't switch to it):

```python
>>> bg_window = session.new_window(attach=False, window_name="bg-work")
>>> bg_window
Window(@... ...:bg-work, Session($... ...))

>>> session.windows.filter(window_name__startswith="bg")
[Window(@... ...:bg-work, Session($... ...))]

>>> session.windows.get(window_name__startswith="bg")
Window(@... ...:bg-work, Session($... ...))

>>> bg_window.kill()
```

### Split windows and send keys

[**Learn more about Pane Interaction**](https://libtmux.git-pull.com/topics/pane_interaction.html)

```python
>>> pane = window.split(attach=False)
>>> pane
Pane(%... Window(@... ...:..., Session($... ...)))
```

Type inside the pane (send keystrokes):

```python
>>> pane.send_keys('echo hello')
>>> pane.send_keys('echo hey', enter=False)
>>> pane.enter()
Pane(%... ...)
```

### Capture pane output

```python
>>> pane.clear()
Pane(%... ...)
>>> pane.send_keys("echo 'hello world'", enter=True)
>>> pane.cmd('capture-pane', '-p').stdout  # doctest: +SKIP
["$ echo 'hello world'", 'hello world', '$']
```

### Traverse the hierarchy

[**Learn more about Traversal**](https://libtmux.git-pull.com/topics/traversal.html)

Navigate from pane up to window to session:

```python
>>> pane.window
Window(@... ...:..., Session($... ...))
>>> pane.window.session
Session($... ...)
```

## Core concepts

| libtmux object | tmux concept                | Notes                          |
|----------------|-----------------------------|--------------------------------|
| [`Server`](https://libtmux.git-pull.com/api/servers.html) | tmux server / socket | Entry point; owns sessions |
| [`Session`](https://libtmux.git-pull.com/api/sessions.html) | tmux session (`$0`, `$1`,...) | Owns windows |
| [`Window`](https://libtmux.git-pull.com/api/windows.html) | tmux window (`@1`, `@2`,...) | Owns panes |
| [`Pane`](https://libtmux.git-pull.com/api/panes.html) | tmux pane (`%1`, `%2`,...) | Where commands run |

Also available: [`Options`](https://libtmux.git-pull.com/api/options.html) and [`Hooks`](https://libtmux.git-pull.com/api/hooks.html) abstractions for tmux configuration.

Collections are live and queryable:

```python
server = libtmux.Server()
session = server.sessions.get(session_name="demo")
api_windows = session.windows.filter(window_name__startswith="api")
pane = session.active_window.active_pane
pane.send_keys("echo 'hello from libtmux'", enter=True)
```

## tmux vs libtmux vs tmuxp

| Tool    | Layer                      | Typical use case                                   |
|---------|----------------------------|----------------------------------------------------|
| tmux    | CLI / terminal multiplexer | Everyday terminal usage, manual control            |
| libtmux | Python API over tmux       | Programmatic control, automation, testing          |
| tmuxp   | App on top of libtmux      | Declarative tmux workspaces from YAML / TOML       |

## Testing & fixtures

[**Learn more about the pytest plugin**](https://libtmux.git-pull.com/pytest-plugin/index.html)

Writing a tool that interacts with tmux? Use our fixtures to keep your tests clean and isolated.

```python
def test_my_tmux_tool(session):
    # session is a real tmux session in an isolated server
    window = session.new_window(window_name="test")
    pane = window.active_pane
    pane.send_keys("echo 'hello from test'", enter=True)

    assert window.window_name == "test"
    # Fixtures handle cleanup automatically
```

- Fresh tmux server/session/window/pane fixtures per test
- Temporary HOME and tmux config fixtures keep indices stable
- `TestServer` helper spins up multiple isolated tmux servers

## When you might not need libtmux

- Layouts are static and live entirely in tmux config files
- You do not need to introspect or control running tmux from other tools
- Python is unavailable where tmux is running

## Project links

**Topics:**
[Traversal](https://libtmux.git-pull.com/topics/traversal.html) ·
[Filtering](https://libtmux.git-pull.com/topics/filtering.html) ·
[Pane Interaction](https://libtmux.git-pull.com/topics/pane_interaction.html) ·
[Workspace Setup](https://libtmux.git-pull.com/topics/workspace_setup.html) ·
[Automation Patterns](https://libtmux.git-pull.com/topics/automation_patterns.html) ·
[Context Managers](https://libtmux.git-pull.com/topics/context_managers.html) ·
[Options & Hooks](https://libtmux.git-pull.com/topics/options_and_hooks.html)

**Reference:**
[Docs][docs] ·
[API][api] ·
[pytest plugin](https://libtmux.git-pull.com/pytest-plugin/index.html) ·
[Architecture][architecture] ·
[Changelog][history] ·
[Migration][migration]

**Project:**
[Issues][issues] ·
[Coverage][coverage] ·
[Releases][releases] ·
[License][license] ·
[Support][support]

**[The Tao of tmux][tao]** — deep-dive book on tmux fundamentals

## Contributing & support

Contributions are welcome. Please open an issue or PR if you find a bug or want to improve the API or docs. If libtmux helps you ship, consider sponsoring development via [support].

[docs]: https://libtmux.git-pull.com
[api]: https://libtmux.git-pull.com/api.html
[architecture]: https://libtmux.git-pull.com/about.html
[history]: https://libtmux.git-pull.com/history.html
[migration]: https://libtmux.git-pull.com/migration.html
[issues]: https://github.com/tmux-python/libtmux/issues
[coverage]: https://codecov.io/gh/tmux-python/libtmux
[releases]: https://pypi.org/project/libtmux/
[license]: https://github.com/tmux-python/libtmux/blob/master/LICENSE
[support]: https://tony.sh/support.html
[tao]: https://leanpub.com/the-tao-of-tmux
[tmuxp]: https://tmuxp.git-pull.com
[tmux]: https://github.com/tmux/tmux
