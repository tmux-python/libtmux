# tmux Command → libtmux Method Mapping

Run the extraction scripts for current data — these numbers shift as
tmux and libtmux evolve:

```console
$ bash .claude-plugin/scripts/extract-tmux-commands.sh ~/study/c/tmux
```

```console
$ bash .claude-plugin/scripts/extract-libtmux-methods.sh
```

## Summary

- **Directly invoked**: 86 of 90 tmux commands
- **Covered indirectly via internal queries / option scoping**: 4
- **Total effective coverage**: 90 / 90 (100%)

## Covered Indirectly (4 commands)

These four tmux commands aren't called by name in `libtmux` source but
their functionality is reachable through other primitives:

| tmux Command | Reached Through |
|---|---|
| `list-panes` | `Window.panes` property (issued internally by `neo.py` queries) |
| `list-windows` | `Session.windows` property (issued internally by `neo.py` queries) |
| `set-window-option` | `OptionsMixin.set_option(scope=OptionScope.Window)` — `set-option -w` |
| `show-window-options` | `OptionsMixin.show_options(scope=OptionScope.Window)` — `show-options -w` |

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
