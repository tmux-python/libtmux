(querylist-filtering)=

# QueryList filtering

Every collection libtmux hands you — `server.sessions`, `session.windows`,
`window.panes` — is a `QueryList`, a list that knows how to filter itself. You
narrow one by calling {meth}`~libtmux._internal.query_list.QueryList.filter`
with keyword arguments, optionally suffixed with a lookup like `__contains`,
`__startswith`, or `__regex`, and you get back another `QueryList` you can
iterate or chain further. It's Django-style filtering applied to sessions,
windows, and panes.

Most readers never look beyond `.filter()`. It's the common path, it works out
of the box on every collection, and the lookup suffixes and chaining cover
almost every query you'll write. The tmux-native `.search_*()` methods at the
end of this page are an optional escape hatch for large servers — you can skip
them until you measure a reason to care.

## Basic filtering

Every collection is already a `QueryList`, so you can inspect one before you
narrow it. Here's the full set of sessions on your server:

```python
>>> server.sessions  # doctest: +ELLIPSIS
[Session($... ...)]
```

### Exact match

When you pass a bare keyword like `session_name=...`, the default lookup is
`exact` — so these two calls mean the same thing:

```python
>>> # These are equivalent
>>> server.sessions.filter(session_name=session.session_name)  # doctest: +ELLIPSIS
[Session($... ...)]
>>> server.sessions.filter(session_name__exact=session.session_name)  # doctest: +ELLIPSIS
[Session($... ...)]
```

### Contains and startswith

Add a suffix to the keyword to match part of a value instead of the whole
thing:

```python
>>> # Create windows for this example
>>> w1 = session.new_window(window_name="api-server")
>>> w2 = session.new_window(window_name="api-worker")
>>> w3 = session.new_window(window_name="web-frontend")

>>> # Windows containing 'api'
>>> api_windows = session.windows.filter(window_name__contains='api')
>>> len(api_windows) >= 2
True

>>> # Windows starting with 'web'
>>> web_windows = session.windows.filter(window_name__startswith='web')
>>> len(web_windows) >= 1
True

>>> # Clean up
>>> w1.kill()
>>> w2.kill()
>>> w3.kill()
```

## Available lookups

Each suffix you append after the `__` selects one of these lookups. The
`i`-prefixed variants ignore case:

| Lookup | Description |
|--------|-------------|
| `exact` | Exact match (default) |
| `iexact` | Case-insensitive exact match |
| `contains` | Substring match |
| `icontains` | Case-insensitive substring |
| `startswith` | Prefix match |
| `istartswith` | Case-insensitive prefix |
| `endswith` | Suffix match |
| `iendswith` | Case-insensitive suffix |
| `in` | Value in list |
| `nin` | Value not in list |
| `regex` | Regular expression match |
| `iregex` | Case-insensitive regex |

## Getting a single item

When you expect exactly one match and want the object itself rather than a
list, reach for {meth}`~libtmux._internal.query_list.QueryList.get`:

```python
>>> window = session.windows.get(window_id=session.active_window.window_id)
>>> window  # doctest: +ELLIPSIS
Window(@... ..., Session($... ...))
```

`get()` insists on exactly one result. If the query matches the wrong number of
objects, it raises:

- {exc}`~libtmux._internal.query_list.ObjectDoesNotExist` - no matching object found
- {exc}`~libtmux._internal.query_list.MultipleObjectsReturned` - more than one object matches

Pass a `default` to get a fallback value back instead of an exception:

```python
>>> session.windows.get(window_name="nonexistent", default=None) is None
True
```

## Chaining filters

You can stack conditions two ways, and both narrow with AND. Pass several
keywords to a single `.filter()` call, or chain `.filter()` calls one after
another:

```python
>>> # Create windows for this example
>>> w1 = session.new_window(window_name="feature-login")
>>> w2 = session.new_window(window_name="feature-signup")
>>> w3 = session.new_window(window_name="bugfix-typo")

>>> # Multiple conditions in one filter (AND)
>>> session.windows.filter(
...     window_name__startswith='feature',
...     window_name__endswith='signup'
... )  # doctest: +ELLIPSIS
[Window(@... ...:feature-signup, Session($... ...))]

>>> # Chained filters (also AND)
>>> session.windows.filter(
...     window_name__contains='feature'
... ).filter(
...     window_name__contains='login'
... )  # doctest: +ELLIPSIS
[Window(@... ...:feature-login, Session($... ...))]

>>> # Clean up
>>> w1.kill()
>>> w2.kill()
>>> w3.kill()
```

## Case-insensitive filtering

Reach for the `i`-prefixed variants when the casing of a name shouldn't matter:

```python
>>> # Create windows with mixed case
>>> w1 = session.new_window(window_name="MyApp-Server")
>>> w2 = session.new_window(window_name="myapp-worker")

>>> # Case-insensitive contains
>>> myapp_windows = session.windows.filter(window_name__icontains='MYAPP')
>>> len(myapp_windows) >= 2
True

>>> # Case-insensitive startswith
>>> session.windows.filter(window_name__istartswith='myapp')  # doctest: +ELLIPSIS
[Window(@... ...:MyApp-Server, Session($... ...)), Window(@... ...:myapp-worker, Session($... ...))]

>>> # Clean up
>>> w1.kill()
>>> w2.kill()
```

## Regex filtering

When a prefix or substring isn't expressive enough, the regex lookups match
against a full pattern:

```python
>>> # Create windows with version-like names
>>> w1 = session.new_window(window_name="app-v1-0")
>>> w2 = session.new_window(window_name="app-v2-0")
>>> w3 = session.new_window(window_name="app-beta")

>>> # Match version pattern
>>> versioned = session.windows.filter(window_name__regex=r'v\d+-\d+$')
>>> len(versioned) >= 2
True

>>> # Case-insensitive regex
>>> session.windows.filter(window_name__iregex=r'BETA')  # doctest: +ELLIPSIS
[Window(@... ...:app-beta, Session($... ...))]

>>> # Clean up
>>> w1.kill()
>>> w2.kill()
>>> w3.kill()
```

## Filtering by list membership

When you already have a set of names in hand, `in` keeps the matches and `nin`
(not in) drops them:

```python
>>> # Create test windows
>>> w1 = session.new_window(window_name="dev")
>>> w2 = session.new_window(window_name="staging")
>>> w3 = session.new_window(window_name="prod")

>>> # Filter windows in a list of names
>>> target_envs = ["dev", "prod"]
>>> session.windows.filter(window_name__in=target_envs)  # doctest: +ELLIPSIS
[Window(@... ...:dev, Session($... ...)), Window(@... ...:prod, Session($... ...))]

>>> # Filter windows NOT in a list
>>> non_prod = session.windows.filter(window_name__nin=["prod"])
>>> any(w.window_name == "prod" for w in non_prod)
False

>>> # Clean up
>>> w1.kill()
>>> w2.kill()
>>> w3.kill()
```

## Filtering across the hierarchy

You aren't limited to one window's panes. Every level of the hierarchy returns
a `QueryList`, and the server-wide collections — `server.panes`,
`server.windows`, `server.sessions` — flatten everything beneath them into a
single list. That lets you query the whole server at once, which is handy when
you want a pane by some attribute and don't care which session or window it
lives in:

```python
>>> # All panes across all windows in the server
>>> server.panes  # doctest: +ELLIPSIS
[Pane(%... Window(@... ..., Session($... ...)))]

>>> # Filter panes by their window's name
>>> pane = session.active_pane
>>> pane  # doctest: +ELLIPSIS
Pane(%... Window(@... ..., Session($... ...)))
```

## Real-world examples

A couple of patterns you'll reach for in practice.

### Find all editor windows

Match several editor names at once with a single regex lookup:

```python
>>> # Create sample windows
>>> w1 = session.new_window(window_name="vim-main")
>>> w2 = session.new_window(window_name="nvim-config")
>>> w3 = session.new_window(window_name="shell")

>>> # Find vim/nvim windows
>>> editors = session.windows.filter(window_name__iregex=r'n?vim')
>>> len(editors) >= 2
True

>>> # Clean up
>>> w1.kill()
>>> w2.kill()
>>> w3.kill()
```

### Find windows by naming convention

If you name windows by convention, a prefix match pulls the whole group, and
`.get()` plucks one out by name:

```python
>>> # Create windows following a naming convention
>>> w1 = session.new_window(window_name="project-frontend")
>>> w2 = session.new_window(window_name="project-backend")
>>> w3 = session.new_window(window_name="logs")

>>> # Find all project windows
>>> project_windows = session.windows.filter(window_name__startswith='project-')
>>> len(project_windows) >= 2
True

>>> # Get specific project window
>>> backend = session.windows.get(window_name='project-backend')
>>> backend.window_name
'project-backend'

>>> # Clean up
>>> w1.kill()
>>> w2.kill()
>>> w3.kill()
```

(native-filtering)=

## tmux-native filtering with `search_*()`

Everything above runs in Python, *after* tmux has already returned every row.
That's fine for the handful of sessions and windows most servers carry. But on
a large server — hundreds or thousands of panes, where you want only a few —
you pay to build objects you immediately discard.

The `search_*()` methods push the filtering down to tmux itself: tmux applies a
format expression and hands back only the matching rows, so libtmux builds
objects for the matches alone. Every level of the hierarchy ships one:

| Caller | Method | Underlying tmux |
|--------|--------|-----------------|
| {class}`~libtmux.Server` | {meth}`~libtmux.Server.search_sessions` | `tmux list-sessions -f <filter>` |
| {class}`~libtmux.Server` | {meth}`~libtmux.Server.search_windows` | `tmux list-windows -a -f <filter>` |
| {class}`~libtmux.Server` | {meth}`~libtmux.Server.search_panes` | `tmux list-panes -a -f <filter>` |
| {class}`~libtmux.Session` | {meth}`~libtmux.Session.search_windows` | `tmux list-windows -t $sess -f <filter>` |
| {class}`~libtmux.Session` | {meth}`~libtmux.Session.search_panes` | `tmux list-panes -s -t $sess -f <filter>` |
| {class}`~libtmux.Window` | {meth}`~libtmux.Window.search_panes` | `tmux list-panes -t @win -f <filter>` |

The {meth}`~libtmux.Server.list_buffers` method also accepts a `filter=`
kwarg with the same semantics.

There is no `search_clients()` method; filter clients via the
{attr}`~libtmux.Server.clients` accessor and Python-side
{meth}`~libtmux._internal.query_list.QueryList.filter`. Filtering
clients in Python is usually enough because a server's client
count is bounded by attached terminals, not by session/window/pane
fan-out.

### Python-side vs. tmux-native

| | `.filter()` | `.search_*()` |
|-|-------------|---------------|
| Where | Python (after fetch) | tmux server (before fetch) |
| Filter language | libtmux's lookup operators (`__contains`, `__regex`, etc.) | tmux's [FORMATS](https://man.openbsd.org/tmux.1#FORMATS) grammar |
| Round trips | one (full list, then filter in memory) | one (tmux returns only matches) |
| Best for | rich Python checks, set membership, post-fetch composition | exact/glob matches over many rows |
| Stability | every libtmux version supports it | requires tmux ≥ 3.2 (≥ 3.4 for `list-clients -f`) |

Both are valid; pick based on data volume and the filter language you want.

### Filter syntax

tmux's filter language is the same one used in `-F` templates. Three
shapes cover most use cases:

```python
>>> # Match by glob
>>> s_alpha = server.new_session(session_name='alpha-1')
>>> s_beta = server.new_session(session_name='beta-1')
>>> alphas = server.search_sessions(filter='#{m:alpha-*,#{session_name}}')
>>> [s.session_name for s in alphas]
['alpha-1']

>>> # Match by equality
>>> exact = server.search_sessions(
...     filter='#{==:#{session_name},alpha-1}'
... )
>>> [s.session_name for s in exact]
['alpha-1']

>>> # Clean up
>>> s_alpha.kill()
>>> s_beta.kill()
```

`#{e:...}` evaluates an arithmetic expression; `#{?cond,a,b}` is the
conditional form. See `man tmux` for the full grammar.

### The silent zero-match trap

A malformed filter expression is the single biggest footgun. tmux expands an
unclosed `#{...}` or an unknown format token to an empty string,
which the filter engine evaluates as "false" — every row is filtered
out and **no stderr is emitted**. A bad filter is indistinguishable
from a filter that genuinely matched nothing.

If `search_*()` returns empty unexpectedly:

1. Replace the filter with `#{m:*,#{session_name}}` (or the
   equivalent for windows/panes). If that returns rows, the issue is
   filter syntax, not data.
2. Expand the expression standalone via
   {meth}`~libtmux.Server.display_message` to see what tmux actually
   produced:

   ```python
   >>> result = server.display_message(
   ...     '#{m:alpha-*,alpha-1}', get_text=True
   ... )
   >>> result[0]
   '1'
   ```

   A non-`1`, non-empty result tells you the expression is parsing as
   text, not as a boolean.

3. Cross-check the token name against the FORMATS section of
   `tmux(1)` and against the version gate (see {ref}`format-tokens`).

### When to prefer which

Use `search_*()` when:

- you have hundreds or thousands of windows/panes and only want a few,
- your filter is a glob (`m:`) or equality check (`==:`),
- you're already in tmux-format thinking (writing `#{...}` for a
  status-line template, for example).

Use `.filter()` when:

- your filter needs Python types you can't express in tmux format
  (set membership, complex regex, computed values from outside tmux),
- you're chaining multiple filters and prefer composing in Python,
- you want predictable, version-independent semantics.

## API reference

See {class}`~libtmux._internal.query_list.QueryList` for the complete
QueryList API, and each `search_*()` method for the tmux-native filter
contract.
