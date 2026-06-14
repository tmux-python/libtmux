(experimental)=

# Experimental

:::{danger}
**No stability guarantee.** Everything under `libtmux._experimental` is **not**
covered by the project's versioning policy. It can change or be removed between
any releases without notice.

These APIs are published so the design can be exercised and reviewed before any
stability commitment. If you depend on something here and want it stabilized,
please [file an issue](https://github.com/tmux-python/libtmux/issues).
:::

## Chainable commands

The `libtmux._experimental.chain` package lets you author an ordered
sequence of typed tmux commands that compiles to **one** native
`tmux ... \; ...` invocation and dispatches once -- instead of issuing one
subprocess per command. It grows in layers:

- **IR** -- the immutable argv intermediate representation: a
  {class}`~libtmux._experimental.chain.ir.CommandCall` is one typed
  command; a {class}`~libtmux._experimental.chain.ir.CommandChain`
  is an ordered group that renders to a single argv with standalone `;`
  separators and dispatches once.

::::{grid} 1 2 2 2
:gutter: 2 2 3 3

:::{grid-item-card} Command IR
:link: api/libtmux._experimental.chain.ir
:link-type: doc
Immutable argv primitives: `CommandCall`, `CommandChain`, `CommandSpec`.
:::

::::

## At a glance

Compose typed calls and dispatch them as one tmux invocation:

```python
>>> from libtmux._experimental.chain.ir import CommandCall
>>> sequence = (
...     CommandCall("set-option", ("-g", "@cc_docs_a", "1"))
...     >> CommandCall("set-option", ("-g", "@cc_docs_b", "2"))
... )
>>> sequence.argv()
('set-option', '-g', '@cc_docs_a', '1', ';', 'set-option', '-g', '@cc_docs_b', '2')
>>> sequence.run(session.server).returncode
0
>>> session.server.cmd("show-option", "-gv", "@cc_docs_b").stdout
['2']
```

```{toctree}
:hidden:
:maxdepth: 1

api/libtmux._experimental.chain.ir
```
