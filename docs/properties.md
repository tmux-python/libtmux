(properties)=

# Properties

Get access to the data attributions behind tmux sessions, windows and panes.

This is done through accessing the [formats][formats] available in `list-sessions`,
`list-windows` and `list-panes`.

open two terminals:

terminal one: start tmux in a seperate terminal:

```
$ tmux
```

terminal two, `python` or `ptpython` if you have it:

```console

$ python

```

import tmux:

```{code-block} python

import tmux

```

attach default tmux {class}`libtmux.Server` to `t`:

```{code-block} python

>>> t = libtmux.Server();
>>> t
<libtmux.server.Server object at 0x10edd31d0>

```

## Session

get the `session` object:

```{code-block} python

>>> session = t.sessions[0]

>>> session
Session($0 libtmux)

```

quick access to basic attributes:

```{code-block} python

>>> session.name
u'libtmux'

>>> session.id
u'$0'

>>> session.width
u'213'

>>> session.height
u'114'

```

to see all attributes for a session:

```{code-block} python

>>> session._info.keys()
[u'session_height', u'session_windows', u'session_width', u'session_id', u'session_created', u'session_attached', u'session_grouped', u'session_name']

>>> session._info
{u'session_height': u'114', u'session_windows': u'3', u'session_width': u'213', u'session_id': u'$0', u'session_created': u'1464905357', u'session_attached': u'1', u'session_grouped': u'0', u'session_name': u'libtmux'}

```

some may conflict with python API, to access them, you can use `.get()`, to get the count
of sessions in a window:

```{code-block} python

>>> session.get('session_windows')
u'3'

```

## Windows

The same concepts apply for window:

```{code-block} python

>>> window = session.attached_window

>>> window
Window(@2 2:docs, Session($0 libtmux))

```

basics:

```{code-block} python

>>> window.name
u'docs'

>>> window.id
u'@2'

>>> window.height
u'114'

>>> window.width
u'213'

```

everything available:

```{code-block} python

>>> window._info
{u'window_panes': u'4', u'window_active': u'1', u'window_height': u'114', u'window_activity_flag': u'0', u'window_width': u'213', u'session_id': u'$0', u'window_id': u'@2', u'window_layout': u'dad5,213x114,0,0[213x60,0,0,4,213x53,0,61{70x53,0,61,5,70x53,71,61,6,71x53,142,61,7}]', u'window_silence_flag': u'0', u'window_index': u'2', u'window_bell_flag': u'0', u'session_name': u'libtmux', u'window_flags': u'*', u'window_name': u'docs'}

>>> window.keys()
[u'window_panes', u'window_active', u'window_height', u'window_activity_flag', u'window_width', u'session_id', u'window_id', u'window_layout', u'window_silence_flag', u'window_index', u'window_bell_flag', u'session_name', u'window_flags', u'window_name']

```

use `get()` for details not accessible via properties:

```{code-block} python

>>> pane.get('window_panes')
u'4'

```

## Panes

get the pane:

```{code-block} python

>>> pane = window.attached_pane

>>> pane
Pane(%5 Window(@2 2:docs, Session($0 libtmux)))

```

basics:

```{code-block} python

>>> pane.current_command
u'python'

>>> pane.height
u'53'

>>> pane.width
u'70'

>>> pane.index
u'1'

```

everything:

```{code-block} python

>>> pane._info
{u'alternate_saved_x': u'0', u'alternate_saved_y': u'0', u'cursor_y': u'47', u'cursor_x': u'0', u'pane_in_mode': u'0', u'insert_flag': u'0', u'keypad_flag': u'0', u'cursor_flag': u'1', u'pane_current_command': u'python', u'window_index': u'2', u'history_size': u'216', u'scroll_region_lower': u'52', u'keypad_cursor_flag': u'0', u'history_bytes': u'38778', u'pane_active': u'1', u'pane_dead': u'0', u'pane_synchronized': u'0', u'window_id': u'@2', u'pane_index': u'1', u'pane_width': u'70', u'mouse_any_flag': u'0', u'mouse_button_flag': u'0', u'window_name': u'docs', u'pane_current_path': u'/Users/me/work/python/libtmux/doc', u'pane_tty': u'/dev/ttys007', u'pane_title': u'Python REPL (ptpython)', u'session_id': u'$0', u'alternate_on': u'0', u'mouse_standard_flag': u'0', u'wrap_flag': u'1', u'history_limit': u'2000', u'pane_pid': u'37172', u'pane_height': u'53', u'session_name': u'libtmux', u'scroll_region_upper': u'0', u'pane_id': u'%5'}

>>> pane._info.keys()
[u'alternate_saved_x', u'alternate_saved_y', u'cursor_y', u'cursor_x', u'pane_in_mode', u'insert_flag', u'keypad_flag', u'cursor_flag', u'pane_current_command', u'window_index', u'history_size', u'scroll_region_lower', u'keypad_cursor_flag', u'history_bytes', u'pane_active', u'pane_dead', u'pane_synchronized', u'window_id', u'pane_index', u'pane_width', u'mouse_any_flag', u'mouse_button_flag', u'window_name', u'pane_current_path', u'pane_tty', u'pane_title', u'session_id', u'alternate_on', u'mouse_standard_flag', u'wrap_flag', u'history_limit', u'pane_pid', u'pane_height', u'session_name', u'scroll_region_upper', u'pane_id']

```

use `get()` for details keys:

```{code-block} python

>>> pane.get('pane_width')
u'70'

```

[formats]: http://man.openbsd.org/OpenBSD-5.9/man1/tmux.1#FORMATS
