(internals)=

# Internals

:::{danger}
**No stability guarantee.** Internal APIs are **not** covered by version
policies. They can break or be removed between any minor versions without
notice.

If you need an internal API stabilized please [file an issue](https://github.com/tmux-python/libtmux/issues).
:::

::::{grid} 1 2 2 2
:gutter: 2 2 3 3

:::{grid-item-card} Dataclass helpers
:link: api/libtmux._internal.dataclasses
:link-type: doc
Typed dataclass utilities used across internal modules.
:::

:::{grid-item-card} Query List
:link: api/libtmux._internal.query_list
:link-type: doc
List filtering and attribute-based querying.
:::

:::{grid-item-card} Constants
:link: api/libtmux._internal.constants
:link-type: doc
Internal format strings and tmux constants.
:::

:::{grid-item-card} Sparse Array
:link: api/libtmux._internal.sparse_array
:link-type: doc
Sparse array data structure for tmux format parsing.
:::

::::

```{toctree}
:hidden:
:maxdepth: 1

api/libtmux._internal.dataclasses
api/libtmux._internal.query_list
api/libtmux._internal.constants
api/libtmux._internal.sparse_array
waiter
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
