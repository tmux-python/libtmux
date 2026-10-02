(throwaway_server)=

# A throwaway tmux server for scripts and tests

{meth}`Server.owned() <libtmux.Server.owned>` runs a tmux server that exists
for one block. It listens on a private socket, reads no configuration file,
never sees `$TMUX`, and is gone when the block ends. It cannot reach the tmux
you are working in, and nothing it does is visible there.

Reach for it in a test, an agent harness, or a CI step that needs a real tmux
and must leave nothing behind. If you want to drive a server you already
run, build a {class}`~libtmux.Server` instead.

## The recipe

```python
>>> from libtmux.server import Server
>>> with Server.owned() as scratch:
...     session = scratch.new_session(session_name="build")
...     pane = session.active_pane
...     pane.send_keys("echo hello", enter=True)
...     scratch.is_alive()
True
>>> scratch.is_alive()
False
```

tmux itself starts when the first session is created, so `is_alive()` is
`False` until then.

## What the block guarantees

- **A private socket.** The socket lives in a new directory made with
  {func}`tempfile.mkdtemp`, mode `0700`, named `lt-<random>/s`. Two blocks
  never share one, so scopes run concurrently, in threads or processes.
- **No user configuration.** `config_file` defaults to {data}`os.devnull`, so
  `~/.tmux.conf` is not read. Pass `config_file=None` to read it, or a path to
  load your own.
- **No inherited pane.** tmux runs without `$TMUX` and `$TMUX_PANE`, so a test
  started from inside a pane does not follow it to the outer server.
- **Cleanup on every exit.** The daemon is killed and the directory removed
  when the block ends, including when it raises. On a normal exit the daemon
  has stopped before the `with` statement returns.
- **Cleanup when the process dies.** A small reaper process starts with the
  server and waits on a pipe the owner holds. When the owner exits for any
  reason, `SIGTERM`, `SIGHUP` and `SIGKILL` included, the reaper kills the
  daemon and removes the directory. No signal handler is installed, so your
  own handlers are untouched.

The reaper needs a POSIX `sh`. Without one, the block still cleans up on
normal exit and on exceptions, but not when the process is killed.

## A path that is too long fails at once

A socket path is capped at 107 bytes on Linux and 103 on macOS. The private
directory is short, but it is created under `$TMPDIR`, and a deep `$TMPDIR`,
or a deep `directory=`, can still overflow the limit.
{meth}`~libtmux.Server.owned` measures the path before starting tmux and raises
{exc}`~libtmux.exc.SocketPathTooLong` with the byte count and how far over the
path is:

```python
>>> import pathlib, tempfile
>>> from libtmux import exc
>>> from libtmux.server import Server
>>> with tempfile.TemporaryDirectory() as parent:
...     deep = pathlib.Path(parent) / ("d" * 110)
...     deep.mkdir()
...     try:
...         with Server.owned(directory=deep):
...             pass
...     except exc.SocketPathTooLong as e:
...         print(e.over > 0)
True
```

Pick a shorter directory, or set `$TMPDIR` to one.

## In a pytest fixture

```python
import collections.abc
import pytest
from libtmux import Server


@pytest.fixture
def scratch_server() -> collections.abc.Iterator[Server]:
    with Server.owned() as server:
        yield server
```

libtmux's own pytest fixtures give each test a uniquely named server on the
default socket directory, which suits a suite that already runs in
`$TMUX_TMPDIR`. `Server.owned()` suits code that has no fixtures, or that must
not depend on the environment it runs in.

## Why `with Server()` does not do this

A {class}`~libtmux.Server` is a handle on a socket, and a bare `Server()`
addresses whichever daemon is already there. Leaving its `with` block kills
nothing unless you pass `kill_on_exit=True`. `Server.owned()` sets
`kill_on_exit=True` on the handle it yields, because it created the daemon.
See {ref}`context_managers`.
