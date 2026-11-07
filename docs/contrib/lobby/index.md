(lobby)=

# Lobby

{class}`~libtmux.contrib.lobby.TmuxLobby` finds local Unix sockets and asks
each one for tmux server metadata. Its `servers` attribute returns a
{class}`~libtmux._internal.query_list.QueryList` of
{class}`~libtmux.contrib.lobby.TmuxLobbyServer` results. Use it when you need
to find servers before traversing their sessions, windows, and panes.

```python
>>> from libtmux.contrib.lobby import TmuxLobby
>>> servers = TmuxLobby.servers
>>> found = servers.get(socket_name=server.socket_name)
>>> found.alive
True
```

The default scan searches the current user's `tmux-UID` directories under
`/tmp` and `$TMUX_TMPDIR`, plus the socket named in `$TMUX`. These locations
follow tmux's [socket options](https://man.openbsd.org/tmux.1#L).
Each access scans again; save the returned list to reuse a scan. Discovery
does not start or kill servers, create sessions, or remove socket files.

Filter the results with the same
{meth}`~libtmux._internal.query_list.QueryList.filter` and
{meth}`~libtmux._internal.query_list.QueryList.get` methods as
{attr}`~libtmux.Server.sessions`. `servers.filter(alive=True)` selects
confirmed tmux servers. Each result exposes `sessions`, `windows`, `panes`,
and a {class}`~libtmux.Server` bound to the discovered socket path.

## Search locations

Construct a lobby with `paths` for literal socket files or directories,
and `patterns` for globs. A directory contributes its immediate children;
`**` in a glob searches recursively. Both accept a single value or an
iterable, expand `~`, and resolve relative paths at scan time. Custom
locations extend the defaults; `include_defaults=False` replaces them.
See {doc}`examples` for runnable searches.

Regular files, missing paths, and unreadable directories are skipped.
Symlinks to sockets resolve to their targets. Results are deduplicated and
sorted by resolved path. Sockets outside the configured locations and
abstract Unix sockets do not appear. `socket_name` is the resolved path's
basename; for a custom location, it need not be a name that tmux can resolve
with `-L`.

## Probe results

Every discovered socket produces a result, including stale sockets and
sockets belonging to other programs. `alive=True` means the probe received
tmux metadata. `alive=False` means that it did not; `error` holds the
diagnostic. A failed probe does not establish whether a socket belongs to
tmux.

Probes run sequentially with a one-second timeout per socket by default.
`timeout` changes that limit; `tmux_bin` selects a client binary when a
server needs a different tmux version. Probe errors, including permission
failures, incompatible clients, and a missing binary, stay on their results.

`alive`, `pid`, and `version` describe the probe, not a continuing health
check. Read `lobby.servers` again to refresh them. The result's `sessions`,
`windows`, and `panes` query current state, returning empty lists after a
failed probe or tmux query. These follow-up queries and direct commands on
`server` use libtmux's usual command behavior; the discovery timeout applies
only to probes. {meth}`~libtmux.Server.cmd` accepts a separate `timeout` for
commands you issue yourself.

```{toctree}
:maxdepth: 1

examples
api
```
