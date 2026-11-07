(instrumentation)=

# Instrumentation

Wrap an engine to count or trace every tmux command that passes through it. A
program that does not wrap one pays nothing, because there is nothing to pay:
{class}`~libtmux.experimental.engines.instrumentation.InstrumentedEngine`
implements the same protocol as the engine it wraps, so observation is a
substitution rather than a feature the engine carries.

## Count what a run costs

{class}`~libtmux.experimental.engines.instrumentation.CountingSink` accumulates
the traffic. {func}`~libtmux.experimental.engines.instrumentation.instrument`
wraps an engine with it and returns something usable anywhere the engine was:

```python
>>> from libtmux.experimental.engines import SubprocessEngine, instrument
>>> from libtmux.experimental.engines.instrumentation import CountingSink
>>> from libtmux.experimental.ops import ListSessions, ListWindows, run
>>> counts = CountingSink()
>>> engine = instrument(SubprocessEngine.for_server(server), counts)
>>> run(ListSessions(), engine).status
'complete'
>>> run(ListWindows(), engine).status
'complete'
>>> counts.requests, counts.tmux_commands, counts.inlined
(2, 2, 0)
>>> counts.elapsed_ns > 0
True
```

## What the three counts mean

`requests` is what the caller asked for, `tmux_commands` is what tmux was told
to do, and
{attr}`~libtmux.experimental.engines.instrumentation.CountingSink.inlined` is
the difference: commands that rode inside another request's argv rather than
costing a dispatch of their own.

The three separate because a request may carry a command group. Sending two
tmux commands in one argv is one dispatch and two commands:

```python
>>> from libtmux.experimental.engines import MockEngine, instrument
>>> from libtmux.experimental.engines.base import CommandRequest, CommandSeparator
>>> from libtmux.experimental.engines.instrumentation import CountingSink
>>> counts = CountingSink()
>>> engine = instrument(MockEngine(), counts)
>>> _ = engine.run(
...     CommandRequest.from_args(
...         "set-option", "-g", "@x", "1", CommandSeparator(";"), "show-options", "-g"
...     )
... )
>>> counts.requests, counts.tmux_commands, counts.inlined
(1, 2, 1)
```

Read the pair against the transport to see what a lane actually costs. A
subprocess engine starts one tmux process per request, so `requests` is also its
process count and every inlined command is a process it did not start. A control
mode engine holds one client for its whole life, so the same `requests` figure
costs no process starts at all — the counts stay comparable across lanes while
the resource they imply does not.

## Write a sink

A sink implements three methods:
{meth}`~libtmux.experimental.engines.instrumentation.Sink.before_command`,
{meth}`~libtmux.experimental.engines.instrumentation.Sink.after_command`, and
{meth}`~libtmux.experimental.engines.instrumentation.Sink.handle_error`. Those
are the hook names OpenTelemetry and Sentry already attach to on SQLAlchemy, so
an exporter written for one transposes here without monkeypatching.

Whatever `before_command` returns comes back as `state`, which is how a sink
carries a span or a timestamp for one command without keeping a map keyed by
request:

```python
>>> import time
>>> from libtmux.experimental.engines import MockEngine, instrument
>>> from libtmux.experimental.engines.base import CommandRequest
>>> class SlowCommandSink:
...     """Record commands that took longer than a threshold."""
...
...     def __init__(self, threshold_ns: int) -> None:
...         self.threshold_ns = threshold_ns
...         self.slow: list[str] = []
...
...     def before_command(self, request):
...         return time.perf_counter_ns()
...
...     def after_command(self, request, result, state):
...         if time.perf_counter_ns() - state > self.threshold_ns:
...             self.slow.append(str(request.args[0]))
...
...     def handle_error(self, request, error, state):
...         self.slow.append(f"{request.args[0]} (failed)")
>>> slow = SlowCommandSink(threshold_ns=0)
>>> engine = instrument(MockEngine(), slow)
>>> _ = engine.run(CommandRequest.from_args("list-panes", "-a"))
>>> slow.slow
['list-panes']

Sinks stack, and each sees every command independently, so counting and tracing
compose without either knowing about the other:

>>> from libtmux.experimental.engines.instrumentation import CountingSink
>>> counts, slow = CountingSink(), SlowCommandSink(threshold_ns=0)
>>> engine = instrument(MockEngine(), counts, slow)
>>> _ = engine.run(CommandRequest.from_args("list-windows"))
>>> counts.requests, len(slow.slow)
(1, 1)
```

An error reaches `handle_error` and then keeps propagating. A sink observes
failures; it does not handle them.

## Export to OpenTelemetry

A tracing sink opens a span in `before_command`, returns it as state, and ends
it in `after_command` or `handle_error`. Mirror the database client
conventions, which map cleanly onto tmux: the span name is the tmux command,
`tmux.command` is the subcommand, `tmux.statement` is the joined argv, and
`tmux.commands` plus `tmux.inlined` carry the counts above so a query can find
the requests that batched work.

```python
>>> from libtmux.experimental.engines import MockEngine, instrument
>>> from libtmux.experimental.engines.base import CommandRequest, CommandSeparator
>>> from libtmux.experimental.engines.control_mode import command_count
>>> class SpanSink:
...     """An exporter's shape, driven here by a recording tracer."""
...
...     def __init__(self, tracer) -> None:
...         self.tracer = tracer
...
...     def before_command(self, request):
...         argv = tuple(str(arg) for arg in request.args)
...         span = self.tracer.start_span(f"tmux {argv[0]}")
...         span.set_attribute("tmux.command", argv[0])
...         span.set_attribute("tmux.statement", " ".join(argv)[:512])
...         commands = command_count(tuple(request.args))
...         span.set_attribute("tmux.commands", commands)
...         span.set_attribute("tmux.inlined", commands - 1)
...         return span
...
...     def after_command(self, request, result, state):
...         state.set_attribute("tmux.returncode", result.returncode)
...         state.end()
...
...     def handle_error(self, request, error, state):
...         state.record_exception(error)
...         state.end()

Driving it proves the lifecycle: one span per command, ended exactly once,
carrying the attributes a query will filter on.

>>> class RecordingSpan:
...     def __init__(self, name):
...         self.name, self.attributes, self.ended = name, {}, False
...     def set_attribute(self, key, value):
...         self.attributes[key] = value
...     def end(self):
...         self.ended = True
>>> class RecordingTracer:
...     def __init__(self):
...         self.spans = []
...     def start_span(self, name):
...         span = RecordingSpan(name)
...         self.spans.append(span)
...         return span
>>> tracer = RecordingTracer()
>>> engine = instrument(MockEngine(), SpanSink(tracer))
>>> _ = engine.run(
...     CommandRequest.from_args(
...         "set-option", "-g", "@x", "1", CommandSeparator(";"), "show-options", "-g"
...     )
... )
>>> span = tracer.spans[0]
>>> span.name, span.ended
('tmux set-option', True)
>>> span.attributes["tmux.commands"], span.attributes["tmux.inlined"]
(2, 1)
>>> span.attributes["tmux.returncode"]
0
```

Swap the recording tracer for `opentelemetry.trace.get_tracer(...)` and the same
sink exports over OTLP, where `{ span.tmux.commands > 1 }` finds every request
that batched work. Nothing else changes, because the sink never learns which
engine it is observing.

That exporter already exists, along with a local Grafana stack to receive it and
dashboards built on these counts. `just otel-verify` starts it, drives a tmux
workload through the seam, and checks that every dashboard panel has data. See
`scripts/lgtm/README.md`.

## Async

{func}`~libtmux.experimental.engines.instrumentation.instrument` returns
{class}`~libtmux.experimental.engines.instrumentation.AsyncInstrumentedEngine`
for an async engine, chosen from the engine's own `run`, so a caller does not
pick the wrapper:

```python
>>> import asyncio
>>> from libtmux.experimental.engines import AsyncMockEngine, instrument
>>> from libtmux.experimental.engines.base import CommandRequest
>>> from libtmux.experimental.engines.instrumentation import CountingSink
>>> counts = CountingSink()
>>> engine = instrument(AsyncMockEngine(), counts)
>>> type(engine).__name__
'AsyncInstrumentedEngine'
>>> async def probe():
...     await asyncio.gather(
...         engine.run(CommandRequest.from_args("list-panes")),
...         engine.run(CommandRequest.from_args("list-windows")),
...     )
>>> asyncio.run(probe())
>>> counts.requests
2
```

The wrapper awaits the inner engine, so commands that overlapped before still
overlap. Sink callbacks are synchronous and run on the event loop between the
await points, which makes a blocking sink an event-loop stall: keep them to
arithmetic and span bookkeeping, and hand anything slower to a background
exporter.

## Why observation is not ambient

An observer could have been ambient instead: a scope that engines consult, so
no call site changes at all. That design was built and measured against this
one, and lost twice.

It costs everyone, always. Consulting a scope means a lookup on every engine
call whether or not anyone is observing, which measured about eight percent per
call and never goes away. Wrapping costs only the programs that wrap.

It also reports numbers that are wrong rather than absent. An ambient scope has
to be consulted by each engine, so covering the engines is a list somebody
maintains. Control mode dispatches some commands over its persistent connection
and others through a subprocess fallback, so an engine missing from that list
does not report zero -- it reports the fallback commands and hides the rest. A
wrapper sits at the boundary the caller already holds, and counts what the
caller asked for however the engine chooses to fulfil it.

The same reasoning rules out installing listeners on the engine. Two concurrent
scopes share one engine, so its listeners cannot tell their commands apart, and
each scope is charged for the other's work.

## Python call counts

Function calls are not a sink. `cProfile` and `sys.monitoring` are both
process-global and single-owner, so a per-command profiler would attribute one
command's calls to whichever command happened to overlap it on the event loop.
Count them for a whole run instead, alongside the sink that counts tmux work:

```python
>>> import cProfile
>>> from libtmux.experimental.engines import MockEngine, instrument
>>> from libtmux.experimental.engines.base import CommandRequest
>>> from libtmux.experimental.engines.instrumentation import CountingSink
>>> counts = CountingSink()
>>> engine = instrument(MockEngine(), counts)
>>> profile = cProfile.Profile()
>>> profile.enable()
>>> for _ in range(3):
...     _ = engine.run(CommandRequest.from_args("list-panes", "-a"))
>>> profile.disable()
>>> calls = sum(entry.callcount for entry in profile.getstats())
>>> counts.requests, calls > counts.requests
(3, True)
```

Pairing them is the point: tmux commands say what the server was asked to do,
and call counts say what Python spent getting there. A change that lowers one
while raising the other has moved cost rather than removed it.

## Overhead

The uninstrumented path is unchanged code, which is the argument for composing
rather than installing. An engine that carried its own event registry would
check whether anyone is listening on every call; an engine that carried wrapper
hooks would build a context object per call whether or not one is used. Wrapping
adds one Python call plus each sink's own work, and only for programs that ask
for it.

The claim is held by two tests: one asserts that wrapping adds no attribute to
the engine it wraps, and one measures an instrumented call against the
millisecond scale of a real tmux round trip.

```console
$ uv run pytest tests/experimental/engines/test_instrumentation.py
```

For measurements of the transports themselves rather than of observation,
see {doc}`orchestration-benchmark`.
