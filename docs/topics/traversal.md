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

Attach default tmux {class}`~libtmux.server.Server` to `t`:

```python
>>> import libtmux
>>> t = libtmux.Server();
>>> t
<libtmux.server.Server object at ...>
```

Get first session {class}`~libtmux.Session` to `session`:

```python
>>> session = server.sessions[0]
>>> session
Session($1 ...)
```

Get a list of sessions:

```python
>>> server.sessions
[Session($1 ...), Session($0 ...)]
```

Iterate through sessions in a server:

```python
>>> for sess in server.sessions:
...     print(sess)
Session($1 ...)
Session($0 ...)
```

Grab a {class}`~libtmux.window.Window` from a session:

```python
>>> session.windows[0]
Window(@1 ...:..., Session($1 ...))
```

Grab the currently focused window from session:

```python
>>> session.attached_window
Window(@1 ...:..., Session($1 ...))
```

Grab the currently focused {class}`Pane` from session:

```python
>>> session.attached_pane
Pane(%1 Window(@1 ...:..., Session($1 ...)))
```

Assign the attached {class}`~libtmux.pane.Pane` to `p`:

```python
>>> p = session.attached_pane
```

Access the window/server of a pane:

```python
>>> p = session.attached_pane
>>> p.window
Window(@1 ...:..., Session($1 ...))

>>> p.server
<libtmux.server.Server object at ...>
```

[target]: http://man.openbsd.org/OpenBSD-5.9/man1/tmux.1#COMMANDS
