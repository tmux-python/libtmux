# libtmux Implementation Patterns

Reference for wrapping new tmux commands in libtmux. Study these patterns when implementing.

## Pattern 1: Simple Command (No Return Value)

Example: `Pane.select()` wrapping `select-pane`

```python
def select(self) -> Self:
    """Select pane. Wraps ``$ tmux select-pane``."""
    proc = self.cmd("select-pane")
    if proc.stderr:
        raise exc.LibTmuxException(proc.stderr)
    return self
```

Key elements:
- Calls `self.cmd("command-name")` which auto-adds `-t {pane_id}`
- Checks `proc.stderr` for errors
- Returns `self` for chaining

## Pattern 2: Command with Flag Arguments

Example: `Pane.send_keys()` wrapping `send-keys`

```python
def send_keys(
    self,
    cmd: str,
    enter: bool = True,
    suppress_history: bool = True,
    literal: bool = False,
) -> None:
    tmux_args: tuple[str | int, ...] = ()
    if literal:
        tmux_args += ("-l",)
    tmux_args += (cmd,)
    self.cmd("send-keys", *tmux_args)
    if enter:
        self.cmd("send-keys", "Enter")
```

Key elements:
- Map Python kwargs to tmux flags (`literal` → `-l`)
- Build `tmux_args` tuple conditionally
- Boolean params for toggle flags, typed params for value flags

## Pattern 3: Command Returning a New Object

Example: `Session.new_window()` wrapping `new-window`

```python
def new_window(
    self,
    window_name: str | None = None,
    start_directory: StrPath | None = None,
    attach: bool = True,
    ...
) -> Window:
    window_args: tuple[str, ...] = ()
    if not attach:
        window_args += ("-d",)
    if window_name is not None:
        window_args += ("-n", window_name)
    if start_directory is not None:
        window_args += ("-c", str(start_directory))
    # Use -P -F to capture created object info
    window_args += ("-P", "-F#{window_id}")
    proc = self.cmd("new-window", *window_args)
    if proc.stderr:
        raise exc.LibTmuxException(proc.stderr)
    window_id = proc.stdout[0].strip()
    return fetch_obj("window_id", window_id, self.server)
```

Key elements:
- Uses `-P -F#{format}` to capture the new object's ID
- Parses stdout to get the created ID
- Calls `fetch_obj()` to return a fully populated object
- Raises on stderr

## Pattern 4: Command with Direction/Enum Args

Example: `Pane.resize()` wrapping `resize-pane`

```python
def resize(
    self,
    adjustment_direction: ResizeAdjustmentDirection | None = None,
    adjustment: int = 1,
    height: int | None = None,
    width: int | None = None,
    zoom: bool | None = None,
) -> Self:
    tmux_args: tuple[str | int, ...] = ()
    if adjustment_direction:
        tmux_args += (RESIZE_ADJUSTMENT_DIRECTION_FLAG_MAP[adjustment_direction],)
        tmux_args += (str(adjustment),)
    if height is not None:
        tmux_args += ("-y", str(height))
    if width is not None:
        tmux_args += ("-x", str(width))
    if zoom is True:
        tmux_args += ("-Z",)
    proc = self.cmd("resize-pane", *tmux_args)
    ...
```

Key elements:
- Uses constants from `libtmux.constants` for flag mapping
- Enum-based direction parameters
- Optional numeric arguments with explicit None checks

## Pattern 5: Mixin Command (EnvironmentMixin)

Example: `set_environment()` in `src/libtmux/common.py`

```python
def set_environment(self, name: str, value: str) -> None:
    args = ["set-environment"]
    if hasattr(self, "session_id"):
        args += ["-t", str(self.session_id)]
    else:
        args += ["-g"]
    args += [name, value]
    cmd = tmux_cmd(*args)  # Uses standalone tmux_cmd, not self.cmd()
```

Key elements:
- Uses standalone `tmux_cmd()` function (not `self.cmd()`)
- Determines scope from object type (session → `-t`, server → `-g`)

## Doctest Requirements

All methods MUST have working doctests using fixtures from `doctest_namespace`:

```python
def swap_pane(self, target: str) -> Self:
    """Swap this pane with target. Wraps ``$ tmux swap-pane``.

    Parameters
    ----------
    target : str
        Target pane identifier

    Returns
    -------
    :class:`Pane`

    Examples
    --------
    >>> pane = window.active_pane
    >>> pane2 = window.split()
    >>> pane.swap_pane(pane2.pane_id)  # doctest: +ELLIPSIS
    Pane(...)
    """
```

Available fixtures: `server`, `session`, `window`, `pane`, `Server`, `Session`, `Window`, `Pane`

Rules:
- Use `# doctest: +ELLIPSIS` for variable output
- Session IDs: `$...`, Window IDs: `@...`, Pane IDs: `%...`
- Never use `# doctest: +SKIP`
- Never convert to `.. code-block::`

## Logging Pattern

```python
logger.info(
    "pane created",
    extra={
        "tmux_subcommand": "split-window",
        "tmux_pane": pane_id,
    },
)
```

- Use `logger.debug()` for command details, `logger.info()` for lifecycle events
- Always use `extra` dict with `tmux_` prefixed keys
- Use lazy formatting: `logger.debug("msg %s", val)` not f-strings

## Error Handling

```python
proc = self.cmd("command-name", *args)
if proc.stderr:
    raise exc.LibTmuxException(proc.stderr)
```

- Check `proc.stderr` after command execution
- Raise `libtmux.exc.LibTmuxException`
- Do NOT catch-log-reraise without adding context

## Coding Standards Checklist

- [ ] `from __future__ import annotations` at top
- [ ] `import typing as t` (namespace import)
- [ ] NumPy docstring format
- [ ] Working doctests (not skipped, not code-blocks)
- [ ] Logging with structured `extra` dict
- [ ] Functional tests only (no test classes)
- [ ] Use `server`, `session`, `window`, `pane` fixtures in tests
