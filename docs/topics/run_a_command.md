(run-a-command)=

# Run a command and get its exit status

{meth}`Pane.run() <libtmux.Pane.run>` types a shell command into a pane, waits
for it to finish, and returns its exit status and output. Reach for it when a
script or an agent needs to know that a command finished, how it ended, and what
it printed. If you only start a process and walk away, {meth}`Pane.send_keys()
<libtmux.Pane.send_keys>` is still the right call.

## The recipe

```python
>>> result = pane.run('echo hello; sh -c "exit 3"', timeout=30)
>>> result.returncode
3

>>> result.stdout
['hello']
```

`stdout` is a list of lines, like `tmux_cmd.stdout`. The pane's terminal carries stdout and stderr
together, so both arrive in it. A nonzero status is a result, not an exception.

The command runs in the pane's own shell, so `cd` and `export` carry over to the
next call:

```python
>>> _ = pane.run('cd /tmp; export GREETING=hi', timeout=30)
>>> pane.run('echo "$PWD $GREETING"', timeout=30).stdout
['/tmp hi']
```

## Why not `send_keys` and `capture_pane`

The usual recipe types the command and then reads the screen back:

```python
pane.send_keys("make test")
time.sleep(5)  # or poll until the screen stops changing
text = pane.capture_pane()
```

It guesses at three things `Pane.run()` knows:

| You need                | `send_keys` + `capture_pane`                         | `Pane.run()`                              |
| ----------------------- | ---------------------------------------------------- | ----------------------------------------- |
| When it finished        | A sleep, or polling a prompt or marker               | The shell signals a tmux channel          |
| How it ended            | Not available; scrape `$?` from the screen           | `returncode`                              |
| Which lines are its own | Diff two captures; the echoed command is in the text | `stdout`, between per-call markers        |
| A hung command          | Loops forever unless you wrote a bound               | `timeout` raises, carrying the output so far |

The cost is an extra tmux round trip or two per call: about 25 ms for `true` on
a loaded machine, against 3 ms for a single tmux command.

## Bound the wait

Every call has a bound; the default is 120 seconds. On expiry
{exc}`~libtmux.exc.PaneRunTimeout` carries what the command had printed:

```python
>>> from libtmux import exc
>>> try:
...     pane.run('echo before; sleep 30', timeout=1)
... except exc.TmuxTimeout as e:
...     print(e.stdout)
['before']

>>> pane.send_keys('C-c', enter=False)
```

{exc}`~libtmux.exc.PaneRunTimeout` is a {exc}`~libtmux.exc.TmuxTimeout`, the same
exception {meth}`Server.wait_for() <libtmux.Server.wait_for>` and the `timeout`
argument of `cmd()` raise, so one `except TmuxTimeout` covers all three. It is not
a {exc}`~libtmux.exc.LibTmuxException`. The command keeps running in the pane;
interrupt it yourself.

## What a call tolerates

These end the call promptly instead of hanging:

- **A command the shell rejects**, such as a syntax error or an unterminated
  quote, returns a nonzero `returncode` with the shell's message in `stdout`.
- **An interrupt** (`C-c`, sent by you or by another process) ends the command
  and returns status 130.
- **A server that exits** raises {exc}`~libtmux.exc.TmuxServerGone`.
- **A command that closes the pane**, such as `exit`, raises
  {exc}`~libtmux.exc.PaneNotFound` at once, also when `remain-on-exit` keeps the
  dead pane. For the length of the call, `Pane.run()` installs `pane-exited` and
  `pane-died` hooks on the server, each at an array index of its own and
  filtered to the pane, and removes them on every path out. Hooks you already
  have are left alone.

A pane killed from outside with `kill-pane` or `kill-window` waits for `timeout`:
tmux runs no hook for it, and then raises {exc}`~libtmux.exc.PaneNotFound`.

## Where it does not work

The pane MUST be at an interactive prompt of a Bourne-style shell. bash, zsh, dash
and sh are tested; fish and csh are not supported.

The typed line reports back through the local tmux server, so a shell that cannot
reach that server cannot answer. That is the case for `ssh` and `docker exec`
panes and for any program already running in the foreground. The shell
acknowledges the line before it runs the command; when no acknowledgement arrives
within five seconds, the call raises {exc}`~libtmux.exc.PaneRunTimeout` with
`started` set to False instead of waiting out `timeout`. The typed line stays in
that pane.

## Threads and processes

One pane has one input stream and one screen, so `Pane.run()` holds a lock per
pane: calls from several threads on the same pane run one after another, each
returning its own output. The lock is keyed by the server's socket and the pane
id, so {class}`~libtmux.Server` objects that share a socket share it, and calls on
different panes run in parallel. The time a call spends waiting for the lock counts
against its `timeout`; a call that never gets the lock raises
{exc}`~libtmux.exc.PaneRunTimeout` with `started` set to False, and nothing is typed.

The lock lives in one Python process. Two processes, or `Pane.run()` and your own
`send_keys`, can still type into the same pane at once; give each pane one driver.
A tmux-side lock (`wait-for -L`) would reach across processes, but tmux keeps it on
the channel and never releases it when its holder dies, so a crashed caller would
block every later call on the pane.

## Shell history

The typed line starts with a space, which bash and zsh skip when
`HISTCONTROL=ignorespace` or `setopt hist_ignore_space` is set. In bash the line
also deletes its own history entry, so no setting is needed. zsh keeps the entry
unless `hist_ignore_space` is on, because zsh offers no way to remove an entry from
inside the line.

## Replacing hand-rolled waits

The snippets below paraphrase patterns from three public projects and link the
code they describe. Each project's own code is longer and handles more than is
shown.

### A prompt-marker poll (OpenHands)

OpenHands' tmux terminal installs a prompt hook that prints a JSON block after
every command, then polls the screen for it and parses the block
([`tmux_terminal.py`](https://github.com/OpenHands/software-agent-sdk/blob/0a9abc87641ad7ffe02e2dadf5e2cb3976b35217/openhands-tools/openhands/tools/terminal/terminal/tmux_terminal.py#L115-L174),
and the older
[`bash.py`](https://github.com/OpenHands/OpenHands/blob/137bede1f5e867a7eb17ae36e78a05ffef6ec09a/openhands/runtime/utils/bash.py#L209-L260)):

```python
# before
pane.send_keys(command, literal=True)
while not finished and time.monotonic() - last_change < no_change_timeout:
    time.sleep(0.5)
    finished, exit_code, output = parse_prompt_blocks(pane.capture_pane())

# after
result = pane.run(command, timeout=no_change_timeout)
result.returncode, result.stdout
```

The prompt hook, the poll loop and the parser go away, and a process that prints
the marker cannot spoof the end, because each call's markers carry a random token.
OpenHands also lets a command run on after a no-change timeout and keeps feeding
it input; `Pane.run()` does not cover that interactive case.

### A fixed wait channel (Harbor)

Harbor's Terminus 2 appends `; tmux wait -S done` to the command and then runs
`timeout N tmux wait done`, taking the pane's text before and after
([`tmux_session.py`](https://github.com/harbor-framework/harbor/blob/bf991e490394ef9c3250a6db2bc5cbda903cb4c3/src/harbor/agents/terminus_2/tmux_session.py#L407-L467)):

```python
# before
pane.send_keys(f"{command}; tmux wait -S done")
subprocess.run(["timeout", "180", "tmux", "wait", "done"], check=False)
output = diff_screens(before, pane.capture_pane())

# after
result = pane.run(command, timeout=180)
```

This gains the exit status, a channel no other call shares, and output cut at
exact markers. The shared channel is also the hazard: on tmux 3.2a through 3.8-rc a
waiter that is killed on timeout stays queued and swallows the next signal.
`Pane.run()` waits through {meth}`Server.wait_for() <libtmux.Server.wait_for>`,
which releases the waiter first. Harbor chunks long commands and stages oversize
payloads through tmux buffers; that sending side is not part of `Pane.run()`.

### Sleep, then capture (CAO)

awslabs' cli-agent-orchestrator delivers text to agent CLIs by pasting it, sleeping
a per-provider delay, and pressing Enter
([`tmux.py`](https://github.com/awslabs/cli-agent-orchestrator/blob/a1c3d138c38e58d1df04f9850b828e0b3df513e6/src/cli_agent_orchestrator/clients/tmux.py#L1445-L1625)).
The same shape appears wherever a script types a shell command, sleeps, and reads
the pane:

```python
# before
pane.send_keys(f"{command}; echo $? > /tmp/status")
wait_for_file("/tmp/status")  # or time.sleep(delay)

# after
pane.run(command, timeout=delay).returncode
```

`Pane.run()` replaces this only for a shell prompt. An agent CLI's text box is not
a shell, so CAO's delivery to agents stays a paste-and-wait.
