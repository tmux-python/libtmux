# Utilities

{func}`libtmux.common.run_command` executes tmux and returns a separate
{class}`libtmux.common.CommandResult`. Constructing a result performs no I/O.
Completed nonzero exits remain result data; transport and timeout failures raise.

```python
>>> from libtmux.common import CommandResult, run_command
>>> result = run_command("-V")
>>> isinstance(result, CommandResult)
True
>>> result.returncode
0
```

The existing {class}`libtmux.common.tmux_cmd` constructor delegates to this
runner. Contextual `server.cmd()` calls retain their existing return type,
attributes and output conventions.

```{eval-rst}
.. automodule:: libtmux.common
   :members:
```
