(properties)=

# Properties

Get access to the data attributions behind tmux sessions, windows and panes.

This is done through accessing the [formats][formats] available in `list-sessions`,
`list-windows` and `list-panes`.

Open two terminals:

Terminal one: start tmux in a separate terminal:

```console
$ tmux
```

Terminal two: `python` or `ptpython` if you have it:

```console
$ python
```

Import libtmux:

```python
>>> import libtmux
```

Attach default tmux {class}`~libtmux.Server` to `t`:

```python
>>> import libtmux
>>> t = libtmux.Server()
>>> t
Server(socket_path=/tmp/tmux-.../default)
```

## Session

Get the {class}`~libtmux.Session` object:

```python
>>> session = server.sessions[0]
>>> session
Session($1 libtmux_...)
```

Quick access to basic attributes:

```python
>>> session.session_name
'libtmux_...'

>>> session.session_id
'$1'
```

To see all attributes for a session:

```python
from libtmux.neo import Obj

>>> sorted(list(Obj.__dataclass_fields__.keys()))
['session_attached', 'session_created', ...]
```

```python
>>> session.session_windows
'...'
```

## Windows

The same concepts apply for {class}`~libtmux.Window`:

```python
>>> window = session.attached_window

>>> window
Window(@1 ...:..., Session($1 ...))
```

Basics:

```python
>>> window.window_name
'...'

>>> window.window_id
'@1'

>>> window.window_height
'...'

>>> window.window_width
'...'
```

Use attribute access for details not accessible via properties:

```python
>>> window.window_panes
'1'
```

## Panes

Get the {class}`~libtmux.Pane`:

```python
>>> pane = window.attached_pane

>>> pane
Pane(%1 Window(@1 ...:..., Session($1 libtmux_...)))
```

Basics:

```python
>>> pane.pane_current_command
'...'

>>> type(pane.pane_current_command)
<class 'str'>

>>> pane.pane_height
'...'

>>> pane.pane_width
'...'

>>> pane.pane_index
'0'
```

[formats]: http://man.openbsd.org/OpenBSD-5.9/man1/tmux.1#FORMATS
