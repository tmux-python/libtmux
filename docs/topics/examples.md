(examples)=

# Runnable examples

Run these complete programs from a checkout with libtmux installed,
tmux 3.2a or newer, and the POSIX utilities `sh`, `cat`, and `stty` on
`PATH`. Each creates a temporary private socket,
uses an empty tmux configuration, checks its result, and kills its own
server in `finally`. Existing sessions stay untouched.

| Program | Result checked |
| --- | --- |
| `examples/create_window.py` | A new window has a distinct ID and the name `logs`. |
| `examples/rename_window.py` | The renamed window keeps its ID and has the name `logs`. |
| `examples/send_keys.py` | A pane reader acknowledges a line and its response appears in captured text. |

The `tests/test_examples.py` check runs these same files twice as separate
Python processes, requires their expected output and a zero exit status,
and verifies that an unrelated session and its program survive. It runs
in the existing `tests` workflow on each supported tmux lane. The examples
are also included in source distributions.

## Create a window

```console
$ uv run python examples/create_window.py
```

Expected output: `created window: logs`.

```{literalinclude} ../../examples/create_window.py
:language: python
```

## Rename a window

```console
$ uv run python examples/rename_window.py
```

Expected output: `renamed window: logs`.

```{literalinclude} ../../examples/rename_window.py
:language: python
```

## Send keys and read the response

```console
$ uv run python examples/send_keys.py
```

Expected output: `received: hello from libtmux`.

{meth}`~libtmux.Pane.send_keys` submits input. The POSIX shell reader turns
terminal echo off, signals when it is ready, and acknowledges the line
after printing its response. {meth}`~libtmux.Server.wait_for` waits for
those ordinary channel signals; a signal sent first is remembered by tmux.
These channels are available at the tmux 3.2a floor and do not use the
event-wait feature added in tmux 3.8.

The local wait helper allows one second for each acknowledgement. A missing
signal tears down this program's private server and raises `TimeoutError`.
The reader remains running until cleanup: neither the channel signal nor
the captured line is process-exit evidence.

```{literalinclude} ../../examples/send_keys.py
:language: python
```

Further standalone programs for watching changes, moving windows, setting
layouts, explicit argument lists, and run-to-exit behavior remain tracked
in [issue #815](https://github.com/tmux-python/libtmux/issues/815).
