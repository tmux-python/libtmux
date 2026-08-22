(howto-connect-to-an-existing-session)=

# Connect to an existing session

You already have tmux running — a session you started this morning, or one a
script left behind — and you want a {class}`~libtmux.Session` object pointing at
it. Nothing needs to be created. Constructing a {class}`~libtmux.Server` costs
nothing and starts nothing, and {attr}`~libtmux.Server.sessions` asks tmux for
the live list every time you read it, so finding a session is a lookup, not a
connection.

tmux keeps session names unique within a server, which makes a name a real key:
one name, at most one session. Start by reading what is there.

```python
from libtmux import Server

server = Server()

for session in server.sessions:
    print(f"{session.session_id}\t{session.session_name}")
```

`Server()` with no arguments means tmux's default socket — the same server a
bare `tmux` in your shell talks to. Pass `socket_name=` or `socket_path=` to
ask about a different one.

## Look one up by name

{meth}`~libtmux._internal.query_list.QueryList.get` pulls a single object out of
a collection. Passing `default=None` turns "not there" into a value you can
branch on instead of an exception.

```python
session = server.sessions.get(session_name="editor", default=None)

if session is None:
    print("no session named 'editor'")
else:
    print(f"editor holds {len(session.windows)} window(s)")
```

Swap `editor` for a name from the listing above. If that block printed *no
session named 'editor'*, fix the name before pasting the next one — everything
below works on the session it found.

:::{warning}
`get()` has two failure modes, and a `default` only covers one of them. With no
`default` it raises {exc}`~libtmux.exc.ObjectDoesNotExist` when nothing matches;
with a `default` it still raises {exc}`~libtmux.exc.MultipleObjectsReturned`
when more than one object does. A `default` stands in for an object that is
absent, never for a choice between candidates.

A lookup by `session_name` cannot be ambiguous, because tmux enforces
uniqueness. A lookup by any other attribute can —
`server.sessions.get(session_attached="0")` raises the moment two sessions are
detached. Use {meth}`~libtmux._internal.query_list.QueryList.filter` when a
query is allowed to match several objects; see {ref}`querylist-filtering`.
:::

An empty {attr}`~libtmux.Server.sessions` deserves the same suspicion. It is
empty when the server holds no sessions, and equally empty when tmux is
unreachable — a dead daemon, a deleted socket, a `tmux` binary that isn't on
`PATH`. Only {meth}`~libtmux.Server.is_alive` tells the two apart; see
{ref}`howto-check-if-tmux-is-running`.

## Hold the id, not the name

A session's name is a label its owner can change at any time. Its
{attr}`~libtmux.Session.session_id` — the `$`-prefixed value in the listing — is
assigned by tmux when the session is born and stays put until it dies. If you plan to come
back later, that is the value to remember.

{meth}`~libtmux.Session.from_session_id` turns one back into an object. It hands
the id straight to tmux as a target rather than scanning a listing, so it cannot
be ambiguous, and it raises {exc}`~libtmux.exc.TmuxObjectDoesNotExist` if the
session is gone.

```python
from libtmux import Session

session_id = session.session_id
found = Session.from_session_id(server, session_id)

print(found.session_name, found.session_id == session_id)
print(server.has_session("editor"), server.has_session("edit"))
```

{meth}`~libtmux.Server.has_session` is the cheap version of the question when
you want a yes or no rather than the object: one tmux call, no objects built.
It matches exactly by default, which is why `edit` is not `editor`. Pass
`exact=False` to get tmux's own pattern matching, where `edit` does match.

## Related

- {ref}`howto-connect-to-an-existing-window` — go one level down, into the
  session you just found.
- {ref}`traversal` — the whole Server → Session → Window → Pane chain, in both
  directions.
- {ref}`querylist-filtering` — every lookup operator `filter()` and `get()`
  accept.
