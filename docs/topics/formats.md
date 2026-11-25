(formats)=

# Literal text and tmux formats

tmux expands [formats](https://man.openbsd.org/tmux.1#FORMATS) such as
`#{session_name}` in many command arguments, including window names, pane
titles and start directories. libtmux keeps the text you pass as plain `str`
exactly as you typed it, so a `#` in a name or path never turns into something
else. When you want tmux to expand a value, wrap it in
{class}`~libtmux.Format`.

```python
>>> from libtmux import Format
```

## Plain strings are kept as typed

A plain `str` is stored exactly, even when it looks like a format:

```python
>>> window.rename_window("build#2")
Window(...)
>>> window.window_name
'build#2'

>>> window.rename_window("#{session_name}")
Window(...)
>>> window.window_name
'#{session_name}'
```

This covers every name, title, start directory and file path libtmux passes
to an argument tmux expands:

- session and window names in {meth}`~libtmux.Server.new_session`,
  {meth}`~libtmux.Session.new_window`, {meth}`~libtmux.Session.rename_session`
  and {meth}`~libtmux.Window.rename_window`
- pane titles in {meth}`~libtmux.Pane.set_title`, and the titles of
  {meth}`~libtmux.Pane.display_popup` and {meth}`~libtmux.Server.display_menu`
- start directories in `new_session`, `new_window`, `split`, `new_pane`, the
  respawn methods, {meth}`~libtmux.Pane.display_popup` and
  {meth}`~libtmux.Server.run_shell`
- buffer files in {meth}`~libtmux.Server.save_buffer` and
  {meth}`~libtmux.Server.load_buffer`

## Ask tmux to expand a value

Wrap a format your program wrote in {class}`~libtmux.Format`, and tmux expands
it as it would in `tmux.conf`:

```python
>>> pane.split(start_directory=Format("#{pane_current_path}"))
Pane(...)
```

Each argument decides for itself, so one call can mix the two. Here the window
name stays literal while the start directory is expanded:

```python
>>> new_window = session.new_window(
...     window_name="build#2",
...     start_directory=Format("#{pane_current_path}"),
... )
>>> new_window.window_name
'build#2'
```

Type checkers see the difference too. Parameters that accept a format are
typed `str | Format`, so passing a {class}`~libtmux.Format` where tmux would
store the text unchanged, such as
{meth}`Pane.break_pane(window_name=...) <libtmux.Pane.break_pane>`, is a type
error.

```{note}
tmux expands a start directory against the session's active pane, not the pane
being split, so `#{pane_current_path}` is the active pane's directory. To start
in a particular pane's directory, pass its
{attr}`~libtmux.Pane.pane_current_path` instead.
```

## A format can run commands

A {class}`~libtmux.Format` hands its text to tmux's format language, which
does more than substitute values. tmux runs `#(...)` as a shell command and
inserts its output, and the `E:` and `T:` modifiers expand a value a second
time, so `#{E:status-right}` runs any `#(...)` stored in the `status-right`
option. Wrapping text in {class}`~libtmux.Format` accepts all of this, the
same as writing it in `tmux.conf`; libtmux does not inspect or limit what a
format does.

Keep text you did not write in a plain `str`, or add it to a format the ways
the next section shows, so tmux reads it as characters, not as format syntax.

## Add text from users or files

Only wrap text your program wrote. Text from users, files or other programs can
contain `#` too, so add it with `+` or {meth}`~libtmux.Format.join`, which keep
it literal:

```python
>>> user_text = "50% #1"
>>> window.rename_window(Format("#{session_name} - ") + user_text)
Window(...)
>>> window.window_name == f"{session.session_name} - 50% #1"
True
```

Plain text can only be added where tmux reads text. Adding it after a format
that ends with `#` or an unfinished `%` time field, or inside an unfinished
`#{...}`, `#(...)` or `#[...]`, raises, because tmux would read it as format
syntax:

```python
>>> Format("#{?pane_active,") + "yes"
Traceback (most recent call last):
...
ValueError: cannot add plain text to Format('#{?pane_active,'): ...
```

To place text inside an expression, such as one side of a comparison, use
{meth}`Format.escape() <libtmux.Format.escape>`. It writes the text so tmux
reads every character back as itself, including the `,` and `}` that would
otherwise end an argument:

```python
>>> same_name = (
...     Format("#{==:#{window_name},")
...     + Format.escape(window.window_name)
...     + Format("}")
... )
>>> window.active_pane.display_message(same_name, get_text=True)
['1']
```

Do not place text from users inside `#(...)`. tmux finds the end of the
command by counting parentheses before the shell sees any quoting, so a `)` in
the text ends the command early. Run the command from Python and pass its
output instead.

## Arguments tmux always expands

Some arguments are formats by design:
{meth}`~libtmux.Pane.display_message`, the commands of
{meth}`~libtmux.Server.run_shell`, {meth}`~libtmux.Server.if_shell` and
{meth}`~libtmux.Pane.pipe`, and the `filter` of the `search_*` methods. A plain
`str` there reaches tmux as written and is expanded, as it always has been:

```python
>>> pane.display_message("#{pane_id}", get_text=True) == [pane.pane_id]
True
```

A plain `str` from a user is therefore a format here, and tmux runs any
`#(...)` it contains. These arguments accept a {class}`~libtmux.Format` too,
so pass such text through {meth}`Format.escape() <libtmux.Format.escape>` to
show it exactly. Some of them also expand `%` as a time field, which
`Format.escape()` keeps literal as well:

```python
>>> pane.display_message(Format.escape("50%d done"), get_text=True)
['50%d done']
```

Menu item names given to {meth}`~libtmux.Server.display_menu` are formats as
well, so a name such as `#{?pane_marked,Unmark,Mark}` changes with the pane.

## What literal means for titles

A literal title is not expanded as a format. tmux still reads `#[...]` style
sequences when it draws a title on screen, as it does for every name it draws,
so a title of `#[fg=red]X` is shown as a red `X`.

## Version notes

- tmux expands {meth}`~libtmux.Server.run_shell`'s `cwd` from tmux 3.8. On
  earlier tmux a plain path is used as given, and `cwd=Format(...)` raises
  {exc}`~libtmux.exc.LibTmuxException`.
- {meth}`~libtmux.Server.save_buffer` takes a plain path only: libtmux creates
  the file readable by its owner before tmux writes it, which needs the final
  path.
- {meth}`~libtmux.Server.new_session` with `kill_session=True` needs a plain
  session name, because a {class}`~libtmux.Format` name is known only after
  tmux creates the session.
- {meth}`~libtmux.Session.new_window` with `select_existing=True` looks the
  name, index or target up itself instead of through tmux's `new-window -S`,
  which matches names differently per release and an index only from tmux 3.8
  ([#914](https://github.com/tmux-python/libtmux/issues/914)). A name passed
  with an index or window ID must match the window there, after a
  {class}`~libtmux.Format` name is expanded; another name raises. The lookup
  and the creation are separate commands, so two callers can both create the
  window. tmux reads a name containing a backslash back with the backslash
  doubled once it stores the name escaped, after
  {meth}`~libtmux.Window.rename_window` and for any new window from tmux 3.7,
  so such a name is not found and another window is created. A
  {class}`~libtmux.Format` name is expanded with `display-message`, where
  `#{command}` reads `display-message` while tmux names the window
  `new-window`, so that name is not found either. Session, window and pane
  fields expand the same way in both.

## Raw commands

{meth}`Server.cmd() <libtmux.Server.cmd>` and the other `cmd()` methods pass
arguments to tmux unchanged, so a `#` there is expanded as tmux sees fit.
