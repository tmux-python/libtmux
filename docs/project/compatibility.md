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

Each {class}`~libtmux.Server` probes its endpoint once, bounded to five
seconds, and reuses the checked release for later commands and optional-flag
decisions. The version fence in every command catches a replaced daemon: it
refuses with no effect and the next command probes again. A vanished daemon is
detected and the next command checks the version again; {meth}`~libtmux.Server.kill` and
an absent endpoint always read the endpoint directly. The query is `run-shell -C` with a marker format, which
fires neither `after-*` hooks nor `command-error`, so a user's hooks never run
for a version check. It exits 1 with the version in its error text. If a replaced
daemon fails the fence on tmux 3.5 or newer, `command-error` fires once for
that refusal, which reports a real error. Binary diagnostics through `tmux -V` and
`tmux -h` remain available. Raw `tmux -c` shell execution is refused; use
{meth}`~libtmux.Server.run_shell` with its documented output mode.

The version check reads the forms tmux reports: a release with an optional patch
letter (`3.3a`), a candidate (`3.8-rc`, `3.8-rc2`) and a development build
(`next-3.9`). They order as `next-3.9` < `3.9-rc` < `3.9-rc2` < `3.9` < `3.9a`,
and minor numbers compare numerically, so a candidate or development build is
supported only when its release number is above the baseline. Such builds do not
inherit stable feature qualification. Everything else is refused: an undated
`master`, a development suffix on a release (`3.3a-dev`), a patch letter on a
development build (`next-3.3a`), leading zeros and OpenBSD's own numbering. On
OpenBSD, an existing daemon must report a qualified release; an executable
without `-V` cannot start an absent endpoint.
The synthetic values returned by legacy version helpers are diagnostic values
and never authorize a command.

If a checked daemon disappears before dispatch, that command fails without
starting the configured executable. Retry against the absent endpoint to
validate the executable before creating a replacement.

Individual features can require a newer daemon. Their API documentation states
those requirements. Raising the core floor does not qualify control startup,
output synchronization or other optional behavior on every later release.

### Optional features

| Operation | Eligible daemon and behavior |
|-----------|------------------------------|
| Ordinary subprocess operations | 3.3a+. Core support continues independently of control availability. |
| `ControlMode` and the pytest control fixture | Stable numbered releases from 3.7, with a local Unix socket whose filesystem permits a private hard link. Refused before control startup on older or unqualified development builds. |
| Explicit named-buffer deletion and rename | 3.4+. On 3.3a, a missing name can select an unrelated top buffer, so these requests are refused before dispatch. |
| Buffer reads, writes, unnamed deletion and explicit named paste-and-delete | Available on 3.3a+. Named paste-and-delete rejects a missing name before any paste or deletion. It does not replace temporary-buffer abort cleanup. |
| Captured shell-job stdout from `Server.run_shell` | 3.5+. On 3.3a and 3.4, the method refuses the capture before the job starts. |
| Background jobs, pane-directed output and `as_tmux_command=True` | Available on 3.3a+. Background and pane-directed calls return `None`; background launch does not promise job completion. |
| `Pane.split(percentage=...)` | Available on 3.3a+, using `-l N%`. Direct `split-window -p` is refused on the affected 3.4 interval. |
| `break-pane` on exact 3.7 | Raw calls and unnamed typed calls are refused. `Pane.break_pane(window_name=...)` applies the explicit name after the move. A later rename failure can leave the moved pane in its new window. |
| `break-pane` on other supported releases | Native behavior is retained. The exact-3.7 restriction does not raise their minimum. |
| Single-pane `break-pane` before 3.6 | Native success prints no window ID. The typed method rereads the pane's actual window after the command. |
| Literal `select-layout` on 3.3a | Require a unique native preset or a serialized layout header before dispatch. Unknown names and malformed headers are refused before any batch effect; valid presets, layout cycling and undo remain available. |
| Window names containing `:` or `.` | Exact 3.7 rejects creation before creating a window. Other tested supported releases retain those names. There is no automatic name substitution. |

Eligibility comes from the selected daemon, including when a newer client is
used. Native dispatch checks the release again before executing the
operation. Feature guards cover direct literal native built-in command items,
their native aliases, abbreviations and batches. They do not interpret opaque
user-authored programs or expand configured command aliases; those contents
remain outside this guarantee.
Raw command stdout is native client output; it does not promise capture of a
nested shell job's stdout.

Backend consumers can require
`libtmux.common.TMUX_OPTIONAL_FEATURE_POLICY_VERSION >= 2` before handing off
work. This identifies the feature enforcement contract in the table; each
operation still checks its daemon and control acquisition still checks its
socket carrier.

On 3.3a, the layout guard validates the preset or serialized header before any
batch effect. Checksum, tree structure and pane-count errors retain native
reporting. The native missing-error-cause defect is fixed from 3.4 by
[the upstream layout repair](https://github.com/tmux/tmux/commit/f10854cfc5e43f646b02b3031bfc4bc3f5f6c513).

The version check assumes library-owned metadata and guard commands retain tmux's
built-in semantics. Owner `command-alias` redefinitions of commands such as
`display-message` or `if-shell` are outside qualification: tmux expands aliases
before resolving even a canonical built-in name.

Control holds a private socket alias for the owned client's lifetime. Failure
to retain or identify that socket refuses acquisition. The native alias and
replacement checks have been exercised on Linux/WSL; other filesystem and
platform combinations need their own qualification. A successful idle attach
does not establish concurrent or sustained-load stability.

Control also needs a natively compatible client. Native clients 3.3a, 3.4 and
3.5 fail to register with an exact-3.7 daemon; the daemon remains alive. A
newer compatible client can register with that same daemon. Ordinary client
operations retain the 3.3a minimum.

### Synchronization and testing

Version eligibility does not remove readiness, buffering or completion waits.
`ControlMode` waits for its own client registration. Shell automation should
use a complete output marker or state predicate, and streams must retain their
framing and cancellation handling. A background command's reply confirms launch.

CI retains ordinary older-server coverage. Only tests and documentation examples
that need an ineligible control client are skipped for that release; control
refusal tests still run. Captured-stdout and named-buffer tests assert refusals
on older daemons, and exact 3.7 tests exercise both single- and multi-pane naming.
The percentage-split test also runs on 3.4 through the portable encoding.

The release boundaries come from tmux's
[3.3a buffer operations](https://github.com/tmux/tmux/blob/0b355ae8114511e1ff6359272b164f1cdf718e80/cmd-set-buffer.c),
[3.4 repair](https://github.com/tmux/tmux/blob/9ae69c3795ab5ef6b4d760f6398cd9281151f632/cmd-set-buffer.c),
[3.5 shell output](https://github.com/tmux/tmux/blob/ac44566c9c7e3e94d23be6def4c7ae83472543f5/cmd-run-shell.c),
and [exact-3.7 break behavior](https://github.com/tmux/tmux/blob/81f88f8517c9fc5371b56cf117530c6b477c96ac/cmd-break-pane.c).

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
