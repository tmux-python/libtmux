# Configuration

You configure libtmux entirely through Python. There are no config files
and no environment variables that libtmux itself reads — you set
everything through method calls on {class}`~libtmux.Server`,
{class}`~libtmux.Session`, {class}`~libtmux.Window`, and
{class}`~libtmux.Pane` objects, and the defaults are sensible. If you're
driving tmux through the standard object API, you're already configured
correctly and can stop reading here.

The rest of this page is for the rarer cases. It documents two lower
layers you can reach for when the defaults aren't enough: the tmux
environment variables that decide which server you connect to, and the
format-string system libtmux uses internally to read tmux state.

## Environment variables

libtmux reads no environment variables of its own, so there's nothing to
set here in normal use. What can still matter is the tmux *server* you
connect to: the standard tmux variables `TMUX` (the address of an
existing server) and `TMUX_TMPDIR` (where tmux keeps its socket) shape
which server a fresh {class}`~libtmux.Server` finds. If you run several
servers, or point tmux at a custom socket directory, those two variables
decide which one you land on — otherwise you can ignore them.

## Format strings

When you read a typed attribute like {attr}`~libtmux.Window.window_name`
or `pane.pane_current_path`, libtmux is querying tmux behind the scenes
through tmux's own format system. The format constants that drive those
queries live in {mod}`libtmux.formats` and are used internally by every
object type, so in normal use you never write format strings yourself —
the typed attributes on each object hand you the values directly.

For the rarer case where you want to know exactly which formats tmux
exposes, see the [tmux man page](http://man.openbsd.org/OpenBSD-current/man1/tmux.1)
for the full list.
