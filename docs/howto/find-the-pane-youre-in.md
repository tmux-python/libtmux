(howto-find-the-pane-youre-in)=

# Find the pane you're in

{meth}`Pane.from_env() <libtmux.Pane.from_env>` returns the
{class}`~libtmux.Pane` your process is running inside. It is the anchor of the
whole `from_env` family: the pane id is the one fact tmux keeps answering for
live, so the session and window calls resolve through it.

```python
from libtmux.pane import Pane

pane = Pane.from_env()

print(f"{pane.pane_id} in {pane.window.window_name} of {pane.session.session_name}")
```

Unlike {meth}`Server.from_env() <libtmux.Server.from_env>`, which only reads
your environment, this one asks tmux where `$TMUX_PANE` is *now* — one command,
paid once. Each hop back up from there is another, so bind
{attr}`pane.window <libtmux.Pane.window>` or
{attr}`pane.session <libtmux.Pane.session>` to a name if you use it in a loop.
Outside a pane the call raises {exc}`~libtmux.exc.NotInsideTmux`; see
{ref}`howto-detect-you-are-inside-tmux` for the branch.

## This is not "the active pane"

It is tempting to find yourself with
{attr}`window.active_pane <libtmux.Window.active_pane>`, and it will even work
the first time you try it — at a prompt, in the pane you are looking at, you
*are* the active one. Then it quietly stops being true.

Active means **currently focused**: the one pane per window that would receive
your keystrokes. A script the user launched and then clicked away from is not
focused. Neither is a pane running a background job, a `run-shell` hook, or a
CI step on a detached session, where nobody is focused on anything. `from_env`
answers "which pane am I", `active_pane` answers "which pane has the cursor",
and those coincide only while somebody is watching you.

```python
focused = pane.window.active_pane

if focused is not None and focused.pane_id == pane.pane_id:
    print("this pane has the focus")
else:
    print("this pane is running in the background")
```

`active_pane` is `None` when the window reports no active pane, which is why
the comparison guards for it. The same split runs one level up:
{attr}`session.active_window <libtmux.Session.active_window>` is where the user
is, and {meth}`Window.from_env() <libtmux.Window.from_env>` is where you are.

## Related

- {ref}`self-location` — why `$TMUX_PANE` is the anchor and the rest is
  resolved live.
- {ref}`howto-find-the-window-youre-in` — one level up, and what happens when
  your window is shared.
- {ref}`pane-interaction` — what to do with the pane once you hold it.
