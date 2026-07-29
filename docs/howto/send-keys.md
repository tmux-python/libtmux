(howto-send-keys)=

# Send keys to a pane

{meth}`~libtmux.Pane.send_keys` types into a {class}`~libtmux.Pane` exactly as
if you were sitting at its keyboard, and presses Enter when it is done. That is
the whole of the sending half: hand it a command string and the pane's shell
runs it.

The reading half is where the care goes. `send_keys` returns as soon as tmux has
accepted the keystrokes — the shell runs the command afterwards, on its own
schedule — so getting the answer back means waiting for it, and waiting for the
*right* thing.

The three blocks below run in sequence. Paste the first into a Python session,
then the second, then the third.

## Type a command and read the answer

```python
import time

from libtmux import Server

server = Server(socket_name="libtmux-howto")
session = server.new_session(session_name="send-keys", kill_session=True)
window = session.active_window
pane = window.active_pane

pane.send_keys("echo hello from $TMUX_PANE")


def answered(pane, line):
    return any(row.strip() == line for row in pane.capture_pane())


answer = f"hello from {pane.pane_id}"
deadline = time.monotonic() + 10
while time.monotonic() < deadline and not answered(pane, answer):
    time.sleep(0.1)

print(answered(pane, answer))
```

Naming the socket puts this session on a server of its own, so nothing on this
page can reach the tmux you already have open, and `kill_session=True` replaces
a `send-keys` session left over from a previous run instead of raising
{exc}`~libtmux.exc.TmuxSessionExists`.

Two details make the wait honest, and both are easy to get wrong. Poll against
a deadline rather than sleeping a fixed amount: a sleep long enough for a cold
shell is dead time on every run after the first, and a short one reports failure
on a machine that was merely busy. And compare *whole lines* —
{meth}`~libtmux.Pane.capture_pane` hands back the screen, which includes the
command tmux just echoed onto it, so `"hello from" in captured_text` is true the
instant the keystrokes land and stays true in a world where no shell ever runs.

## Type without running

Pass `enter=False` to leave the text sitting at the prompt: staging a command
for someone to look over, or feeding a keystroke to a program that is already
waiting for one. {meth}`~libtmux.Pane.enter` presses Enter on its own when you
are ready.

`literal=True` matters as soon as what you type could be read as a key. tmux
resolves the string you send against its key names first, so `send_keys("Enter")`
presses the Enter key rather than typing the five letters. `literal=True` turns
that off and sends the characters through untouched — which is what you want for
anything you did not write by hand, including user input and file contents.

```python
pane.send_keys("echo ", enter=False)
pane.send_keys("Enter", enter=False, literal=True)
pane.enter()

deadline = time.monotonic() + 10
while time.monotonic() < deadline and not answered(pane, "Enter"):
    time.sleep(0.1)

print(answered(pane, "Enter"))
```

The pane runs `echo Enter` and prints `Enter`. Drop `literal=True` from the
second call and the same line becomes `echo ` followed by a press of Enter — a
command you did not mean to run, assembled out of text you did not think of as
keys.

## Keep a command out of shell history

`suppress_history=True` prepends a single space to the command. That is the
entire mechanism, and it makes the flag a request to your shell rather than
something tmux enforces: bash honours it under `HISTCONTROL=ignorespace` or
`ignoreboth`, zsh under `setopt histignorespace`, and a shell configured with
neither records the command exactly as it would have anyway.

Because the outcome belongs to the shell, this example runs its own bash with
the option set, rather than trusting whatever your default shell does.

```python
history_pane = window.split(shell="bash --norc --noprofile")
history_pane.send_keys("HISTCONTROL=ignorespace")
history_pane.send_keys("echo public")
history_pane.send_keys("echo private", suppress_history=True)
history_pane.send_keys("history")


def recorded(pane):
    entries = []
    for row in pane.capture_pane():
        number, _, command = row.strip().partition("  ")
        if number.isdigit():
            entries.append(command.strip())
    return entries


deadline = time.monotonic() + 10
while time.monotonic() < deadline and "history" not in recorded(history_pane):
    time.sleep(0.1)

print("public recorded:", "echo public" in recorded(history_pane))
print("private recorded:", "echo private" in recorded(history_pane))

session.kill()
```

Reading the `history` listing back, rather than trusting the flag, is the point
of the exercise: it is the only way to find out whether the shell in front of
you cooperates.

Even where it works, a suppressed command is hidden from one place only. It was
typed onto the screen, it is in the pane's scrollback, and its arguments are
visible in the process table while it runs — so treat the flag as tidiness, not
as a way to pass a secret.

{meth}`~libtmux.Session.kill` tears the session down. For work that should clean
up after itself even when something raises, see {ref}`context_managers`.

## Related

- {ref}`pane-interaction` — the rest of what a pane can do: capture flags,
  scrollback, resizing, and querying state.
- {ref}`howto-send-keys-to-every-pane` — the same command across a whole window.
- {ref}`howto-create-panes` — build the panes to type into.
