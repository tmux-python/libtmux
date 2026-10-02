(capture)=

# Capture

Incremental pane reading for {meth}`~libtmux.Pane.capture_since`.

Where {meth}`~libtmux.Pane.capture_pane` returns a snapshot of a pane,
{meth}`~libtmux.Pane.capture_since` returns a *delta* — the rows written since a
{class}`~libtmux.capture.CaptureCursor` — plus a fresh cursor to resume from.

Cursors are immutable, so a call never advances the cursor it was handed, and
serialize through `str()` / {meth}`~libtmux.capture.CaptureCursor.from_str` for
callers that carry them across a process or wire boundary.

{meth}`~libtmux.Pane.wait_for_text` and {meth}`~libtmux.Pane.wait_for_idle` wait
on the same cursors and return a {class}`~libtmux.capture.TextMatch` or a
{class}`~libtmux.capture.CaptureSince`.

See {ref}`capture-since` for a worked walkthrough.

```{eval-rst}
.. automodule:: libtmux.capture
    :members:
    :private-members:
    :show-inheritance:
    :member-order: bysource
```
