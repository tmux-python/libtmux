(context_managers)=

# Context managers and ownership

Use an owned scope to accept responsibility for destroying a remote tmux resource. Looking up a handle leaves that resource alive. A plain `Server` context also leaves remote state intact; `server.own()` accepts whole-daemon destruction.

## Session context manager

This program uses your configured tmux endpoint and removes each session it creates at scope exit. The outer session keeps the daemon alive while the example checks that the inner session was removed. Other sessions remain. The imports and server constructor are part of the example; a test harness can redirect the unchanged code through environment defaults.

```python
>>> import libtmux
>>> server = libtmux.Server()
>>> with server.new_session() as keeper:
...     with server.new_session() as session:
...         print(session in server.sessions)
...         window = session.new_window()
...     print(session in server.sessions)
...     print(keeper in server.sessions)
True
False
True
```

Session, window and pane contexts accept ownership when entered. Objects returned by creation retain the creating daemon's identity; context entry verifies that identity instead of accepting a replacement daemon. Handles returned by lookup accept their identity at entry. Renaming a session or moving a window or pane does not redirect cleanup. A second active context on the same handle raises instead of replacing its unfinished cleanup scope.

## Taking ownership of an existing object

Call `.own()` on a server, session, window or pane. This example looks up a session after creating it, then takes ownership of the returned handle:

```python
>>> import libtmux
>>> server = libtmux.Server()
>>> created = server.new_session()
>>> existing = server.sessions.get(session_id=created.session_id)
>>> assert existing is not None
>>> owner = existing.own()
>>> with owner as session:
...     print(session.session_id == created.session_id)
True
>>> print(owner.closed)
True
```

`owner.value` gives you the borrowed handle. `owner.identity` records the immutable cleanup target. Editing the handle's ID, parent or server after acceptance does not change that identity. You can call `owner.close()` without using a context; repeating a successful close has no effect.

## Window context manager

Window destruction removes its panes and links from all sessions. The outer session scope removes the session created for this example:

```python
>>> import libtmux
>>> server = libtmux.Server()
>>> with server.new_session() as session:
...     with session.new_window() as window:
...         print(window in session.windows)
...         pane = window.split()
...     print(window in session.windows)
True
False
```

## Pane context manager

Pane destruction removes that pane. The window's original pane remains after the split pane's scope exits:

```python
>>> import libtmux
>>> server = libtmux.Server()
>>> with server.new_session() as session:
...     window = session.active_window
...     with window.split() as pane:
...         print(pane in window.panes)
...         pane.send_keys('echo "Hello"')
...     print(pane in window.panes)
True
False
```

## Nested context managers

Nest session, window and pane scopes to clean up the hierarchy in reverse order:

```python
>>> import libtmux
>>> server = libtmux.Server()
>>> with server.new_session() as session:
...     with session.new_window() as window:
...         with window.split() as pane:
...             print(pane.pane_id.startswith("%"))
True
```

Cleanup runs from the innermost scope outward. tmux may terminate a server itself when its last session disappears; leaving a borrowed `Server` context does not send `kill-server`.

## Server context manager

A plain server context leaves its sessions alive. This example checks that behavior, then explicitly removes the session it created:

```python
>>> import libtmux
>>> with libtmux.Server() as server:
...     session = server.new_session()
...     print(session in server.sessions)
True
>>> print(session in server.sessions)
True
>>> session.own().close()
>>> print(session in server.sessions)
False
```

## Whole-server destruction

A server owner destroys the daemon and its sessions, windows and panes. This cleanup demonstration uses a private endpoint because destroying your normal daemon would interrupt its sessions. Explicit isolation belongs in this example's subject; ordinary examples above use normal defaults.

```python
>>> import pathlib
>>> import tempfile
>>> import libtmux
>>> with tempfile.TemporaryDirectory(prefix="libtmux-owned-server-") as directory:
...     server = libtmux.Server(
...         socket_path=pathlib.Path(directory) / "tmux",
...         config_file="/dev/null",
...     )
...     session = server.new_session()
...     with server.own() as owned_server:
...         print(owned_server.is_alive())
...     print(server.is_alive())
True
False
```

On Linux, the owner retains a process descriptor to observe daemon exit. Removing a socket or directory does not establish termination. If the accepted daemon remains alive but its endpoint disappears, cleanup raises and remains retryable. A replacement daemon at the same path raises `StaleTmuxOwner` before destruction.

## Daemon identity

Creation and ownership acceptance initialize the reserved server option `@libtmux_owner_generation` if it is absent, then read that token, PID, start time and object ID through the same tmux connection. The token contains 32 ASCII hexadecimal characters. An existing empty or malformed value fails before creation or acceptance without replacing the value. Keep this reserved option unchanged for the daemon's lifetime and do not shadow it on sessions or windows.

The destructive command checks the token, PID and start time inside the receiving daemon's command dispatch. The random token distinguishes daemons even if the operating system reuses a PID within tmux's whole-second start-time precision. Changing the token after acceptance makes an existing owner stale; it does not authorize cleanup of another daemon.

## Cleanup failures and cancellation

If the body and teardown both fail, `BaseExceptionGroup` retains the body error followed by the cleanup error. Python 3.10 uses the `exceptiongroup` backport; Python 3.11 and later use the built-in class. This includes `KeyboardInterrupt` and `SystemExit`. `owner.cleanup_error` retains the latest teardown error, and `owner.closed` stays false until cleanup succeeds. Repair the cause and call `owner.close()` to retry. A successful retry clears the retained cleanup error.

`resource.own(timeout=5.0)` bounds acceptance and each cleanup attempt, including time spent waiting for another cleanup call. A command timeout kills and reaps the tmux client process; it cannot undo a remote operation that was already dispatched. The owner remains open for inspection and retry. Garbage collection releases local observation descriptors and does not destroy remote resources. These APIs are synchronous; they do not provide an asynchronous task-cancellation supervisor.

After timeout or interruption, output draining and client reaping each allow up to 0.1 seconds. If another process keeps the output pipes open, the client closes its readers and retains the bytes already captured. Cleanup targets the launched client process; it does not terminate other processes holding those pipes. Creation receipt capture observes an interruption within its next 0.05-second read interval before starting that cleanup.

## Creation failures

`Server.new_session()`, `Session.new_window()` and `Pane.split()` retain a creation receipt before decoding the returned object. The receipt contains the endpoint, daemon generation and new object ID. A failed snapshot, parser, context entry or final generation check triggers rollback of that known resource. The same rule applies when tmux returns an ID alongside a nonzero client status. A timeout or Ctrl-C kills and reaps the client, retains readable receipt bytes and attempts that rollback before re-raising the original failure. Rollback uses the original daemon identity and cannot destroy a replacement daemon.

Each creation command, identity query and rollback has a five-second client deadline. This is a per-step limit, not a five-second limit on the whole Python call. Snapshot queries retain their existing timeout behavior. These synchronous calls do not supervise a killed Python process; the external harness must own that recovery boundary.

If rollback also fails, the resulting `BaseExceptionGroup` retains the original operation error and a `CreationCleanupError`. That error's `__cause__` is the cleanup failure. Its `owner.identity` identifies the resource, `owner.cleanup_error` retains the failure, and `owner.close()` retries after the cause is repaired. An interruption during rollback remains a `BaseException` in the group alongside the recovery owner.

`UnknownCreation` means the client returned no trustworthy receipt. This includes a successful empty response or a timeout without a readable ID. Inspect the endpoint before retrying; a new resource may exist. Ctrl-C without a receipt remains `KeyboardInterrupt` with a note explaining that uncertainty. The `select_existing=True` window option can also return no creation output when tmux selects an existing window; it does not supply a created/reused result. A valid new-window receipt still requires rollback if later work fails.

The repository's `tests/test_creation_recovery.py` executes failed materialization, daemon replacement before return or context entry, nonzero results with valid IDs, paired rollback failures, retry, timeout, interruption and missing-receipt behavior. `tests/test_ownership.py` executes adoption for all four resource types, replacement refusal, edited-handle cleanup and a missing socket with a live daemon. `tests/test_example_harness.py` executes the ordinary example unchanged under both socket environment defaults. Discovery and explicit created/reused find-or-create APIs remain separate implementation work.
