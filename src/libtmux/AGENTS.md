# AGENTS.md

Scope: `src/libtmux/**`. Root policy in the
[root `AGENTS.md`](../../AGENTS.md) still applies; this file adds the
facts specific to this package.

## Architecture notes

- Every tmux command goes through the `cmd()` method on `Server`,
  `Session`, `Window`, and `Pane`; it returns a `CommandResult` with
  `stdout` and `stderr`. Reach for it when there is no dedicated
  method.
- tmux's format-string system (`#{session_id}`, `#{window_name}`, …)
  is libtmux's query mechanism; format constants live in `formats.py`.
- An object can go stale when tmux state changes externally. Call
  `.refresh()` to reconcile it, or use the `neo` query interface,
  which always queries fresh.

## List-returning accessors: empty by default on tmux errors

`Server.sessions`, `Server.clients`, and `Server.attached_sessions`
return an empty `QueryList` when tmux's underlying list command fails
for any reason. Callers that need to distinguish an empty server from
an unreachable one use `Server.is_alive()` or `Server.raise_if_dead()`.

Keep list-shaped accessors lenient by default. Add an explicit opt-in
for loud failure rather than changing an existing accessor's contract.

## Logging

### Ownership

- Use `logging.getLogger(__name__)` only in modules that emit records.
- Keep handlers, levels, and formatters under application control.
- `_internal/log_context.py` owns structured context:
  `command_extra(argv)` describes a command and
  `object_extra(subcommand, ...)` describes an object operation.
- `tmux_cmd` is the sole producer of subprocess dispatch and
  completion records. Do not duplicate them in query or object layers.
- Control mode uses the same command context, then retains it for its
  client lifecycle.

### Command records

`tmux_cmd` emits `DEBUG` before and after a subprocess. The
`tmux_cmd` field contains a quoted, one-line rendering of the complete argv.
Printable values use shell quoting; control characters use escaped forms.
Completion records retain the first 100 stdout and stderr lines alongside
`tmux_stdout_len` and `tmux_stderr_len`. Keep command-specific redaction,
alias maps, and output classifiers out of the producer; applications select
fields through standard-library handlers and formatters. Treat derived
subcommand and socket fields as best effort and stop parsing unknown options.

Guard command-context construction with
`logger.isEnabledFor(logging.DEBUG)`. Use lazy interpolation for any
message arguments.

### Levels and failures

| Level | Contract |
| ----- | -------- |
| `DEBUG` | Subprocess dispatch/completion and internal lookup details |
| `INFO` | Successful server, session, window, and pane lifecycle events |
| `WARNING` | A recoverable problem libtmux handled, aggregated once per item |
| `ERROR` | A failure libtmux intentionally swallowed |

Propagated or translated failures stay in their exceptions; do not
catch, log, and re-raise. A non-zero tmux exit is not enough to justify
an `ERROR` because probes use it to answer false.
`Server.is_alive()` stays quiet.

Normalize executable-launch `ENOENT`, `EACCES`, and `ENOEXEC` errors to
`TmuxCommandNotFound`, preserving the operating-system message and cause.
Keep unrelated `OSError` behavior caller-specific. A failed `PATH` preflight
uses a factual message without inventing a cause.

`Server.sessions` and `Server.clients` log once in
`libtmux.server` when they convert `LibTmuxException` to an empty
result. `Server.attached_sessions` inherits that behavior through
`Server.sessions`. The boundary record includes the subcommand,
socket, first 100 stderr lines, and total stderr line count.

Deprecations and ignored arguments use `warnings.warn`, not a second
log record. Applications can route them through
`logging.captureWarnings(True)`.

### Structured fields

All fields are optional because each record carries only relevant
context.

| Field | Type | Meaning |
| ----- | ---- | ------- |
| `tmux_cmd` | `str` | Quoted, one-line complete command |
| `tmux_subcommand` | `str` | tmux subcommand |
| `tmux_socket` | `str` | Socket name or path |
| `tmux_target` | `str` | Target specifier |
| `tmux_session` | `str` | Session name |
| `tmux_window` | `str` | Window name or index |
| `tmux_pane` | `str` | Pane identifier |
| `tmux_exit_code` | `int` | Subprocess exit status |
| `tmux_stdout` | `list[str]` | First 100 stdout lines |
| `tmux_stderr` | `list[str]` | First 100 stderr lines |
| `tmux_stdout_len` | `int` | stdout line count |
| `tmux_stderr_len` | `int` | stderr or error line count |
| `tmux_option_key` | `str` | Option whose entries could not be parsed |
| `tmux_option_skipped` | `int` | Entries skipped for that option |

Treat field names and types as compatibility-sensitive. Omit unknown
values instead of storing `None`. Keep identity and count fields scalar;
stdout and stderr snapshots are lists of lines.

### Messages and tests

- Use short lowercase event messages without trailing punctuation.
- Assert on `caplog.records` fields, not rendered `caplog.text`.
- Scope capture to the emitting logger.
- Pair new record behavior with a deliberate break that proves the
  assertion fails.
- Give formatter examples safe `defaults=`; not every record carries
  every field.
