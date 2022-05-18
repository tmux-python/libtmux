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
import libtmux
```

Attach default tmux {class}`~libtmux.Server` to `t`:

```python
>>> t = libtmux.Server()
>>> t
<libtmux.server.Server object at 0x10edd31d0>
```

## Session

Get the {class}`~libtmux.Session` object:

```python
>>> session = t.sessions[0]
>>> session
Session($0 libtmux)
```

Quick access to basic attributes:

```python
>>> session.name
'libtmux'

>>> session.id
'$0'

>>> session.width
'213'

>>> session.height
'114'
```

To see all attributes for a session:

```python
>>> session._info.keys()
['session_height', 'session_windows', 'session_width', 'session_id', 'session_created', 'session_attached', 'session_grouped', 'session_name']

>>> session._info
{'session_height': '114', 'session_windows': '3', 'session_width': '213', 'session_id': '$0', 'session_created': '1464905357', 'session_attached': '1', 'session_grouped': '0', 'session_name': 'libtmux'}

```

Some may conflict with python API, to access them, you can use `.get()`, to get the count
of sessions in a window:

```python
>>> session.get('session_windows')
'3'
```

## Windows

The same concepts apply for {class}`~libtmux.Window`:

```python
>>> window = session.attached_window

>>> window
Window(@2 2:docs, Session($0 libtmux))
```

Basics:

```python
>>> window.name
'docs'

>>> window.id
'@2'

>>> window.height
'114'

>>> window.width
'213'
```

Everything available:

```python
>>> window._info
{'window_panes': '4', 'window_active': '1', 'window_height': '114', 'window_activity_flag': '0', 'window_width': '213', 'session_id': '$0', 'window_id': '@2', 'window_layout': 'dad5,213x114,0,0[213x60,0,0,4,213x53,0,61{70x53,0,61,5,70x53,71,61,6,71x53,142,61,7}]', 'window_silence_flag': '0', 'window_index': '2', 'window_bell_flag': '0', 'session_name': 'libtmux', 'window_flags': '*', 'window_name': 'docs'}

>>> window.keys()
['window_panes', 'window_active', 'window_height', 'window_activity_flag', 'window_width', 'session_id', 'window_id', 'window_layout', 'window_silence_flag', 'window_index', 'window_bell_flag', 'session_name', 'window_flags', 'window_name']
```

Use `get()` for details not accessible via properties:

```python
>>> pane.get('window_panes')
'4'
```

## Panes

Get the {class}`~libtmux.Pane`:

```python
>>> pane = window.attached_pane

>>> pane
Pane(%5 Window(@2 2:docs, Session($0 libtmux)))
```

Basics:

```python
>>> pane.current_command
'python'

>>> pane.height
'53'

>>> pane.width
'70'

>>> pane.index
'1'
```

Everything:

```python
>>> pane._info
{'alternate_saved_x': '0', 'alternate_saved_y': '0', 'cursor_y': '47', 'cursor_x': '0', 'pane_in_mode': '0', 'insert_flag': '0', 'keypad_flag': '0', 'cursor_flag': '1', 'pane_current_command': 'python', 'window_index': '2', 'history_size': '216', 'scroll_region_lower': '52', 'keypad_cursor_flag': '0', 'history_bytes': '38778', 'pane_active': '1', 'pane_dead': '0', 'pane_synchronized': '0', 'window_id': '@2', 'pane_index': '1', 'pane_width': '70', 'mouse_any_flag': '0', 'mouse_button_flag': '0', 'window_name': 'docs', 'pane_current_path': '/Users/me/work/python/libtmux/doc', 'pane_tty': '/dev/ttys007', 'pane_title': 'Python REPL (ptpython)', 'session_id': '$0', 'alternate_on': '0', 'mouse_standard_flag': '0', 'wrap_flag': '1', 'history_limit': '2000', 'pane_pid': '37172', 'pane_height': '53', 'session_name': 'libtmux', 'scroll_region_upper': '0', 'pane_id': '%5'}

>>> pane._info.keys()
['alternate_saved_x', 'alternate_saved_y', 'cursor_y', 'cursor_x', 'pane_in_mode', 'insert_flag', 'keypad_flag', 'cursor_flag', 'pane_current_command', 'window_index', 'history_size', 'scroll_region_lower', 'keypad_cursor_flag', 'history_bytes', 'pane_active', 'pane_dead', 'pane_synchronized', 'window_id', 'pane_index', 'pane_width', 'mouse_any_flag', 'mouse_button_flag', 'window_name', 'pane_current_path', 'pane_tty', 'pane_title', 'session_id', 'alternate_on', 'mouse_standard_flag', 'wrap_flag', 'history_limit', 'pane_pid', 'pane_height', 'session_name', 'scroll_region_upper', 'pane_id']
```

Use `get()` for details keys:

```python
>>> pane.get('pane_width')
'70'
```

[formats]: http://man.openbsd.org/OpenBSD-5.9/man1/tmux.1#FORMATS
