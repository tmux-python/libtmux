(which-call)=

# Which call do I want?

Find the task in the left column, then use the call next to it. Every row names
what the call returns, what it raises, and the tmux mechanism underneath, so you
know what you are trusting.

Most scripts need the first four rows.

## Run, wait, read

| Task | Call | Returns / raises | tmux mechanism |
| ---- | ---- | ---------------- | -------------- |
| Run a command, get exit status and output | {meth}`Pane.run(cmd) <libtmux.Pane.run>` | {class}`~libtmux.run.PaneRunResult` (`returncode`, `stdout`); {exc}`~libtmux.exc.PaneRunTimeout`, {exc}`~libtmux.exc.PaneNotFound`, {exc}`~libtmux.exc.TmuxServerGone` | Typed line; the shell signals a `wait-for` channel |
| Wait for text a process prints | {meth}`Pane.wait_for_text(pattern) <libtmux.Pane.wait_for_text>` | {class}`~libtmux.capture.TextMatch`; {exc}`~libtmux.exc.WaitTimeout` | Polls `capture-pane`, searches rows after an anchor |
| Wait until the screen stops changing | {meth}`Pane.wait_for_idle() <libtmux.Pane.wait_for_idle>` | {class}`~libtmux.capture.CaptureSince`; {exc}`~libtmux.exc.WaitTimeout` | Polls `capture-pane` until `quiet` seconds pass unchanged |
| Wait for the pane's process to exit | {meth}`Pane.wait() <libtmux.Pane.wait>` | {class}`~libtmux.pane.PaneExit` (`status`, `signal`); {exc}`~libtmux.exc.WaitTimeout` | `remain-on-exit` plus polling the pane's dead state |
| Wait for a channel you signal yourself | {meth}`Server.wait_for(channel) <libtmux.Server.wait_for>` | `None`; {exc}`~libtmux.exc.TmuxTimeout`, {exc}`~libtmux.exc.TmuxServerGone` | `tmux wait-for` |
| Read only what is new since last time | {meth}`Pane.capture_since(cursor) <libtmux.Pane.capture_since>` | {class}`~libtmux.capture.CaptureSince` (`lines`, `cursor`, `lines_missed`) | `capture-pane` with history offsets |
| Snapshot the screen | {meth}`Pane.capture_pane() <libtmux.Pane.capture_pane>` | `list[str]` | `capture-pane -p` |

## Send input

| Task | Call | Returns / raises | tmux mechanism |
| ---- | ---- | ---------------- | -------------- |
| Type a short command or a key | {meth}`Pane.send_keys(...) <libtmux.Pane.send_keys>` | `None` | `send-keys` |
| Send multi-line or large text, unchanged | {meth}`Pane.paste_text(text) <libtmux.Pane.paste_text>` | `None`; {exc}`~libtmux.exc.LibTmuxException` | `load-buffer` from stdin, then `paste-buffer -d` |

## Servers, sessions, panes

| Task | Call | Returns / raises | tmux mechanism |
| ---- | ---- | ---------------- | -------------- |
| A private server that cleans up after itself | {meth}`Server.owned() <libtmux.Server.owned>` | context manager yielding a {class}`~libtmux.Server`; {exc}`~libtmux.exc.SocketPathTooLong` | Own socket directory, no config file, reaper process |
| Get a session by name, creating it if absent | {meth}`Server.ensure_session(name) <libtmux.Server.ensure_session>` | {class}`~libtmux.Session`; {exc}`~libtmux.exc.BadSessionName` | Exact-name lookup in `list-sessions`, else `new-session` |
| List objects, failing loudly when tmux is unreachable | {meth}`Server.fetch_sessions() <libtmux.Server.fetch_sessions>`, {meth}`~libtmux.Server.fetch_windows`, {meth}`~libtmux.Server.fetch_panes` | `list`; {exc}`~libtmux.exc.ListCommandFailed` | `list-sessions`, `list-windows -a`, `list-panes -a` |
| List objects, empty when tmux is unreachable | {attr}`Server.sessions <libtmux.Server.sessions>` and its siblings | {class}`~libtmux._internal.query_list.QueryList`; never raises | Same list commands, failure swallowed |
| Add many panes without "no space for new pane" | {meth}`Window.split_many(n) <libtmux.Window.split_many>` | `list[Pane]`; {exc}`~libtmux.exc.LibTmuxException` | `split-window`, then `select-layout` after each split |
| Name a pane durably | {meth}`Pane.set_label(text) <libtmux.Pane.set_label>`, {attr}`Pane.label <libtmux.Pane.label>` | the pane / `str` or `None` | A `@` user option, not the title an app can overwrite |
| Find the pane your code runs in | {meth}`Pane.from_env() <libtmux.Pane.from_env>` | {class}`~libtmux.Pane`; {exc}`~libtmux.exc.NotInsideTmux` | `$TMUX` and `$TMUX_PANE` |
| Any tmux command | {meth}`Server.cmd(...) <libtmux.Server.cmd>` (on any object) | {class}`~libtmux.common.tmux_cmd` (`stdout`, `stderr`) | The command, with your socket flags |

## Tests

| Task | Call | Returns / raises | tmux mechanism |
| ---- | ---- | ---------------- | -------------- |
| Assert on what a TUI drew | {func}`~libtmux.test.screen.assert_screen` | `None`; `AssertionError` with a line diff | Repeats `capture-pane` until equal or timed out |
| Get a shell that looks the same everywhere | `@pytest.mark.deterministic_shell` | A pane running bash with no startup files | `env -i bash --norc` as the session's window command |
| Attach to a failed test's server | Printed in the pytest report | An attach command | The test server's socket path |
| An isolated server and session per test | {fixture}`server`, {fixture}`session` | {class}`~libtmux.Server`, {class}`~libtmux.Session` | A private socket per test |

## Choosing between neighbours

- **`run` or `send_keys`?** Use `run` when you need the result. Use `send_keys`
  to start something and walk away, or to answer a prompt in a running program.
  See {ref}`run-a-command`.
- **`wait_for_text` or `wait_for_idle`?** Wait for text when the program prints
  a marker. Wait for idle when it does not. See {ref}`recipe-wait-for-text`.
- **`wait` or `wait_for_text`?** `wait` ends when the pane's process ends, not
  when a command typed into its shell ends.
- **`fetch_*` or the properties?** `fetch_*` raises when tmux is unreachable, so
  an empty list means no objects. The properties return an empty list instead.
- **`send_keys` or `paste_text`?** `send_keys` types keys and names, and tmux
  refuses a command above 16 KiB. `paste_text` sends any size and never reads
  its text as key names or flags.

:::{seealso}
- {ref}`api` for every class and method
- {doc}`../api/libtmux.exc` for the exception hierarchy
:::
