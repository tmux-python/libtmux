(howto-create-a-floating-pane)=

# Create a floating pane

A floating pane hovers above the window's layout instead of dividing it: you
place it where you want, at the size you want, and the panes underneath keep
every cell they had. Reach for one when something is transient — a log tail, a
scratch shell, a status readout — and rearranging the workspace to make room for
it would cost more than the thing is worth.

{meth}`Window.new_pane() <libtmux.Window.new_pane>` creates one, the way
{meth}`Window.split() <libtmux.Window.split>` creates a tiled pane, and hands
back an ordinary {class}`~libtmux.Pane`. {ref}`floating-panes` covers the model
and the full set of arguments; this page is the recipe.

The three blocks below run in sequence. Paste the first into a Python session,
then the second, then the third.

## Float a pane over the layout

```python
from libtmux import Server
from libtmux.common import has_gte_version

if not has_gte_version("3.7"):
    raise RuntimeError("floating panes require tmux 3.7 or newer")

server = Server(socket_name="libtmux-howto")
session = server.new_session(session_name="floating", kill_session=True)
window = session.active_window
window.resize(height=40, width=120)

overlay = window.new_pane(width=60, height=12, x=4, y=2)

print("floating:", overlay.pane_floating_flag == "1")
print("size:", overlay.pane_width, "x", overlay.pane_height)
print("origin:", overlay.pane_x, overlay.pane_y)
```

`width` and `height` are the pane's size in cells, and `x` and `y` place its
top-left corner, counted from the top-left of the window. All four are optional;
tmux picks a default size and centres the pane when you leave them out.

The version check is the honest part of this recipe. Floating panes are a tmux
3.7 feature, and on anything older `new_pane()` raises
{exc}`~libtmux.exc.LibTmuxException` — but it raises at the call, by which point
your script has already built a session it now has to clean up. Asking
{func}`~libtmux.common.has_gte_version` first turns that into one clear failure
before anything exists. Skip the check only if you control the tmux you are
running against.

## It is an ordinary pane

```python
import time

overlay.send_keys("echo floating $TMUX_PANE")

answer = f"floating {overlay.pane_id}"


def answered():
    return any(row.strip() == answer for row in overlay.capture_pane())


deadline = time.monotonic() + 10
while time.monotonic() < deadline and not answered():
    time.sleep(0.1)

print(answered())
```

Nothing on this page's second block is float-specific: {meth}`~libtmux.Pane.send_keys`
and {meth}`~libtmux.Pane.capture_pane` behave exactly as they do on a tiled
pane, and so does everything else a {class}`~libtmux.Pane` offers. A float is a
placement, not a different kind of object — see {ref}`howto-send-keys` for the
reading technique this block uses, and why it compares whole lines.

## Find them, and close them

```python
tiled = window.active_pane
extra = tiled.new_pane(width=30, height=6, x=70, y=24, shell="sleep 30")

floating = [pane for pane in window.panes if pane.pane_floating_flag == "1"]
print("floating:", len(floating), "of", len(window.panes), "panes")

for pane in floating:
    pane.kill()

print("left:", [pane.pane_id for pane in window.panes])

session.kill()
```

{meth}`Pane.new_pane() <libtmux.Pane.new_pane>` is the same call addressed at a
pane rather than a window — the float lands in that pane's window either way, so
use whichever object you are already holding.

Floats appear in {attr}`Window.panes <libtmux.Window.panes>` alongside the tiled
ones, which is convenient until a loop over the window's panes reaches an
overlay you did not mean to touch.
{attr}`~libtmux.Pane.pane_floating_flag` is `"1"` on a float and `"0"`
otherwise, and it is the only thing that tells them apart.

{meth}`~libtmux.Pane.kill` closes a float and leaves the layout underneath
untouched, since it never took space from it. The float also closes on its own
when the command it runs exits — pass `keep=True` or a `message` to hold it open
and read what it printed, both covered in {ref}`floating-panes`.

## Related

- {ref}`floating-panes` — sizing, positioning, styling, and keeping a float
  open after its command exits.
- {ref}`howto-create-panes` — tiled panes, which divide the window instead.
- {ref}`howto-send-keys` — driving a pane, float or not.
