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

## Turn it on

The shortest thing that works — lifecycle events, no tmux command noise:

```python
import logging

logging.basicConfig(level=logging.INFO)
```

To see the tmux commands themselves, including their output, drop only libtmux
to `DEBUG` and leave the rest of your application alone:

```python
logging.getLogger("libtmux").setLevel(logging.DEBUG)
```

## Diagnosing a failure

When libtmux is not doing what you expect, this shows every tmux command it
runs, the exit code, and whatever tmux wrote back:

```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)s %(name)s %(message)s | %(tmux_cmd)s -> %(tmux_exit_code)s",
)
```

That format string names two keys that not every record carries, so pair it
with defaults or you will lose records — see
[Formatting records safely](#formatting-records-safely). The version that will
not drop anything:

```python
logging.basicConfig(level=logging.DEBUG)
```

Then read `tmux_cmd` off the record and run it yourself. It is shell-quoted, so
it pastes into a terminal as-is and reproduces what libtmux did — including the
`-L` or `-S` flag that selects the right server.

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

Silence the command chatter while keeping lifecycle events:

```python
logging.getLogger("libtmux.common").setLevel(logging.INFO)
```

## What each level gives you

| Level | You get |
|---|---|
| `ERROR` | A tmux command libtmux treated as a failure, and subprocess errors |
| `WARNING` | Option and hook output libtmux could not parse |
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

## The `extra` schema

Every field is attached under `extra`, which makes it an attribute on the
{class}`~logging.LogRecord`. Keys are `snake_case`, prefixed `tmux_`, and hold
scalars.

### Context, on any record that knows it

| Key | Type | Meaning |
|---|---|---|
| `tmux_cmd` | `str` | Full command line, shell-quoted, secrets redacted |
| `tmux_subcommand` | `str` | tmux subcommand, e.g. `new-session` |
| `tmux_socket` | `str` | Socket name or path identifying which tmux server |
| `tmux_target` | `str` | tmux target the operation addressed |
| `tmux_session` | `str` | Session name |
| `tmux_window` | `str` | Window name or index |
| `tmux_pane` | `str` | Pane identifier |
| `tmux_option_key` | `str` | Option name, on `libtmux.options` warnings |

### Outcome, on completion and failure records

| Key | Type | Meaning |
|---|---|---|
| `tmux_exit_code` | `int` | tmux process exit code |
| `tmux_stdout` | `list[str]` | stdout lines, capped |
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
>>> caplog.clear()
>>> with caplog.at_level(logging.DEBUG, logger="libtmux.common"):
...     _ = window.rename_window("release")
>>> completed = [
...     r for r in caplog.records
...     if r.getMessage() == "tmux command completed"
...     and getattr(r, "tmux_subcommand", None) == "rename-window"
... ]
>>> completed[0].tmux_exit_code
0
>>> window.kill()
```

## Formatting records safely

A format string that names a `tmux_` key will fail on records that do not carry
it. {mod}`logging` catches the error, prints it to stderr, and **drops the
record** — so a formatter written against `DEBUG` records silently loses your
`INFO` ones.

Give every custom key a default:

```python
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

## What libtmux does not log

Environment values never reach a log record. libtmux redacts them where the
command line is turned into text, so the variable names stay visible for
debugging while the values do not:

```python
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

Two things libtmux cannot redact for you, because it cannot tell a secret from a
keystroke:

- **{meth}`Pane.send_keys() <libtmux.Pane.send_keys>` payloads.** What you type
  into a pane appears verbatim in `tmux_cmd` at `DEBUG`. If you send
  credentials, do not ship `DEBUG` records off the host.
- **Anything you pass as a `start_directory`, `window_command`, or shell
  command**, for the same reason.

The command line also reaches the process table, so it is visible to `ps` for
the same user regardless of logging. Logs differ in that they travel.

## Cost

libtmux guards the expensive work — quoting the command line and slicing tmux's
output — behind {meth}`Logger.isEnabledFor() <logging.Logger.isEnabledFor>`, so
leaving `DEBUG` off costs a level comparison per command. Messages use lazy
`%s` interpolation, which keeps a given event under one message template in an
aggregator instead of producing a distinct string per occurrence.

At `DEBUG`, `tmux_stdout` and `tmux_stderr` are capped, and the untruncated
counts stay available as `tmux_stdout_len` and `tmux_stderr_len`. A
`list-panes` against a large server can still be a lot of text — prefer the
`_len` fields when you only need volume.

## Recipes

### Structured JSON output

Emit one JSON object per record, promoting the tmux fields to top level:

```python
import json
import logging


class TmuxJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(
            {k: v for k, v in record.__dict__.items() if k.startswith("tmux_")}
        )
        return json.dumps(payload)
```

### Route one server's records somewhere else

`tmux_socket` identifies the server, so a {class}`~logging.Filter` can split a
multi-server application's logs:

```python
class SocketFilter(logging.Filter):
    def __init__(self, socket: str) -> None:
        super().__init__()
        self.socket = socket

    def filter(self, record: logging.LogRecord) -> bool:
        return getattr(record, "tmux_socket", None) == self.socket
```

### Attach records to an OpenTelemetry span

The `tmux_` keys map onto span attributes without transformation, since they are
already flat scalars:

```python
def annotate(span, record: logging.LogRecord) -> None:
    for key, value in record.__dict__.items():
        if key.startswith("tmux_") and isinstance(value, (str, int)):
            span.set_attribute(key, value)
```
