(api)=

# API Reference

:::{seealso}

{ref}`quickstart`.

:::

```{module} libtmux

```

## Server Object

```{eval-rst}
.. autoclass:: Server
    :members:
    :inherited-members:
    :private-members:
    :show-inheritance:
    :member-order: bysource
```

## Session Object

```{eval-rst}
.. autoclass:: Session
    :members:
    :inherited-members:
    :private-members:
    :show-inheritance:
    :member-order: bysource
```

## Window Object

```{eval-rst}
.. autoclass:: Window
    :members:
    :inherited-members:
    :private-members:
    :show-inheritance:
    :member-order: bysource
```

## Pane Object

```{eval-rst}
.. autoclass:: Pane
    :members:
    :inherited-members:
    :private-members:
    :show-inheritance:
    :member-order: bysource
```

## Internals

```{eval-rst}
.. autodata:: libtmux.common.TMUX_MIN_VERSION
```

```{eval-rst}
.. autodata:: libtmux.common.TMUX_MAX_VERSION
```

```{eval-rst}
.. autoclass:: libtmux.common.TmuxRelationalObject
    :members:
```

```{eval-rst}
.. autoclass:: libtmux.common.TmuxMappingObject
    :members:
```

```{eval-rst}
.. autoclass:: libtmux.common.EnvironmentMixin
    :members:
```

```{eval-rst}
.. autoclass:: libtmux.common.tmux_cmd
```

```{eval-rst}
.. automethod:: libtmux.common.which
```

```{eval-rst}
.. automethod:: libtmux.common.get_version
```

```{eval-rst}
.. automethod:: libtmux.common.has_version
```

```{eval-rst}
.. automethod:: libtmux.common.has_gt_version
```

```{eval-rst}
.. automethod:: libtmux.common.has_gte_version
```

```{eval-rst}
.. automethod:: libtmux.common.has_lt_version
```

```{eval-rst}
.. automethod:: libtmux.common.has_lte_version
```

```{eval-rst}
.. automethod:: libtmux.common.has_minimum_version
```

```{eval-rst}
.. automethod:: libtmux.common.handle_option_error
```

```{eval-rst}
.. automethod:: libtmux.common.get_libtmux_version
```

## Exceptions

```{eval-rst}
.. autoexception:: libtmux.exc.LibTmuxException
```

```{eval-rst}
.. autoexception:: libtmux.exc.TmuxCommandNotFound
```

```{eval-rst}
.. autoexception:: libtmux.exc.VersionTooLow
```

```{eval-rst}
.. autoexception:: libtmux.exc.TmuxSessionExists
```

```{eval-rst}
.. autoexception:: libtmux.exc.BadSessionName
```

```{eval-rst}
.. autoexception:: libtmux.exc.OptionError
```

```{eval-rst}
.. autoexception:: libtmux.exc.UnknownOption
```

```{eval-rst}
.. autoexception:: libtmux.exc.InvalidOption
```

```{eval-rst}
.. autoexception:: libtmux.exc.AmbiguousOption
```

## Test tools

```{eval-rst}
.. automethod:: libtmux.test.retry
```

```{eval-rst}
.. automethod:: libtmux.test.get_test_session_name
```

```{eval-rst}
.. automethod:: libtmux.test.get_test_window_name
```

```{eval-rst}
.. automethod:: libtmux.test.temp_session
```

```{eval-rst}
.. automethod:: libtmux.test.temp_window
```

```{eval-rst}
.. autoclass:: libtmux.test.EnvironmentVarGuard
```

## Environmental variables

### tmux format separator

```{versionadded} 0.11.0b0

```

`LIBTMUX_TMUX_FORMAT_SEPARATOR` can be used to override the default string used
to split `tmux(1)`'s formatting information.

If you find any compatibility problems with the default, or better yet find a string copacetic
many environments and tmux releases, note it at https://github.com/tmux-python/libtmux/discussions/355.
