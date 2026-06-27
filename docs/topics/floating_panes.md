(floating-panes)=

# Floating Panes

```{note}
Floating panes require **tmux 3.7+**
({meth}`Window.new_pane() <libtmux.Window.new_pane>` /
{meth}`Pane.new_pane() <libtmux.Pane.new_pane>` raise
{exc}`~libtmux.exc.LibTmuxException` on older tmux).
```

tmux 3.7 introduced *floating panes* — panes that sit above the tiled layout
like a popup, but unlike a popup are not modal and behave like ordinary panes
(full escape-sequence support, capture, send-keys, and so on). libtmux exposes
them through {meth}`Window.new_pane() <libtmux.Window.new_pane>` and
{meth}`Pane.new_pane() <libtmux.Pane.new_pane>`, which wrap tmux's `new-pane`
command.

## Creating a floating pane

{meth}`Window.new_pane() <libtmux.Window.new_pane>` returns the new
{class}`~libtmux.Pane`, just like {meth}`Window.split() <libtmux.Window.split>`.
The returned pane reports `pane_floating_flag == "1"`:

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

`width` and `height` set the pane's **size** (tmux's `-x` / `-y`); `x` and `y`
set its **position** in cells from the top-left of the window (tmux's `-X` /
`-Y`). The placement is reported back by the `pane_x` / `pane_y` fields:

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

Floating panes accept the same overlay styling as tmux's `new-pane`: `style`
(the pane body), `active_border_style`, and `inactive_border_style`. Each takes
a tmux style string, e.g. `style="bg=black"` or
`active_border_style="fg=green"`.

## Identifying floating panes

Every pane carries the tmux 3.7 `pane_floating_flag` field, so floating panes
can be told apart from tiled panes anywhere a {class}`~libtmux.Pane` is
available — including filtering a window's {attr}`~libtmux.Window.panes`:

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
reference and {ref}`format-tokens` for the floating-pane geometry fields (`pane_x`,
`pane_y`, `pane_z`, `pane_floating_flag`).
