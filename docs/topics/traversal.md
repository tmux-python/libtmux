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

libtmux collections support Django-style filtering with `filter()` and `get()`.
For comprehensive coverage of all lookup operators, see {ref}`querylist-filtering`.

### Basic Filtering

Find windows by exact attribute match:

```python
>>> session.windows.filter(window_index=window.window_index)  # doctest: +ELLIPSIS
[Window(@... ..., Session($... ...))]
```

Get a specific pane by ID:

```python
>>> window.panes.get(pane_id=pane.pane_id)  # doctest: +ELLIPSIS
Pane(%... Window(@... ..., Session($... ...)))
```

### Partial Matching

Use lookup suffixes like `__contains`, `__startswith`, `__endswith`:

```python
>>> # Create windows to demonstrate filtering
>>> w1 = session.new_window(window_name="app-frontend")
>>> w2 = session.new_window(window_name="app-backend")
>>> w3 = session.new_window(window_name="logs")

>>> # Find windows starting with 'app-'
>>> session.windows.filter(window_name__startswith='app-')  # doctest: +ELLIPSIS
[Window(@... ...:app-frontend, Session($... ...)), Window(@... ...:app-backend, Session($... ...))]

>>> # Find windows containing 'end'
>>> session.windows.filter(window_name__contains='end')  # doctest: +ELLIPSIS
[Window(@... ...:app-frontend, Session($... ...)), Window(@... ...:app-backend, Session($... ...))]

>>> # Clean up
>>> w1.kill()
>>> w2.kill()
>>> w3.kill()
```

### Case-Insensitive Matching

Prefix any lookup with `i` for case-insensitive matching:

```python
>>> # Create windows with mixed case
>>> w1 = session.new_window(window_name="MyApp")
>>> w2 = session.new_window(window_name="myapp-worker")

>>> # Case-insensitive search
>>> session.windows.filter(window_name__istartswith='myapp')  # doctest: +ELLIPSIS
[Window(@... ...:MyApp, Session($... ...)), Window(@... ...:myapp-worker, Session($... ...))]

>>> # Clean up
>>> w1.kill()
>>> w2.kill()
```

### Regex Filtering

For complex patterns, use `__regex` or `__iregex`:

```python
>>> # Create versioned windows
>>> w1 = session.new_window(window_name="release-v1.0")
>>> w2 = session.new_window(window_name="release-v2.0")
>>> w3 = session.new_window(window_name="dev")

>>> # Match semantic version pattern
>>> session.windows.filter(window_name__regex=r'v\d+\.\d+')  # doctest: +ELLIPSIS
[Window(@... ...:release-v1.0, Session($... ...)), Window(@... ...:release-v2.0, Session($... ...))]

>>> # Clean up
>>> w1.kill()
>>> w2.kill()
>>> w3.kill()
```

### Chaining Filters

Multiple conditions can be combined:

```python
>>> # Create windows for chaining example
>>> w1 = session.new_window(window_name="api-prod")
>>> w2 = session.new_window(window_name="api-staging")
>>> w3 = session.new_window(window_name="web-prod")

>>> # Multiple conditions in one call (AND)
>>> session.windows.filter(
...     window_name__startswith='api',
...     window_name__endswith='prod'
... )  # doctest: +ELLIPSIS
[Window(@... ...:api-prod, Session($... ...))]

>>> # Chained calls (also AND)
>>> session.windows.filter(
...     window_name__contains='api'
... ).filter(
...     window_name__contains='staging'
... )  # doctest: +ELLIPSIS
[Window(@... ...:api-staging, Session($... ...))]

>>> # Clean up
>>> w1.kill()
>>> w2.kill()
>>> w3.kill()
```

### Get with Default

Avoid exceptions when an object might not exist:

```python
>>> # Returns None instead of raising ObjectDoesNotExist
>>> session.windows.get(window_name="nonexistent", default=None) is None
True
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
