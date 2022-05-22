(internals)=

# Internals

:::{warning}

These APIs are internal and not covered by versioning policy.

:::

```{toctree}

test
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
