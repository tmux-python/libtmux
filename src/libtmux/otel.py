"""OpenTelemetry helpers for libtmux (optional)."""

from __future__ import annotations

import os
from contextlib import ExitStack
from typing import Any

from ._internal import trace as libtmux_trace

_initialized = False
_tracer = None
_provider = None

DEFAULT_OTLP_ENDPOINT = "http://localhost:4318"


def _env_flag(name: str) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return False
    value = raw.strip().lower()
    return value in {"1", "true"}


def _otel_enabled() -> bool:
    if _env_flag("VIBE_TMUX_OTEL") or _env_flag("LIBTMUX_OTEL"):
        return True
    return bool(
        os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        or os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    )


def _normalize_endpoint(endpoint: str) -> str:
    if endpoint.endswith("/v1/traces"):
        return endpoint
    if endpoint.endswith("/"):
        return f"{endpoint}v1/traces"
    return f"{endpoint}/v1/traces"


def init_otel() -> None:
    global _initialized, _tracer, _provider
    if _initialized:
        return
    _initialized = True

    if not _otel_enabled():
        return

    try:
        from opentelemetry import propagate, trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_NAMESPACE
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.trace.propagation.tracecontext import (
            TraceContextTextMapPropagator,
        )
        from libtmux.__about__ import __version__
    except Exception:
        return

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    if endpoint is None and (_env_flag("VIBE_TMUX_OTEL") or _env_flag("LIBTMUX_OTEL")):
        endpoint = DEFAULT_OTLP_ENDPOINT
        os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint)
    if _env_flag("VIBE_TMUX_OTEL") or _env_flag("LIBTMUX_OTEL"):
        os.environ.setdefault("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")

    exporter = (
        OTLPSpanExporter(endpoint=_normalize_endpoint(endpoint))
        if endpoint
        else OTLPSpanExporter()
    )

    resource = Resource.create(
        {
            SERVICE_NAME: "libtmux",
            SERVICE_NAMESPACE: "vibe-tmux",
            "service.version": __version__,
        }
    )

    _provider = TracerProvider(resource=resource)
    use_batch = _env_flag("VIBE_TMUX_OTEL_BATCH") or _env_flag("LIBTMUX_OTEL_BATCH")
    use_sync = _env_flag("VIBE_TMUX_OTEL_SYNC") or _env_flag("LIBTMUX_OTEL_SYNC")
    if use_batch or (not use_sync and not _env_flag("VIBE_TMUX_OTEL")):
        _provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        _provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(_provider)
    propagate.set_global_textmap(TraceContextTextMapPropagator())
    _tracer = trace.get_tracer("libtmux")
    if _provider is not None:
        import atexit

        atexit.register(_provider.shutdown)



def _normalize_attr(value: Any):
    if value is None:
        return None
    if isinstance(value, (str, bytes, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        items = []
        for item in value:
            normalized = _normalize_attr(item)
            if normalized is None:
                continue
            items.append(normalized)
        return items
    return str(value)

def start_span(name: str, attributes: dict[str, Any] | None = None, **fields: Any):
    init_otel()
    stack = ExitStack()
    stack.enter_context(libtmux_trace.span(name, **fields))
    if _tracer is None:
        return stack
    otel_attrs = attributes or fields
    filtered = {k: _normalize_attr(v) for k, v in otel_attrs.items() if _normalize_attr(v) is not None}
    stack.enter_context(_tracer.start_as_current_span(name, attributes=filtered))
    return stack
