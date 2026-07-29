(howto-find-the-session-youre-in)=

# Find the session you're in

A script running in a pane usually wants the session around it, not a session
it names: log to the session you were launched in, open a window beside your
own, refuse to run twice in the same one.
{meth}`Session.from_env() <libtmux.Session.from_env>` hands you that
{class}`~libtmux.Session` with no arguments and no search.

```python
from libtmux.session import Session

session = Session.from_env()

print(f"{session.session_name} ({session.session_id})")
```

The call raises {exc}`~libtmux.exc.NotInsideTmux` outside a pane, so wrap it
the way {ref}`howto-detect-you-are-inside-tmux` shows if your program has to
run both in and out of tmux.

`$TMUX` carries a session id as its third field, and parsing it out yourself
looks like it would save the round-trip. It would also be wrong: tmux writes
that value once, when it spawns the pane, and never revises it, so it names
where your process was *born* rather than where it lives. Move the window into
another session and the id lies. `from_env` asks tmux instead —
{ref}`self-location` has the full account.

## Back onto the hierarchy

Once you hold the session you hold everything under and above it:
{attr}`session.windows <libtmux.Session.windows>` for its windows,
{attr}`session.server <libtmux.Session.server>` for the server it lives on.
Finding yourself is only the first hop of a walk that {ref}`traversal`
describes in full.

```python
for other in session.server.sessions:
    marker = "*" if other.session_id == session.session_id else " "
    print(f"{marker} {other.session_name}")
```

The object you get back is a snapshot. `session.session_name` is the name tmux
reported at the moment you asked, so a rename that happens afterwards — by you,
by the user, by a hook — leaves it stale. Call
{meth}`~libtmux.Session.refresh` to re-read it, or call `Session.from_env()`
again; the id never changes, so either is safe to redo.

## Related

- {ref}`self-location` — why the session id in `$TMUX` is never read.
- {ref}`howto-find-the-window-youre-in` — the window inside that session.
- {ref}`traversal` — walking the hierarchy once you hold a handle.
