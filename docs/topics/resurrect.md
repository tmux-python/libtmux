# Workspace Archives

libtmux includes pure Python helpers for capturing and restoring tmux
workspaces without installing tmux plugins. The API is modeled on
tmux-resurrect and tmux-continuum, but it uses libtmux calls and JSON archives
so it can run in tests, background jobs, and MCP servers.

## Capture and Restore

Capture the current server into a typed archive:

```python
from pathlib import Path

from libtmux import Server
from libtmux.resurrect import capture_archive, write_archive

server = Server()
archive = capture_archive(server)
write_archive(archive, Path("workspace.json"))
```

Restore an archive into a fresh or reusable server:

```python
from pathlib import Path

from libtmux import Server
from libtmux.resurrect import restore_archive

server = Server()
restore_archive(Path("workspace.json"), server, on_exists="reuse")
```

Archives preserve sessions, windows, panes, working directories, layouts,
active panes, active and alternate windows, grouped sessions, pane titles,
zoom flags, `automatic-rename`, and attached-client session focus when tmux can
replay it.

## Process Commands

By default, process restore uses a conservative tmux-resurrect-style allow-list
for interactive commands such as `vim`, `less`, `tail`, and `top`. Shell panes
are recreated at their saved working directory without replaying a command.

Use a policy when you want to add commands or restore everything:

```python
from pathlib import Path

from libtmux import Server
from libtmux.resurrect import ProcessRestorePolicy, restore_archive

server = Server()
policy = ProcessRestorePolicy.from_options("'python->uv run python *' 'git log'")
restore_archive(Path("workspace.json"), server, process_policy=policy)
```

Full command capture is explicit because command lines can contain sensitive
arguments. Pass a provider when you want to save process arguments:

```python
from libtmux import Server
from libtmux.resurrect import capture_archive, default_process_command_provider

server = Server()
archive = capture_archive(server, process_provider=default_process_command_provider())
```

The default provider chain reads Linux procfs first and falls back to `ps`, so
it works headlessly on common POSIX systems. On unsupported systems it simply
leaves `full_command` empty.

## tmux-resurrect Files

Existing tmux-resurrect save files can be imported without running TPM or the
plugin scripts:

```python
from pathlib import Path

from libtmux.resurrect import archive_from_resurrect_file, write_archive

archive = archive_from_resurrect_file(Path("last").read_text(encoding="utf-8"))
write_archive(archive, Path("workspace.json"))
```

You can also export a libtmux archive back to tmux-resurrect tab rows:

```python
from pathlib import Path

from libtmux.resurrect import archive_to_resurrect_file, read_archive

archive = read_archive(Path("workspace.json"))
Path("last").write_text(archive_to_resurrect_file(archive), encoding="utf-8")
```

## Autosave and Rotation

Autosave helpers provide tmux-continuum-style interval checks and socket-aware
paths. Snapshot storage adds timestamped archives, retention rotation, and a
`last.json` pointer:

```python
from pathlib import Path

from libtmux import Server
from libtmux.resurrect import autosave_once, default_autosave_paths

server = Server(socket_name="main")
paths = default_autosave_paths(server, Path("archives"))
autosave_once(server, archive_path=paths.archive_path, state_path=paths.state_path)
```

```python
from pathlib import Path

from libtmux.resurrect import capture_archive, write_archive_snapshot

archive = capture_archive(server)
write_archive_snapshot(archive, Path("archives"), keep=10, portable_last=True)
```

Use `portable_last=True` when a filesystem or operating system does not allow
symlink creation. Without it, libtmux writes a relative symlink when possible
and falls back to a copy when symlink creation fails.

## Startup Restore

Startup restore is split into a decision helper and a one-shot restore helper.
This makes downstream service wrappers explicit about when restore is allowed:

```python
from pathlib import Path

from libtmux import Server
from libtmux.resurrect import startup_restore_once

server = Server(socket_name="main")
result = startup_restore_once(
    server,
    Path("archives/last.json"),
    enabled=True,
    halt_file=Path("archives/restore-halt"),
    another_server_running=False,
)
```

The helper skips restore when disabled, when a halt file exists, when sessions
already exist, when another server owns the restore window, or when the startup
grace period has elapsed. `result.reason` contains a stable reason string for
service logs.

For a systemd user service, run a small Python wrapper that calls
`startup_restore_once()` after starting tmux:

```ini
[Unit]
Description=Restore tmux workspace

[Service]
Type=oneshot
ExecStart=python -m your_restore_module

[Install]
WantedBy=default.target
```

For launchd, use the same wrapper from a `ProgramArguments` entry:

```xml
<key>ProgramArguments</key>
<array>
  <string>python</string>
  <string>-m</string>
  <string>your_restore_module</string>
</array>
```

The wrapper should compute `another_server_running` using the service manager
or deployment environment that owns tmux startup.
