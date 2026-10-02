(aio-api)=

# Asyncio

Streaming, incremental capture and waits for `async` code, built on an
{class}`~libtmux.engines.base.AsyncTmuxEngine`. Nothing here blocks the event
loop, and cancelling any awaitable leaves no tmux process and no pending reply
behind. See {ref}`asyncio` for the guide.

## Streaming

{class}`~libtmux.aio.stream.PaneStream` yields a pane's output as `bytes` and
{class}`~libtmux.aio.stream.Gap`.

```{eval-rst}
.. automodule:: libtmux.aio.stream
   :members:
```

## Capture and waits

{func}`~libtmux.aio.capture.capture_since` and
{func}`~libtmux.aio.capture.wait_for_text` are the awaitable forms of
{meth}`Pane.capture_since() <libtmux.Pane.capture_since>` and
{meth}`Pane.wait_for_text() <libtmux.Pane.wait_for_text>`. They use the same
{class}`~libtmux.capture.CaptureCursor`, so a cursor from one is valid in the
other.

```{eval-rst}
.. automodule:: libtmux.aio.capture
   :members: capture_since, wait_for_text, FALLBACK_INTERVAL
```
