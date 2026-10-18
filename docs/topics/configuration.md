# Configuration

{class}`~libtmux.Server` captures one tmux endpoint when you construct it.
You can use ordinary defaults, pass a socket selector, or configure the same
program from its launch environment. Commands and cleanup retain that
endpoint after you change the host environment.

## Environment variables

The first selected value wins:

1. An explicit `socket_path` or `socket_name`. Passing both raises `ValueError`.
2. Nonempty `LIBTMUX_SOCKET_PATH`.
3. Nonempty `LIBTMUX_SOCKET_NAME`.
4. Nonempty `TMUX`, parsed as `socket_path,server_pid,session_id`.
5. The named `default` socket.

Empty environment selectors count as absent. An invalid selected value raises
without trying a lower priority selector. Lower priority values cannot
invalidate an explicit choice. Paths must be absolute and contain no NUL;
libtmux preserves spaces and commas. Socket names must be nonempty leaf
names without `/`, `\`, NUL, `.` or `..`.

For a named/default socket, libtmux captures nonempty `TMUX_TMPDIR` or `/tmp`
and derives `<root>/tmux-<uid>/<name>`. The supplied root must be absolute
and exist when you issue a command. Libtmux creates the private per-UID
directory if needed, checks its owner and permissions, and passes the captured
path to tmux. A missing or removed root raises; an explicit path does not
create its parent directory. `socket_path` exposes the captured absolute
path for named sockets too. `socket_name_factory` supplies an explicit name
when you omit both explicit selectors.

`TMUX` splits from the last two commas so the socket path can contain commas.
Its PID must be positive ASCII decimal; its session field accepts a
nonnegative ASCII decimal ID, one optional `$` prefix, or tmux's `-1`
no-session sentinel. Malformed context raises
{exc}`~libtmux.exc.NotInsideTmux`. The selected path still requires an
absolute path. {meth}`Server.from_env() <libtmux.Server.from_env>` reads a
supplied mapping or the host `TMUX` context; child
{meth}`Session.from_env() <libtmux.Session.from_env>`,
{meth}`Window.from_env() <libtmux.Window.from_env>`, and
{meth}`Pane.from_env() <libtmux.Pane.from_env>` also resolve `TMUX_PANE`
against the live server. See {ref}`self-location` for pane context.

## Client and tmux environments

`child_environment` supplies overrides for a copy of the host environment at
construction. The endpoint resolver reads that copy, then client launches
receive its immutable snapshot with `TMUX` and `TMUX_PANE` removed. Commands,
including {meth}`Server.new_session() <libtmux.Server.new_session>`, leave the
host environment unchanged. `child_environment` cannot redirect an explicit
socket selector. There is no `LIBTMUX_SOCKET_ENV` variable.

The constructor also resolves `tmux_bin` against the captured `PATH` and working directory. `server.tmux_bin` reports that absolute path, or `None` when a bare executable name was not found. Adding an executable to `PATH` later does not repair an existing handle; construct a new one. The captured path preserves filesystem traversal, including symlinks and `..`; it does not pin the executable's bytes against replacement on disk. Commands, object queries, control clients, health checks and version probes all use this path and the captured environment. Each handle caches its own version probe. The standalone `libtmux.common.get_version()` and `get_version_str()` functions keep their separate process-wide caches.

The `environment=` argument to session, window and pane creation configures
tmux's environment for those resources. Methods such as
{meth}`~libtmux.common.EnvironmentMixin.set_environment` change tmux's
server/session environment. They do not edit a handle's captured client
environment or restore earlier tmux values on scope exit.

{class}`~libtmux.test.environment.EnvironmentVarGuard` edits process-global
variables and restores their original value or absence after repeated edits
and exceptions. Concurrent writers share that host state. Prefer a child
environment for an external example harness: it leaves the parent's
environment unchanged and keeps whole-server cleanup outside the ordinary
program. The repository's `tests/test_example_harness.py` executes
`examples/session_scope.py` unchanged using both socket selector variables,
checks session cleanup after success and body failure, then destroys its
private server. On Linux it checks daemon exit through a retained PID handle
and checks the endpoint before releasing its temporary root.

`LIBTMUX_TMUX_FORMAT_SEPARATOR` configures the separator (default `␞`) used
to parse tmux's format output. It has no role in endpoint selection.

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
