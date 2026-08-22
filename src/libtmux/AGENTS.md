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
| `WARNING` | Recoverable issues, deprecation | Deprecated method, missing optional program |
| `ERROR` | Failures that stop an operation | tmux command failed, invalid target |

### Message style

- Lowercase, past tense for events: `"session created"`, `"tmux
  command failed"`.
- No trailing punctuation.
- Keep messages short; put details in `extra`, not the message string.

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
  defaults (missing keys raise `KeyError`).
