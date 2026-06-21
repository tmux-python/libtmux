(experimental)=

# Experimental: operations & engines

```{warning}
Everything under {mod}`libtmux.experimental` is **not** covered by the
versioning policy and may change or be removed between any two releases.
```

`libtmux.experimental` hosts an inert, typed *operation* substrate and the
*engines* that execute it. An operation describes a tmux command (it renders
argv, carries its result type and metadata, and serializes) without dispatching;
an engine runs operations and returns typed results. The same operation returns
the same typed result whether executed by a subprocess, an in-memory simulator,
a persistent `tmux -C` control connection, or an async transport.

See ``tmux-python/libtmux`` issue 689 for the operationalization plan.

## Operation catalog

The catalog below is generated from the operation registry, so it always matches
the code.

```{tmuxop-catalog}
```

### Read-only operations

```{tmuxop-catalog}
:safety: readonly
```

### Destructive operations

```{tmuxop-catalog}
:safety: destructive
```
