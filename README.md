libtmux - scripting library for tmux

[![Python Package](https://img.shields.io/pypi/v/libtmux.svg)](http://badge.fury.io/py/libtmux)
[![Docs](https://github.com/tmux-python/libtmux/workflows/Publish%20Docs/badge.svg)](https://github.com/tmux-python/libtmux/actions?query=workflow%3A%22Publish+Docs%22)
[![Build Status](https://github.com/tmux-python/libtmux/workflows/tests/badge.svg)](https://github.com/tmux-python/tmux-python/actions?query=workflow%3A%22tests%22)
[![Code Coverage](https://codecov.io/gh/tmux-python/libtmux/branch/master/graph/badge.svg)](https://codecov.io/gh/tmux-python/libtmux)
[![License](https://img.shields.io/github/license/tmux-python/libtmux.svg)](https://github.com/tmux-python/libtmux/blob/master/LICENSE)

libtmux is the tool behind [tmuxp], a tmux
workspace manager in python.

it builds upon tmux's
[target](http://man.openbsd.org/OpenBSD-5.9/man1/tmux.1#COMMANDS) and
[formats](http://man.openbsd.org/OpenBSD-5.9/man1/tmux.1#FORMATS) to
create an object mapping to traverse, inspect and interact with live
tmux sessions.

view the [documentation](https://libtmux.git-pull.com/) homepage,
[API](https://libtmux.git-pull.com/api.html) information and
[architectural details](https://libtmux.git-pull.com/about.html).

Python 2.x will be deprecated in libtmux 0.9. The backports branch is
[v0.8.x](https://github.com/tmux-python/libtmux/tree/v0.8.x).

# install

```console
$ pip install --user libtmux
```

# open a tmux session

session name `foo`, window name `bar`

```console
$ tmux new-session -s foo -n bar
```

# pilot your tmux session via python

```console
$ python

# or for nice autocomplete and syntax highlighting
$ pip install --user ptpython
$ ptpython
```

connect to a live tmux session:

```python
>>> import libtmux
>>> server = libtmux.Server()
>>> server
<libtmux.server.Server object at 0x7fbd622c1dd0>
```

Tip: You can also use [tmuxp]'s [`tmuxp shell`] to drop straight into your
current tmux server / session / window pane.

[tmuxp]: https://tmuxp.git-pull.com/
[`tmuxp shell`]: https://tmuxp.git-pull.com/cli.html#shell

list sessions:

```python
>>> server.list_sessions()
[Session($3 foo), Session($1 libtmux)]
```

find session:

```python
>>> server.get_by_id('$3')
Session($3 foo)
```

find session by dict lookup:

```python
>>> server.find_where({ "session_name": "foo" })
Session($3 foo)
```

assign session to `session`:

```python
>>> session = server.find_where({ "session_name": "foo" })
```

play with session:

```python
>>> session.new_window(attach=False, window_name="ha in the bg")
Window(@8 2:ha in the bg, Session($3 foo))
>>> session.kill_window("ha in")
```

create new window in the background (don't switch to it):

```python
>>> w = session.new_window(attach=False, window_name="ha in the bg")
Window(@11 3:ha in the bg, Session($3 foo))
```

kill window object directly:

```python
>>> w.kill_window()
```

grab remaining tmux window:

```python
>>> window = session.attached_window
>>> window.split_window(attach=False)
Pane(%23 Window(@10 1:bar, Session($3 foo)))
```

rename window:

```python
>>> window.rename_window('libtmuxower')
Window(@10 1:libtmuxower, Session($3 foo))
```

create panes by splitting window:

```python
>>> pane = window.split_window()
>>> pane = window.split_window(attach=False)
>>> pane.select_pane()
>>> window = session.new_window(attach=False, window_name="test")
>>> pane = window.split_window(attach=False)
```

send key strokes to panes:

```python
>>> pane.send_keys('echo hey send now')

>>> pane.send_keys('echo hey', enter=False)
>>> pane.enter()
```

grab the output of pane:

```python
>>> pane.clear()  # clear the pane
>>> pane.send_keys('cowsay hello')
>>> print('\n'.join(pane.cmd('capture-pane', '-p').stdout))
```

    sh-3.2$ cowsay 'hello'
     _______
    < hello >
     -------
            \   ^__^
             \  (oo)\_______
                (__)\       )\/\
                    ||----w |
                    ||     ||

powerful traversal features:

    >>> pane.window
    Window(@10 1:libtmuxower, Session($3 foo))
    >>> pane.window.session
    Session($3 foo)

# Donations

Your donations fund development of new features, testing and support.
Your money will go directly to maintenance and development of the
project. If you are an individual, feel free to give whatever feels
right for the value you get out of the project.

See donation options at <https://git-pull.com/support.html>.

# Project details

- tmux support: 1.8, 1.9a, 2.0, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
- python support: >= 3.7, pypy, pypy3
- Source: <https://github.com/tmux-python/libtmux>
- Docs: <https://libtmux.git-pull.com>
- API: <https://libtmux.git-pull.com/api.html>
- Changelog: <https://libtmux.git-pull.com/history.html>
- Issues: <https://github.com/tmux-python/libtmux/issues>
- Test Coverage: <https://codecov.io/gh/tmux-python/libtmux>
- pypi: <https://pypi.python.org/pypi/libtmux>
- Open Hub: <https://www.openhub.net/p/libtmux-python>
- License: [MIT](http://opensource.org/licenses/MIT).
