(capabilities-api)=

# Capabilities

{meth}`Server.capabilities() <libtmux.Server.capabilities>` inspects a live
tmux daemon without starting a server or firing `after-*` hooks, returning a
{class}`~libtmux.capabilities.ServerCapabilities` snapshot of the daemon's
version, generation (`pid` and `start_time`), supported features, and active
release workarounds.

Most callers never need this module directly; libtmux's methods consult the
capability registry automatically when gating post-floor flags and retired
options. Reach for it when your code branches on what the connected daemon can
do or pairs mutations with a {class}`~libtmux.engine.DaemonGuard`.

```{eval-rst}
.. automodule:: libtmux.capabilities
   :members:
```
