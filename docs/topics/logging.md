(logging)=

# Logging

libtmux emits structured records through Python's {mod}`logging` module. It
does not install handlers or choose a level. Configure the `libtmux` logger in
your application; `INFO` reports object lifecycle events, while `DEBUG` adds
tmux subprocess boundaries.

Command records include the complete tmux command. Completion records also
include bounded stdout and stderr snapshots. Applications choose which fields
reach each destination through standard-library handlers and formatters.

## Enable records

The `libtmux` logger is the parent of every package logger. A handler attached
there receives records from `libtmux.common`, `libtmux.server`, and the
object modules.

Use your application's normal logging configuration. For a short script,
`logging.basicConfig(level=logging.INFO)` is enough. To inspect command
metadata without changing other libraries, set only `libtmux.common` to
`DEBUG`.

```python
>>> import logging
>>> command_logger = logging.getLogger("libtmux.common")
>>> previous_level = command_logger.level
>>> command_logger.setLevel(logging.DEBUG)
>>> command_logger.isEnabledFor(logging.DEBUG)
True
>>> command_logger.setLevel(previous_level)
```

## Records by level

| Level | What libtmux records |
| ----- | -------------------- |
| `DEBUG` | tmux command dispatch and completion; internal lookup details |
| `INFO` | successful server, session, window, and pane lifecycle events |
| `WARNING` | recoverable problems libtmux handled |
| `ERROR` | a failure libtmux intentionally converted to a fallback result |

The main emitters are:

| Logger | Records |
| ------ | ------- |
| `libtmux.common` | subprocess dispatch and completion |
| `libtmux.server` | server/session lifecycle and swallowed list failures |
| `libtmux.session` | session/window lifecycle |
| `libtmux.window` | window lifecycle |
| `libtmux.pane` | pane lifecycle |
| `libtmux.options` | aggregated option parsing warnings |

## Command records

Each tmux subprocess can produce two `DEBUG` records:

- `tmux command dispatched` before execution;
- `tmux command completed` after execution.

Both carry `tmux_cmd`, a one-line rendering of the complete argv. Printable
values use shell quoting; control characters use escaped representations. The
completion record adds the exit code, the first 100 stdout and stderr lines,
and the total line counts.

```python
>>> import logging
>>> marker = "caller-payload"
>>> with caplog.at_level(logging.DEBUG, logger="libtmux.common"):
...     proc = session.server.cmd("list-sessions", "-F", marker)
>>> marker in proc.stdout
True
>>> command_records = [
...     record for record in caplog.records
...     if record.getMessage().startswith("tmux command")
... ]
>>> dispatched, completed = command_records[-2:]
>>> dispatched.tmux_subcommand
'list-sessions'
>>> dispatched.tmux_socket == session.server.socket_name
True
>>> dispatched.tmux_cmd.endswith("list-sessions -F caller-payload")
True
>>> marker in dispatched.tmux_cmd
True
>>> completed.tmux_stdout == proc.stdout
True
>>> completed.tmux_stderr == proc.stderr
True
>>> completed.tmux_stdout_len == len(proc.stdout)
True
```

The result object retains every output line. The completion record snapshots
at most 100 lines from each stream and reports the full lengths separately.
`tmux_subcommand` and `tmux_socket` are best-effort conveniences. An unknown
global option leaves uncertain derived fields absent; `tmux_cmd` remains
complete.

## Failures

libtmux does not log an error and then raise it. Propagated and translated
failures remain exception data, so callers decide whether and where to log
them. Expected probes such as {meth}`Server.is_alive()
<libtmux.Server.is_alive>` also stay quiet.

Three list-shaped accessors intentionally hide
{exc}`~libtmux.exc.LibTmuxException`:

- {attr}`Server.sessions <libtmux.Server.sessions>`;
- {attr}`Server.attached_sessions <libtmux.Server.attached_sessions>`;
- {attr}`Server.clients <libtmux.Server.clients>`.

They return an empty collection and emit one `ERROR` record on
`libtmux.server`. The record carries the subcommand, socket, the first 100 lines
of exception text, and the total line count. Use {meth}`Server.raise_if_dead()
<libtmux.Server.raise_if_dead>` when an unreachable server must be loud.

A non-zero exit code alone does not produce an `ERROR`; tmux also uses
non-zero status to answer probes with “no.”

## Structured fields

Records contain only fields relevant to their event.

| Field | Type | Meaning |
| ----- | ---- | ------- |
| `tmux_cmd` | `str` | quoted, one-line complete command |
| `tmux_subcommand` | `str` | tmux subcommand |
| `tmux_socket` | `str` | socket name or path |
| `tmux_target` | `str` | target specifier |
| `tmux_session` | `str` | session name |
| `tmux_window` | `str` | window name or index |
| `tmux_pane` | `str` | pane identifier |
| `tmux_exit_code` | `int` | subprocess exit status |
| `tmux_stdout` | `list[str]` | first 100 stdout lines |
| `tmux_stderr` | `list[str]` | first 100 stderr lines |
| `tmux_stdout_len` | `int` | stdout line count |
| `tmux_stderr_len` | `int` | stderr or swallowed-error line count |
| `tmux_option_key` | `str` | option whose entries could not be parsed |
| `tmux_option_skipped` | `int` | entries skipped for that option |

All identity fields are strings. Unknown identities are omitted rather than
set to `None`.

## Format records

Not every record carries every field. A formatter that requires
`%(tmux_cmd)s` drops lifecycle records unless it supplies a default. Python
3.10 and later accept defaults directly:

```python
>>> import logging
>>> formatter = logging.Formatter(
...     "%(levelname)s %(message)s subcommand=%(tmux_subcommand)s exit=%(tmux_exit_code)s",
...     defaults={"tmux_subcommand": "-", "tmux_exit_code": "-"},
... )
>>> record = logging.LogRecord(
...     "libtmux.server", logging.INFO, "server.py", 1,
...     "session created", (), None,
... )
>>> formatter.format(record)
'INFO session created subcommand=- exit=-'
```

Use the same defaulting rule in JSON formatters and telemetry exporters.

### Select fields at the handler

A handler's filter chooses its records, and its formatter chooses the fields
written to that destination. This Python 3.10-compatible example retains the
payload fields on each record but writes only event names and bounded metadata:

```python
>>> import io
>>> import logging
>>> stream = io.StringIO()
>>> handler = logging.StreamHandler(stream)
>>> handler.addFilter(
...     lambda record: getattr(record, "tmux_subcommand", None) == "display-message"
... )
>>> handler.setFormatter(logging.Formatter(
...     "%(levelname)s %(message)s subcommand=%(tmux_subcommand)s "
...     "stdout_lines=%(tmux_stdout_len)s",
...     defaults={"tmux_subcommand": "-", "tmux_stdout_len": "-"},
... ))
>>> command_logger = logging.getLogger("libtmux.common")
>>> previous_level = command_logger.level
>>> command_logger.setLevel(logging.DEBUG)
>>> command_logger.addHandler(handler)
>>> proc = session.server.cmd("display-message", "-p", "payload-marker")
>>> _ = session.server.cmd("list-sessions")  # filtered from this handler
>>> command_logger.removeHandler(handler)
>>> command_logger.setLevel(previous_level)
>>> handler.close()
>>> "payload-marker" in proc.stdout
True
>>> "payload-marker" in stream.getvalue()
False
>>> "list-sessions" in stream.getvalue()
False
>>> stream.getvalue().count("tmux command")
2
```

The standard library documents handler-level
[filters](https://docs.python.org/3/library/logging.html#filter-objects).
Its [Logging Cookbook](https://docs.python.org/3/howto/logging-cookbook.html)
covers contextual fields, routing, handlers, and custom formatting.

## Assert on records in tests

Use pytest's `caplog.records` so assertions read structured fields instead of
rendered text:

```python
>>> import logging
>>> with caplog.at_level(logging.INFO, logger="libtmux.session"):
...     logged_window = session.new_window(window_name="logged")
>>> records = [
...     record for record in caplog.records
...     if getattr(record, "tmux_subcommand", None) == "new-window"
... ]
>>> len(records) >= 1
True
>>> records[-1].tmux_socket == session.server.socket_name
True
>>> logged_window.kill()
```

Scope capture to the logger under test and filter by message or subcommand;
fixture setup may have emitted earlier records.

## Warnings are separate

Deprecations, ignored arguments, and version advisories use
{mod}`warnings`, not logging. Applications that need one stream can route
them through the `py.warnings` logger:

```python
>>> import logging
>>> logging.captureWarnings(True)
>>> logging.captureWarnings(False)
```

libtmux does not duplicate a warning as a log record.

## Payload size and application policy

`DEBUG` records contain caller-provided command operands and output lines.
Choose handler destinations, formatting, and retention for the data your
application sends through tmux. libtmux does not redact command or output
payloads; use a handler formatter such as the example above when a destination
needs metadata only.

When `DEBUG` is disabled, command-context construction is skipped. With it
enabled, `tmux_cmd` grows with argv, and each completion record retains up to
100 lines from each stream. Individual lines are not truncated. libtmux keeps
no shared logging state, so threads and async callers rely on the standard
library's logging guarantees.
