# tmux Command → libtmux Method Mapping

Generated from tmux HEAD and libtmux source. Re-generate with:
```bash
bash .claude-plugin/scripts/extract-tmux-commands.sh ~/study/c/tmux
bash .claude-plugin/scripts/extract-libtmux-methods.sh
```

## Wrapped Commands (28/88)

| tmux Command | Alias | Getopt Flags | Target | libtmux Location | Methods |
|---|---|---|---|---|---|
| `attach-session` | `attach` | `c:dEf:rt:x` | none | `server.py` | `Server.attach_session()` |
| `capture-pane` | `capturep` | `ab:CeE:JMNpPqS:Tt:` | pane | `pane.py` | `Pane.capture_pane()` |
| `display-message` | `display` | `aCc:d:lINpt:F:v` | pane | `pane.py` | `Pane.display_message()` |
| `has-session` | `has` | `t:` | session | `server.py` | `Server.has_session()` |
| `kill-pane` | `killp` | `at:` | pane | `pane.py` | `Pane.kill()` |
| `kill-server` | — | (none) | none | `server.py` | `Server.kill()` |
| `kill-session` | — | `aCt:` | session | `server.py`, `session.py` | `Server.kill_session()`, `Session.kill()` |
| `kill-window` | `killw` | `at:` | window | `session.py` | `Session.kill_window()`, `Window.kill()` |
| `list-sessions` | `ls` | `F:f:O:r` | none | `server.py`, `neo.py` | `Server.sessions`, internal fetch |
| `list-windows` | `lsw` | `aF:f:O:rst:` | window | `neo.py` | Internal fetch for `Session.windows` |
| `list-panes` | `lsp` | `aF:f:O:rst:` | window | `neo.py` | Internal fetch for `Window.panes` |
| `move-window` | `movew` | `abdkrs:t:` | window | `window.py` | `Window.move_window()` |
| `new-session` | `new` | `Ac:dDe:EF:f:n:Ps:t:x:Xy:` | session | `server.py` | `Server.new_session()` |
| `new-window` | `neww` | `abc:de:F:kn:PSt:` | window | `session.py` | `Session.new_window()` |
| `rename-session` | `rename` | `t:` | session | `session.py` | `Session.rename_session()` |
| `rename-window` | `renamew` | `t:` | window | `window.py` | `Window.rename_window()` |
| `resize-pane` | `resizep` | `DLMRTt:Ux:y:Z` | pane | `pane.py` | `Pane.resize()` |
| `resize-window` | `resizew` | `aADLRt:Ux:y:` | window | `window.py` | `Window.resize()` |
| `select-layout` | `selectl` | `Enopt:` | pane | `window.py` | `Window.select_layout()` |
| `select-pane` | `selectp` | `DdegLlMmP:RT:t:UZ` | pane | `window.py`, `pane.py` | `Window.select_pane()`, `Pane.select()`, `Pane.set_title()` |
| `select-window` | `selectw` | `lnpTt:` | window | `session.py`, `window.py` | `Session.select_window()`, `Window.select()` |
| `send-keys` | `send` | `c:FHKlMN:Rt:X` | pane | `pane.py` | `Pane.send_keys()` |
| `set-environment` | `setenv` | `Fhgrt:u` | session | `common.py` | `EnvironmentMixin.set_environment()`, `.unset_environment()`, `.remove_environment()` |
| `set-hook` | — | `agpRt:uw` | pane | `hooks.py` | `HooksMixin.set_hook()`, `.unset_hook()` |
| `set-option` | `set` | `aFgopqst:uUw` | pane | `options.py` | `OptionsMixin.set_option()`, `.unset_option()` |
| `show-environment` | `showenv` | `hgst:` | session | `common.py` | `EnvironmentMixin.show_environment()`, `.getenv()` |
| `show-hooks` | — | `gpt:w` | pane | `hooks.py` | `HooksMixin.show_hooks()`, `.show_hook()` |
| `show-options` | `show` | `AgHpqst:vw` | pane | `options.py` | `OptionsMixin.show_options()`, `.show_option()` |
| `split-window` | `splitw` | `bc:de:fF:hIl:p:Pt:vZ` | pane | `pane.py` | `Pane.split()`, `Window.split()` |
| `switch-client` | `switchc` | `c:EFlnO:pt:rT:Z` | none | `server.py`, `session.py` | `Server.switch_client()`, `Session.switch_client()` |

## Not Wrapped Commands (60/88)

### High Priority (useful for programmatic/scripting use)

| tmux Command | Alias | Getopt | Target | Notes |
|---|---|---|---|---|
| `break-pane` | `breakp` | `abdPF:n:s:t:` | window | Move pane to its own window |
| `join-pane` | `joinp` | `bdfhvp:l:s:t:` | pane | Merge pane into another window |
| `move-pane` | `movep` | `bdfhvp:l:s:t:` | pane | Move pane between windows (like join-pane) |
| `respawn-pane` | `respawnp` | `c:e:kt:` | pane | Re-run command in pane |
| `respawn-window` | `respawnw` | `c:e:kt:` | window | Re-run command in all window panes |
| `run-shell` | `run` | `bd:Ct:Es:c:` | pane | Execute shell command in background |
| `swap-pane` | `swapp` | `dDs:t:UZ` | pane | Swap two panes |
| `swap-window` | `swapw` | `ds:t:` | window | Swap two windows |
| `display-popup` | `popup` | `Bb:Cc:d:e:Eh:kNs:S:t:T:w:x:y:` | pane | Create popup overlay (tmux 3.2+) |
| `pipe-pane` | `pipep` | `IOot:` | pane | Pipe pane output to command |
| `clear-history` | `clearhist` | `Ht:` | pane | Clear pane scrollback buffer |

### Medium Priority (navigation, buffers, info)

| tmux Command | Alias | Getopt | Target | Notes |
|---|---|---|---|---|
| `last-pane` | `lastp` | `det:Z` | window | Select previous pane |
| `last-window` | `last` | `t:` | session | Select previous window |
| `next-window` | `next` | `at:` | session | Select next window |
| `previous-window` | `prev` | `at:` | session | Select previous window |
| `link-window` | `linkw` | `abdks:t:` | window | Link window to another session |
| `unlink-window` | `unlinkw` | `kt:` | window | Unlink window from session |
| `rotate-window` | `rotatew` | `Dt:UZ` | window | Rotate pane positions |
| `list-buffers` | `lsb` | `F:f:O:r` | none | List paste buffers |
| `list-clients` | `lsc` | `F:f:O:rt:` | session | List connected clients |
| `load-buffer` | `loadb` | `b:t:w` | none | Load file into paste buffer |
| `save-buffer` | `saveb` | `ab:` | none | Save paste buffer to file |
| `set-buffer` | `setb` | `ab:t:n:w` | none | Set paste buffer contents |
| `show-buffer` | `showb` | `b:` | none | Show paste buffer contents |
| `delete-buffer` | `deleteb` | `b:` | none | Delete a paste buffer |
| `paste-buffer` | `pasteb` | `db:prSs:t:` | pane | Paste buffer into pane |
| `wait-for` | `wait` | `LSU` | none | Wait for/signal/lock a channel |
| `if-shell` | `if` | `bFt:` | pane | Conditional command execution |
| `detach-client` | `detach` | `aE:s:t:P` | session | Detach client from session |
| `refresh-client` | `refresh` | `A:B:cC:Df:r:F:lLRSt:U` | none | Refresh client display |
| `show-window-options` | `showw` | `gvt:` | window | Show window options (alias for show-options -w) |
| `set-window-option` | `setw` | `aFgoqt:u` | window | Set window option (alias for set-option -w) |

### Low Priority (interactive UI, config, rarely scripted)

| tmux Command | Alias | Getopt | Target | Notes |
|---|---|---|---|---|
| `bind-key` | `bind` | `nrN:T:` | none | Bind key to command |
| `unbind-key` | `unbind` | `anqT:` | none | Unbind a key |
| `choose-buffer` | — | `F:f:K:NO:rt:yZ` | pane | Interactive buffer chooser |
| `choose-client` | — | `F:f:K:NO:rt:yZ` | pane | Interactive client chooser |
| `choose-tree` | — | `F:f:GK:NO:rst:wyZ` | pane | Interactive session/window tree |
| `clock-mode` | — | `t:` | pane | Show clock in pane |
| `command-prompt` | — | `1beFiklI:Np:t:T:` | none | Open command prompt |
| `confirm-before` | `confirm` | `bc:p:t:y` | none | Confirm before running command |
| `copy-mode` | — | `deHMqSs:t:u` | pane | Enter copy mode |
| `customize-mode` | — | `F:f:Nt:yZ` | pane | Enter customize mode |
| `display-menu` | `menu` | `b:c:C:H:s:S:MOt:T:x:y:` | pane | Display popup menu |
| `display-panes` | `displayp` | `bd:Nt:` | none | Show pane numbers |
| `find-window` | `findw` | `CiNrt:TZ` | pane | Search window contents |
| `list-commands` | `lscm` | `F:` | none | List tmux commands |
| `list-keys` | `lsk` | `1aF:NO:P:rT:` | none | List key bindings |
| `lock-client` | `lockc` | `t:` | none | Lock a client |
| `lock-server` | `lock` | (none) | none | Lock the server |
| `lock-session` | `locks` | `t:` | session | Lock a session |
| `next-layout` | `nextl` | `t:` | window | Cycle to next layout |
| `previous-layout` | `prevl` | `t:` | window | Cycle to previous layout |
| `send-prefix` | — | `2t:` | pane | Send prefix key |
| `server-access` | — | `adlrw` | none | Manage server access control |
| `show-messages` | `showmsgs` | `JTt:` | none | Show message log |
| `show-prompt-history` | `showphist` | `T:` | none | Show prompt history |
| `clear-prompt-history` | `clearphist` | `T:` | none | Clear prompt history |
| `source-file` | `source` | `t:Fnqv` | pane | Source a config file |
| `start-server` | `start` | (none) | none | Start server (usually implicit) |
| `suspend-client` | `suspendc` | `t:` | none | Suspend a client |
