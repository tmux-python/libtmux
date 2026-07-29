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
```
