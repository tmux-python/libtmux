(howto-check-if-tmux-is-running)=

# Check if tmux is running

A {class}`~libtmux.Server` is a handle, not a connection. Constructing one
costs nothing and starts nothing — it only records *which* socket you mean.
So holding a `Server` tells you nothing about whether a tmux server is
actually alive on the other end of it, and every attribute that reaches for
live state has to find out.

{meth}`~libtmux.Server.is_alive` is how you ask. It runs a single cheap
command against the socket and answers yes or no; it never starts a server and
never stops one.

```python
from libtmux import Server

server = Server()

if server.is_alive():
    print(f"tmux is running with {len(server.sessions)} session(s)")
else:
    print("tmux is not running")
```

`Server()` with no arguments means tmux's default socket — the same one a bare
`tmux` in your shell would use. Pass `socket_name=` or `socket_path=` to ask
about a different one.

:::{warning}
Ask about a server with a plain handle, as above. `Server` is also a context
manager, and {meth}`~libtmux.Server.__exit__` **kills the server** on the way
out — so `with Server() as server:` around a liveness check would end the very
tmux you were asking about, along with every session in it.
:::

## When you want the reason, not the answer

{meth}`~libtmux.Server.is_alive` folds every way of failing to reach a server
into a single `False`: no daemon, a socket that was deleted, a permission
error, a `tmux` binary that isn't on `PATH`. That is the right shape for a
branch, and the wrong shape for a diagnostic.

Reach for {meth}`~libtmux.Server.raise_if_dead` when you need to tell those
apart. It runs the same probe and lets the failure through:
{exc}`~libtmux.exc.TmuxCommandNotFound` when there is no tmux binary to run,
and {exc}`subprocess.CalledProcessError` when tmux ran and reported no server.

The same leniency governs the list accessors. {attr}`~libtmux.Server.sessions`
returns an empty {class}`~libtmux._internal.query_list.QueryList` when the
underlying `list-sessions` fails, for any reason at all — so an empty list
means "no sessions *or* no server", and only `is_alive()` or
`raise_if_dead()` will tell you which.

## Related

- {ref}`howto-send-keys-to-every-pane` — drive a session once you have one.
- {ref}`traversal` — walk from a live server down to its panes.
- {ref}`about` — what a `Server` handle is, and what it is not.
