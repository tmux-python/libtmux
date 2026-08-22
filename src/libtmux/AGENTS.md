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
- An object can go stale when tmux state changes externally (another
  client kills a window, a session gets renamed). Call `.refresh()` to
  reconcile it, or use the `neo` query interface, which always queries
  fresh.

## List-returning accessors: empty by default on tmux errors

`Server.sessions`, `Server.clients`, and `Server.attached_sessions`
return an empty `QueryList` when tmux's underlying list command fails
for any reason — no running daemon, a missing socket, a permission
error, a subprocess crash. This is a deliberate API contract:
list-shaped accessors are lenient by default. Callers that need to
distinguish "no rows" from "tmux unreachable" use the explicit
`Server.is_alive()` or `Server.raise_if_dead()` primitives.

When adding a new list-returning accessor, follow this convention. If a
future feature genuinely benefits from loud-failure semantics, expose
it as a scoped opt-in (e.g. a `Server.raise_server_errors()` context
manager) rather than changing the default contract of an existing
accessor or hard-coding raise-on-tmux-error into a new one.
Empty-on-tmux-error stays the default; raise is opt-in.

## Logging

These rules guide future logging changes; existing code may not yet
conform.

### Logger setup

- Use `logging.getLogger(__name__)` in every module.
- Add `NullHandler` in library `__init__.py` files.
- Never configure handlers, levels, or formatters in library code —
  that's the application's job.
- Define a logger only in modules that log; an unused one is dead
  code.

### Where the schema is built

`_internal/log_context.py` owns both producers. Reuse them instead of
hand-rolling an `extra` dict:

- `describe_command(argv)` derives `tmux_cmd`, `tmux_subcommand`, and
  `tmux_socket` from a tmux command line, redacting environment values.
  It parses tmux's global flags per the `getopt` string in tmux's
  `tmux.c`; a flag that takes a value must never be read as the
  subcommand.
- `object_extra(subcommand, ...)` builds lifecycle records, enforcing
  that every value is a `str` and an unknown key is omitted rather than
  set to `None`.

`tmux_cmd` carries the command line for every command record, so no
other layer should log one — a second producer means two shapes under
one key.

Redaction is two-directional. `describe_command()` covers what libtmux
sends and `redact_output()` covers what tmux returns; a subcommand that
carries a secret one way almost always carries it back the other.
`redact_output()` also decides control data from content: a subcommand
returning screen or buffer contents reports `tmux_stdout_len` and
nothing else, since the caller already holds the value and the log
would only duplicate it at size. Neither can classify content a caller
composed — `send_keys` payloads, shell commands, format queries — so
that boundary is documented rather than guessed at.

A `logging.Filter` belongs on a handler. `Logger.callHandlers()` walks
ancestor loggers for their handlers and never consults their filters,
so a filter on `libtmux` never sees a record from `libtmux.common`. It
quotes control characters into shell `$'…'` form: a caller controls
much of what reaches a command line, and a raw newline there would let
the tail of an argument pose as its own record. Object names need no
such guard — tmux rejects control characters in them before libtmux
logs anything.

### Structured context via `extra`

Pass structured data on every log call where useful for filtering,
searching, or test assertions.

**Core keys** (stable, scalar, safe at any log level):

| Key | Type | Context |
|-----|------|---------|
| `tmux_cmd` | `str` | tmux command line |
| `tmux_subcommand` | `str` | tmux subcommand (e.g. `new-session`) |
| `tmux_target` | `str` | tmux target specifier (e.g. `mysession:1.2`) |
| `tmux_exit_code` | `int` | tmux process exit code |
| `tmux_session` | `str` | session name |
| `tmux_window` | `str` | window name or index |
| `tmux_pane` | `str` | pane identifier |
| `tmux_option_key` | `str` | tmux option name |
| `tmux_option_skipped` | `int` | entries skipped under one option |
| `tmux_socket` | `str` | socket name or path identifying the tmux server |

**Heavy/optional keys** (DEBUG only, potentially large):

| Key | Type | Context |
|-----|------|---------|
| `tmux_stdout` | `list[str]` | tmux stdout lines (truncate or cap; `%(tmux_stdout)s` produces repr) |
| `tmux_stderr` | `list[str]` | tmux stderr lines (same caveats) |
| `tmux_stdout_len` | `int` | number of stdout lines |
| `tmux_stderr_len` | `int` | number of stderr lines |

Treat established keys as compatibility-sensitive — downstream users
may build dashboards and alerts on them. Change deliberately.

### Key naming rules

- `snake_case`, not dotted; `tmux_` prefix.
- Prefer stable scalars; avoid ad-hoc objects.
- Heavy keys (`tmux_stdout`, `tmux_stderr`) are DEBUG-only; consider
  companion `tmux_stdout_len` fields or hard truncation (e.g.
  `stdout[:100]`).

### Lazy formatting

`logger.debug("msg %s", val)` not f-strings. Two rationales:

- Deferred string interpolation: skipped entirely when level is
  filtered.
- Aggregator message template grouping: `"Running %s"` is one signature
  grouped ×10,000; f-strings make each line unique.

When computing `val` itself is expensive, guard with
`if logger.isEnabledFor(logging.DEBUG)`.

### `stacklevel` for wrappers

Increment for each wrapper layer so `%(filename)s:%(lineno)d` and OTel
`code.filepath` point to the real caller. Verify whenever call depth
changes.

### `LoggerAdapter` for persistent context

For objects with stable identity (Session, Window, Pane), use
`LoggerAdapter` to avoid repeating the same `extra` on every call. Lead
with the portable pattern (override `process()` to merge);
`merge_extra=True` simplifies this on Python 3.13+.

### Log levels

| Level | Use for | Examples |
|-------|---------|----------|
| `DEBUG` | Internal mechanics, tmux I/O | tmux command + stdout, format queries |
| `INFO` | Object lifecycle, user-visible operations | Session created, window added |
| `WARNING` | Recoverable issues libtmux resolved itself | Output it could not parse, a client it had to kill |
| `ERROR` | Failures that stop an operation | tmux command failed, invalid target |

### Message style

- Lowercase, past tense for events: `"session created"`, `"tmux
  command failed"`.
- No trailing punctuation.
- Keep messages short; put details in `extra`, not the message string.

Deprecations and ignored arguments go through `warnings.warn`, not a
logger — that is the Python mechanism for them, and
`logging.captureWarnings(True)` is how an application routes them into
the same stream. Do not log a deprecation as well; a warning already
deduplicates per source location and a log record would not.

### Thread safety

`logging` locks handler output, so the only race libtmux could add is
handing one mutable value to two records. Keep every list and dict
per-record — slice before you pass it — and no lock is needed anywhere
on this path.

### Failure records

`raise_if_stderr()` is where libtmux decides a tmux command *failed*,
so it is the one place that logs `ERROR` for that. A command tmux ran
successfully can still fail libtmux — `parse_output()` logs the field
counts when a row does not match the template, because the `zip()`
message names neither tmux nor the subcommand. Converting such an error
to `LibTmuxException` would be worse than leaving it: the lenient list
accessors catch that type, so a loud failure would become a silent
empty result. Paths that tolerate a non-zero exit — `has-session`
probes, `is_alive()` — do not route through it and stay quiet. Do not
log `ERROR` on a non-zero exit code alone; tmux uses one to answer
"no".

It logs with `stacklevel=2` so the record names the wrapper that ran
the command. Verify that whenever call depth changes: with the wrong
value, all of its call sites collapse onto one file and line.

`tmux_stderr` rides on the failure record despite being a heavy key,
because a failure without tmux's own message is not actionable. It
stays capped.

A per-item parse loop reports once for the whole item, with a count,
rather than once per entry — see `_warn_skipped()` in `options.py`.

### Exception logging

- Use `logger.exception()` only inside `except` blocks when you are
  **not** re-raising.
- Use `logger.error(..., exc_info=True)` when you need the traceback
  outside an `except` block.
- Avoid `logger.exception()` followed by `raise` — this duplicates the
  traceback. Either add context via `extra` that would otherwise be
  lost, or let the exception propagate.

### Testing logs

Assert on `caplog.records` attributes, not string matching on
`caplog.text`:

- Scope capture: `caplog.at_level(logging.DEBUG,
  logger="libtmux.common")`.
- Filter records rather than index by position: `[r for r in
  caplog.records if hasattr(r, "tmux_cmd")]`.
- Assert on schema: `record.tmux_exit_code == 0` not `"exit code 0" in
  caplog.text`.
- `caplog.record_tuples` cannot access extra fields — always use
  `caplog.records`.

### Avoid

- f-strings/`.format()` in log calls.
- Unguarded logging in hot loops (guard with `isEnabledFor()`).
- Catch-log-reraise without adding new context.
- `print()` for diagnostics.
- Logging secret env var values (log key names only).
- Non-scalar ad-hoc objects in `extra`.
- Requiring custom `extra` fields in format strings without safe
  defaults. A missing field makes `Formatter.format()` raise
  `ValueError`, which `handleError()` prints to stderr before dropping
  the record; with `logging.raiseExceptions = False` even that goes
  away. Pass `defaults=` (Python 3.10+).
