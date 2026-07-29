(howto-send-keys-to-every-pane)=

# Send keys to every pane

Fanning one command out across a split window — starting the same watcher in
three directories, restarting a process in each — is a loop over
{attr}`Window.panes <libtmux.Window.panes>`. There is no `Window.send_keys`:
typing is something you do *to a pane*, and a window is a container, so the
window hands you its panes and you drive each one.

The three blocks below run in sequence. Paste the first into a Python session,
then the second, then the third.

## Build a window with three panes

{meth}`~libtmux.Window.split` splits the window's active pane and returns the
new {class}`~libtmux.Pane`. Calling it twice leaves you with three.

```python
from libtmux import Server

server = Server(socket_name="libtmux-howto")
session = server.new_session(session_name="fanout", kill_session=True)
window = session.active_window

window.split()
window.split()

print(f"{len(window.panes)} panes in {window.window_id}")
```

Two habits here are worth stealing. Naming the socket puts this window on a
server of its own, so nothing you do next can reach the tmux you already have
open. And `kill_session=True` replaces a `fanout` session left over from last
time instead of raising {exc}`~libtmux.exc.TmuxSessionExists` — which matters
the second time you run a script you are still writing.

## Type the command into each one

{meth}`~libtmux.Pane.send_keys` types into a pane and presses Enter, exactly as
if you had typed at the keyboard. Iterating {attr}`Window.panes
<libtmux.Window.panes>` re-queries tmux, so the two panes you just split are
already there.

```python
for pane in window.panes:
    pane.send_keys('echo "$TMUX_PANE is ready"')
```

Each pane's own shell expands `$TMUX_PANE`, so every pane answers with its own
id — proof the fan-out landed in three places rather than three times in one.

## Read the output back

{meth}`~libtmux.Pane.capture_pane` returns the pane's visible lines. It is a
snapshot, not a stream, and `send_keys` returns as soon as tmux has accepted
the keystrokes — the shell runs the command afterwards. So you wait for the
answer rather than assume it has arrived.

Two details make that wait honest. Poll against a deadline instead of sleeping
a fixed amount: a sleep long enough for a cold shell is dead time on every run
after the first, and a sleep short enough to feel quick reports "not ready" on
a machine that was merely busy. And compare *whole lines* — the captured lines
include the command tmux echoed onto the pane, so a substring test for `is
ready` matches that echo and is true before the shell has run anything at all.

```python
import time


def ready(pane):
    answer = f"{pane.pane_id} is ready"
    return any(line.strip() == answer for line in pane.capture_pane())


deadline = time.monotonic() + 10
while time.monotonic() < deadline and not all(ready(p) for p in window.panes):
    time.sleep(0.1)

for pane in window.panes:
    print(pane.pane_id, ready(pane))

session.kill()
```

{meth}`~libtmux.Session.kill` tears the session down. For work that should
clean itself up even when something raises, see {ref}`context_managers`.

## Related

- {ref}`pane-interaction` — the rest of what a pane can do, including waiting
  on output as a first-class operation.
- {ref}`howto-check-if-tmux-is-running` — confirm there is a server first.
