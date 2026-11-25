# Capture results and cursors

See {doc}`../topics/incremental_capture` for the selection policy and the
limits of counter-aligned history.

```{eval-rst}
.. autoclass:: libtmux.capture.CaptureCursor
   :members: grid
   :exclude-members: _snapshot, _rows, __init__

.. autoclass:: libtmux.capture.CaptureSince
   :members: lines, cursor, status, reason, text
   :exclude-members: __init__
   :member-order: bysource
```
