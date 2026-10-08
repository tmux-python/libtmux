# Lobby examples

{class}`~libtmux.contrib.lobby.TmuxLobby` returns queryable socket results.
These examples run against the {doc}`isolated tmux fixtures
</api/testing/pytest-plugin/index>` in libtmux's test suite.

## Traverse a discovered server

Limit the scan to a known socket, then use
{meth}`~libtmux._internal.query_list.QueryList.filter` and
{meth}`~libtmux._internal.query_list.QueryList.get` to find its objects:

```python
>>> from libtmux.contrib.lobby import TmuxLobby
>>> socket_path = server.cmd("display-message", "-p", "#{socket_path}").stdout[0]
>>> lobby = TmuxLobby(paths=[socket_path], include_defaults=False)
>>> servers = lobby.servers
>>> found = servers.filter(alive=True).get(socket_path=socket_path)
>>> found.socket_name == server.socket_name
True
>>> found.sessions.get(session_id=session.session_id).session_name == session.session_name
True
>>> found.windows.get(window_id=window.window_id).window_name == window.window_name
True
>>> found.panes.get(pane_id=pane.pane_id).pane_id == pane.pane_id
True
>>> found.server.cmd("display-message", "-p", "#{pid}", timeout=1).stdout == [str(found.pid)]
True
```

## Search directories and patterns

Overlapping paths and patterns produce one result per resolved socket path:

```python
>>> import pathlib
>>> from libtmux.contrib.lobby import TmuxLobby
>>> socket_path = pathlib.Path(server.cmd("display-message", "-p", "#{socket_path}").stdout[0])
>>> lobby = TmuxLobby(
...     paths=[socket_path.parent],
...     patterns=[str(socket_path.parent / "libtmux_test*")],
...     include_defaults=False,
...     timeout=0.5,
... )
>>> matches = lobby.servers.filter(socket_name=server.socket_name)
>>> len(matches)
1
```

## Inspect a failed probe

A stale socket remains visible. Its result carries the failure, and its
child accessors return empty lists:

```python
>>> import socket
>>> from libtmux.contrib.lobby import TmuxLobby
>>> directory = request.getfixturevalue("tmp_path")
>>> path = directory / "stale"
>>> with socket.socket(socket.AF_UNIX) as listener:
...     listener.bind(str(path))
>>> servers = TmuxLobby(paths=directory, include_defaults=False).servers
>>> failed = servers.get(alive=False)
>>> failed.socket_name
'stale'
>>> bool(failed.error)
True
>>> failed.sessions == failed.windows == failed.panes == []
True
>>> servers.filter(alive=True)
[]
```
