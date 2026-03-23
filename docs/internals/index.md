(internals)=

# Internals

:::{danger}
**No stability guarantee.** Internal APIs are **not** covered by version
policies. They can break or be removed between any minor versions without
notice.

If you need an internal API stabilized please [file an issue](https://github.com/tmux-python/libtmux/issues).
:::

```{toctree}
api/libtmux._internal.dataclasses
api/libtmux._internal.query_list
api/libtmux._internal.constants
api/libtmux._internal.sparse_array
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
