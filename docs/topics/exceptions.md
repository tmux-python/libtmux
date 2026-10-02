(exceptions)=

# Exceptions

Every exception libtmux defines is a {exc}`~libtmux.exc.TmuxError`, so one
`except TmuxError` catches all of them. Under it, tmux-side failures are
{exc}`~libtmux.exc.LibTmuxException`; a call to a removed API is
{exc}`~libtmux.exc.DeprecatedError`, a sibling that `except LibTmuxException`
does not catch.

## The tree

```text
TmuxError                         the root: catch this for "anything libtmux raised"
├── DeprecatedError               a removed API was called (also an AttributeError; not a LibTmuxException)
└── LibTmuxException              a tmux operation failed or gave up
    ├── TmuxCommandFailed         tmux answered with an error, or output libtmux cannot parse
    │   └── ListCommandFailed     a strict listing (fetch_sessions) could not list
    ├── TmuxCommandNotFound       the tmux binary is missing
    ├── SocketPathTooLong         the socket path cannot fit in a UNIX socket address
    ├── VersionTooLow             tmux is older than libtmux supports
    ├── TmuxTimeout               a tmux client outlived its timeout and was killed
    ├── WaitTimeout               a wait gave up; the condition was not met
    │   └── PaneRunTimeout        Pane.run: both a WaitTimeout and a TmuxTimeout
    ├── TmuxServerGone            the server was not running when a wait ended
    │   └── TmuxServerNotRunning  Server.raise_if_dead: also a CalledProcessError
    ├── ObjectDoesNotExist        a lookup matched nothing
    │   └── TmuxObjectDoesNotExist
    ├── MultipleObjectsReturned   a lookup matched several
    ├── PaneError                 PaneNotFound
    ├── WindowError               NoActiveWindow, MultipleActiveWindows, NoWindowsExist, ...
    ├── OptionError               UnknownOption, InvalidOption, AmbiguousOption
    ├── CaptureCursorError        InvalidCaptureCursor, PaneLifecycleChanged
    └── TmuxSessionExists, BadSessionName, NotInsideTmux, VariableUnpackingError, ...
```

The {doc}`exceptions API reference </api/libtmux.exc>` documents each class.
Several of these also inherit a builtin where callers would expect one:
`InvalidCaptureCursor` and the adjustment errors are `ValueError`s, and
`DeprecatedError` is an `AttributeError`.

## Removed APIs and feature detection

{exc}`~libtmux.exc.DeprecatedError` is an `AttributeError` because a removed name
is, to Python, a name that is not there. `hasattr(obj, "old_name")` is `False`
and `getattr(obj, "old_name", default)` returns the default, so code that tries
the new name and falls back to the old one keeps working across versions.
Reading the name directly raises, and the message names the replacement.

```python
>>> from libtmux import exc

>>> hasattr(session, "attached_window")
False

>>> getattr(session, "attached_window", None) is None
True

>>> try:
...     session.attached_window
... except exc.DeprecatedError as e:
...     print(e)
Session.attached_window was deprecated in 0.31.0 and has been removed. Use Session.active_window instead.
```

It is not a `LibTmuxException`, so an `except LibTmuxException` fallback around
tmux calls does not take the old-API path by accident.

## Which timeout is which

Three timeouts, told apart by what happened to tmux:

| Exception | Raised by | What happened | Safe to retry? |
| --- | --- | --- | --- |
| {exc}`~libtmux.exc.WaitTimeout` | {meth}`Pane.wait() <libtmux.Pane.wait>`, {meth}`Pane.wait_for_text() <libtmux.Pane.wait_for_text>` | The condition was not met in time. Nothing was killed. | Yes: wait again. |
| {exc}`~libtmux.exc.TmuxTimeout` | `cmd()` with `timeout=`, {meth}`Server.wait_for() <libtmux.Server.wait_for>` | A tmux client outlived its bound and was killed. The command may or may not have taken effect. | Read the state back first. |
| {exc}`~libtmux.exc.PaneRunTimeout` | {meth}`Pane.run() <libtmux.Pane.run>` | The command did not finish in time. It keeps running in the pane. | No: it is still running. |

{exc}`~libtmux.exc.PaneRunTimeout` is both because {meth}`Pane.run()
<libtmux.Pane.run>` is both: a wait for a condition (the command finishing),
carried out by a bounded tmux `wait-for` call. `except WaitTimeout` and
`except TmuxTimeout` each catch it, and it adds `stdout` and `started`.

```python
>>> from libtmux import exc

>>> issubclass(exc.PaneRunTimeout, exc.WaitTimeout)
True

>>> issubclass(exc.PaneRunTimeout, exc.TmuxTimeout)
True

>>> issubclass(exc.WaitTimeout, exc.TmuxTimeout)
False
```

## When each is raised

| Exception | Raised when |
| --- | --- |
| {exc}`~libtmux.exc.TmuxCommandFailed` | tmux writes to stderr for a command libtmux wraps, or a list returns rows libtmux cannot parse |
| {exc}`~libtmux.exc.ListCommandFailed` | {meth}`Server.fetch_sessions() <libtmux.Server.fetch_sessions>`, `fetch_windows()` or `fetch_panes()` could not list. Chained from the original error |
| {exc}`~libtmux.exc.TmuxCommandNotFound` | no `tmux` on `PATH` (or at `tmux_bin`) |
| {exc}`~libtmux.exc.SocketPathTooLong` | the resolved socket path exceeds the UNIX socket address limit |
| {exc}`~libtmux.exc.TmuxServerGone` | {meth}`Server.wait_for() <libtmux.Server.wait_for>`, {meth}`Pane.wait() <libtmux.Pane.wait>` or {meth}`Pane.run() <libtmux.Pane.run>` finds the server exited |
| {exc}`~libtmux.exc.TmuxServerNotRunning` | {meth}`Server.raise_if_dead() <libtmux.Server.raise_if_dead>` and no server answers |
| {exc}`~libtmux.exc.PaneNotFound` | the pane was closed while libtmux waited on it |
| {exc}`~libtmux.exc.DeprecatedError` | any removed method, property or parameter; the message names the replacement |

## Lenient listings do not hide a hang

{attr}`Server.sessions <libtmux.Server.sessions>` and
{attr}`Server.clients <libtmux.Server.clients>` return an empty list when tmux
cannot be queried. They catch {exc}`~libtmux.exc.TmuxCommandFailed`,
{exc}`~libtmux.exc.TmuxCommandNotFound`, {exc}`~libtmux.exc.SocketPathTooLong`
and {exc}`~libtmux.exc.VersionTooLow`, not
{exc}`~libtmux.exc.LibTmuxException`, so a timeout or a vanished server is
raised rather than read as "no sessions". The behavior does not depend on where
a class sits in the tree.

```python
>>> from libtmux import Server

>>> Server(socket_name="no_such_server").sessions
[]
```

## Choosing a handler

| You want | Catch |
| --- | --- |
| Everything libtmux raises | {exc}`~libtmux.exc.TmuxError` |
| tmux failed or gave up; fall back | {exc}`~libtmux.exc.LibTmuxException` (a removed API still raises) |
| Any timeout from a bounded call | {exc}`~libtmux.exc.TmuxTimeout` |
| A wait that gave up | {exc}`~libtmux.exc.WaitTimeout` |
| The server is not there | {exc}`~libtmux.exc.TmuxServerGone` |
