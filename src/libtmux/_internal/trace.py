"""Lightweight tracing for libtmux timing audits."""

from __future__ import annotations

import contextlib
import contextvars
import itertools
import json
import os
import pathlib
import threading
import time
import typing as t

TRACE_PATH = os.getenv("LIBTMUX_TRACE_PATH", "/tmp/libtmux-trace.jsonl")


def _env_flag(name: str) -> bool:
    value = os.getenv(name)
    if value is None:
        return False
    return value not in {"", "0", "false", "False", "no", "NO"}


TRACE_ENABLED = _env_flag("LIBTMUX_TRACE")
TRACE_RESET = _env_flag("LIBTMUX_TRACE_RESET")

_TRACE_TEST: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "libtmux_trace_test", default=None
)
_TRACE_STACK: contextvars.ContextVar[tuple[int, ...]] = contextvars.ContextVar(
    "libtmux_trace_stack", default=()
)
_TRACE_COUNTER = itertools.count(1)


def set_test_context(name: str | None) -> None:
    _TRACE_TEST.set(name)


def reset_trace(path: str | None = None) -> None:
    if not TRACE_ENABLED:
        return
    target = path or TRACE_PATH
    with pathlib.Path(target).open("w", encoding="utf-8") as handle:
        handle.write("")


def _write_event(event: dict[str, t.Any]) -> None:
    if not TRACE_ENABLED:
        return
    event["pid"] = os.getpid()
    event["thread"] = threading.get_ident()
    test_name = _TRACE_TEST.get()
    if test_name:
        event["test"] = test_name
    with pathlib.Path(TRACE_PATH).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=False))
        handle.write("\n")


@contextlib.contextmanager
def span(name: str, **fields: t.Any) -> t.Iterator[None]:
    if not TRACE_ENABLED:
        yield
        return
    span_id = next(_TRACE_COUNTER)
    stack = _TRACE_STACK.get()
    parent_id = stack[-1] if stack else None
    _TRACE_STACK.set((*stack, span_id))
    start_ns = time.perf_counter_ns()
    try:
        yield
    finally:
        duration_ns = time.perf_counter_ns() - start_ns
        _TRACE_STACK.set(stack)
        event = {
            "event": name,
            "span_id": span_id,
            "parent_id": parent_id,
            "depth": len(stack),
            "start_ns": start_ns,
            "duration_ns": duration_ns,
        }
        event.update(fields)
        _write_event(event)


def point(name: str, **fields: t.Any) -> None:
    if not TRACE_ENABLED:
        return
    event = {"event": name, "point": True, "ts_ns": time.perf_counter_ns()}
    event.update(fields)
    _write_event(event)


def summarize(path: str | None = None, limit: int = 20) -> str:
    target = path or TRACE_PATH
    if not pathlib.Path(target).exists():
        return "libtmux trace: no data collected"

    totals: dict[str, dict[str, int]] = {}
    slowest: list[tuple[int, str]] = []

    with pathlib.Path(target).open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("point"):
                continue
            name = str(event.get("event", "unknown"))
            duration = int(event.get("duration_ns", 0))
            entry = totals.setdefault(name, {"count": 0, "total_ns": 0, "max_ns": 0})
            entry["count"] += 1
            entry["total_ns"] += duration
            if duration > entry["max_ns"]:
                entry["max_ns"] = duration
            slowest.append((duration, json.dumps(event, sort_keys=False)))

    if not totals:
        return "libtmux trace: no span data collected"

    sorted_totals = sorted(
        totals.items(), key=lambda item: item[1]["total_ns"], reverse=True
    )
    sorted_slowest = sorted(slowest, key=lambda item: item[0], reverse=True)[:limit]

    lines = ["libtmux trace summary (ns):"]
    for name, stats in sorted_totals[:limit]:
        avg = stats["total_ns"] // max(stats["count"], 1)
        lines.append(
            f"- {name}: count={stats['count']} total={stats['total_ns']} avg={avg} "
            f"max={stats['max_ns']}"
        )
    lines.append("libtmux trace slowest spans:")
    for duration, payload in sorted_slowest:
        lines.append(f"- {duration} {payload}")
    return "\n".join(lines)


if TRACE_ENABLED and TRACE_RESET:
    reset_trace()
