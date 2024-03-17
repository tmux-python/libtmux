# libtmux

`libtmux` is a [typed](https://docs.python.org/3/library/typing.html) Python library that provides a wrapper for interacting programmatically with tmux, a terminal multiplexer. You can use it to manage tmux servers,
sessions, windows, and panes. Additionally, `libtmux` powers [tmuxp], a tmux workspace manager.

[![Python Package](https://img.shields.io/pypi/v/libtmux.svg)](https://pypi.org/project/libtmux/)
[![Docs](https://github.com/tmux-python/libtmux/workflows/docs/badge.svg)](https://libtmux.git-pull.com/)
[![Build Status](https://github.com/tmux-python/libtmux/workflows/tests/badge.svg)](https://github.com/tmux-python/tmux-python/actions?query=workflow%3A%22tests%22)
[![Code Coverage](https://codecov.io/gh/tmux-python/libtmux/branch/master/graph/badge.svg)](https://codecov.io/gh/tmux-python/libtmux)
[![License](https://img.shields.io/github/license/tmux-python/libtmux.svg)](https://github.com/tmux-python/libtmux/blob/master/LICENSE)

libtmux builds upon tmux's
[target](http://man.openbsd.org/OpenBSD-5.9/man1/tmux.1#COMMANDS) and
[formats](http://man.openbsd.org/OpenBSD-5.9/man1/tmux.1#FORMATS) to
create an object mapping to traverse, inspect and interact with live
tmux sessions.

View the [documentation](https://libtmux.git-pull.com/),
[API](https://libtmux.git-pull.com/api.html) information and
[architectural details](https://libtmux.git-pull.com/about.html).

# Install

```console
$ pip install --user libtmux
```

# Open a tmux session

Session name `foo`, window name `bar`

```console
$ tmux new-session -s foo -n bar
```

# Pilot your tmux session via python

```console
$ python
```

Use [ptpython], [ipython], etc. for a nice shell with autocompletions:

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
Server(socket_path=/tmp/tmux-.../default)
```

Tip: You can also use [tmuxp]'s [`tmuxp shell`] to drop straight into your
current tmux server / session / window pane.

[tmuxp]: https://tmuxp.git-pull.com/
[`tmuxp shell`]: https://tmuxp.git-pull.com/cli/shell.html
[ptpython]: https://github.com/prompt-toolkit/ptpython
[ipython]: https://ipython.org/

Run any tmux command, respective of context:

Honors tmux socket name and path:

```python
>>> server = Server(socket_name='libtmux_doctest')
>>> server.cmd('display-message', 'hello world')
<libtmux...>
```

New session:

```python
>>> server.cmd('new-session', '-d', '-P', '-F#{session_id}').stdout[0]
'$2'
```

```python
>>> session.cmd('new-window', '-P').stdout[0]
'libtmux...:2.0'
```

From raw command output, to a rich `Window` object (in practice and as shown
later, you'd use `Session.new_window()`):

```python
>>> Window.from_window_id(window_id=session.cmd('new-window', '-P', '-F#{window_id}').stdout[0], server=session.server)
Window(@2 2:..., Session($1 libtmux_...))
```

Create a pane from a window:

```python
>>> window.cmd('split-window', '-P', '-F#{pane_id}').stdout[0]
'%2'
```

Raw output directly to a `Pane`:

```python
>>> Pane.from_pane_id(pane_id=window.cmd('split-window', '-P', '-F#{pane_id}').stdout[0], server=window.server)
Pane(%... Window(@1 1:..., Session($1 libtmux_...)))
```

List sessions:

```python
>>> server.sessions
[Session($1 ...), Session($0 ...)]
```

Filter sessions by attribute:

```python
>>> server.sessions.filter(history_limit='2000')
[Session($1 ...), Session($0 ...)]
```

Direct lookup:

```python
>>> server.sessions.get(session_id="$1")
Session($1 ...)
```

Filter sessions:

```python
>>> server.sessions[0].rename_session('foo')
Session($1 foo)
>>> server.sessions.filter(session_name="foo")
[Session($1 foo)]
>>> server.sessions.get(session_name="foo")
Session($1 foo)
```

Control your session:

```python
>>> session
Session($1 ...)

>>> session.rename_session('my-session')
Session($1 my-session)
```

Create new window in the background (don't switch to it):

```python
>>> bg_window = session.new_window(attach=False, window_name="ha in the bg")
>>> bg_window
Window(@... 2:ha in the bg, Session($1 ...))

# Session can search the window
>>> session.windows.filter(window_name__startswith="ha")
[Window(@... 2:ha in the bg, Session($1 ...))]

# Directly
>>> session.windows.get(window_name__startswith="ha")
Window(@... 2:ha in the bg, Session($1 ...))

# Clean up
>>> bg_window.kill()
```

Close window:

```python
>>> w = session.active_window
>>> w.kill()
```

Grab remaining tmux window:

```python
>>> window = session.active_window
>>> window.split(attach=False)
Pane(%2 Window(@1 1:... Session($1 ...)))
```

Rename window:

```python
>>> window.rename_window('libtmuxower')
Window(@1 1:libtmuxower, Session($1 ...))
```

Split window (create a new pane):

```python
>>> pane = window.split()
>>> pane = window.split(attach=False)
>>> pane.select()
Pane(%3 Window(@1 1:..., Session($1 ...)))
>>> window = session.new_window(attach=False, window_name="test")
>>> window
Window(@2 2:test, Session($1 ...))
>>> pane = window.split(attach=False)
>>> pane
Pane(%5 Window(@2 2:test, Session($1 ...)))
```

Type inside the pane (send key strokes):

```python
>>> pane.send_keys('echo hey send now')

>>> pane.send_keys('echo hey', enter=False)
>>> pane.enter()
Pane(%1 ...)
```

Grab the output of pane:

```python
>>> pane.clear()  # clear the pane
Pane(%1 ...)
>>> pane.send_keys("cowsay 'hello'", enter=True)
>>> print('\n'.join(pane.cmd('capture-pane', '-p').stdout))  # doctest: +SKIP
$ cowsay 'hello'
 _______
< hello >
 -------
        \   ^__^
         \  (oo)\_______
            (__)\       )\/\
                ||----w |
                ||     ||
...
```

Traverse and navigate:

```python
>>> pane.window
Window(@1 1:..., Session($1 ...))
>>> pane.window.session
Session($1 ...)
```

# Python support

Unsupported / no security releases or bug fixes:

- Python 2.x: The backports branch is
  [`v0.8.x`](https://github.com/tmux-python/libtmux/tree/v0.8.x).

# Donations

Your donations fund development of new features, testing and support.
Your money will go directly to maintenance and development of the
project. If you are an individual, feel free to give whatever feels
right for the value you get out of the project.

See donation options at <https://git-pull.com/support.html>.

# Project details

- tmux support: 1.8+
- python support: >= 3.8, pypy, pypy3
- Source: <https://github.com/tmux-python/libtmux>
- Docs: <https://libtmux.git-pull.com>
- API: <https://libtmux.git-pull.com/api.html>
- Changelog: <https://libtmux.git-pull.com/history.html>
- Issues: <https://github.com/tmux-python/libtmux/issues>
- Test Coverage: <https://codecov.io/gh/tmux-python/libtmux>
- pypi: <https://pypi.python.org/pypi/libtmux>
- Open Hub: <https://www.openhub.net/p/libtmux-python>
- Repology: <https://repology.org/project/python:libtmux/versions>
- License: [MIT](http://opensource.org/licenses/MIT).
