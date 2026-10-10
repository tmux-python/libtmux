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

The repository's `tests/test_creation_recovery.py` executes failed materialization, daemon replacement before return or context entry, nonzero results with valid IDs, paired rollback failures, retry, timeout, interruption and missing-receipt behavior. `tests/test_ownership.py` executes adoption for all four resource types, replacement refusal, edited-handle cleanup and a missing socket with a live daemon. `tests/test_example_harness.py` executes the ordinary example unchanged under both socket environment defaults. The sections below describe discovery and created/reused find-or-create scopes.

## Find or create

Use a `FoundOrCreated` scope when an example should reuse an existing object and remove only what it creates. Session and window methods match the full name. Pane matching uses the local `@libtmux_pane_key` option because tmux has no stable pane name.

This program uses your normal endpoint. The external example harness executes this same file with path and name defaults, checks the displayed source, and checks cleanup after successful execution and an injected body failure:

```python
"""Reuse matching objects and clean up only the objects this program creates."""

from __future__ import annotations

import libtmux

server = libtmux.Server()
with (
    server.find_or_create_session("libtmux-example") as session,
    session.find_or_create_window("worker") as window,
    window.find_or_create_pane("worker") as pane,
):
    print(pane.pane_id, flush=True)
```

Inspect the result before entering its scope when the distinction matters:

```python
>>> import libtmux
>>> server = libtmux.Server()
>>> with server.new_session() as keeper:
...     created = server.find_or_create_session("libtmux-find-example")
...     with created as session:
...         reused = server.find_or_create_session("libtmux-find-example")
...         with reused as same_session:
...             print(created.created, reused.created)
...             print(session.session_id == same_session.session_id)
...         print(server.has_session("libtmux-find-example"))
...     print(server.has_session("libtmux-find-example"))
True False
True
True
False
```

`result.value` holds the public object. `result.owner` exists for a proven creation; `result.close()` leaves a reused object alive. A created owner retains its identity and cleanup error for retry. Body and teardown failures remain separate exceptions inside a `BaseExceptionGroup`, including on Python 3.10 through the existing backport.

Lookup failures raise instead of returning an empty match. Older tmux versions sanitize some session names, including backslashes and a dollar sign before a variable name. If tmux changes a requested name during creation, the call raises `ValueError` and rolls back the created object instead of returning a different name. Duplicate window names or pane keys raise `AmbiguousMatch`. Lookup and creation use separate tmux commands. Concurrent session creators can receive a duplicate-name error; concurrent window or pane creators can each create a matching object. Serialize those callers when your application requires uniqueness. Other clients can rename, move or destroy a borrowed object after lookup.

The lifecycle lookup writes `@libtmux_owner_generation` when absent so that subsequent lookup and creation commands can reject a replacement daemon. Reuse does not transfer destruction responsibility. Pane creation writes `@libtmux_pane_key` only on its new pane, and rolls back that pane if the write fails. Window and global options with the same key do not count as a pane's identity.

## Find or create a server

`server.find_or_create()` borrows an answering daemon or owns a daemon whose startup it proves. A new daemon inherits a fresh environment nonce; the same tmux connection checks that nonce and returns the generation receipt. A concurrent caller that reaches the daemon after startup receives a borrowed result. Server reuse leaves its options and ownership metadata unchanged.

This server-destruction example names a disposable endpoint because the created owner will destroy the whole daemon:

```python
>>> import libtmux
>>> server = libtmux.Server(socket_name="libtmux-disposable-example", config_file="/dev/null")
>>> result = server.find_or_create()
>>> with result as running:
...     print(running.cmd("display-message", "-p", "#{pid}").returncode)
0
>>> print(result.owner is None or result.owner.closed)
True
```

A proven new server sets the server option `exit-empty` to `off`, so it can remain alive without a session until its owner closes. Startup adds a per-call `LIBTMUX_STARTUP_PROOF_<nonce>` variable to that daemon's initial environment. This internal variable is distinct from the public endpoint-default variables. The host environment does not change. A configuration that removes the proof prevents the caller from claiming ownership; the answering daemon remains borrowed. A startup failure without a trustworthy receipt requires inspecting the endpoint before retrying.

## Finding running tmux servers

`server.discover()` checks its captured endpoint, the endpoint's parent directory, the captured `TMUX_TMPDIR/tmux-UID` directory, and `/tmp/tmux-UID`. Pass additional socket directories through `roots`, or set `include_configured=False` to inspect only those directories. Discovery does not start tmux or write ownership metadata.

This example limits the scan to the normal endpoint's socket directory. The test harness redirects the server before construction:

```python
>>> import pathlib
>>> import libtmux
>>> server = libtmux.Server()
>>> with server.new_session() as keeper:
...     found = server.discover([pathlib.Path(server.socket_path).parent], include_configured=False)
...     print(any(item.server.socket_path == server.socket_path for item in found.servers))
...     print(found.truncated)
True
False
```

Each `DiscoveredServer` contains a borrowed `server`, its `server_pid`, and its whole-second `start_time`. Inspect `diagnostics` for skipped paths and failed probes. `max_entries`, `max_probes`, `timeout`, and `probe_timeout` bound the scan. `entries` counts roots and directory entries; `probes` counts launched tmux clients. `truncated=True` means a limit prevented the scan from finishing. A blocked filesystem call must return before Python can check the deadline; the final client's timeout cleanup can add up to 0.2 seconds. `KeyboardInterrupt` propagates after the client has been reaped.

The scan covers direct children of the selected directories, not every socket on the machine. It checks sockets owned by the current user, deduplicates filesystem aliases, and retains path components for the filesystem to resolve. A missing component in `missing/../root` remains an error; `symlink/..` follows the symlink before resolving its parent.
