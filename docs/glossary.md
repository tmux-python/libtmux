(glossary)=

# Glossary

```{glossary}

tmuxp
    A tool to manage workspaces with tmux. A pythonic abstraction of
    tmux.

tmux
tmux(1)
    The tmux binary. Used internally to distinguish tmuxp is only a
    layer on top of tmux.

kaptan
    configuration management library, see [kaptan on github](https://github.com/emre/kaptan).

Server
    Tmux runs in the background of your system as a process.

    The server holds multiple {term}`Session`. By default, tmux
    automatically starts the server the first time ``$ tmux`` is run.

    A server contains {term}`session`'s.

    tmux starts the server automatically if it's not running.

    Advanced cases: multiple can be run by specifying
    ``[-L socket-name]`` and ``[-S socket-path]``.

Client
    Attaches to a tmux {term}`server`.  When you use tmux through CLI,
    you are using tmux as a client.

Session
    Inside a tmux {term}`server`.

    The session has 1 or more {term}`Window`. The bottom bar in tmux
    show a list of windows. Normally they can be navigated with
    ``Ctrl-a [0-9]``, ``Ctrl-a n`` and ``Ctrl-a p``.

    Sessions can have a ``session_name``.

    Uniquely identified by ``session_id``.

Window
    Entity of a {term}`session`.

    Can have 1 or more {term}`pane`.

    Panes can be organized with a layouts.

    Windows can have names.

Pane
    Linked to a {term}`Window`.

    a pseudoterminal.

Target
    A target, cited in the manual as ``[-t target]`` can be a session,
    window or pane.

TMUX
    Environment variable tmux exports into every {term}`Pane` it spawns.

    Holds ``socket_path,server_pid,session_id`` for the {term}`Server`
    the pane belongs to. The session id is spelled bare, e.g. ``47``, where
    libtmux spells the same session ``$47``.

    Written once, when the pane is spawned, and never revised — so its
    session id records where the process was *launched*, and goes stale if
    the pane's {term}`Window` later moves.

    libtmux takes only the socket path from it, and asks tmux for the rest.
    See {ref}`self-location`.

TMUX_PANE
    Environment variable tmux exports into every {term}`Pane` it spawns.

    Holds that pane's ``pane_id``, e.g. ``%1``. Unlike ``TMUX`` it always
    names the pane the process is really in, so it is the id libtmux
    anchors on to answer where a process is running.

    Read back by libtmux in {ref}`self-location`.
```
