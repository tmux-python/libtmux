# Configuration

## Environment Variables

libtmux itself does not read environment variables for configuration.
All configuration is done programmatically through the Python API.

The tmux server libtmux connects to may be influenced by standard tmux
environment variables (`TMUX`, `TMUX_TMPDIR`).

## Format Strings

libtmux uses tmux's format system to query state. Format constants are
defined in {mod}`libtmux.formats` and used internally by all object types.

See the [tmux man page](http://man.openbsd.org/OpenBSD-current/man1/tmux.1)
for the full list of available formats.
