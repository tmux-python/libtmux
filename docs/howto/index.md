(howto)=

# How-to guides

Task-shaped recipes you can lift straight into your own code. Every code block
on these pages is plain, runnable Python — no doctest prompts, no test
scaffolding — so pasting the blocks of a page in order does on your machine
what the page says it does.

Reach for a how-to when you know what you want and want the shortest correct
way to get it. When you want the model behind it instead, each page links the
{doc}`topic <../topics/index>` that explains why the API is shaped the way it
is.

## Servers

::::{grid} 1 1 2 2
:gutter: 2 2 3 3

:::{grid-item-card} Check if tmux is running
:link: check-if-tmux-is-running
:link-type: doc
Ask a {class}`~libtmux.Server` whether anything is alive on the other end of
its socket, and tell "no server" apart from "no sessions".
:::

:::{grid-item-card} Start a tmux server
:link: start-a-server
:link-type: doc
Boot a daemon that outlives your script, attach to it from a shell, and see
why {meth}`~libtmux.Server.start_server` is not the call you want.
:::

:::{grid-item-card} Run multiple tmux servers
:link: run-multiple-servers
:link-type: doc
Give each daemon its own socket so their sessions, windows and panes cannot
reach one another.
:::

:::{grid-item-card} Connect to an existing tmux server
:link: connect-to-an-existing-server
:link-type: doc
Point a {class}`~libtmux.Server` handle at a socket someone else started, and
confirm anything is listening on it.
:::

::::

## Driving panes

::::{grid} 1 1 2 2
:gutter: 2 2 3 3

:::{grid-item-card} Send keys to every pane
:link: send-keys-to-every-pane
:link-type: doc
Split a window, fan one command across its {class}`~libtmux.Pane` objects,
and wait for each one's answer.
:::

::::

## Sessions, windows, and panes

::::{grid} 1 1 2 2
:gutter: 2 2 3 3

:::{grid-item-card} Connect to an existing session
:link: connect-to-an-existing-session
:link-type: doc
Look a {class}`~libtmux.Session` up by name on a running server, and tell
"no such session" apart from "no server".
:::

:::{grid-item-card} Connect to an existing window
:link: connect-to-an-existing-window
:link-type: doc
Find a {class}`~libtmux.Window` inside a session by name or index, and learn
which of the two survives a rename.
:::

:::{grid-item-card} Connect to an existing pane
:link: connect-to-an-existing-pane
:link-type: doc
Find a {class}`~libtmux.Pane` inside a window, and see why the newest pane is
not the last one in the list.
:::

::::

## Code running inside tmux

::::{grid} 1 1 2 2
:gutter: 2 2 3 3

:::{grid-item-card} Detect that you are inside tmux
:link: detect-you-are-inside-tmux
:link-type: doc
Branch on whether your own process was spawned by a pane, and tell that apart
from the server still being reachable.
:::

:::{grid-item-card} Find the session you're in
:link: find-the-session-youre-in
:link-type: doc
Get the {class}`~libtmux.Session` holding your process, then walk out from it.
:::

:::{grid-item-card} Find the window you're in
:link: find-the-window-youre-in
:link-type: doc
Get the {class}`~libtmux.Window` that contains you, and every session that
holds it when it is shared.
:::

:::{grid-item-card} Find the pane you're in
:link: find-the-pane-youre-in
:link-type: doc
Get the {class}`~libtmux.Pane` your code runs in, which is not the same as the
pane holding the focus.
:::

::::

```{toctree}
:hidden:

check-if-tmux-is-running
send-keys-to-every-pane
start-a-server
run-multiple-servers
connect-to-an-existing-server
connect-to-an-existing-session
connect-to-an-existing-window
connect-to-an-existing-pane
detect-you-are-inside-tmux
find-the-session-youre-in
find-the-window-youre-in
find-the-pane-youre-in
```
