(traversal)=

# Traversal

libtmux convenient access to move around the hierachy of sessions,
windows and panes in tmux.

This is done by libtmux's object abstraction of {term}`target`s (the `-t`
argument) and the permanent internal ID's tmux gives to objects.

Open two terminals:

Terminal one: start tmux in a seperate terminal:

```console
$ tmux
```

Terminal two, `python` or `ptpython` if you have it:

```console
$ python
```

Import `libtmux`:

```python
import libtmux
```

Attach default tmux {class}`~libtmux.Server` to `t`:

```python
>>> t = libtmux.Server();
>>> t
<libtmux.server.Server object at 0x10edd31d0>
```

Get first session {class}`~libtmux.Session` to `session`:

```python
>>> session = t.sessions[0]
>>> session
Session($0 libtmux)
```

Get a list of sessions:

```python
>>> t.sessions
[Session($0 libtmux), Session($1 tmuxp)]
```

Iterate through sessions in a server:

```python
>>> for sess in t.sessions:
...     print(sess)

Session($0 libtmux)
Session($1 tmuxp)
```

Grab a {class}`~libtmux.Window` from a session:

```python
>>> session.windows[0]
Window(@1 1:libtmux, Session($0 libtmux))
```

Grab the currently focused window from session:

```python
>>> session.attached_window
>>> Window(@2 2:docs, Session($0 libtmux))grab the currently focused {class}`Pane` from session:
```

```python
>>> session.attached_pane
Pane(%5 Window(@2 2:docs, Session($0 libtmux)))
```

Assign the attached {class}`~libtmux.Pane` to `p`:

```python
>>> p = session.attached_pane
```

Access the window/server of a pane:

```python
>>> p.window
Window(@2 2:docs, Session($0 libtmux))

>>> p.server
<libtmux.server.Server object at 0x104191a10>
```

[target]: http://man.openbsd.org/OpenBSD-5.9/man1/tmux.1#COMMANDS
