(logging)=

# Logging

libtmux narrates itself through the standard {mod}`logging` module. Every tmux
command it runs, and every object it creates, renames, or kills, becomes a log
record — with the tmux context attached as structured fields rather than baked
into the message text. That means you filter on `tmux_session == "deploy"`
instead of running a regular expression over prose.

libtmux never configures logging for you. It attaches a
{class}`~logging.NullHandler` and nothing else, so a library import stays silent
until your application asks for output.

Most readers need only the next two sections: turn it on, and read a failure.
The field schema and the testing and formatting sections below are for when you
route these records somewhere — a test assertion, a log aggregator, a trace.

## Turn it on

The shortest thing that works — lifecycle events, no tmux command noise:

```python
>>> import logging
>>> logging.basicConfig(level=logging.INFO)
```

To see the tmux commands themselves, including their output, drop only libtmux
to `DEBUG` and leave the rest of your application alone:

```python
>>> import logging
>>> libtmux_logger = logging.getLogger("libtmux")
>>> previous_level = libtmux_logger.level
>>> libtmux_logger.setLevel(logging.DEBUG)
>>> libtmux_logger.getEffectiveLevel() == logging.DEBUG
True
>>> libtmux_logger.setLevel(previous_level)
```

## Diagnosing a failure

When libtmux is not doing what you expect, this shows every tmux command it
runs, the exit code, and whatever tmux wrote back. It installs a real handler
with safe defaults for records that carry no command outcome. The final three
lines restore the shared documentation process; keep the handler installed in
your application:

```python
>>> import logging
>>> handler = logging.StreamHandler()
>>> formatter = logging.Formatter(
...     "%(levelname)s %(name)s %(message)s | %(tmux_cmd)s -> %(tmux_exit_code)s",
...     defaults={"tmux_cmd": "-", "tmux_exit_code": "-"},
... )
>>> handler.setFormatter(formatter)
>>> libtmux_logger = logging.getLogger("libtmux")
>>> previous_level = libtmux_logger.level
>>> libtmux_logger.addHandler(handler)
>>> libtmux_logger.setLevel(logging.DEBUG)
>>> record = logging.LogRecord(
...     "libtmux.common", logging.DEBUG, "common.py", 1,
...     "tmux command completed", None, None,
... )
>>> record.tmux_cmd = "tmux -Ldemo list-sessions"
>>> record.tmux_exit_code = 0
>>> formatter.format(record)
'DEBUG libtmux.common tmux command completed | tmux -Ldemo list-sessions -> 0'
>>> libtmux_logger.removeHandler(handler)
>>> handler.close()
>>> libtmux_logger.setLevel(previous_level)
```

Then read `tmux_cmd` off the record. It is shell-quoted and includes the
`-L` or `-S` flag that selects the right server. It reproduces the command
unless libtmux replaced sensitive content with `REDACTED` or shortened an
oversized rendering.

An argument holding control characters appears in `$'…'` form. Shell escapes
keep the rendering familiar and pasteable for ordinary tmux arguments without
placing a literal line boundary in the record, so nothing in a command line can
pose as a log record of its own:

```python
>>> import logging
>>> caplog.clear()
>>> pane = session.active_window.active_pane
>>> with caplog.at_level(logging.DEBUG, logger="libtmux.common"):
...     pane.send_keys("echo one\necho two", enter=False)
>>> record = next(
...     r for r in caplog.records
...     if getattr(r, "tmux_subcommand", None) == "send-keys"
... )
>>> "\n" in record.tmux_cmd
False
>>> record.tmux_cmd.endswith("$'echo one\\necho two'")
True
```

## Where records come from

Loggers are named after their module, so the package name is a prefix you can
configure as one unit:

| Logger | Emits |
|---|---|
| `libtmux.common` | Every tmux command: dispatch, completion, failure |
| `libtmux.server` | Server and session lifecycle |
| `libtmux.session` | Window lifecycle, session rename and kill |
| `libtmux.window` | Window rename and kill |
| `libtmux.pane` | Pane split, floating pane creation, pane kill |
| `libtmux.options` | Option values tmux returned that libtmux could not parse |
| `libtmux.hooks` | Hook lines tmux returned that libtmux could not parse |
| `libtmux.neo` | Rows of tmux output libtmux could not parse |
| `libtmux._internal.control_mode` | The `tmux -C` client used by the test fixtures |

Silence the command chatter while keeping lifecycle events:

```python
>>> import logging
>>> command_logger = logging.getLogger("libtmux.common")
>>> previous_level = command_logger.level
>>> command_logger.setLevel(logging.INFO)
>>> command_logger.isEnabledFor(logging.DEBUG)
False
>>> command_logger.setLevel(previous_level)
```

## What each level gives you

| Level | You get |
|---|---|
| `ERROR` | A tmux command libtmux treated as a failure, and subprocess errors |
| `WARNING` | Option and hook output libtmux could not parse; a control-mode client killed after declining to exit |
| `INFO` | Object lifecycle: created, renamed, killed |
| `DEBUG` | Every tmux command line, exit code, stdout, and stderr |

`ERROR` records are worth wiring up even if you catch libtmux's exceptions,
because libtmux's list accessors deliberately swallow tmux errors. {attr}`Server.sessions
<libtmux.Server.sessions>` returns an empty {class}`~libtmux._internal.query_list.QueryList`
when tmux is unreachable, which is otherwise indistinguishable from a server
that genuinely has no sessions. The `ERROR` record is how you tell those two
apart without changing your code:

```python
>>> import logging
>>> from libtmux.server import Server
>>> unreachable = Server(socket_name="no-such-socket")
>>> caplog.clear()
>>> with caplog.at_level(logging.ERROR, logger="libtmux.common"):
...     sessions = unreachable.sessions
>>> sessions
[]
>>> record = caplog.records[-1]
>>> record.getMessage()
'tmux command failed'
>>> record.tmux_subcommand
'list-sessions'
>>> record.tmux_socket
'no-such-socket'
```

Polling with {meth}`Server.is_alive() <libtmux.Server.is_alive>` stays quiet, so
a health check loop does not fill your logs with errors.

A failure record is attributed to the libtmux method that ran the command, not
to the helper that raised. So `%(filename)s:%(lineno)d` in a format string —
and `code.filepath` in OpenTelemetry — point at the operation you called:

```python
>>> import logging
>>> caplog.clear()
>>> from libtmux import exc
>>> with caplog.at_level(logging.ERROR, logger="libtmux.common"):
...     try:
...         session.kill_window(target_window="no_such_window")
...     except exc.LibTmuxException:
...         pass
>>> caplog.records[-1].funcName
'kill_window'
```

An option whose value libtmux cannot parse warns once for that option, with
`tmux_option_skipped` counting the entries it dropped, rather than once per
entry.

Not every failure comes from tmux. When libtmux cannot parse a row tmux returned
successfully, the exception mentions only the parsing primitive that raised, so
an `ERROR` record on `libtmux.neo` carries what the exception cannot: the
subcommand, and how many fields the row held against how many it should have.
A count one higher than expected means a value contained the character libtmux
splits rows on.

## What does not come through logging

libtmux raises about as many advisories through {mod}`warnings` as it logs — a
deprecated method, a flag your tmux is too old for, an argument being ignored.
Those never reach a logging handler, so an application configured exactly as
above receives none of them.

Route them in with {func}`logging.captureWarnings`, which sends them to the
`py.warnings` logger at `WARNING`:

```python
>>> import logging
>>> import warnings
>>> records = []
>>> class Capture(logging.Handler):
...     def emit(self, record):
...         records.append(record)
>>> handler = Capture()
>>> warnings_logger = logging.getLogger("py.warnings")
>>> warnings_logger.addHandler(handler)

Without the bridge, nothing arrives:

>>> with warnings.catch_warnings(record=True):
...     warnings.simplefilter("always")
...     warnings.warn("a tmux flag was ignored", stacklevel=2)
>>> len(records)
0

With it, the advisory becomes a record:

>>> logging.captureWarnings(True)
>>> with warnings.catch_warnings():
...     warnings.simplefilter("always")
...     warnings.warn("a tmux flag was ignored", stacklevel=2)
>>> [(r.name, r.levelname) for r in records]
[('py.warnings', 'WARNING')]

>>> logging.captureWarnings(False)
>>> warnings_logger.removeHandler(handler)
```

The two channels do not behave alike, and the difference bites. Python delivers
a given warning **once per source location** by default, while a logger emits
every call. An advisory you see once may have fired on every iteration, so treat
a warning as "this happened at least once" rather than as a count.

## The `extra` schema

Every field is attached under `extra`, which makes it an attribute on the
{class}`~logging.LogRecord`. Keys are `snake_case` and prefixed `tmux_`.
Context and count fields are scalars; bounded stdout and stderr fields are
lists of strings.

### Context, on any record that knows it

| Key | Type | Meaning |
|---|---|---|
| `tmux_cmd` | `str` | Rendered command line: shell-quoted, single-line, secrets redacted |
| `tmux_subcommand` | `str` | tmux subcommand, e.g. `new-session` |
| `tmux_socket` | `str` | Socket name or path identifying which tmux server |
| `tmux_target` | `str` | tmux target the operation addressed |
| `tmux_session` | `str` | Session name |
| `tmux_window` | `str` | Window name or index |
| `tmux_pane` | `str` | Pane identifier |
| `tmux_option_key` | `str` | Option name, on `libtmux.options` warnings |
| `tmux_option_skipped` | `int` | Entries libtmux could not parse under that option |
| `tmux_fields_expected` | `int` | Fields a row of tmux output should have held |
| `tmux_fields_received` | `int` | Fields it actually held |

### Outcome, on completion and failure records

| Key | Type | Meaning |
|---|---|---|
| `tmux_exit_code` | `int` | tmux process exit code |
| `tmux_stdout` | `list[str]` | stdout lines, capped; empty for sensitive output commands |
| `tmux_stderr` | `list[str]` | stderr lines, capped |
| `tmux_stdout_len` | `int` | Total stdout line count before capping |
| `tmux_stderr_len` | `int` | Total stderr line count before capping |

A key is absent when libtmux does not know it, never present-and-`None`. So
test with {func}`getattr` and a default, or {func}`hasattr`, rather than
comparing to `None`.

`tmux_socket` is what distinguishes servers when one process drives several.
`tmux_exit_code` is not an error signal on its own: libtmux probes with
`has-session`, which exits non-zero as its normal way of saying "no". Match on
the `ERROR` level, not on a non-zero exit code.

## Reading records in tests

Assert on `caplog.records`, not on `caplog.text`. The structured fields are what
you actually care about, and `caplog.record_tuples` cannot reach them at all.

```python
>>> import logging
>>> caplog.clear()
>>> with caplog.at_level(logging.INFO, logger="libtmux.session"):
...     window = session.new_window(window_name="deploy")
>>> record = next(
...     r for r in caplog.records
...     if getattr(r, "tmux_subcommand", None) == "new-window"
... )
>>> record.getMessage()
'window created'
>>> record.tmux_window
'deploy'
```

Scope the capture to the logger you mean, and filter the records rather than
indexing by position — libtmux may add records between the one you want and the
end of the list:

```python
>>> import logging
>>> caplog.clear()
>>> release = session.new_window(window_name="release")
>>> with caplog.at_level(logging.DEBUG, logger="libtmux.common"):
...     release.rename_window("released")
Window(@... ...:released, Session($... ...))
>>> completed = [
...     r for r in caplog.records
...     if r.getMessage() == "tmux command completed"
...     and getattr(r, "tmux_subcommand", None) == "rename-window"
... ]
>>> completed[0].tmux_exit_code
0
```

## Formatting records safely

A format string that names a `tmux_` key will fail on records that do not carry
it. {mod}`logging` catches the error, prints it to stderr, and **drops the
record** — so a formatter written against `DEBUG` records silently loses your
`INFO` ones.

Give every custom key a default:

```python
>>> import logging
>>> formatter = logging.Formatter(
...     "%(levelname)s %(message)s cmd=%(tmux_cmd)s",
...     defaults={"tmux_cmd": "-"},
... )
>>> record = logging.LogRecord(
...     "libtmux.session", logging.INFO, "session.py", 1,
...     "session created", None, None,
... )
>>> formatter.format(record)
'INFO session created cmd=-'
```

`tmux_stdout` and `tmux_stderr` hold lists, and a `%s` renders a list as its
Python repr rather than as lines. Join them yourself when you want them
readable:

```python
>>> import logging
>>> record = logging.LogRecord(
...     "libtmux.common", logging.DEBUG, "common.py", 1,
...     "tmux command completed", None, None,
... )
>>> record.tmux_stdout = ["line one", "line two"]
>>> logging.Formatter("%(message)s out=%(tmux_stdout)s").format(record)
"tmux command completed out=['line one', 'line two']"
```

## What libtmux does not log

Environment values passed through tmux's environment options never reach a log
record. libtmux redacts them where the command line is turned into text, so the
variable names stay visible for debugging while the values do not:

```python
>>> import logging
>>> caplog.clear()
>>> with caplog.at_level(logging.DEBUG, logger="libtmux.common"):
...     env_session = server.new_session(
...         session_name="env-demo",
...         environment={"API_TOKEN": "hunter2"},
...     )
>>> dispatched = next(
...     r for r in caplog.records
...     if getattr(r, "tmux_subcommand", None) == "new-session"
...     and r.getMessage() == "tmux command dispatched"
... )
>>> "hunter2" in dispatched.tmux_cmd
False
>>> "-eAPI_TOKEN=REDACTED" in dispatched.tmux_cmd
True
>>> env_session.kill()
```

This covers `environment=` on {meth}`Server.new_session()
<libtmux.Server.new_session>`, {meth}`Session.new_window()
<libtmux.Session.new_window>`, and {meth}`Pane.split() <libtmux.Pane.split>`, as
well as {meth}`set_environment()
<libtmux.common.EnvironmentMixin.set_environment>`.

tmux hands those values straight back, and a value may span output lines.
{meth}`getenv() <libtmux.common.EnvironmentMixin.getenv>` and
{meth}`show_environment() <libtmux.common.EnvironmentMixin.show_environment>`
keep their existing API results, but their records omit `tmux_stdout` content
and retain `tmux_stdout_len`.

```python
>>> import logging
>>> caplog.clear()
>>> server = session.server
>>> server.set_environment("DEPLOY_KEY", "hunter2")
>>> with caplog.at_level(logging.DEBUG, logger="libtmux.common"):
...     server.getenv("DEPLOY_KEY")
'hunter2'
>>> completed = next(
...     r for r in caplog.records
...     if r.getMessage() == "tmux command completed"
... )
>>> completed.tmux_stdout
[]
>>> completed.tmux_stdout_len
1
```

Paste-buffer data follows the same body-versus-metadata boundary. The payload
passed to {meth}`Server.set_buffer() <libtmux.Server.set_buffer>` is replaced
with `REDACTED` in `tmux_cmd`, and buffer contents returned by tmux stay
off the record.

### What libtmux cannot redact

libtmux hides what tmux's own grammar marks as an environment value. It cannot
classify content you compose yourself:

- **{meth}`Pane.send_keys() <libtmux.Pane.send_keys>` payloads.** What you type
  into a pane appears in `tmux_cmd` at `DEBUG`.
- **A `start_directory`, `window_command`, or shell command.**
- **A format string that prints a variable**, such as
  `display-message -p '#{q:DEPLOY_KEY}'`.

The built-in names, aliases, and command abbreviations are covered. A command
defined in `command-alias` has server-specific grammar that libtmux cannot
inspect on this path. An alias name that shares a protected command prefix is
handled conservatively; any other custom alias remains unclassified.

Only your application knows which of those carry secrets, so redacting them is
its job — with a {class}`~logging.Filter` that rewrites the fields you care
about.

Placement matters more than the filter does. A filter on a logger runs only for
records that logger made; {meth}`Logger.callHandlers()
<logging.Logger.callHandlers>` walks to ancestor loggers for their *handlers*
and never consults their filters. Since every record comes from a child such as
`libtmux.common`, attaching one to `logging.getLogger("libtmux")` protects
nothing, and says nothing about it. Attach it to a **handler**:

```python
>>> import logging
>>> import re

>>> class RedactFilter(logging.Filter):
...     def __init__(self, *patterns: str) -> None:
...         super().__init__()
...         self.patterns = [re.compile(p) for p in patterns]
...
...     def _redact(self, value: str | list[str]) -> str | list[str]:
...         for pattern in self.patterns:
...             if isinstance(value, str):
...                 value = pattern.sub("REDACTED", value)
...             else:
...                 value = [pattern.sub("REDACTED", item) for item in value]
...         return value
...
...     def filter(self, record: logging.LogRecord) -> bool:
...         for field in ("tmux_cmd", "tmux_stdout", "tmux_stderr"):
...             value = getattr(record, field, None)
...             if isinstance(value, (str, list)):
...                 setattr(record, field, self._redact(value))
...         return True

>>> records = []
>>> class Capture(logging.Handler):
...     def emit(self, record):
...         records.append(record)

>>> handler = Capture()
>>> libtmux_logger = logging.getLogger("libtmux")
>>> previous_level = libtmux_logger.level
>>> libtmux_logger.addHandler(handler)
>>> libtmux_logger.setLevel(logging.DEBUG)
>>> pane = session.active_window.active_pane
>>> on_logger = RedactFilter("hunter2")

On the logger, it never runs:

>>> libtmux_logger.addFilter(on_logger)
>>> pane.send_keys("login hunter2", enter=False)
>>> any("hunter2" in r.tmux_cmd for r in records if hasattr(r, "tmux_cmd"))
True

On the handler, it does:

>>> libtmux_logger.removeFilter(on_logger)
>>> handler.addFilter(RedactFilter("hunter2"))
>>> records.clear()
>>> result = server.cmd("display-message", "-p", "login hunter2")
>>> result.stdout
['login hunter2']
>>> any(
...     "hunter2" in str(getattr(r, field, ""))
...     for r in records
...     for field in ("tmux_cmd", "tmux_stdout", "tmux_stderr")
... )
False

Put the logger back as you found it — a level set on a shared logger outlives
the code that set it:

>>> libtmux_logger.removeHandler(handler)
>>> libtmux_logger.setLevel(previous_level)
```

The command line also reaches the process table, so it is visible to `ps` for
the same user regardless of logging. Logs differ in that they travel.

## Cost

libtmux guards the expensive work — quoting the command line and slicing tmux's
output — behind {meth}`Logger.isEnabledFor() <logging.Logger.isEnabledFor>`, so
leaving `DEBUG` off costs a level comparison per command. Messages use lazy
`%s` interpolation, which keeps a given event under one message template in an
aggregator instead of producing a distinct string per occurrence.

`DEBUG` is dominated by `tmux_cmd`, because libtmux queries tmux with large
`-F` format templates and each command is recorded twice — once on dispatch,
once on completion — so that either line stands on its own. If you want object
lifecycle without that, leave `libtmux` at `DEBUG` and raise just the command
logger:

```python
>>> import logging
>>> command_logger = logging.getLogger("libtmux.common")
>>> previous_level = command_logger.level
>>> command_logger.setLevel(logging.INFO)
>>> command_logger.isEnabledFor(logging.DEBUG)
False
>>> command_logger.setLevel(previous_level)
```

At `DEBUG`, `tmux_stdout` and `tmux_stderr` are capped, and the untruncated
counts stay available as `tmux_stdout_len` and `tmux_stderr_len`. A
`list-panes` against a large server can still be a lot of text — prefer the
`_len` fields when you only need volume.

Commands that return content rather than control data — pane capture, buffer
inspection, message history, prompt history, and environment inspection —
report only `tmux_stdout_len`. The output may contain terminal text, commands,
or multiline values, and the caller already has it as a return value. This is
the same line HTTP clients draw when they log a status and a content length but
never a response body.

`tmux_cmd` is bounded too, at a practical rendered-character ceiling derived
from tmux's transport limit, and a shortened one ends in an ellipsis. tmux
counts transport bytes while log quoting expands some characters, so this cap
deliberately does not claim to be the exact largest command tmux accepts.

## Threads and async

libtmux adds no locking of its own and needs none. {mod}`logging` serialises
handler output behind a lock, and libtmux never hands the same list or dict to
two records, so concurrent tmux calls cannot interleave into one another's
fields. Records name the server they came from through `tmux_socket`, which is
what tells apart several servers driven at once.

Blocking work belongs off the event loop, and a handler writing to a file or a
socket is blocking work. The standard answer is
{class}`~logging.handlers.QueueHandler` with a
{class}`~logging.handlers.QueueListener`, and every `tmux_` field survives that
round trip — including through a {mod}`multiprocessing` queue, since records
pickle cleanly.

One trap comes with it. `QueueHandler` runs **its own formatter** when it
enqueues, so a format string there that names a field some records lack drops
those records *before they reach the queue* — the listener's handlers never see
them. Leave the `QueueHandler` unformatted and format in the listener, or give
it the same `defaults` as any other formatter.

```python
>>> import logging
>>> import logging.handlers
>>> import queue
>>> log_queue: queue.Queue[logging.LogRecord] = queue.Queue()
>>> handler = logging.handlers.QueueHandler(log_queue)
>>> handler.formatter is None
True
>>> handler.close()
```

An `asyncio` task name does not follow work into
{func}`asyncio.to_thread`, so records made there carry no `taskName`. Bind your
own identifier if you need to correlate tmux calls back to a task.

## Recipes

### Structured JSON output

Emit one JSON object per record, promoting the tmux fields to top level:

```python
>>> import json
>>> import logging
>>> class TmuxJsonFormatter(logging.Formatter):
...     def format(self, record: logging.LogRecord) -> str:
...         payload = {
...             "level": record.levelname,
...             "logger": record.name,
...             "message": record.getMessage(),
...         }
...         payload.update(
...             {k: v for k, v in record.__dict__.items() if k.startswith("tmux_")}
...         )
...         return json.dumps(payload)
>>> record = logging.LogRecord(
...     "libtmux.server", logging.INFO, "server.py", 1,
...     "session created", None, None,
... )
>>> record.tmux_socket = "demo"
>>> TmuxJsonFormatter().format(record)
'{"level": "INFO", "logger": "libtmux.server", "message": "session created", "tmux_socket": "demo"}'
```

### Route one server's records somewhere else

`tmux_socket` identifies the server, so a {class}`~logging.Filter` can split a
multi-server application's logs. Attach it to the handler, for the reason
[above](#what-libtmux-cannot-redact):

```python
>>> import logging
>>> class SocketFilter(logging.Filter):
...     def __init__(self, socket: str) -> None:
...         super().__init__()
...         self.socket = socket
...
...     def filter(self, record: logging.LogRecord) -> bool:
...         return getattr(record, "tmux_socket", None) == self.socket
>>> record = logging.LogRecord(
...     "libtmux.server", logging.INFO, "server.py", 1,
...     "session created", None, None,
... )
>>> record.tmux_socket = "deploy"
>>> SocketFilter("deploy").filter(record)
True
>>> SocketFilter("staging").filter(record)
False
```

### Attach records to an OpenTelemetry span

The scalar `tmux_` keys map onto span attributes without transformation. The
bounded stdout and stderr lists are intentionally left out of this compact
recipe:

```python
>>> import logging
>>> class Span:
...     def __init__(self) -> None:
...         self.attributes = {}
...
...     def set_attribute(self, key, value) -> None:
...         self.attributes[key] = value
>>> def annotate(span, record: logging.LogRecord) -> None:
...     for key, value in record.__dict__.items():
...         if key.startswith("tmux_") and isinstance(value, (str, int)):
...             span.set_attribute(key, value)
>>> span = Span()
>>> record = logging.LogRecord(
...     "libtmux.common", logging.DEBUG, "common.py", 1,
...     "tmux command completed", None, None,
... )
>>> record.tmux_socket = "deploy"
>>> record.tmux_exit_code = 0
>>> annotate(span, record)
>>> span.attributes
{'tmux_socket': 'deploy', 'tmux_exit_code': 0}
```
