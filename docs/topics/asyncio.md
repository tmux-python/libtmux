(asyncio)=

# Asyncio

libtmux's asyncio layer is a set of functions and an iterator over an
{class}`~libtmux.engines.base.AsyncTmuxEngine`. They keep the guarantees of the
engines under them: a cancelled call leaves no tmux client behind, and a slow
consumer cannot stall a pane.

Streaming and event-woken waits need
{class}`~libtmux.engines.control.aio.AsyncControlModeEngine`, because only a
control-mode client receives pane output. See {ref}`engines` for the engines.

## Stream a pane's output

{class}`~libtmux.aio.stream.PaneStream` is an async iterator. It yields `bytes`,
a chunk of what the pane printed in order, and
{class}`~libtmux.aio.stream.Gap`, which means output was discarded at that
point.

```python
>>> import asyncio
>>> from libtmux.aio import Gap, PaneStream
>>> from libtmux.engines import AsyncControlModeEngine, CommandRequest
>>> async def demo():
...     async with AsyncControlModeEngine.for_server(server) as engine:
...         await engine.run(
...             CommandRequest.from_args("display-message", "-p", "up")
...         )
...         async with PaneStream(engine, pane.pane_id) as out:
...             await engine.run(
...                 CommandRequest.from_args(
...                     "send-keys", "-t", pane.pane_id,
...                     "printf '%s%s' streamed _text", "Enter",
...                 )
...             )
...             seen = b""
...             async for item in out:
...                 if not isinstance(item, Gap):
...                     seen += item
...                 if b"streamed_text" in seen:
...                     return True
>>> asyncio.run(demo())
True
```

There is no callback API and no queue to size. The consumer's pace is the only
thing that decides how much is buffered, and the buffer is bounded.

### What happens to a slow consumer

A pane that prints faster than the consumer reads must not be allowed to fill a
pipe, because a full pipe stalls the pane's own process. The stream's queue has
two marks. At `high` queued bytes the pane is paused at tmux; when the consumer
has drained to `low` it is resumed. tmux throws away what the pane prints while
it is paused, so the stream puts a `Gap` where that output would have been.
Nothing is dropped without a `Gap`.

Dropping the oldest output instead would keep the queue just as small and lose
most of a large flood without saying so, which is why that policy is not
offered. `policy="unbounded"` never pauses and never loses, and holds whatever
the consumer has not read; ask for it by name.

### Resynchronise on a gap

A consumer that needs every byte reads the pane's screen when it sees a `Gap`.
{func}`~libtmux.aio.capture.capture_since` takes the
{class}`~libtmux.capture.CaptureCursor` from before the output and returns every
row written since, or says `lines_missed` when the scrollback no longer holds
them:

```python
>>> import asyncio
>>> from libtmux.aio import capture_since
>>> from libtmux.engines import AsyncSubprocessEngine, CommandRequest
>>> async def demo():
...     engine = AsyncSubprocessEngine.for_server(server)
...     cursor = (await capture_since(engine, pane.pane_id)).cursor
...     await engine.run(
...         CommandRequest.from_args(
...             "send-keys", "-t", pane.pane_id, "echo one; echo two", "Enter"
...         )
...     )
...     while True:
...         rows = await capture_since(engine, pane.pane_id, cursor)
...         if "two" in rows.lines:
...             return rows.lines_missed
...         await asyncio.sleep(0.05)
>>> asyncio.run(demo())
False
```

The cursor is the same value {meth}`Pane.capture_since() <libtmux.Pane.capture_since>`
reads, so a cursor from either side works in the other.

## Wait for text

{func}`~libtmux.aio.capture.wait_for_text` returns when a pattern appears in the
rows written after an anchor. It does not poll. It subscribes to the pane's
output before it reads, reads once so text already there is found at once, and
then sleeps until the pane prints. Each wake-up decides from a rendered
`capture-pane`, never from the output bytes, so cursor movement and wrapping are
seen as tmux drew them. The text the typed command echoes does not count.

```python
>>> import asyncio
>>> from libtmux.aio import capture_since, wait_for_text
>>> from libtmux.engines import AsyncControlModeEngine, CommandRequest
>>> async def demo():
...     async with AsyncControlModeEngine.for_server(server) as engine:
...         await engine.run(
...             CommandRequest.from_args("display-message", "-p", "up")
...         )
...         anchor = (await capture_since(engine, pane.pane_id)).cursor
...         waiter = asyncio.ensure_future(
...             wait_for_text(engine, pane.pane_id, "done 7", since=anchor, timeout=30)
...         )
...         await engine.run(
...             CommandRequest.from_args(
...                 "send-keys", "-t", pane.pane_id, "printf 'done %s\\n' 7", "Enter"
...             )
...         )
...         return (await waiter).match.string
>>> asyncio.run(demo())
'done 7'
```

The text is found within milliseconds of the pane printing it, with no tmux
command per tick; polling every 50 ms costs a read per tick whether or not
anything changed. With an engine that has no output to wake on, such as
{class}`~libtmux.engines.subprocess.AsyncSubprocessEngine`, the wait polls.

A control client receives output for the panes of the session it is attached to.
For a pane elsewhere the wait still finishes, because it also re-reads every
second, but it is not woken early.

## Cancellation

Cancelling a wait closes its subscription and leaves no tmux process behind.
Cancelling a stream's consumer needs nothing special: leaving the `async with`
block, however it is left, stops the stream, and with nobody listening the
engine tells tmux to send no pane output again.
