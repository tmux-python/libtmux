(howto-detect-you-are-inside-tmux)=

# Detect that you are inside tmux

tmux tells its children where they are. Every pane it spawns gets two
environment variables — `$TMUX`, holding the server's socket path, and
`$TMUX_PANE`, holding the pane's id — and every process descended from that
pane's shell inherits them. So "am I inside tmux?" is not a search. It is a
question your own environment already answers.

{meth}`Server.from_env() <libtmux.Server.from_env>` asks it. Inside a pane it
returns a {class}`~libtmux.Server` bound to the socket you are running on;
outside one it raises {exc}`~libtmux.exc.NotInsideTmux`. That is the whole
detection, and for most scripts it is the whole page.

```python
from libtmux import exc
from libtmux.server import Server

try:
    server = Server.from_env()
except exc.NotInsideTmux:
    server = None

if server is None:
    print("running outside tmux")
else:
    print(f"running inside tmux on {server.socket_path}")
```

Reading `os.environ["TMUX"]` yourself would answer the same question less
carefully. `from_env` also checks the value's *shape* — tmux writes
`socket_path,server_pid,session_id`, and a truncated or hand-edited value is
not a socket you want to hand onward — so a malformed `$TMUX` raises here
rather than surfacing later as a confusing tmux error.

The socket matters as much as the answer. A bare `Server()` means tmux's
default socket, which is a guess about where you are; the server `from_env`
hands back is the one you are actually inside, whatever socket name or path it
was started with.

## Inside tmux is not the same as tmux being reachable

`from_env` costs no subprocess. It is a read of your own environment, so what
it really establishes is your process's ancestry: you were spawned by a pane.
It does not confirm anything is still listening on the other end of that
socket, and it cannot — the variables are frozen into your environment at spawn
time and tmux never revises them. Kill the server while your script runs and
`$TMUX` still names it.

If your script is about to *do* something with that server rather than merely
report on it, follow the detection with a liveness check.

```python
if server is not None:
    if server.is_alive():
        print(f"{len(server.sessions)} session(s) on this server")
    else:
        print("the server named by $TMUX is gone")
```

Two cheap calls, two different facts: {meth}`~libtmux.Server.from_env` says
where you came from, {meth}`~libtmux.Server.is_alive` says whether it is still
there. See {ref}`howto-check-if-tmux-is-running` for what liveness does and
does not tell you.

## Related

- {ref}`self-location` — the model behind `from_env`, including why the
  session id inside `$TMUX` is never read.
- {ref}`howto-find-the-pane-youre-in` — go from "inside tmux" to the pane
  itself.
- {ref}`howto-check-if-tmux-is-running` — the same question about a server you
  are *not* running inside.
