# Compatibility

## Python

- **Minimum**: Python 3.10
- **Tested**: Python 3.10, 3.11, 3.12, 3.13
- **Maximum**: Python < 4.0

## tmux

Core operations require tmux **3.3a or newer**, including the patch letter.
Tmux 3.3 is below the minimum. The CI matrix includes 3.3a and later releases;
`master` is a development lane.

Commands check the connected daemon, which can differ from the selected
client executable. An absent endpoint uses the executable's fresh version
report before startup. Raw commands, batches and liveness checks share this
rule. An unsupported or unreadable version raises
{exc}`~libtmux.exc.VersionTooLow` before the requested command runs.
A replacement daemon is checked again before dispatch.
{meth}`~libtmux.Server.kill` returns without dispatching when its endpoint is
absent.

Each command adds a read-only version query, bounded to five seconds. Admission
does not cache daemon versions. Binary diagnostics through `tmux -V` and
`tmux -h` remain available. Raw `tmux -c` shell execution is refused; use
{meth}`~libtmux.Server.run_shell` for a tmux command instead.

Numbered development reports are accepted as candidates when their release
base meets the baseline; a `next-` build precedes the release it names. These
candidates do not inherit stable feature qualification. Unknown reports,
including an undated `master`, are refused. On OpenBSD, an existing daemon
must report a qualified release; an executable without `-V` cannot start an
absent endpoint.
The synthetic values returned by legacy version helpers are diagnostic values
and never authorize a command.

If a checked daemon disappears before dispatch, that command fails without
starting the configured executable. Retry against the absent endpoint to
validate the executable before creating a replacement.

Individual features can require a newer daemon. Their API documentation states
those requirements. Raising the core floor does not qualify control startup,
output synchronization or other optional behavior on every later release.

## Platforms

| Platform | Status |
|----------|--------|
| Linux | Fully supported |
| macOS | Fully supported |
| WSL / WSL2 | Supported (tmux runs inside WSL) |
| Windows (native) | Not supported (tmux does not run natively on Windows) |

## Known Limitations

- tmux must be running and accessible via the default socket or a specified socket
- Some operations require the tmux server to have at least one session
- Format string availability depends on tmux version
