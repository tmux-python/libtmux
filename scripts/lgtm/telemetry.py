"""OpenTelemetry exporters for the engine instrumentation seam.

These are sinks, in the sense
:mod:`libtmux.experimental.engines.instrumentation` means it: they observe
commands through :func:`~libtmux.experimental.engines.instrumentation.instrument`
and the engines themselves are never touched. Nothing here is imported by
libtmux, so the library keeps no OpenTelemetry dependency.

One sink emits both spans and metrics rather than two sinks emitting one each,
because the histogram must record while its span is current. That is what
attaches an exemplar, and the exemplar is what lets a Grafana panel jump from a
latency spike to the trace that caused it.
"""

from __future__ import annotations

import contextlib
import time
import typing as t

import identity
from opentelemetry import baggage, context, metrics, trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from libtmux.experimental.engines.control_mode import command_count

if t.TYPE_CHECKING:
    from libtmux.experimental.engines.base import CommandRequest, CommandResult

SERVICE_NAME = "libtmux-engines"

# Latency buckets in seconds. A control-mode command is tens of microseconds and
# a subprocess command is a few milliseconds, so the buckets have to span four
# orders of magnitude or one transport lands entirely in the first bucket.
DURATION_BUCKETS = (
    0.0001,
    0.00025,
    0.0005,
    0.001,
    0.0025,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
)


class BaggageSpanProcessor(SpanProcessor):
    """Copy selected baggage entries onto every span as it starts.

    Baggage is how a value set once -- the test now running, the phase a
    workload is in -- reaches spans created deep inside the engines, without
    threading a parameter through call signatures that have no business knowing
    about telemetry.

    Only the keys in :data:`identity.BAGGAGE_KEYS` are copied. Baggage
    propagates to other processes, so mirroring all of it onto spans would let
    an unrelated caller's entries silently become attributes here.

    The cost is one context read per span and nothing per tmux command, and
    when no baggage is set the loop body never runs.
    """

    def on_start(self, span: t.Any, parent_context: t.Any = None) -> None:
        """Stamp the active baggage onto a starting span."""
        entries = baggage.get_all(parent_context)
        if not entries:
            return
        for key in identity.BAGGAGE_KEYS:
            value = entries.get(key)
            if value is not None:
                span.set_attribute(key, str(value))

    def on_end(self, span: t.Any) -> None:
        """Nothing to do; export is another processor's job."""

    def shutdown(self) -> None:
        """Nothing to release."""

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Nothing buffered."""
        del timeout_millis
        return True


@contextlib.contextmanager
def scope(**entries: str) -> t.Iterator[None]:
    """Attach *entries* to every span started inside the block.

    Examples
    --------
    >>> with scope(**{"libtmux.phase": "warmup"}):
    ...     pass
    """
    token = None
    current = context.get_current()
    for key, value in entries.items():
        current = baggage.set_baggage(key, value, context=current)
    token = context.attach(current)
    try:
        yield
    finally:
        context.detach(token)


class OTelSink:
    """Emit one span and one set of metric points per tmux command.

    Attributes
    ----------
    tracer : opentelemetry.trace.Tracer
        Tracer used for per-command spans.
    lane : str
        Transport label attached to every metric point.
    """

    __slots__ = (
        "_commands",
        "_duration",
        "_failures",
        "_identity",
        "_inlined",
        "_lane",
        "_requests",
        "_tracer",
    )

    def __init__(
        self,
        tracer: t.Any,
        meter: t.Any,
        lane: str,
        identity_labels: t.Mapping[str, str] | None = None,
    ) -> None:
        self._tracer = tracer
        self._lane = lane
        # Resolved once per process, merged into every point. Building the dict
        # per command would allocate on the hot path for a value that cannot
        # change.
        self._identity = dict(identity_labels or {})
        self._requests = meter.create_counter(
            "tmux.requests", description="Requests dispatched to an engine."
        )
        self._commands = meter.create_counter(
            "tmux.commands", description="tmux commands those requests carried."
        )
        self._inlined = meter.create_counter(
            "tmux.inlined",
            description="Commands that rode inside another request's argv.",
        )
        self._failures = meter.create_counter(
            "tmux.failures", description="Commands tmux rejected."
        )
        self._duration = meter.create_histogram(
            "tmux.command.duration",
            unit="s",
            description="Wall time spent inside the engine per request.",
            explicit_bucket_boundaries_advisory=DURATION_BUCKETS,
        )

    def _attrs(self, command: str) -> dict[str, str]:
        return {"tmux.lane": self._lane, "tmux.command": command, **self._identity}

    def before_command(self, request: CommandRequest) -> tuple[t.Any, float, str]:
        """Open a span and count the request, returning per-command state."""
        argv = tuple(str(arg) for arg in request.args)
        command = argv[0] if argv else "unknown"
        commands = command_count(tuple(request.args))
        attrs = self._attrs(command)

        span = self._tracer.start_span(f"tmux {command}")
        span.set_attribute("tmux.command", command)
        span.set_attribute("tmux.lane", self._lane)
        span.set_attribute("tmux.statement", " ".join(argv)[:512])
        span.set_attribute("tmux.commands", commands)
        span.set_attribute("tmux.inlined", commands - 1)

        self._requests.add(1, attrs)
        self._commands.add(commands, attrs)
        self._inlined.add(commands - 1, attrs)
        return span, time.perf_counter(), command

    def after_command(
        self, request: CommandRequest, result: CommandResult, state: t.Any
    ) -> None:
        """Close the span and record its duration with an exemplar."""
        del request
        span, started, command = state
        attrs = self._attrs(command)
        span.set_attribute("tmux.returncode", result.returncode)
        if result.returncode != 0:
            self._failures.add(1, attrs)
        # Recording while the span is current is what attaches the exemplar.
        with trace.use_span(span, end_on_exit=False):
            self._duration.record(time.perf_counter() - started, attrs)
        span.end()

    def handle_error(
        self, request: CommandRequest, error: BaseException, state: t.Any
    ) -> None:
        """Record the failure, then let the exception continue."""
        del request
        span, started, command = state
        attrs = self._attrs(command)
        self._failures.add(1, attrs)
        span.record_exception(error)
        with trace.use_span(span, end_on_exit=False):
            self._duration.record(time.perf_counter() - started, attrs)
        span.end()


class Telemetry(t.NamedTuple):
    """Providers and handles for one instrumented process.

    Attributes
    ----------
    tracer_provider : opentelemetry.sdk.trace.TracerProvider
        Provider owning span export; needs an explicit shutdown.
    meter_provider : opentelemetry.sdk.metrics.MeterProvider
        Provider owning metric export; needs an explicit shutdown.
    logger_provider : opentelemetry.sdk._logs.LoggerProvider
        Provider owning log export; needs an explicit shutdown.
    tracer : opentelemetry.trace.Tracer
        Tracer for per-command spans.
    meter : opentelemetry.metrics.Meter
        Meter the sinks build instruments from.
    handler : logging.Handler
        Handler that ships records to Loki with trace context attached.
    resource_attributes : dict
        Full identity for this run; on every span and log by construction.
    metric_labels : dict
        The bounded subset metrics may carry, already renamed for Prometheus.
    profile_tags : dict
        Static identity for Pyroscope.
    """

    tracer_provider: t.Any
    meter_provider: t.Any
    logger_provider: t.Any
    tracer: t.Any
    meter: t.Any
    handler: t.Any
    resource_attributes: dict[str, str]
    metric_labels: dict[str, str]
    profile_tags: dict[str, str]

    def shutdown(self) -> None:
        """Flush and stop every provider, in export order."""
        self.tracer_provider.force_flush()
        self.meter_provider.force_flush()
        self.logger_provider.force_flush()
        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()
        self.logger_provider.shutdown()


def build(
    endpoint: str,
    *,
    run_id: str,
    spike: str | None = None,
    export_interval_ms: int = 2000,
) -> Telemetry:
    """Wire OTLP exporters for traces, metrics, and logs.

    Parameters
    ----------
    endpoint : str
        OTLP HTTP base URL, for example ``http://127.0.0.1:4318``.
    run_id : str
        Identifies one smoke run, so a dashboard can isolate it.
    spike : str or None
        Names an experiment several runs belong to, for grouped comparison.
    export_interval_ms : int
        How often metrics are pushed. Short, because a smoke run is short.

    Returns
    -------
    Telemetry
        Providers and handles; call :meth:`Telemetry.shutdown` when done.
    """
    attributes = identity.resolve(run_id=run_id, spike=spike, service_name=SERVICE_NAME)
    resource = Resource.create(dict(attributes))

    tracer_provider = TracerProvider(resource=resource)
    # Baggage first: it must stamp a span before the batch processor sees it.
    tracer_provider.add_span_processor(BaggageSpanProcessor())
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    trace.set_tracer_provider(tracer_provider)

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"),
                export_interval_millis=export_interval_ms,
            )
        ],
    )
    metrics.set_meter_provider(meter_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{endpoint}/v1/logs"))
    )

    return Telemetry(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        logger_provider=logger_provider,
        tracer=trace.get_tracer("libtmux.engines"),
        meter=metrics.get_meter("libtmux.engines"),
        handler=LoggingHandler(logger_provider=logger_provider),
        resource_attributes=attributes,
        metric_labels=identity.metric_attributes(attributes),
        profile_tags=identity.profile_tags(attributes),
    )
