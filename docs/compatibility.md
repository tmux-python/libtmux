(compatibility)=

# Compatibility

## Python

- **Minimum**: Python 3.11
- **CI targets**: see the [CI matrix](https://github.com/tmux-python/libtmux/blob/master/.github/workflows/tests.yml)
- **Maximum**: Python < 4.0

## tmux

- **Minimum**: tmux 3.3a
- **CI targets**: the releases and development branch in the matrix above
- libtmux uses tmux's format system and control mode -- older tmux versions
  may lack required format variables

### Capabilities by tmux release

Core {class}`~libtmux.Server`, {class}`~libtmux.Session`,
{class}`~libtmux.Window`, and {class}`~libtmux.Pane` calls work from tmux 3.3a
up. Flags and commands added in newer tmux releases check the running tmux
version first: optional flags warn and send the command without the flag, while
features that have no fallback raise {exc}`~libtmux.exc.LibTmuxException` before
tmux runs.

The matrix below is generated from the same capability table that drives those
runtime gates and `capabilities.json`.

```{tmux-capabilities}
```

## Platforms

| Platform | Status |
|----------|--------|
| Linux | Fully supported |
| macOS | Fully supported |
| WSL / WSL2 | Supported (tmux runs inside WSL) |
| Windows (native) | Not supported (tmux does not run natively on Windows) |

## Known Limitations

- Commands targeting existing objects need a running, accessible tmux server.
  {meth}`~libtmux.Server.new_session` starts a server when needed.
- Some operations require the tmux server to have at least one session
- Format string availability depends on tmux version
