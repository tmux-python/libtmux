(querylist-filtering)=

# QueryList Filtering

libtmux uses `QueryList` to enable Django-style filtering on tmux objects.
Every collection (`server.sessions`, `session.windows`, `window.panes`) returns
a `QueryList`, letting you filter sessions, windows, and panes with a fluent,
chainable API.

## Basic Filtering

The `filter()` method accepts keyword arguments with optional lookup suffixes:

```python
>>> server.sessions  # doctest: +ELLIPSIS
[Session($... ...)]
```

### Exact Match

The default lookup is `exact`:

```python
>>> # These are equivalent
>>> server.sessions.filter(session_name=session.session_name)  # doctest: +ELLIPSIS
[Session($... ...)]
>>> server.sessions.filter(session_name__exact=session.session_name)  # doctest: +ELLIPSIS
[Session($... ...)]
```

### Contains and Startswith

Use suffixes for partial matching:

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

## Available Lookups

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

## Getting a Single Item

Use `get()` to retrieve exactly one matching item:

```python
>>> window = session.windows.get(window_id=session.active_window.window_id)
>>> window  # doctest: +ELLIPSIS
Window(@... ..., Session($... ...))
```

If no match or multiple matches are found, `get()` raises an exception:

- `ObjectDoesNotExist` - no matching object found
- `MultipleObjectsReturned` - more than one object matches

You can provide a default value to avoid the exception:

```python
>>> session.windows.get(window_name="nonexistent", default=None) is None
True
```

## Chaining Filters

Filters can be chained for complex queries:

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

## Case-Insensitive Filtering

Use `i` prefix variants for case-insensitive matching:

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

## Regex Filtering

For complex patterns, use regex lookups:

```python
>>> # Create windows with version-like names
>>> w1 = session.new_window(window_name="app-v1.0")
>>> w2 = session.new_window(window_name="app-v2.0")
>>> w3 = session.new_window(window_name="app-beta")

>>> # Match version pattern
>>> versioned = session.windows.filter(window_name__regex=r'v\d+\.\d+$')
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

## Filtering by List Membership

Use `in` and `nin` (not in) for list-based filtering:

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

## Filtering Across the Hierarchy

Filter at any level of the tmux hierarchy:

```python
>>> # All panes across all windows in the server
>>> server.panes  # doctest: +ELLIPSIS
[Pane(%... Window(@... ..., Session($... ...)))]

>>> # Filter panes by their window's name
>>> pane = session.active_pane
>>> pane  # doctest: +ELLIPSIS
Pane(%... Window(@... ..., Session($... ...)))
```

## Real-World Examples

### Find all editor windows

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

```python
>>> # Create windows following a naming convention
>>> w1 = session.new_window(window_name="project:frontend")
>>> w2 = session.new_window(window_name="project:backend")
>>> w3 = session.new_window(window_name="logs")

>>> # Find all project windows
>>> project_windows = session.windows.filter(window_name__startswith='project:')
>>> len(project_windows) >= 2
True

>>> # Get specific project window
>>> backend = session.windows.get(window_name='project:backend')
>>> backend.window_name
'project:backend'

>>> # Clean up
>>> w1.kill()
>>> w2.kill()
>>> w3.kill()
```

(native-filtering)=

## Native Filtering with `search_*()`

`QueryList.filter()` runs in Python *after* tmux has returned every
row. For large servers, or when you only need a handful of matches,
push the predicate down to tmux instead. Every level of the hierarchy
ships a `search_*()` method that compiles a format predicate and runs
it inside the tmux server:

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
{meth}`~libtmux._internal.query_list.QueryList.filter`. Pushing a
client-side predicate to tmux is rarely a hot path — a server's client
count is bounded by attached terminals, not by session/window/pane
fan-out.

### Python-side vs. native

| | `.filter()` | `.search_*()` |
|-|-------------|---------------|
| Where | Python (after fetch) | tmux server (before fetch) |
| Predicate vocabulary | libtmux's lookup operators (`__contains`, `__regex`, etc.) | tmux's [FORMATS](https://man.openbsd.org/tmux.1#FORMATS) grammar |
| Round trips | one (full list, then filter in memory) | one (tmux returns only matches) |
| Best for | rich Python predicates, set membership, post-fetch composition | exact/glob matches over many rows |
| Stability | every libtmux version supports it | requires tmux ≥ 3.2 (≥ 3.4 for `list-clients -f`) |

Both are valid; pick on data volume and predicate shape.

### Predicate syntax

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

A malformed predicate is the single biggest footgun. tmux expands an
unclosed `#{...}` or an unknown format token to an empty string,
which the filter engine evaluates as "false" — every row is filtered
out and **no stderr is emitted**. A bad filter is indistinguishable
from a filter that genuinely matched nothing.

If `search_*()` returns empty unexpectedly:

1. Replace the predicate with `#{m:*,#{session_name}}` (or the
   equivalent for windows/panes). If that returns rows, the issue is
   predicate syntax, not data.
2. Expand the predicate standalone via
   {meth}`~libtmux.Server.display_message` to see what tmux actually
   produced:

   ```python
   >>> result = server.display_message(
   ...     '#{m:alpha-*,alpha-1}', get_text=True
   ... )
   >>> result[0]
   '1'
   ```

   A non-`1`, non-empty result tells you the predicate is parsing as
   text, not as a boolean.

3. Cross-check the token name against the FORMATS section of
   `tmux(1)` and against the version gate (see {ref}`format-tokens`).

### When to prefer which

Use `search_*()` when:

- you have hundreds or thousands of windows/panes and only want a few,
- your predicate is a glob (`m:`) or equality check (`==:`),
- you're already in tmux-format thinking (writing `#{...}` for a
  status-line template, for example).

Use `.filter()` when:

- your predicate needs Python types you can't express in tmux format
  (set membership, complex regex, computed values from outside tmux),
- you're chaining multiple filters and prefer composing in Python,
- you want predictable, version-independent semantics.

## API Reference

See {class}`~libtmux._internal.query_list.QueryList` for the complete
QueryList API, and each `search_*()` method for the native filter
contract.
