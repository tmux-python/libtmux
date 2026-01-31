"""OpenTelemetry helpers for libtmux.

This module is intentionally lightweight and optional. When OpenTelemetry
dependencies are not installed, the APIs degrade to no-ops so libtmux can
still be used without OTEL configured.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import os
import typing as t
from dataclasses import dataclass

from .__about__ import __version__

logger = logging.getLogger(__name__)

propagate = None
trace = None
OTLPSpanExporter = None
Resource = None
TracerProvider = None
BatchSpanProcessor = None

try:  # pragma: no cover - optional dependency
    from opentelemetry import propagate as otel_propagate, trace as otel_trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter as otel_otlp_exporter,
    )
    from opentelemetry.sdk.resources import (
        Resource as otel_resource,
    )
    from opentelemetry.sdk.trace import (
        TracerProvider as otel_tracer_provider,
    )
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor as otel_batch_span_processor,
    )
except Exception:  # pragma: no cover - optional dependency
    propagate = None
    trace = None
    OTLPSpanExporter = None
    Resource = None
    TracerProvider = None
    BatchSpanProcessor = None
else:
    propagate = otel_propagate
    trace = otel_trace
    OTLPSpanExporter = otel_otlp_exporter
    Resource = otel_resource
    TracerProvider = otel_tracer_provider
    BatchSpanProcessor = otel_batch_span_processor


@dataclass(frozen=True)
class TraceHeaders:
    """Trace headers captured for tmux subprocess propagation."""

    traceparent: str
    tracestate: str | None = None
    baggage: str | None = None


_TRACE_HEADERS_STACK: contextvars.ContextVar[tuple[TraceHeaders, ...]] = (
    contextvars.ContextVar("libtmux_trace_headers", default=())
)
_OTEL_READY = False


def _env_flag(name: str) -> bool | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    value = raw.strip().lower()
    if not value:
        return None
    if value in {"1", "true"}:
        return True
    if value in {"0", "false"}:
        return False
    return None


def otel_enabled() -> bool:
    """Return True when OTEL export is enabled by environment.

    Examples
    --------
    >>> from libtmux.otel import otel_enabled
    >>> _ = otel_enabled()
    """
    if _env_flag("VIBE_TMUX_OTEL") is not None:
        return _env_flag("VIBE_TMUX_OTEL") is True
    return bool(
        os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        or os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    )


def _ensure_provider() -> bool:
    global _OTEL_READY
    if _OTEL_READY:
        return True
    if (
        trace is None
        or propagate is None
        or Resource is None
        or TracerProvider is None
        or BatchSpanProcessor is None
        or OTLPSpanExporter is None
    ):
        return False
    if not otel_enabled():
        return False

    provider = trace.get_tracer_provider()
    if provider.__class__.__name__ != "ProxyTracerProvider":
        _OTEL_READY = True
        return True

    try:
        resource = Resource.create(
            {
                "service.name": "libtmux",
                "service.version": __version__,
            }
        )
        tracer_provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter()
        tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(tracer_provider)
    except Exception:  # pragma: no cover - optional dependency
        logger.debug("libtmux otel init failed", exc_info=True)
        return False
    else:
        _OTEL_READY = True
        return True


def _inject_headers() -> TraceHeaders | None:
    if propagate is None:
        return None
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    traceparent = carrier.get("traceparent")
    if not traceparent:
        return None
    return TraceHeaders(
        traceparent=traceparent,
        tracestate=carrier.get("tracestate"),
        baggage=carrier.get("baggage"),
    )


def current_trace_headers() -> TraceHeaders | None:
    """Return the current trace headers, if any.

    Examples
    --------
    >>> from libtmux.otel import current_trace_headers
    >>> _ = current_trace_headers()
    """
    stack = _TRACE_HEADERS_STACK.get()
    if not stack:
        return None
    return stack[-1]


def _push_headers(headers: TraceHeaders) -> contextvars.Token[tuple[TraceHeaders, ...]]:
    stack = list(_TRACE_HEADERS_STACK.get())
    stack.append(headers)
    return _TRACE_HEADERS_STACK.set(tuple(stack))


@contextlib.contextmanager
def start_span(name: str) -> t.Iterator[t.Any]:
    """Start a span and set trace headers for subprocess propagation.

    Examples
    --------
    >>> from libtmux.otel import start_span, current_trace_headers
    >>> with start_span("libtmux.test"):
    ...     _ = current_trace_headers()
    """
    if trace is None or propagate is None:
        yield None
        return
    if not _ensure_provider():
        yield None
        return
    tracer = trace.get_tracer("libtmux")
    with tracer.start_as_current_span(name) as span:
        token = None
        headers = _inject_headers()
        if headers is not None:
            token = _push_headers(headers)
        try:
            yield span
        finally:
            if token is not None:
                _TRACE_HEADERS_STACK.reset(token)


__all__ = [
    "TraceHeaders",
    "current_trace_headers",
    "start_span",
]
