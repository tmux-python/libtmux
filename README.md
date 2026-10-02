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

## What do you want to do?

| I want to | Use |
|-----------|-----|
| Run a command and get its output | `Pane.run()` |
| Wait for text to appear | `Pane.wait_for_text()` |
| Send text safely | `Pane.paste_text()` |
| Use a throwaway server | `Server.owned()` |
| Test a TUI | `assert_screen()` |
| Orchestrate many panes | `Window.split_many()` |

Each example below is a test. The full task-to-call map, with return values, exceptions, and tmux mechanism, is [Which call do I want?](https://libtmux.git-pull.com/topics/which_call/)

### Run a command and get its output

[**Learn more**](https://libtmux.git-pull.com/topics/run_a_command/)

`Pane.run()` waits for the command to finish and returns its exit status and output. No sleeping, no screen scraping.

```python
>>> result = pane.run('echo hello; sh -c "exit 3"', timeout=30)
>>> result.returncode
3
>>> result.stdout
['hello']
```

### Wait for text

[**Learn more**](https://libtmux.git-pull.com/topics/pane_interaction/#recipe-wait-for-text-without-matching-your-own-command)

`Pane.wait_for_text()` searches only output written after an anchor. Anchor the pattern to the whole row (`^...$`) so the echo of your own command, which shares the row with the prompt, cannot match:

```python
>>> start = pane.capture_since().cursor
>>> pane.send_keys('echo deploy_ok')
>>> pane.wait_for_text(r'^deploy_ok$', regex=True, since=start, timeout=5).match.string
'deploy_ok'
```

### Send text safely

[**Learn more**](https://libtmux.git-pull.com/topics/pane_interaction/)

`Pane.paste_text()` sends multi-line or large text through a paste buffer. It is never read as key names or flags, and tmux's 16 KiB command limit does not apply:

```python
>>> cat = window.split(attach=False, shell='cat')
>>> start = cat.capture_since().cursor
>>> cat.paste_text('- a line;\nsecond --line\n')
>>> cat.wait_for_text('second --line', since=start, timeout=5).match.string
'second --line'
>>> cat.kill()
```

### Use a throwaway server

[**Learn more**](https://libtmux.git-pull.com/topics/throwaway_server/)

`Server.owned()` starts a private tmux server that reads no config, never sees `$TMUX`, and is removed when the block ends, even if the process is killed:

```python
>>> import libtmux
>>> with libtmux.Server.owned() as scratch:
...     shell = scratch.new_session(session_name="demo").active_pane
...     shell.run("echo isolated", timeout=30).stdout
['isolated']
>>> scratch.is_alive()
False
```

### Test a TUI

[**Learn more**](https://libtmux.git-pull.com/topics/testing_terminal_apps/)

The pytest plugin gives each test its own server. `assert_screen()` retries until the screen matches, then fails with a line diff:

```python
import pytest
from libtmux.test.screen import assert_screen


@pytest.mark.deterministic_shell  # bash, no rc files, prompt "$ "
def test_greeter(session):
    pane = session.active_pane
    pane.send_keys('read -p "name? " n; echo "hello $n"')
    assert_screen(pane, "name?", contains=True)
```

### Orchestrate many panes

[**Learn more**](https://libtmux.git-pull.com/topics/automation_patterns/)

`Window.split_many()` re-applies a layout after every split, so a window never runs out of room mid-fan-out:

```python
>>> fleet = session.new_window(window_name="fleet", attach=False)
>>> panes = fleet.split_many(3)
>>> [p.run("echo $((6 * 7))", timeout=30).stdout for p in panes]
[['42'], ['42'], ['42']]
>>> fleet.kill()
```

Also: [traverse](https://libtmux.git-pull.com/topics/traversal/) and [filter](https://libtmux.git-pull.com/topics/filtering/) live objects, [locate yourself](https://libtmux.git-pull.com/topics/self_location/) with `from_env()`, [context managers](https://libtmux.git-pull.com/topics/context_managers/), the `.cmd(...)` escape hatch, and [options and hooks](https://libtmux.git-pull.com/topics/options_and_hooks/).

## Requirements & support

- tmux: >= 3.2a
- Python: >= 3.10 (CPython and PyPy)

Maintenance-only backports (no new fixes):

- Python 2.x: [`v0.8.x`](https://github.com/tmux-python/libtmux/tree/v0.8.x)
- tmux 1.8-3.1c: [`v0.48.x`](https://github.com/tmux-python/libtmux/tree/v0.48.x)

## 📦 Installation

Stable release:

```console
$ pip install libtmux
```

With pipx:

```console
$ pipx install libtmux
```

With uv / uvx:

```console
$ uv add libtmux
```

```console
$ uvx --from "libtmux" python
```

From the main branch (bleeding edge):

```console
$ pip install 'git+https://github.com/tmux-python/libtmux.git'
```

Tip: libtmux is pre-1.0 and minor releases can change the API. Pin the minor version you tested against, for example `libtmux==X.Y.*`, and read the [changelog][history] before upgrading.

## 🚀 Explore the object model

The jobs above work on any pane. To poke at a live session by hand:

### Open a tmux session

First, start a tmux session to connect to:

```console
$ tmux new-session -s foo -n bar
```

### Pilot your tmux session via Python

Use [ptpython], [ipython], etc. for a nice REPL with autocompletions:

```console
$ pip install --user ptpython
```

```console
$ ptpython
```

Connect to a live tmux session:

```python
>>> import libtmux
>>> svr = libtmux.Server()
>>> svr
Server(socket_path=.../default)
```

**Tip:** You can also use [tmuxp]'s [`tmuxp shell`] to drop straight into your
current tmux server / session / window / pane.

[ptpython]: https://github.com/prompt-toolkit/ptpython
[ipython]: https://ipython.org/
[`tmuxp shell`]: https://tmuxp.git-pull.com/cli/shell/

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

[**Learn more about Filtering**](https://libtmux.git-pull.com/topics/filtering/)

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

[**Learn more about Workspace Setup**](https://libtmux.git-pull.com/topics/workspace_setup/)

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

`send_keys()` types and returns at once. It suits starting a program or answering a prompt; to know a command finished, use `Pane.run()`.

[**Learn more about Pane Interaction**](https://libtmux.git-pull.com/topics/pane_interaction/)

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

### Snapshot the screen

`capture_pane()` returns the visible rows. To get a command's output, use `Pane.run()`; to read only what is new, use `Pane.capture_since()`.

```python
>>> pane.clear()
Pane(%... ...)
>>> pane.send_keys("echo 'hello world'", enter=True)
>>> pane.capture_pane()  # doctest: +SKIP
["$ echo 'hello world'", 'hello world', '$']
```

### Traverse the hierarchy

[**Learn more about Traversal**](https://libtmux.git-pull.com/topics/traversal/)

Navigate from pane up to window to session:

```python
>>> pane.window
Window(@... ...:..., Session($... ...))
>>> pane.window.session
Session($... ...)
```

### Know where you're running

[**Learn more about Locating yourself**](https://libtmux.git-pull.com/topics/self_location/)

Code *running inside* a pane — a script in a split, a tmux hook, an agent — can ask where it is. tmux writes `TMUX` and `TMUX_PANE` into every pane it spawns, and `Server`, `Session`, `Window`, and `Pane` each read them back:

```python
>>> socket_path = server.cmd(
...     "display-message", "-p", "-t", session.session_id, "#{socket_path}"
... ).stdout[0]
>>> monkeypatch.setenv("TMUX", f"{socket_path},1,{session.session_id}")
>>> monkeypatch.setenv("TMUX_PANE", pane.pane_id)

>>> Pane.from_env()
Pane(%... ...)
>>> Session.from_env().session_name == session.session_name
True
```

In a real pane tmux has already set those two variables, so `from_env()` takes no arguments and there is nothing to arrange — this README is not running in a pane, so the example sets them first. Outside tmux there is no pane to return, and `from_env()` raises `NotInsideTmux`.

## Core concepts

The jobs above sit on a four-level hierarchy that mirrors tmux.


| libtmux object | tmux concept                | Notes                          |
|----------------|-----------------------------|--------------------------------|
| [`Server`](https://libtmux.git-pull.com/api/libtmux.server/) | tmux server / socket | Entry point; owns sessions |
| [`Session`](https://libtmux.git-pull.com/api/libtmux.session/) | tmux session (`$0`, `$1`,...) | Owns windows |
| [`Window`](https://libtmux.git-pull.com/api/libtmux.window/) | tmux window (`@1`, `@2`,...) | Owns panes |
| [`Pane`](https://libtmux.git-pull.com/api/libtmux.pane/) | tmux pane (`%1`, `%2`,...) | Where commands run |

Also available: [`Options`](https://libtmux.git-pull.com/api/libtmux.options/) and [`Hooks`](https://libtmux.git-pull.com/api/libtmux.hooks/) abstractions for tmux configuration.

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

[**Learn more about the pytest plugin**](https://libtmux.git-pull.com/api/pytest-plugin/) · [**Testing terminal apps**](https://libtmux.git-pull.com/topics/testing_terminal_apps/)

Writing a tool that interacts with tmux? Use our fixtures to keep your tests clean and isolated.

```python
def test_my_tmux_tool(session):
    # session is a real tmux session in an isolated server
    window = session.new_window(window_name="test")
    pane = window.active_pane
    assert pane.run("echo hello from test").stdout == ["hello from test"]
    assert window.window_name == "test"
    # Fixtures handle cleanup automatically
```

- Fresh `server` and `session` fixtures per test, each on an isolated
  tmux socket; derive windows and panes from `session`
- `assert_screen()` retries until a pane's screen matches, then fails with a line diff
- `@pytest.mark.deterministic_shell` fixes the shell, prompt, and environment
- A failing test prints the command that attaches to its tmux server
- Temporary HOME and tmux config fixtures keep indices stable
- `TestServer` helper spins up multiple isolated tmux servers

## When you might not need libtmux

- Layouts are static and live entirely in tmux config files
- You do not need to introspect or control running tmux from other tools
- Python is unavailable where tmux is running

## Project links

**Topics:**
[Which call do I want?](https://libtmux.git-pull.com/topics/which_call/) ·
[Run a Command](https://libtmux.git-pull.com/topics/run_a_command/) ·
[Throwaway Server](https://libtmux.git-pull.com/topics/throwaway_server/) ·
[Testing Terminal Apps](https://libtmux.git-pull.com/topics/testing_terminal_apps/) ·
[Traversal](https://libtmux.git-pull.com/topics/traversal/) ·
[Filtering](https://libtmux.git-pull.com/topics/filtering/) ·
[Pane Interaction](https://libtmux.git-pull.com/topics/pane_interaction/) ·
[Workspace Setup](https://libtmux.git-pull.com/topics/workspace_setup/) ·
[Automation Patterns](https://libtmux.git-pull.com/topics/automation_patterns/) ·
[Context Managers](https://libtmux.git-pull.com/topics/context_managers/) ·
[Options & Hooks](https://libtmux.git-pull.com/topics/options_and_hooks/)

**Reference:**
[Docs][docs] ·
[API][api] ·
[pytest plugin](https://libtmux.git-pull.com/api/pytest-plugin/) ·
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
[api]: https://libtmux.git-pull.com/api/
[architecture]: https://libtmux.git-pull.com/topics/architecture/
[history]: https://libtmux.git-pull.com/history/
[migration]: https://libtmux.git-pull.com/migration/
[issues]: https://github.com/tmux-python/libtmux/issues
[coverage]: https://codecov.io/gh/tmux-python/libtmux
[releases]: https://pypi.org/project/libtmux/
[license]: https://github.com/tmux-python/libtmux/blob/master/LICENSE
[support]: https://tony.sh/support.html
[tao]: https://leanpub.com/the-tao-of-tmux
[tmuxp]: https://tmuxp.git-pull.com
[tmux]: https://github.com/tmux/tmux
