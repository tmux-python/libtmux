(internals)=

(about)=

# About

:::{seealso}

{ref}`api`

:::

```{currentmodule} libtmux

```

libtmux is a [typed](https://docs.python.org/3/library/typing.html) [abstraction layer] for tmux.

It builds upon the concept of targets `-t`, to direct commands against
individual session, windows and panes and `FORMATS`, template variables
exposed by tmux to describe their properties. Think of `-t` analagously
to [scope].

{class}`common.TmuxRelationalObject` acts as a container to connect the
relations of {class}`Server`, {class}`Session`, {class}`Window` and
{class}`Pane`.

| Object           | Child            | Parent           |
| ---------------- | ---------------- | ---------------- |
| {class}`Server`  | {class}`Session` | None             |
| {class}`Session` | {class}`Window`  | {class}`Server`  |
| {class}`Window`  | {class}`Pane`    | {class}`Session` |
| {class}`Pane`    | None             | {class}`Window`  |

Internally, tmux allows multiple servers to be ran on a system. Each one
uses a socket. The server-client architecture is executed so cleanly,
many users don't think about it. tmux automatically connects to a default
socket name and location for you if none (`-L`, `-S`) is specified.
A server will be created automatically upon starting if none exists.

A server can have multiple sessions. `Ctrl-a s` can be used to switch
between sessions running on the server.

Sessions, Windows and Panes all have their own unique identifier for
internal purposes. {class}`common.TmuxMappingObject` will make use of the
unique identifiers (`session_id`, `window_id`, `pane_id` ) to look
up the data stored in the {class}`Server` object.

| Object           | Prefix | Example                                   |
| ---------------- | ------ | ----------------------------------------- |
| {class}`Server`  | N/A    | N/A, uses `socket-name` and `socket-path` |
| {class}`Session` | `$`    | `$13`                                     |
| {class}`Window`  | `@`    | `@3243`                                   |
| {class}`Pane`    | `%`    | `%5433`                                   |

## Similarities to tmux and Pythonics

libtmux was built in the spirit of understanding how tmux operates
and how python objects and tools can abstract the API's in a pleasant way.

libtmux uses `FORMATTERS` in tmux to give identity attributes to
{class}`Session`, {class}`Window` and {class}`Pane` objects. See
[format.c].

[format.c]: https://github.com/tmux/tmux/blob/master/format.c

How is libtmux able to keep references to panes, windows and sessions?

> Tmux has unique ID's for sessions, windows and panes.
>
> panes use `%`, such as `%1234`
>
> windows use `@`, such as `@2345`
>
> sessions use `$`, for money, such as `$`
>
> How is libtmux able to handle windows with no names?

> Tmux provides `window_id` as a unique identifier.
>
> What is a {pane,window}\_index vs a {pane,window,session}\_id?

> Pane index refers to the order of a pane on the screen.
>
> Window index refers to the # of the window in the session.
>
> To assert pane, window and session data, libtmux will use
> {meth}`Server.sessions()`, {meth}`Session.windows()`,
> {meth}`Window.panes()` to update objects.

## Naming conventions

Because this is a python abstraction and commands like `new-window`
have dashes (-) replaced with underscores (\_).

## Reference

- tmux docs <http://www.openbsd.org/cgi-bin/man.cgi?query=tmux&sektion=1>
- tmux source code <http://sourceforge.net/p/tmux/tmux-code/ci/master/tree/>

[abstraction layer]: http://en.wikipedia.org/wiki/Abstraction_layer
[scope]: https://en.wikipedia.org/wiki/Variable_(computer_science)#Scope_and_extent
