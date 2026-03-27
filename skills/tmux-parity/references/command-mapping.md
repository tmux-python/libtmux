# tmux Command → libtmux Method Mapping

Generated from tmux HEAD and libtmux source. Re-generate with:
```bash
bash .claude-plugin/scripts/extract-tmux-commands.sh ~/study/c/tmux
bash .claude-plugin/scripts/extract-libtmux-methods.sh
```

## Summary

- **Directly wrapped**: 82/90 commands (91%)
- **Covered by alias/flag**: 8 additional commands
- **Total effective coverage**: 90/90 (100%)

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

## Test Gaps (1 command)

| tmux Command | Method | Why |
|---|---|---|
| `display-menu` | `Server.display_menu()` | Requires TTY-backed client. Control-mode clients have `tty.sy=0`, causing `menu_prepare()` to return NULL. Method exists but cannot be tested hermetically. |

## Notable Test Innovations

| Command | Testing Approach |
|---|---|
| `confirm-before` | `send-keys -K -c <client>` injects 'y' into status prompt handler (tmux 3.4+) |
| `command-prompt` | `send-keys -K -c <client>` types text + Enter into status prompt (tmux 3.4+) |
| `display-popup` | ControlMode client + marker file side-effect verification |
| `detach-client` | ControlMode client + `list-clients` count assertion |
