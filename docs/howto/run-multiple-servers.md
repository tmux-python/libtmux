(howto-run-multiple-servers)=

# Run multiple tmux servers

tmux runs one daemon per socket, and a socket is the real isolation boundary —
not a session. Name a second socket and you get a second server that shares
nothing with the first: its own sessions, its own windows and panes, its own
options, its own attached clients. Killing one cannot touch the other.

Reach for this when work must not collide: a test suite that has to stay out of
your editor's tmux, a daemon per project, a scratch server you can destroy
wholesale without thinking about what else lives there.

## Two servers, same session name

```python
from libtmux import Server

alpha = Server(socket_name="libtmux-howto-alpha")
beta = Server(socket_name="libtmux-howto-beta")

alpha_build = alpha.new_session(session_name="build", kill_session=True)
beta_build = beta.new_session(session_name="build", kill_session=True)

print([s.session_name for s in alpha.sessions])
print([s.session_name for s in beta.sessions])
```

Both sessions are called `build` and neither daemon knows the other exists.
Session names only have to be unique within a server, so per-socket separation
lets you use the same vocabulary — `build`, `test`, `shell` — in every project
without inventing prefixes.

## Everything below the server is per-server too

{attr}`Server.windows <libtmux.Server.windows>` and {attr}`Server.panes
<libtmux.Server.panes>` flatten every window and pane on that socket into one
list. They stop at the socket, exactly like {attr}`~libtmux.Server.sessions`
does, so adding a window to `alpha` leaves `beta` reporting what it always did.

```python
alpha_build.new_window(window_name="tests")

print(len(alpha.windows), len(alpha.panes))
print(len(beta.windows), len(beta.panes))
```

Those flattened collections are the fastest way to ask a whole server a
question — {ref}`querylist-filtering` covers filtering them.

## Two handles for one daemon are not equal

Here is the trap. `socket_name=` and `socket_path=` are independent attributes,
and libtmux never derives one from the other: a server built with a name keeps
{attr}`~libtmux.Server.socket_path` at `None` forever, even though tmux
obviously resolved a path to reach the daemon.
{meth}`Server.__eq__ <libtmux.Server.__eq__>` compares both attributes, so two
handles addressing the identical daemon — one by name, one by that same socket's
path — compare unequal.

```python
socket_path = alpha.cmd("display-message", "-p", "#{socket_path}").stdout[0]
same_daemon = Server(socket_path=socket_path)

print(alpha.socket_path)
print(same_daemon.is_alive(), [s.session_name for s in same_daemon.sessions])
print(same_daemon == alpha)

alpha.kill()
beta.kill()
```

The second line proves they are the same server: `same_daemon` is alive and sees
`alpha`'s sessions. The third line still prints `False`. Equality is answering a
narrower question than it looks like — *are these handles configured the same
way* — and it cannot see through to the daemon they share.

So don't use `==` to decide whether two handles mean the same server. Build one
handle per daemon and pass that object around; when you genuinely have to
compare handles that were constructed differently, compare what tmux resolved
them to by asking each for `#{socket_path}`, as above.

## Related

- {ref}`howto-start-a-server` — what actually boots a daemon.
- {ref}`howto-connect-to-an-existing-server` — `socket_name=` against
  `socket_path=`, and finding the sockets that exist.
- {ref}`context_managers` — scope a whole throwaway server to a `with` block.
- {ref}`about` — the Server → Session → Window → Pane hierarchy each socket
  carries its own copy of.
