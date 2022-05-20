(api)=

# API Reference

:::{warning}

All APIs are considered experimental and subject to break pre-1.0. They can and will break between
versions.

:::

```{module} libtmux

```

## Server Object

```{eval-rst}
.. autoapiclass:: Server
    :members:
    :inherited-members:
    :private-members:
    :show-inheritance:
    :member-order: bysource
```

## Session Object

```{eval-rst}
.. autoapiclass:: Session
    :members:
    :inherited-members:
    :private-members:
    :show-inheritance:
    :member-order: bysource
```

## Window Object

```{eval-rst}
.. autoapiclass:: Window
    :members:
    :inherited-members:
    :private-members:
    :show-inheritance:
    :member-order: bysource
```

## Pane Object

```{eval-rst}
.. autoapiclass:: Pane
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
.. autoapiclass:: libtmux.common.TmuxRelationalObject
    :members:
```

```{eval-rst}
.. autoapiclass:: libtmux.common.TmuxMappingObject
    :members:
```

```{eval-rst}
.. autoapiclass:: libtmux.common.EnvironmentMixin
    :members:
```

```{eval-rst}
.. autoapiclass:: libtmux.common.tmux_cmd
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
.. automethod:: libtmux.test.retry_until
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
.. autoapiclass:: libtmux.test.EnvironmentVarGuard
```

## Environmental variables

(LIBTMUX_TMUX_FORMAT_SEPARATOR)=

### tmux format separator

```{versionadded} 0.11.0b0

```

`LIBTMUX_TMUX_FORMAT_SEPARATOR` can be used to override the default string used
to split `tmux(1)`'s formatting information.

If you find any compatibility problems with the default, or better yet find a string copacetic
many environments and tmux releases, note it at <https://github.com/tmux-python/libtmux/discussions/355>.
