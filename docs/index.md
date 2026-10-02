(index)=

# libtmux

Typed Python API for [tmux](https://github.com/tmux/tmux). Control
servers, sessions, windows, and panes as Python objects.

::::{grid} 1 1 3 3
:gutter: 2 2 3 3

:::{grid-item-card} Which call do I want?
:link: topics/which_call
:link-type: doc
Task to API to return value, exceptions, and tmux mechanism.
:::

:::{grid-item-card} Quickstart
:link: quickstart
:link-type: doc
Install, then run a command and read its output.
:::

:::{grid-item-card} Topics
:link: topics/index
:link-type: doc
Architecture, traversal, filtering, and automation patterns.
:::

:::{grid-item-card} API Reference
:link: api/index
:link-type: doc
Every public class, function, and exception.
:::

:::{grid-item-card} Testing
:link: api/testing/index
:link-type: doc
Isolated tmux fixtures and test helpers.
:::

:::{grid-item-card} Contributing
:link: project/index
:link-type: doc
Development setup, code style, release process.
:::

::::

## Install

```console
$ pip install libtmux
```

```console
$ uv add libtmux
```

Tip: libtmux is pre-1.0 and minor releases can change the API. Pin the minor
version you tested against, for example `libtmux==X.Y.*`.

See [Quickstart](quickstart.md) for all methods and first steps.

## What do you want to do?

| I want to | Use | Jump to |
| --------- | --- | ------- |
| Run a command and get its output | {meth}`Pane.run() <libtmux.Pane.run>` | {ref}`run-a-command` |
| Wait for text to appear | {meth}`Pane.wait_for_text() <libtmux.Pane.wait_for_text>` | {ref}`recipe-wait-for-text` |
| Send text safely | {meth}`Pane.paste_text() <libtmux.Pane.paste_text>` | {ref}`pane-interaction` |
| Use a throwaway server | {meth}`Server.owned() <libtmux.Server.owned>` | {ref}`throwaway_server` |
| Test a TUI | {func}`~libtmux.test.screen.assert_screen` | {ref}`testing-terminal-apps` |
| Orchestrate many panes | {meth}`Window.split_many() <libtmux.Window.split_many>` | {ref}`automation-patterns` |

Anything else is in {ref}`which-call`, which also lists what each call returns,
what it raises, and the tmux mechanism underneath.

### Run a command and get its output

{meth}`Pane.run() <libtmux.Pane.run>` waits for the command to finish and
returns its exit status and output. Nothing sleeps or scrapes the screen.
See {ref}`run-a-command`.

```python
>>> result = pane.run('echo hello; sh -c "exit 3"', timeout=30)
>>> result.returncode
3
>>> result.stdout
['hello']
```

### Wait for text

{meth}`Pane.wait_for_text() <libtmux.Pane.wait_for_text>` searches only output
written after an anchor. Anchor the pattern to the whole row (`^...$`) so the
echo of your own command, which shares the row with the prompt, cannot match. See
{ref}`recipe-wait-for-text`.

```python
>>> start = pane.capture_since().cursor
>>> pane.send_keys('echo deploy_ok')
>>> pane.wait_for_text(r'^deploy_ok$', regex=True, since=start, timeout=5).match.string
'deploy_ok'
```

### Send text safely

{meth}`Pane.paste_text() <libtmux.Pane.paste_text>` sends multi-line or large
text through a paste buffer. It is never read as key names or flags, and tmux's
16 KiB command limit does not apply.

```python
>>> cat = window.split(attach=False, shell='cat')
>>> start = cat.capture_since().cursor
>>> cat.paste_text('- a line;\nsecond --line\n')
>>> cat.wait_for_text('second --line', since=start, timeout=5).match.string
'second --line'
>>> cat.kill()
```

### Use a throwaway server

{meth}`Server.owned() <libtmux.Server.owned>` starts a private tmux server that
reads no config, never sees `$TMUX`, and is removed when the block ends, even if
the process is killed. See {ref}`throwaway_server`.

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

The [pytest plugin](api/testing/pytest-plugin/index.md) gives each test its own
server. {func}`~libtmux.test.screen.assert_screen` retries until the screen
matches, then fails with a line diff. See {ref}`testing-terminal-apps`.

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

{meth}`Window.split_many() <libtmux.Window.split_many>` re-applies a layout after
every split, so a window does not run out of room mid-fan-out. See
{ref}`automation-patterns`.

```python
>>> fleet = session.new_window(window_name="fleet", attach=False)
>>> panes = fleet.split_many(3)
>>> [p.run("echo $((6 * 7))", timeout=30).stdout for p in panes]
[['42'], ['42'], ['42']]
>>> fleet.kill()
```

## The object model

```
Server  →  Session  →  Window  →  Pane
```

Every level of the [tmux hierarchy](topics/architecture.md) is a typed
Python object with traversal, filtering, and command execution.

| Object | What it wraps |
|--------|---------------|
| {class}`~libtmux.server.Server` | tmux server / socket |
| {class}`~libtmux.session.Session` | tmux session |
| {class}`~libtmux.window.Window` | tmux window |
| {class}`~libtmux.pane.Pane` | tmux pane |

## Know where you're running

Sometimes you hold no handle at all, because your code is *running inside* a
pane. You don't have to search the server for yourself — tmux writes `TMUX` and
`TMUX_PANE` into every pane it spawns, and each level of the hierarchy reads
them back:

```python
>>> socket_path = server.cmd(
...     "display-message", "-p", "-t", session.session_id, "#{socket_path}"
... ).stdout[0]
>>> monkeypatch.setenv("TMUX", f"{socket_path},1,{session.session_id}")
>>> monkeypatch.setenv("TMUX_PANE", pane.pane_id)

>>> Pane.from_env().pane_id == pane.pane_id
True
>>> Session.from_env().session_name == session.session_name
True
```

Inside a pane tmux has already set those two variables, so {meth}`Pane.from_env()
<libtmux.Pane.from_env>` takes no arguments; these docs are not running in a
pane, so the example sets them first. Outside tmux there is no pane to return and
{exc}`~libtmux.exc.NotInsideTmux` is raised instead. See {ref}`self-location`.

```{toctree}
:hidden:

quickstart
topics/index
api/index
api/testing/index
internals/index
project/index
history
migration
glossary
MCP <https://libtmux-mcp.git-pull.com>
GitHub <https://github.com/tmux-python/libtmux>
```
