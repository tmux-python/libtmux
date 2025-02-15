(traversal)=

# Traversal

libtmux provides convenient access to move around the hierarchy of sessions,
windows and panes in tmux.

This is done by libtmux's object abstraction of {term}`target`s (the `-t`
argument) and the permanent internal ID's tmux gives to objects.

Open two terminals:

Terminal one: start tmux in a separate terminal:

```console
$ tmux
```

Terminal two, `python` or `ptpython` if you have it:

```console
$ python
```

## Setup

First, create a test session:

```python
>>> session = server.new_session()  # Create a test session using existing server
```

## Server Level

View the server's representation:

```python
>>> server  # doctest: +ELLIPSIS
Server(socket_name=...)
```

Get all sessions in the server:

```python
>>> server.sessions  # doctest: +ELLIPSIS
[Session($... ...)]
```

Get all windows across all sessions:

```python
>>> server.windows  # doctest: +ELLIPSIS
[Window(@... ..., Session($... ...))]
```

Get all panes across all windows:

```python
>>> server.panes  # doctest: +ELLIPSIS
[Pane(%... Window(@... ..., Session($... ...)))]
```

## Session Level

Get first session:

```python
>>> session = server.sessions[0]
>>> session  # doctest: +ELLIPSIS
Session($... ...)
```

Get windows in a session:

```python
>>> session.windows  # doctest: +ELLIPSIS
[Window(@... ..., Session($... ...))]
```

Get active window and pane:

```python
>>> session.active_window  # doctest: +ELLIPSIS
Window(@... ..., Session($... ...))

>>> session.active_pane  # doctest: +ELLIPSIS
Pane(%... Window(@... ..., Session($... ...)))
```

## Window Level

Get a window and inspect its properties:

```python
>>> window = session.windows[0]
>>> window.window_index  # doctest: +ELLIPSIS
'...'
```

Access the window's parent session:

```python
>>> window.session  # doctest: +ELLIPSIS
Session($... ...)
>>> window.session.session_id == session.session_id
True
```

Get panes in a window:

```python
>>> window.panes  # doctest: +ELLIPSIS
[Pane(%... Window(@... ..., Session($... ...)))]
```

Get active pane:

```python
>>> window.active_pane  # doctest: +ELLIPSIS
Pane(%... Window(@... ..., Session($... ...)))
```

## Pane Level

Get a pane and traverse upwards:

```python
>>> pane = window.panes[0]
>>> pane.window.window_id == window.window_id
True
>>> pane.session.session_id == session.session_id
True
>>> pane.server is server
True
```

## Filtering and Finding Objects

Find windows by index:

```python
>>> session.windows.filter(window_index=window.window_index)  # doctest: +ELLIPSIS
[Window(@... ..., Session($... ...))]
```

Get a specific pane by ID:

```python
>>> window.panes.get(pane_id=pane.pane_id)  # doctest: +ELLIPSIS
Pane(%... Window(@... ..., Session($... ...)))
```

## Checking Relationships

Check if objects are related:

```python
>>> window in session.windows
True
>>> pane in window.panes
True
>>> session in server.sessions
True
```

Check if a window is active:

```python
>>> window.window_id == session.active_window.window_id
True
```

Check if a pane is active:

```python
>>> pane.pane_id == window.active_pane.pane_id
True
```

[target]: http://man.openbsd.org/OpenBSD-5.9/man1/tmux.1#COMMANDS
