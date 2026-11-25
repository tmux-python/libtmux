(program_arguments)=

# Program arguments

Pass `argv` when a program needs individual arguments without shell expansion:

```python
>>> program = session.new_window(argv=["cat", "-n"])
>>> program.active_pane.pane_dead
'0'
```

`argv` contains the executable followed by at least one argument. Spaces,
empty arguments, `$HOME`, `$(...)`, tmux format syntax, Unicode, semicolons,
and leading dashes reach the program literally. libtmux preserves argument
boundaries and escapes tmux's command-separator syntax; callers should not
shell-quote individual arguments.

An empty sequence or a one-element sequence raises `ValueError` before
creation or replacement. This is deliberate: tmux invokes a shell for a
single command argument. To run a program without arguments, keep using
authored shell text, such as `window_shell="exec cat"`; that text follows
the existing shell rules. A string passed as `argv`, a non-string element,
an empty executable, and embedded NUL characters are rejected.

## Creation and respawn

The same `argv` parameter is available on session creation, window creation,
pane splitting, and pane/window respawn:

```python
>>> created = server.new_session(session_name="argv-example", argv=["cat", "-n"])
>>> first = created.active_window
>>> from libtmux.constants import WindowDirection
>>> adjacent = first.new_window(argv=["cat", "-n"], direction=WindowDirection.After)
>>> tiled = adjacent.split(argv=["cat", "-n"])
>>> another = tiled.split(argv=["cat", "-n"])
>>> another.respawn(kill=True, argv=["cat", "-n"])
>>> first.respawn(kill=True, argv=["cat", "-n"])
>>> another.refresh()
>>> another.pane_dead
'0'
```

Floating-pane creation accepts `argv` on versions that already support
floating panes:

```python
>>> from libtmux.common import has_gte_version
>>> if has_gte_version("3.7"):
...     floating = window.new_pane(argv=["cat", "-n"])
...     other_floating = pane.new_pane(argv=["cat", "-n"])
```

Do not combine `argv` with `window_command`, `window_shell`, or `shell`,
including an explicitly empty shell string. These conflicts raise `ValueError`
before mutation, including when `kill_session`, `kill_existing`, or `kill`
would replace a running program. `argv` also conflicts with `empty=True`.
Omitting `argv` preserves the existing shell-string behavior and native
respawn defaults. Successful submission does not establish program exit.

## Native support

Multiple program arguments already use `execvp` at the tmux 3.2a floor;
see the tagged [3.2a implementation](https://github.com/tmux/tmux/blob/3.2a/spawn.c#L415-L437)
and [3.8 implementation](https://github.com/tmux/tmux/blob/3.8/spawn.c#L546-L568).
One argument follows the separate shell path in both versions. The CLI
also recognizes a trailing semicolon as a command separator; libtmux accounts
for the [3.2a argument parser](https://github.com/tmux/tmux/blob/3.2a/cmd-parse.y#L921-L1003)
without changing the program's received text.
