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

## API Reference

See {class}`~libtmux._internal.query_list.QueryList` for the complete API.
