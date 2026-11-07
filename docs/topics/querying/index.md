(querying)=

# Querying tmux

libtmux offers five query styles because callers need different trade-offs:
convenient object traversal, expressive Python filtering, server-side tmux
formats, raw fresh rows, or immutable snapshot plans.

## Choose a query style

| Style | Best fit | Freshness | Failure signal |
| --- | --- | --- | --- |
| [Hierarchy traversal](hierarchy.md) | move between related libtmux objects | child accessors query tmux on access | stale point objects fail when refreshed |
| [QueryList filtering](query-list.md) | filter an object collection in Python | collection is a fetched snapshot | `get()` distinguishes absent from ambiguous |
| [tmux format queries](tmux-formats.md) | discard rows inside tmux before Python object creation | one server-side query | malformed filters can silently match nothing |
| [Neo raw-row queries](neo.md) | consume fresh format dictionaries without ORM objects | one explicit list command | missing point targets and transport errors differ |
| [Snapshot queries](snapshot.md) | compose pure pane reads and bulk commands | caller controls the snapshot | empty queries return empty values or plans |

Start with [hierarchy traversal](hierarchy.md). Use
[QueryList](query-list.md) when a collection needs narrowing. Move filtering
into [tmux formats](tmux-formats.md) only when row volume or tmux-native
expressions justify it. The [Neo](neo.md) and [snapshot](snapshot.md) layers are
lower-level and experimental, respectively.

```{toctree}
:hidden:

hierarchy
query-list
tmux-formats
neo
snapshot
```
