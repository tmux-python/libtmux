(properties)=

# Properties

Get access to the data attributions behind tmux sessions, windows and panes.

This is done through accessing the [formats][formats] available in `list-sessions`,
`list-windows` and `list-panes`.

Open two terminals:

Terminal one: start tmux in a seperate terminal:

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
<libtmux.server.Server object at ...>
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
>>> session.name
'libtmux_...'

>>> session.id
'$1'
```

To see all attributes for a session:

```python
>>> sorted(list(session._info.keys()))
['session_attached', 'session_created', ...]
```

Some may conflict with python API, to access them, you can use `.get()`, to get the count
of sessions in a window:

```python
>>> session.get('session_windows')
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
>>> window.name
'...'

>>> window.id
'@1'

>>> window.height
'...'

>>> window.width
'...'
```

Everything available:

```python
>>> sorted(list(window.keys()))
['session_id', 'session_name', 'window_active', ..., 'window_width']
```

Use `get()` for details not accessible via properties:

```python
>>> window.get('window_panes')
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
>>> pane.current_command
'...'

>>> type(pane.current_command)
<class 'str'>

>>> pane.height
'...'

>>> pane.width
'...'

>>> pane.index
'0'
```

Everything:

````python
>>> sorted(list(pane._info.keys()))
['alternate_on', 'alternate_saved_x', ..., 'wrap_flag']

Use `get()` for details keys:

```python
>>> pane.get('pane_width')
'...'
````

[formats]: http://man.openbsd.org/OpenBSD-5.9/man1/tmux.1#FORMATS
