# Start the tmux server if it is not already running

{class}`~libtmux.experimental.ops.StartServer` asks tmux to ensure its server is
running through
{class}`~libtmux.experimental.engines.subprocess.SubprocessEngine` and returns
{class}`~libtmux.experimental.ops.results.AckResult`.

## Example

This executable example creates a disposable server that is initially stopped.
`tmp_path` provides a private temporary configuration file.

```python
>>> import uuid
>>> from libtmux.server import Server
>>> from libtmux.experimental.engines import SubprocessEngine
>>> from libtmux.experimental.ops import StartServer, run
>>> config = tmp_path / "start-server.conf"
>>> _ = config.write_text("set -g exit-empty off\n", encoding="utf-8")
>>> socket_name = f"libtmux-doc-{uuid.uuid4().hex}"
>>> with Server(socket_name=socket_name, config_file=str(config)) as candidate:
...     before = candidate.is_alive()
...     result = run(
...         StartServer(),
...         SubprocessEngine.for_server(candidate),
...     ).raise_for_status()
...     proof = before, type(result).__name__, candidate.is_alive()
>>> proof
(False, 'AckResult', True)
```

## Operation reference

```{tmuxop:operation} start_server
```

## Failure and effects

The command is idempotent when the target server is already running. The
example disables `exit-empty` so the new empty server remains alive long enough
for a live check; the context manager stops that owned server afterward.

## Related operations

- {tmuxop:op}`source_file`
- {tmuxop:op}`delete_buffer`
