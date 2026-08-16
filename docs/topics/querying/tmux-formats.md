(native-filtering)=

# Query with tmux formats

The `search_*()` methods pass a tmux format expression to a `list-* -f`
command. tmux discards non-matching rows before libtmux creates Python objects.

## When to use it

Use tmux-native filtering when a server has enough windows or panes that
discarding rows before object creation matters, or when the query already fits
tmux's format language. Prefer [QueryList](query-list.md) for Python regexes,
set membership, and composable post-fetch logic.

tmux format filters require tmux 3.2 or newer. The main entry points are:

| Scope | Methods |
| --- | --- |
| Server | {meth}`~libtmux.Server.search_sessions`, {meth}`~libtmux.Server.search_windows`, {meth}`~libtmux.Server.search_panes` |
| Session | {meth}`~libtmux.Session.search_windows`, {meth}`~libtmux.Session.search_panes` |
| Window | {meth}`~libtmux.Window.search_panes` |

## Tutorial

### Happy path

Match a session name with tmux's `m:` glob operator:

```python
>>> _ = server.new_session(session_name="format-alpha")
>>> _ = server.new_session(session_name="format-beta")
>>> matches = server.search_sessions(
...     filter="#{m:format-a*,#{session_name}}"
... )
>>> [item.session_name for item in matches]
['format-alpha']
```

### Sad path

tmux expands an unknown token to an empty string. In a filter position, that is
false, so a malformed query can look exactly like a valid zero-match query:

```python
>>> _ = server.new_session(session_name="format-visible")
>>> server.search_sessions(filter="#{query_token_does_not_exist}")
[]
>>> bool(server.search_sessions(filter="#{m:*,#{session_name}}"))
True
```

When an unexpected query is empty, first run a known-all filter, then expand
the suspect expression with {meth}`~libtmux.Server.display_message`. tmux does
not emit stderr for this class of format mistake.

## API reference

```{eval-rst}
.. automethod:: libtmux.Server.search_sessions
   :no-index:

.. automethod:: libtmux.Server.search_windows
   :no-index:

.. automethod:: libtmux.Server.search_panes
   :no-index:

.. automethod:: libtmux.Session.search_windows
   :no-index:

.. automethod:: libtmux.Session.search_panes
   :no-index:

.. automethod:: libtmux.Window.search_panes
   :no-index:
```

## Related topics

- [QueryList filtering](query-list.md) compares Python-side lookup semantics.
- [Format-token fields](../format-tokens.md) lists typed tokens and version
  gates.
- The tmux `FORMATS` grammar is documented in the
  [tmux manual](https://man.openbsd.org/tmux.1#FORMATS).
