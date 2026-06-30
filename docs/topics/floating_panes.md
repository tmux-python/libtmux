(floating-panes)=

# Floating panes

You can create floating panes — non-modal panes that hover above the tiled
layout like a popup, but with full escape-sequence support and all the regular
pane operations (capture, send-keys, and so on). You create them with
{meth}`Window.new_pane() <libtmux.Window.new_pane>` or
{meth}`Pane.new_pane() <libtmux.Pane.new_pane>`, the same way you reach for
{meth}`Window.split() <libtmux.Window.split>` to add a tiled pane.

Most workflows never need one — tiled panes cover the everyday cases, and you
can stop reading here unless you want a transient overlay (a quick log tail, a
scratch shell, a status readout) sitting on top of your layout without
rearranging it. Because a floating pane behaves like any other
{class}`~libtmux.Pane`, everything you already do — capturing output, sending
keys, querying state — works on it unchanged.

```{note}
Floating panes require **tmux 3.7+**
({meth}`Window.new_pane() <libtmux.Window.new_pane>` /
{meth}`Pane.new_pane() <libtmux.Pane.new_pane>` raise
{exc}`~libtmux.exc.LibTmuxException` on older tmux).
```

## Creating a floating pane

When you call {meth}`Window.new_pane() <libtmux.Window.new_pane>`, you get back
the new {class}`~libtmux.Pane`, exactly as {meth}`Window.split()
<libtmux.Window.split>` hands you a tiled one. You can confirm a pane is
floating by reading its {attr}`pane_floating_flag <libtmux.Pane.pane_floating_flag>`,
which is `"1"` when it floats:

```python
>>> from libtmux.common import has_gte_version

>>> if has_gte_version("3.7"):
...     floating = window.new_pane(width=20, height=5, shell="sleep 30")
...     is_floating = floating.pane_floating_flag
... else:
...     is_floating = "1"
>>> is_floating
'1'
```

## Sizing and positioning

You set the pane's **size** with `width` and `height` (tmux's `-x` / `-y`), and
its **position** with `x` and `y` — cells measured from the top-left of the
window (tmux's `-X` / `-Y`). tmux reports the placement back through the
{attr}`pane_x <libtmux.Pane.pane_x>` /
{attr}`pane_y <libtmux.Pane.pane_y>` fields:

```python
>>> from libtmux.common import has_gte_version

>>> if has_gte_version("3.7"):
...     placed = window.new_pane(width=20, height=5, x=2, y=1, shell="sleep 30")
...     position = (placed.pane_x, placed.pane_y)
... else:
...     position = ("2", "1")
>>> position
('2', '1')
```

## Styling

For the rarer cases where appearance matters, you can style a floating pane with
the same overlay options tmux's `new-pane` accepts: `style` (the pane body),
`active_border_style`, and `inactive_border_style`. Each takes a tmux style
string, for example `style="bg=black"` or `active_border_style="fg=green"`. The
defaults read fine on most terminals, so reach for these only when you want a
float to stand out.

## Keeping a pane open

By default a floating pane closes the moment its command exits — fine for a
fire-and-forget command, but you lose whatever it printed. When you want the
output to linger, pass `keep=True` to hold the pane open until you press a key
(tmux's `-k`), or `message="..."` to hold it open showing a custom
`remain-on-exit-format` line (tmux's `-m`). The cost is explicit and small:
both flip the pane's `remain-on-exit` option to `key`, which buys you a pane
that stays on screen and waits for you after the command finishes instead of
vanishing:

```python
>>> from libtmux.common import has_gte_version

>>> if has_gte_version("3.7"):
...     held = window.new_pane(width=20, height=5, shell="sleep 30", keep=True)
...     remain = held.cmd("show-options", "-p", "-v", "remain-on-exit").stdout
... else:
...     remain = ["key"]
>>> remain
['key']
```

## Identifying floating panes

When you need to tell floating panes from tiled ones in code, reach for the
tmux 3.7 {attr}`pane_floating_flag <libtmux.Pane.pane_floating_flag>` field.
Every {class}`~libtmux.Pane` carries it, so you can branch on it anywhere you
hold a pane — including filtering a window's {attr}`~libtmux.Window.panes` down
to just the floats:

```python
>>> from libtmux.common import has_gte_version

>>> if has_gte_version("3.7"):
...     _ = window.new_pane(width=20, height=5, shell="sleep 30")
...     floating = [p for p in window.panes if p.pane_floating_flag == "1"]
...     found = len(floating) >= 1
... else:
...     found = True
>>> found
True
```

See {meth}`Pane.new_pane() <libtmux.Pane.new_pane>` for the full parameter
reference and {ref}`format-tokens` for the floating-pane geometry fields
({attr}`pane_x <libtmux.Pane.pane_x>`, {attr}`pane_y <libtmux.Pane.pane_y>`,
{attr}`pane_z <libtmux.Pane.pane_z>`,
{attr}`pane_floating_flag <libtmux.Pane.pane_floating_flag>`).
