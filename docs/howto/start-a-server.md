(howto-start-a-server)=

# Start a tmux server

You don't really start a tmux server — you ask for something that needs one, and
tmux boots the daemon underneath you. libtmux inherits that bargain:
{meth}`~libtmux.Server.new_session` is the call that brings a server up, because
a session is the first thing a server has to hold.

That also settles a question people ask twice. "Start a server" and "start a
server in the background" are the same operation here. Attaching means handing a
terminal over to tmux, and a Python process running a script has none to hand
over — so every server you start from Python is detached from the moment it
exists, and it keeps running after your process exits. There is no flag to pass
and nothing to daemonize.

## Bring one up

```python
from libtmux import Server

server = Server(socket_name="libtmux-howto")
session = server.new_session(session_name="worker", kill_session=True)

print(f"{session.session_name} is up: {server.is_alive()}")
```

Two arguments there are habits worth keeping. Naming the socket puts this daemon
beside the tmux you already have open rather than inside it, so nothing here can
disturb your real sessions — see {ref}`howto-run-multiple-servers` for what that
separation buys. And `kill_session=True` replaces a `worker` session left over
from an earlier run instead of raising {exc}`~libtmux.exc.TmuxSessionExists`,
which is what you want from a script you are still writing.

## The daemon is not your handle

A {class}`~libtmux.Server` object records which socket you mean; the daemon is a
separate process with its own lifetime. Throwing the handle away does nothing to
it, and a fresh handle pointed at the same socket finds the same sessions —
which is also what happens when your script exits and you come back tomorrow.

```python
del server

reconnected = Server(socket_name="libtmux-howto")

print(reconnected.is_alive())
print([s.session_name for s in reconnected.sessions])
```

:::{warning}
{meth}`Server.__exit__ <libtmux.Server.__exit__>` **kills the server**, so
`with Server(socket_name="libtmux-howto") as server:` starts a daemon and
destroys it, and everything in it, at the end of the block. That is occasionally
what you want — see {ref}`context_managers` — but it is the opposite of starting
a server that outlives you.
:::

## Attach to it from a shell

Once the server is up you look at it from a terminal, naming the same socket:
`tmux -L libtmux-howto attach-session -t worker`. Detach with your prefix key
and `d`, and the server stays up behind you.

Doing that from Python is not an option. {meth}`~libtmux.Session.attach` runs
tmux's `attach-session`, which needs a terminal to take over and fails when
there is none behind the process — the same reason a server you start from a
script is detached whether you asked for that or not. So the division of labour
is: start and drive the server from Python, attach from a shell when you want to
watch it.

## `start_server` is not the one you want

tmux has a `start-server` command and libtmux exposes it as
{meth}`~libtmux.Server.start_server`, which makes it look like the obvious way to
launch a daemon. Run it and you get nothing:

```python
empty = Server(socket_name="libtmux-howto-empty")
empty.start_server()

print(empty.is_alive())

reconnected.kill()
```

That prints `False`. tmux's `exit-empty` option is on by default, and it tells a
server holding no sessions to exit immediately — so the daemon `start-server`
booted is already gone by the time the next command reaches its socket. Create
the session and let tmux start the server for you.

{meth}`~libtmux.Server.kill` is how you take one down again, and it takes every
session on that socket with it.

## Related

- {ref}`howto-run-multiple-servers` — one daemon per socket, and why that is the
  isolation boundary.
- {ref}`howto-connect-to-an-existing-server` — point a handle at a server
  somebody else started.
- {ref}`howto-check-if-tmux-is-running` — the liveness question on its own.
- {ref}`about` — what a `Server` object is a proxy for.
