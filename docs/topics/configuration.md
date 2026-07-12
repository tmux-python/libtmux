# Configuration

You configure libtmux through Python: there are no config files, and you
set everything through method calls on {class}`~libtmux.Server`,
{class}`~libtmux.Session`, {class}`~libtmux.Window`, and
{class}`~libtmux.Pane` objects, with sensible defaults. If you're driving
tmux through the standard object API, you're already configured correctly
and can stop reading here.

The rest of this page is for the rarer cases. It documents two lower
layers you can reach for when the defaults aren't enough: the
environment variables libtmux reads, and the format-string system
libtmux uses internally to read tmux state.

## Environment variables

You set almost nothing here. The two variables that matter most, tmux
writes for you and libtmux only reads back, so a normal Python process
driving tmux has nothing to arrange in this section.

tmux exports both into every pane it spawns:

| Variable | What tmux puts in it |
|---|---|
| `TMUX` | the server that pane belongs to, as `socket_path,server_pid,session_id` |
| `TMUX_PANE` | the id of the pane itself, e.g. `%1` |

Code running *inside* a pane — a script you started in a split, a hook, a
test harness — reads them back to get a handle on itself, rather than
searching the server for a pane it already is. That is the `from_env`
family: {meth}`Server.from_env() <libtmux.Server.from_env>`,
{meth}`Session.from_env() <libtmux.Session.from_env>`,
{meth}`Window.from_env() <libtmux.Window.from_env>`, and
{meth}`Pane.from_env() <libtmux.Pane.from_env>`. Outside a pane neither
variable is set, and all four raise {exc}`~libtmux.exc.NotInsideTmux`.
You never write them yourself: {ref}`self-location` covers what each call
does with them, why the session id in `TMUX` goes stale, and the `env`
mapping you hand `from_env` in tests instead of touching the real
environment.

tmux reads `TMUX` too — it is how tmux notices you are already inside a
session and guards against nesting one. {meth}`Server.new_session()
<libtmux.Server.new_session>` unsets it for the length of that one call
and restores it afterward, so creating a session from inside a pane works
without you arranging anything.

That leaves the two variables that *are* yours to set, and most people
set neither. `TMUX_TMPDIR` is tmux's own — the directory it keeps sockets
in. libtmux never reads it, but the tmux binary it shells out to does, so
it shapes which server a bare {class}`~libtmux.Server` lands on; pass
`socket_name` or `socket_path` when you would rather name the server
outright. `LIBTMUX_TMUX_FORMAT_SEPARATOR` is the one variable libtmux
itself defines: an advanced override for the separator (default `␞`) it
uses internally to parse tmux's format output — you'd touch it only if
that character ever collided with your own data.

## Format strings

When you read a typed attribute like {attr}`~libtmux.Window.window_name`
or {attr}`pane.pane_current_path <libtmux.Pane.pane_current_path>`, libtmux is
querying tmux behind the scenes through tmux's own format system. The format
constants that drive those
queries live in {mod}`libtmux.formats` and are used internally by every
object type, so in normal use you never write format strings yourself —
the typed attributes on each object hand you the values directly.

For the rarer case where you want to know exactly which formats tmux
exposes, see the [tmux man page](http://man.openbsd.org/OpenBSD-current/man1/tmux.1)
for the full list.
