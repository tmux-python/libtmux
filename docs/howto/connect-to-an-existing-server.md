(howto-connect-to-an-existing-server)=

# Connect to an existing tmux server

A {class}`~libtmux.Server` is a handle, not a connection. Constructing one opens
nothing, starts nothing and verifies nothing — it records which socket you mean,
and every method you call afterwards runs one tmux command against that socket.
So "connecting" to a server someone else started is just naming their socket
correctly, and then checking that something is listening on it.

There are two ways to name one. `socket_name=` is tmux's `-L`: a short name that
tmux resolves inside its own socket directory, and the same name you would pass
to `tmux -L`. `socket_path=` is tmux's `-S`: an absolute path, which is what you
need when the socket sits somewhere tmux would not look — a container mount, a
service's runtime directory, a path some other tool chose. `Server()` with
neither argument means tmux's `default` socket, the one a bare `tmux` in your
shell uses.

## See what is out there

Sockets named with `-L` all land in one directory, so listing it answers "what
could I connect to":

```python
import os
import pathlib

socket_dir = (
    pathlib.Path(os.environ.get("TMUX_TMPDIR", "/tmp")) / f"tmux-{os.geteuid()}"
)
sockets = sorted(path for path in socket_dir.glob("*") if path.is_socket())

for path in sockets:
    print(path.name)
```

Treat that as a list of candidates, not of servers. tmux does not remove a
socket file when its daemon exits, so a name in the listing may be the leftover
of a server that died last week. The file existing is not the answer to your
question.

## Point a handle at one, then confirm

```python
from libtmux import Server

server = Server(socket_name="libtmux-howto")

if server.is_alive():
    for session in server.sessions:
        print(session.session_name, len(session.windows), "window(s)")
else:
    print("no tmux server is listening on that socket")
```

{meth}`~libtmux.Server.is_alive` before you trust the handle is the whole
ceremony, and it matters more here than anywhere else, because the accessors are
deliberately lenient. {attr}`~libtmux.Server.sessions` returns an empty
{class}`~libtmux._internal.query_list.QueryList` when tmux's `list-sessions`
fails for *any* reason — a socket that never existed, a daemon that exited, a
permission error. A handle pointed at nothing therefore reads exactly like a
healthy server with no sessions, and only the liveness check tells the two
apart. {ref}`howto-check-if-tmux-is-running` goes into how to get the reason
rather than the verdict.

## Connect by path instead

Everything above works the same when you address the socket by path — you are
handing tmux `-S` rather than `-L`, so nothing has to be resolvable in tmux's
socket directory:

```python
by_path = Server(socket_path=socket_dir / "libtmux-howto")

print(by_path.is_alive())
print([s.session_name for s in by_path.sessions])
```

One thing not to expect from this: `by_path` and the `server` above address the
same daemon but are *not* equal, because the two constructor arguments are
independent attributes and libtmux fills in neither from the other. See
{ref}`howto-run-multiple-servers` for why, and what to compare instead.

## When your code already runs inside tmux

If your process was spawned by tmux — a script you launched in a pane, a hook, a
test harness — don't go looking for the socket. tmux exported it into your
environment, and {meth}`Server.from_env() <libtmux.Server.from_env>` reads it
back with no subprocess at all. {ref}`self-location` covers that whole family,
down to the pane you are running in.

## Related

- {ref}`howto-check-if-tmux-is-running` — telling "no server" from "no sessions".
- {ref}`howto-run-multiple-servers` — the sockets you would be connecting to.
- {ref}`traversal` — walking from the server you connected to down to its panes.
