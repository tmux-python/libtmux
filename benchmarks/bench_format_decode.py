"""Benchmark: decoding a tmux ``-F`` reply into typed records.

Synthetic input, no tmux process involved -- this isolates decode cost
(splitting on ``FORMAT_SEPARATOR``, zipping into fields, dropping empties)
from the subprocess round trip that bench_listing.py measures instead.

Run with::

    $ just bench

Equivalent to::

    $ uv run pytest benchmarks/ -o python_files='bench_*.py' --benchmark-only

Not part of ``pytest``'s default run -- see bench_dispatch.py.
"""

from __future__ import annotations

import pytest_benchmark.fixture

from libtmux.formats import FORMAT_SEPARATOR
from libtmux.neo import _split_records, get_output_format, parse_output

_RECORD_COUNT = 64


def _synthetic_pane_blob() -> tuple[str, int]:
    """Build a synthetic multi-record ``list-panes -F`` reply."""
    fields, _ = get_output_format("list-panes", "3.6a")
    record = FORMAT_SEPARATOR.join(f"{name}-value" for name in fields) + (
        FORMAT_SEPARATOR
    )
    return "\n".join([record] * _RECORD_COUNT), len(fields)


def test_bench_split_records(
    benchmark: pytest_benchmark.fixture.BenchmarkFixture,
) -> None:
    """_split_records(): regroup 64 records' worth of raw stdout lines."""
    blob, field_count = _synthetic_pane_blob()
    stdout = blob.split("\n")
    benchmark(_split_records, stdout, field_count)


def test_bench_parse_output(
    benchmark: pytest_benchmark.fixture.BenchmarkFixture,
) -> None:
    """parse_output(): decode one already-split record into a dict."""
    blob, _ = _synthetic_pane_blob()
    one_record = blob.split("\n", 1)[0]
    benchmark(parse_output, one_record, "list-panes", "3.6a")
