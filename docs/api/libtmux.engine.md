(engine-api)=

# Engine

An *engine* runs a tmux command and returns its raw bytes. Every dispatch in
libtmux — {meth}`Server.cmd() <libtmux.Server.cmd>`, the listing queries behind
{attr}`~libtmux.Server.sessions`, and
{meth}`Server.raise_if_dead() <libtmux.Server.raise_if_dead>` — runs through
one. By default that engine is {class}`~libtmux.engine.SubprocessEngine`, which
spawns the `tmux` executable per call.

Pass `engine=` to {class}`~libtmux.Server` to swap the transport for a
recorded double, a persistent {class}`~libtmux.engine.ControlModeEngine`
client, or an {class}`~libtmux.engine.ExecEngine` wrapper such as `docker exec`
or `ssh`.

See {ref}`engines` for the guide and runnable patterns.

```{eval-rst}
.. automodule:: libtmux.engine
   :members:
```
