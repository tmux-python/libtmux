# tmux Command → libtmux Method Mapping

Generated from tmux HEAD and libtmux source. Re-generate with:
```bash
bash .claude-plugin/scripts/extract-tmux-commands.sh ~/study/c/tmux
bash .claude-plugin/scripts/extract-libtmux-methods.sh
```

## Summary

- **Directly wrapped**: 79/90 commands (87%)
- **Covered by alias/flag**: 8 additional commands
- **Truly unwrappable**: 3 commands (block waiting for interactive input)
- **Total effective coverage**: 87/90 (96%)

## Covered by Alias/Flag (8 commands)

These commands are not called directly but their functionality is available:

| tmux Command | Covered By | How |
|---|---|---|
| `last-pane` | `Window.last_pane()`, `Pane.select(last=True)` | `-l` flag on select-pane |
| `list-panes` | `Window.panes` property | Used internally by `neo.py` |
| `list-windows` | `Session.windows` property | Used internally by `neo.py` |
| `move-pane` | `Pane.join()` | Same C source as join-pane |
| `next-layout` | `Window.select_layout(next_layout=True)` | `-n` flag on select-layout |
| `previous-layout` | `Window.select_layout(previous_layout=True)` | `-o` flag on select-layout |
| `set-window-option` | `OptionsMixin.set_option(scope=OptionScope.Window)` | Alias for `set-option -w` |
| `show-window-options` | `OptionsMixin.show_options(scope=OptionScope.Window)` | Alias for `show-options -w` |

## Not Wrappable (3 commands)

These block forever waiting for interactive user input:

| tmux Command | Why |
|---|---|
| `command-prompt` | Opens interactive prompt, blocks until user types |
| `confirm-before` | Blocks waiting for y/n confirmation (even `-y` blocks in control mode) |
| `display-menu` | Opens interactive menu, blocks until selection |
