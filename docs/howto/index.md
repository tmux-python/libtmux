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

```{toctree}
:hidden:

check-if-tmux-is-running
send-keys-to-every-pane
start-a-server
run-multiple-servers
connect-to-an-existing-server
```
