(quickstart)=

# Quickstart

libtmux allows for developers and system administrators to control live tmux
sessions using python code.

In this example, we will launch a tmux session and control the windows
from inside a live tmux session.

(requirements)=

## Requirements

- [tmux][tmux]
- [pip][pip] - for this handbook's examples

[pip]: https://pip.pypa.io/en/stable/installing/

[tmux]: https://tmux.github.io/

(installation)=

## Installation

Next, ensure `libtmux` is installed:

```console

$ pip install --user libtmux

```

## Start a tmux session

Now, let's open a tmux session.

```console

$ tmux new-session -n bar -s foo

```

This tutorial will be using the session and window name in the example.

Window name `-n`: `bar`
Session name `-s`: `foo`

## Control tmux via python

:::{seealso}

{ref}`api`

:::

```{eval-rst}
.. todo:: Do a version of this with `sliderepl`_

```

```console

$ python

```

For commandline completion, you can also use [ptpython].

```console

$ pip install --user ptpython
$ ptpython

```

[ptpython]: https://github.com/prompt-toolkit/ptpython

```{module} libtmux

```

First, we can grab a {class}`Server`.

```{code-block} python

>>> import libtmux
>>> server = libtmux.Server()
>>> server
<libtmux.server.Server object at 0x7fbd622c1dd0>

```

:::{tip}

You can also use [tmuxp]'s [`tmuxp shell`] to drop straight into your
current tmux server / session / window pane.

[tmuxp]: https://tmuxp.git-pull.com/
[`tmuxp shell`]: https://tmuxp.git-pull.com/cli.html#shell

:::

:::{note}

You can specify a `socket_name`, `socket_path` and `config_file`
in your server object. `libtmux.Server(socket_name='mysocket')` is
equivalent to `$ tmux -L mysocket`.

:::

`server` is now a living object bound to the tmux server's Sessions,
Windows and Panes.

## Find your {class}`Session`

If you have multiple tmux sessions open, you can see that all of the
methods in {class}`Server` are available.

We can list sessions with {meth}`Server.list_sessions`:

```{code-block} python

>>> server.list_sessions()
[Session($3 foo), Session($1 libtmux)]

```

This returns a list of {class}`Session` objects you can grab. We can
find our current session with:

```{code-block} python

>>> server.list_sessions()[0]

```

However, this isn't guaranteed, libtmux works against current tmux information, the
session's name could be changed, or another tmux session may be created,
so {meth}`Server.get_by_id` and {meth}`Server.find_where` exists as a lookup.

## Get session by ID

tmux sessions use the `$[0-9]` convention as a way to identify sessions.

`$3` is whatever the ID `list_sessions()` returned above.

```{code-block} python

>>> server.get_by_id('$3')
Session($3 foo)

```

You may `session = server.get_by_id('$<yourId>')` to use the session object.

## Get session by name / other properties

```{code-block} python

>>> server.find_where({ "session_name": "foo" })
Session($3 foo)

```

With `find_where`, pass in a dict and return the first object found. In
this case, a {class}`Server` holds a collection of child {class}`Session`.
{class}`Session` and {class}`Window` both utilize `find_where` to sift
through Windows and Panes, respectively.

So you may now use:

```{code-block} python

>>> session = server.find_where({ "session_name": "foo" })

```

to give us a `session` object to play with.

## Playing with our tmux session

We now have access to `session` from above with all of the methods
available in {class}`Session`.

Let's make a {meth}`Session.new_window`, in the background:

```{code-block} python

>>> session.new_window(attach=False, window_name="ha in the bg")
Window(@8 2:ha in the bg, Session($3 foo))

```

So a few things:

1. `attach=False` meant to create a new window, but not to switch to it.
   It is the same as `$ tmux new-window -d`.
2. `window_name` may be specified.
3. Returns the {class}`Window` object created.

:::{note}

Use the API reference {ref}`api` for more commands.

:::

Let's delete that window ({meth}`Session.kill_window`).

Method 1: Use passthrough to tmux's `target` system.

```{code-block} python

>>> session.kill_window("ha in")

```

The window in the bg dissappeared. This was the equivalent of
`$ tmux kill-window -t'ha in'`

Internally, tmux uses `target`. Its specific behavior depends on what the
target is, view the tmux manpage for more information:

```
This section contains a list of the commands supported by tmux.  Most commands
accept the optional -t argument with one of target-client, target-session,
target-window, or target-pane.
```

In this case, you can also go back in time and recreate the window again. The CLI
should have history, so navigate up with the arrow key.

```{code-block} python

>>> session.new_window(attach=False, window_name="ha in the bg")
Window(@11 3:ha in the bg, Session($3 foo))

```

Try to kill the window by the matching id `@[0-9999]`.

```{code-block} python

>>> session.new_window(attach=False, window_name="ha in the bg")
Window(@12 3:ha in the bg, Session($3 foo))

```

In addition, you could also `.kill_window` direction from the {class}`Window`
object:

```{code-block} python

>>> window = session.new_window(attach=False, window_name="check this out")

```

And kill:

```{code-block} python

>>> window.kill_window()

```

Use {meth}`Session.list_windows()` and {meth}`Session.find_where()` to list and sort
through active {class}`Window`'s.

## Manipulating windows

Now that we know how to create windows, let's use one. Let's use {meth}`Session.attached_window()`
to grab our current window.

```{code-block} python

>>> window = session.attached_window()

```

`window` now has access to all of the objects inside of {class}`Window`.

Let's create a pane, {meth}`Window.split_window`:

```{code-block} python

>>> window.split_window(attach=False)
Pane(%23 Window(@10 1:bar, Session($3 foo)))

```

Powered up. Let's have a break down:

1. `window = session.attached_window()` gave us the {class}`Window` of the current attached to window.
2. `attach=False` assures the cursor didn't switch to the newly created pane.
3. Returned the created {class}`Pane`.

Also, since you are aware of this power, let's commemorate the experience:

```{code-block} python

>>> window.rename_window('libtmuxower')
Window(@10 1:libtmuxower, Session($3 foo))

```

You should have noticed {meth}`Window.rename_window` renamed the window.

## Moving cursor across windows and panes

You have two ways you can move your cursor to new sessions, windows and panes.

For one, arguments such as `attach=False` can be omittted.

```{code-block} python

>>> pane = window.split_window()

```

This gives you the {class}`Pane` along with moving the cursor to a new window. You
can also use the `.select_*` available on the object, in this case the pane has
{meth}`Pane.select_pane()`.

```{code-block} python

>>> pane = window.split_window(attach=False)
>>> pane.select_pane()

```

```{eval-rst}
.. todo:: create a ``kill_pane()`` method.
```

```{eval-rst}
.. todo:: have a ``.kill()`` and ``.select()`` proxy for Server, Session, Window and Pane objects.
```

## Sending commands to tmux panes remotely

You may send commands to panes, windows and sessions **without** them being visible.
As long as you have the object, or are iterating through a list of them, you can use `.send_keys`.

```{code-block} python

>>> window = session.new_window(attach=False, window_name="test")
>>> pane = window.split_window(attach=False)
>>> pane.send_keys('echo hey', enter=False)

```

See the other window, notice that {meth}`Pane.send_keys` has " `echo hey`" written,
_still in the prompt_. Note the leading space character so the command won't be added to the user's history. Use {}`pane.cmd('send-keys', text)` to send keys without this leading space.

`enter=False` can be used to send keys without pressing return. In this case,
you may leave it to the user to press return himself, or complete a command
using {meth}`Pane.enter()`:

```{code-block} python

>>> pane.enter()

```

## Final notes

These objects created use tmux's internal usage of ID's to make servers,
sessions, windows and panes accessible at the object level.

You don't have to see the tmux session to be able to orchestrate it. After
all, {class}`WorkspaceBuilder` uses these same internals to build your
sessions in the background. :)

:::{seealso}

If you want to dig deeper, check out {ref}`API`, the code for
and our [test suite][test suite] (see {ref}`developing`.)

:::

[sliderepl]: http://discorporate.us/projects/sliderepl/
[workspacebuilder.py]: https://github.com/tmux-python/libtmux/blob/master/libtmux/workspacebuilder.py
[test suite]: https://github.com/tmux-python/libtmux/tree/master/tests
[ptpython]: https://github.com/jonathanslenders/ptpython
