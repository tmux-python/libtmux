(traversal)=

# Traversal

When you navigate a tmux server with libtmux, you move through a hierarchy of
related objects: a {class}`~libtmux.Server` holds {class}`~libtmux.Session`
objects, each session holds {class}`~libtmux.Window` objects, and each window
holds {class}`~libtmux.Pane` objects. Every object knows both its parents and
its children, so you can traverse in either direction — reach for
{attr}`session.windows <libtmux.Session.windows>` to list the windows under a
session, or {attr}`pane.session <libtmux.Pane.session>` to jump
from a pane back up to the session that contains it.

Most of the time you call a handful of properties like
{attr}`session.windows <libtmux.Session.windows>` and
{attr}`pane.session <libtmux.Pane.session>` and never look further. This works
out of the box, with no setup. The filtering and relationship checks later on
the page are there for the rarer cases where you need to find a specific object
by name or pattern, or confirm how two objects relate.

Under the hood this all rides on libtmux's object abstraction of {term}`target`s
(the `-t` argument) and the permanent internal IDs tmux assigns to each object,
but you rarely have to think about that layer to move around.

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

## Server level

The {class}`~libtmux.Server` sits at the top of the hierarchy. Start by viewing
its representation:

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

Each of these properties queries tmux fresh every time you access it, so the
result always reflects the server's current state. That freshness costs a tmux
round-trip per access — worth it for correctness, but if you iterate over the
same collection repeatedly, bind it to a variable once instead of re-reading the
property inside a loop.

## Session level

A {class}`~libtmux.Session` groups windows. Get the first one:

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

## Window level

A {class}`~libtmux.Window` groups panes. Get one and inspect its properties:

```python
>>> window = session.windows[0]
>>> window.window_index  # doctest: +ELLIPSIS
'...'
```

Traverse upward to the window's parent session:

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

## Pane level

A {class}`~libtmux.Pane` is the leaf of the hierarchy. From a pane you can walk
all the way back up to its window, session, and server:

```python
>>> pane = window.panes[0]
>>> pane.window.window_id == window.window_id
True
>>> pane.session.session_id == session.session_id
True
>>> pane.server is server
True
```

## Locating yourself

Everything above starts from a handle you already hold. Sometimes you hold
nothing, because your code is *running inside* a pane — and tmux has already told
it where it is. {meth}`Pane.from_env() <libtmux.Pane.from_env>`, and its siblings
on {class}`~libtmux.Server`, {class}`~libtmux.Session` and
{class}`~libtmux.Window`, read that back, so you can pick up the hierarchy from
wherever you happen to be running.

See {ref}`self-location` for the whole story, including the window that
*contains* you versus the one in front of you, and windows that live in more than
one session at once.

## Filtering and finding objects

Sometimes a property like {attr}`session.windows <libtmux.Session.windows>`
hands you more objects than you
want, and you need the one — or the few — matching a name, an index, or a
pattern. Every libtmux collection lets you narrow it down: call
{meth}`~libtmux._internal.query_list.QueryList.filter` to keep the objects that
match a condition, or {meth}`~libtmux._internal.query_list.QueryList.get` to
pull out a single object (it raises if it finds zero or more than one). You match
on the same attributes the objects already expose — `window_name`,
`window_index`, `pane_id`, and so on.

This is the opt-in part of the page. If the plain properties above already get
you to the object you want, you can stop here. For comprehensive coverage of all
lookup operators, see {ref}`querylist-filtering`. For tmux-native filters that
return only matching rows on large servers, see {ref}`native-filtering`.

### Basic filtering

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

### Partial matching

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

### Case-insensitive matching

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

### Regex filtering

For complex patterns, use `__regex` or `__iregex`:

```python
>>> # Create versioned windows
>>> w1 = session.new_window(window_name="release-v1-0")
>>> w2 = session.new_window(window_name="release-v2-0")
>>> w3 = session.new_window(window_name="dev")

>>> # Match version pattern
>>> session.windows.filter(window_name__regex=r'v\d+-\d+')  # doctest: +ELLIPSIS
[Window(@... ...:release-v1-0, Session($... ...)), Window(@... ...:release-v2-0, Session($... ...))]

>>> # Clean up
>>> w1.kill()
>>> w2.kill()
>>> w3.kill()
```

### Chaining filters

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

### Get with default

Avoid exceptions when an object might not exist:

```python
>>> # Returns None instead of raising ObjectDoesNotExist
>>> session.windows.get(window_name="nonexistent", default=None) is None
True
```

## Checking relationships

Two questions come up often: does an object belong to a collection (membership),
and do two handles point at the same tmux entity (identity)? Python's `in`
operator answers the first — whether an object is part of a collection:

```python
>>> window in session.windows
True
>>> pane in window.panes
True
>>> session in server.sessions
True
```

Comparing IDs answers the second — here, whether the window you hold is the
session's active window:

```python
>>> window.window_id == session.active_window.window_id
True
```

And whether the pane you hold is the window's active pane:

```python
>>> pane.pane_id == window.active_pane.pane_id
True
```

[target]: http://man.openbsd.org/OpenBSD-5.9/man1/tmux.1#COMMANDS
