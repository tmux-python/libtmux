(logging)=

# Logging

libtmux emits structured records through Python's {mod}`logging` module. It
does not install handlers or choose a level. Configure the `libtmux` logger in
your application; `INFO` reports object lifecycle events, while `DEBUG` adds
tmux subprocess boundaries.

Command records identify the operation without retaining its operands, stdout,
or stderr. This keeps shell commands, keystrokes, environment values, buffer
contents, and pane contents out of logs by default.

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

Both carry a safe `tmux_cmd` summary. It contains the executable, effective
socket selector, subcommand, and the number of operands omitted after the
subcommand. The completion record adds the exit code and stdout/stderr line
counts.

```python
>>> import logging
>>> marker = "caller-secret"
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
>>> dispatched.tmux_cmd.endswith("list-sessions <2 arguments omitted>")
True
>>> marker in dispatched.tmux_cmd
False
>>> completed.tmux_stdout_len == len(proc.stdout)
True
>>> hasattr(completed, "tmux_stdout") or hasattr(completed, "tmux_stderr")
False
```

The result object still returns stdout and stderr normally. Only the record
omits their bodies.

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
`libtmux.server`. The record carries the subcommand, socket, and error line
count, but not the error text. Use {meth}`Server.raise_if_dead()
<libtmux.Server.raise_if_dead>` when an unreachable server must be loud.

A non-zero exit code alone does not produce an `ERROR`; tmux also uses
non-zero status to answer probes with “no.”

## Structured fields

Records contain only fields relevant to their event.

| Field | Type | Meaning |
| ----- | ---- | ------- |
| `tmux_cmd` | `str` | executable/socket/subcommand summary |
| `tmux_subcommand` | `str` | tmux subcommand |
| `tmux_socket` | `str` | socket name or path |
| `tmux_target` | `str` | target specifier |
| `tmux_session` | `str` | session name |
| `tmux_window` | `str` | window name or index |
| `tmux_pane` | `str` | pane identifier |
| `tmux_exit_code` | `int` | subprocess exit status |
| `tmux_stdout_len` | `int` | stdout line count |
| `tmux_stderr_len` | `int` | stderr or swallowed-error line count |
| `tmux_option_key` | `str` | option whose entries could not be parsed |
| `tmux_option_skipped` | `int` | entries skipped for that option |

All identity fields are strings. Unknown identities are omitted rather than
set to `None`.

## Format records safely

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

## Privacy and cost

Command operands and process output bodies never enter libtmux records. Socket
identities, executable paths, object names, and target specifiers do, because
they identify the operation. Choose handler destinations and retention with
that metadata in mind.

When `DEBUG` is disabled, command-context construction is skipped. With it
enabled, records contain scalars and counts only; their size does not grow with
command payloads or terminal output. libtmux keeps no shared logging state, so
threads and async callers rely on the standard library's logging guarantees.
