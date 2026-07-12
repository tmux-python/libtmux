(self-location)=

# Locating yourself

Most libtmux code starts from a handle you already hold — you make a
{class}`~libtmux.Server`, you find a {class}`~libtmux.Session`, you walk down.
Sometimes you hold nothing, because your code is *running inside* a pane: a
script you launched in a split, a tmux hook, a test harness, an agent. Before it
can do anything useful it has to answer one question — **where am I?**

You don't have to search the server for yourself. tmux already told you. It
writes two variables into every pane it spawns, and each level of the hierarchy
reads them back:

| | |
|---|---|
| {meth}`Server.from_env() <libtmux.Server.from_env>` | the tmux server you are running on |
| {meth}`Session.from_env() <libtmux.Session.from_env>` | the session that holds you |
| {meth}`Window.from_env() <libtmux.Window.from_env>` | the window that contains you |
| {meth}`Pane.from_env() <libtmux.Pane.from_env>` | the pane you are running in |

If all you need is a handle on yourself, the first section is the whole story.
The rest is for the rarer cases: outside tmux, background panes, and windows that
live in more than one session.

To follow along live, start tmux, then run `python` *inside* a pane — that is
the situation this page is about:

```console
$ tmux
```

```console
$ python
```

## Ask where you are

Inside a pane each call takes no arguments. It reads {data}`os.environ`, which is
where tmux put the answer:

```python
>>> socket_path = server.cmd(
...     "display-message", "-p", "-t", session.session_id, "#{socket_path}"
... ).stdout[0]
>>> monkeypatch.setenv("TMUX", f"{socket_path},1,{session.session_id}")
>>> monkeypatch.setenv("TMUX_PANE", pane.pane_id)

>>> Pane.from_env().pane_id == pane.pane_id
True
>>> Window.from_env().window_id == window.window_id
True
>>> Session.from_env().session_id == session.session_id
True
```

That is the whole call — in a real pane tmux has already set those two variables
for you, and there is nothing to arrange. These docs are not running in a pane,
so the example sets them first.

Once you hold any of the four you are back on the hierarchy, and everything in
{ref}`traversal` applies.

Each call also accepts an environment *mapping* in place of {data}`os.environ`.
The examples below pass one explicitly, and it is the seam your own tests can use
— see {ref}`self-location-testing`.

```python
>>> socket_path = server.cmd(
...     "display-message", "-p", "-t", session.session_id, "#{socket_path}"
... ).stdout[0]
>>> env = {
...     "TMUX": f"{socket_path},1,{session.session_id}",
...     "TMUX_PANE": pane.pane_id,
... }

>>> Session.from_env(env).session_id == session.session_id
True
```

## When you are not in tmux

There is no pane to return, and answering with somebody else's would be worse
than not answering, so all four raise {exc}`~libtmux.exc.NotInsideTmux`. Catch it
when your program is meant to run inside a pane *and* out:

```python
>>> from libtmux import exc

>>> try:
...     here = Pane.from_env({})
... except exc.NotInsideTmux:
...     here = None

>>> here is None
True
```

## The window that contains you, not the one in front

A background pane is still somewhere. {meth}`Window.from_env()
<libtmux.Window.from_env>` returns the window that *contains* you, which is not
the window someone happens to be looking at:

```python
>>> socket_path = server.cmd(
...     "display-message", "-p", "-t", session.session_id, "#{socket_path}"
... ).stdout[0]
>>> worker_window = session.new_window(window_name="worker", attach=False)
>>> worker = worker_window.active_pane
>>> env = {
...     "TMUX": f"{socket_path},1,{session.session_id}",
...     "TMUX_PANE": worker.pane_id,
... }

>>> session.active_window.window_id == worker_window.window_id
False

>>> Window.from_env(env).window_id == worker_window.window_id
True
```

{attr}`session.active_window <libtmux.Session.active_window>` answers a different
question — *what is focused*.

## The server answers, not the environment

`TMUX` looks like it settles the session question on its own. Its three fields are
`socket_path,server_pid,session_id`, and that last one is a session id.

Don't reach for it. tmux writes these variables into a pane's environment *once*,
when it spawns the pane, and never revises them — a running process's environment
is not something tmux can rewrite. Move the pane's window to another session and
the pane really is somewhere else, while `TMUX` still names the session it was
born in.

So `from_env` anchors on `TMUX_PANE`, the one id tmux keeps answering for live,
and asks the server where that pane is *now*:

```python
>>> socket_path = server.cmd(
...     "display-message", "-p", "-t", session.session_id, "#{socket_path}"
... ).stdout[0]
>>> worker_window = session.new_window(window_name="worker", attach=False)
>>> worker = worker_window.active_pane
>>> env = {
...     "TMUX": f"{socket_path},1,{session.session_id}",  # names *this* session
...     "TMUX_PANE": worker.pane_id,
... }

>>> elsewhere = server.new_session(session_name="elsewhere")
>>> _ = worker_window.move_window(session=elsewhere.session_id, no_select=True)

>>> Session.from_env(env).session_name  # where the pane is, not where TMUX says
'elsewhere'
```

The same staleness is why {attr}`pane.session <libtmux.Pane.session>` resolves
through {attr}`pane.window <libtmux.Pane.window>` instead of reading the
`session_id` it is already carrying: a {class}`~libtmux.Pane` you fetched earlier
remembers the session it was in *then*. The extra round-trip is what keeps the
answer current. If you read it in a loop, bind it to a variable once.

## When a window belongs to two sessions

`link-window` puts a single window in several sessions at once, and then the pane
genuinely belongs to all of them. Asked "which session am I in?", there is more
than one true answer.

libtmux does not invent a tie-break. tmux already has to settle this every time
you type a command with a `-t` target, so libtmux asks it, and hands you back the
session tmux itself would act on. Below, the pane's window is linked into a
second session — `holders` shows it really is in both — and libtmux answers with
the session tmux's own `display-message -t` names:

```python
>>> socket_path = server.cmd(
...     "display-message", "-p", "-t", session.session_id, "#{socket_path}"
... ).stdout[0]
>>> home = server.new_session(session_name="aaa-home")
>>> shared = home.new_window(window_name="shared", attach=False)
>>> worker = shared.active_pane
>>> env = {
...     "TMUX": f"{socket_path},1,{home.session_id}",
...     "TMUX_PANE": worker.pane_id,
... }

>>> guest = server.new_session(session_name="zzz-guest")
>>> _ = server.cmd(
...     "link-window", "-s", shared.window_id, "-t", f"{guest.session_id}:"
... )

>>> holders = {p.session_name for p in server.panes.filter(pane_id=worker.pane_id)}
>>> holders == {"aaa-home", "zzz-guest"}
True

>>> tmux_says = server.cmd(
...     "display-message", "-p", "-t", worker.pane_id, "#{session_name}"
... ).stdout[0]
>>> Session.from_env(env).session_name == tmux_says
True
```

So the rule, in full: `TMUX_PANE` says which pane you are, and tmux says which
session that pane is in — including when the answer is contested. The session id
in `TMUX` is never read, not even as a tie-break. It records where the process was
*spawned*, which is a different fact from where it is, and one that goes stale.

## There is no `Client.from_env()`

A {class}`~libtmux.Client` is an attached terminal, and a pane is not owned by
one. No client may be attached at all — a detached session, a CI job, a
`send-keys` script all run with a perfectly good `TMUX_PANE` and nobody watching
— or several may be, each with its own view. tmux exports no client id into a
pane, so there is nothing to read back. See {ref}`clients` for the
view-versus-identity model this follows from.

(self-location-testing)=

## Testing code that locates itself

Every `from_env` takes an optional `env` mapping. Passing one is how you test a
function that locates itself without running your test suite inside a pane:

```python
>>> def announce(env=None):
...     """Report the session this code is running in."""
...     return Session.from_env(env).session_name

>>> socket_path = server.cmd(
...     "display-message", "-p", "-t", session.session_id, "#{socket_path}"
... ).stdout[0]
>>> env = {
...     "TMUX": f"{socket_path},1,{session.session_id}",
...     "TMUX_PANE": pane.pane_id,
... }

>>> announce(env) == session.session_name
True
```

In production `announce()` takes no argument and reads the real environment.

:::{seealso}
- {ref}`traversal` — walking the hierarchy once you hold a handle
- {ref}`clients` — why an attached terminal is a view, not an identity
- {class}`~libtmux.Server`, {class}`~libtmux.Session`, {class}`~libtmux.Window`,
  {class}`~libtmux.Pane` for the full API
:::
