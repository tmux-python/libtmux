(howto-find-the-window-youre-in)=

# Find the window you're in

{meth}`Window.from_env() <libtmux.Window.from_env>` returns the
{class}`~libtmux.Window` that contains the pane your process runs in. It takes
no arguments: it resolves through your pane, so the answer is the window you
are *in*, never the window someone happens to be looking at.

```python
from libtmux.window import Window

window = Window.from_env()

print(f"{window.window_name} ({window.window_id}), {len(window.panes)} pane(s)")
```

That distinction is the reason to call this rather than reach for
{attr}`session.active_window <libtmux.Session.active_window>`. A script
launched in a split, left running while the user moves on, is still in its own
window and answers correctly here; `active_window` would answer with wherever
the user went. Outside tmux there is no window to name and the call raises
{exc}`~libtmux.exc.NotInsideTmux` — see
{ref}`howto-detect-you-are-inside-tmux`.

## When your window is in more than one session

A window is not owned by one session. `link-window` and grouped sessions
(`tmux new-session -t existing`) put a single window in several at once, and
then it genuinely belongs to all of them — the panes are the same panes, and a
change in one view is a change in every view.

So "which session am I in?" can have more than one true answer, and
{meth}`Session.from_env() <libtmux.Session.from_env>` gives you one of them:
the session tmux itself would act on for a `-t` target. When you need every
holder instead, ask the window.

```python
for holder in window.linked_sessions:
    print(holder.session_name)
```

{attr}`~libtmux.Window.linked_sessions` costs two list commands however many
holders come back, and in the ordinary case there is exactly one — the same
session {attr}`window.session <libtmux.Window.session>` gives you. Reach for it
when your code must be correct in the shared case: killing "your" session, or
counting on your window disappearing with it, is where the assumption of a
single owner actually bites.

## Related

- {ref}`self-location` — the model behind `from_env`, and what stays live
  versus what tmux froze at spawn time.
- {ref}`howto-find-the-pane-youre-in` — one level down, and why it is not the
  active pane.
- {ref}`winlinks` — filtering windows by the sessions that hold them.
