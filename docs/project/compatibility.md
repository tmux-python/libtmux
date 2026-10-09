# Compatibility

## Python

- **Minimum**: Python 3.10
- **Tested**: Python 3.10, 3.11, 3.12, 3.13
- **Maximum**: Python < 4.0

## tmux

- **Minimum**: tmux 3.2a
- **Tested**: latest stable tmux release
- libtmux uses tmux's format system and control mode -- older tmux versions
  may lack required format variables

## Platforms

| Platform | Status |
|----------|--------|
| Linux | Fully supported |
| macOS | Fully supported |
| WSL / WSL2 | Supported (tmux runs inside WSL) |
| Windows (native) | Not supported (tmux does not run natively on Windows) |

## Known Limitations

- tmux must be running and accessible via the default socket or a specified socket
- Some operations require the tmux server to have at least one session
- Format string availability depends on tmux version
