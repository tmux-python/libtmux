"""Execute every dashboard panel's own queries and fail on any that is empty.

A dashboard that renders is not a dashboard that works. A panel whose query
returns nothing looks identical to a panel reporting healthy zero, so the only
way to know the wiring holds end to end is to run each panel's query and insist
on a result.

This reads the generated JSON rather than a separate list of expectations, so a
panel added to :mod:`scripts.lgtm.generate_dashboards` is covered the moment it
exists and cannot be forgotten here.

Template variables are expanded the way Grafana would: ``$lane`` becomes the
match-anything selector the "All" option produces, and ``$__rate_interval``
becomes a window wide enough to cover a smoke run.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import subprocess
import sys
import time
import typing as t
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DASHBOARDS = ROOT / "scripts" / "lgtm" / "dashboards"
SERVICE = "libtmux-engines"

# Grafana expands these per-panel; the acceptance run expands them once.
RATE_INTERVAL = "5m"
# Boards default to now-1h, so $__range interpolates to that.
DASHBOARD_RANGE = "1h"
LOOKBACK_SECONDS = 3600


class Endpoints(t.NamedTuple):
    """Where each backend answers.

    Attributes
    ----------
    prometheus : str
        Prometheus base URL.
    loki : str
        Loki base URL.
    tempo : str
        Tempo base URL.
    pyroscope : str
        Pyroscope base URL.
    """

    prometheus: str
    loki: str
    tempo: str
    pyroscope: str


class Result(t.NamedTuple):
    """One panel's verdict.

    Attributes
    ----------
    board : str
        Dashboard uid.
    panel : str
        Panel title.
    kind : str
        Datasource type queried.
    ok : bool
        Whether the query returned usable data.
    detail : str
        Series count, or why it failed.
    """

    board: str
    panel: str
    kind: str
    ok: bool
    detail: str


def expand(expr: str) -> str:
    """Expand the template variables Grafana would substitute."""
    return (
        expr.replace("$__rate_interval", RATE_INTERVAL)
        .replace("$__interval", RATE_INTERVAL)
        .replace("$__range", DASHBOARD_RANGE)
        .replace("$lane", ".*")
    )


def fetch(url: str, params: dict[str, str], *, timeout: float = 30.0) -> dict:
    """GET *url* with *params* and decode the JSON body."""
    query = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{url}?{query}", timeout=timeout) as response:
        return json.loads(response.read().decode())


def _finite_series(rows: list[dict], *, ranged: bool) -> int:
    """Count series carrying at least one real number.

    ``histogram_quantile`` over empty buckets yields NaN rather than an empty
    result, so a series of nothing but NaN carries no data.
    """
    found = 0
    for row in rows:
        samples = row.get("values", []) if ranged else [row.get("value", [])]
        for sample in samples:
            if len(sample) < 2:
                continue
            try:
                if math.isfinite(float(sample[1])):
                    found += 1
                    break
            except (TypeError, ValueError):
                continue
    return found


def check_prometheus(base: str, expr: str, *, ranged: bool) -> tuple[bool, str]:
    """Query Prometheus the way the panel does, and report what came back.

    Honoring the panel's own mode matters. Grafana evaluates a range panel
    across the dashboard window, so a ``rate`` panel still draws a line from
    samples earlier in the window even when nothing arrived in the last few
    minutes. Checking that same panel with an instant query at ``now`` reports
    an emptiness the viewer never sees, and checking an instant panel with a
    range query would hide one they do.
    """
    if ranged:
        now = int(time.time())
        params = {
            "query": expr,
            "start": str(now - LOOKBACK_SECONDS),
            "end": str(now),
            "step": "60",
        }
        url = f"{base}/api/v1/query_range"
    else:
        params = {"query": expr}
        url = f"{base}/api/v1/query"
    try:
        body = fetch(url, params)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        return False, f"{type(error).__name__}: {error}"
    if body.get("status") != "success":
        return False, str(body.get("error", "query failed"))[:120]
    rows = body["data"]["result"]
    if not rows:
        return False, "no series"
    finite = _finite_series(rows, ranged=ranged)
    if not finite:
        return False, f"{len(rows)} series, all NaN"
    return True, f"{finite} series"


def check_loki(base: str, expr: str) -> tuple[bool, str]:
    """Run a range query and report whether any stream carried entries."""
    now = int(time.time())
    try:
        body = fetch(
            f"{base}/loki/api/v1/query_range",
            {
                "query": expr,
                "start": f"{now - LOOKBACK_SECONDS}000000000",
                "end": f"{now}000000000",
                "limit": "50",
            },
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        return False, f"{type(error).__name__}: {error}"
    streams = body.get("data", {}).get("result", [])
    entries = sum(len(s.get("values", [])) for s in streams)
    if not entries:
        return False, "no log entries"
    return True, f"{entries} entries"


def check_tempo(base: str, query: str) -> tuple[bool, str]:
    """Run a TraceQL search and report whether it matched traces."""
    now = int(time.time())
    try:
        body = fetch(
            f"{base}/api/search",
            {
                "q": query,
                "limit": "20",
                "start": str(now - LOOKBACK_SECONDS),
                "end": str(now),
            },
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        return False, f"{type(error).__name__}: {error}"
    found = body.get("traces") or []
    if not found:
        return False, "no traces"
    return True, f"{len(found)} traces"


def check_pyroscope(base: str, profile_type: str, selector: str) -> tuple[bool, str]:
    """Render a flame graph and report whether it carried frames."""
    now = int(time.time())
    try:
        body = fetch(
            f"{base}/pyroscope/render",
            {
                "query": f"{profile_type}{selector}",
                "from": str(now - LOOKBACK_SECONDS),
                "until": str(now),
                "format": "json",
            },
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        return False, f"{type(error).__name__}: {error}"
    names = body.get("flamebearer", {}).get("names", [])
    # A response with only the synthetic "total" root carries no samples.
    if len(names) <= 1:
        return False, "no profile samples"
    return True, f"{len(names)} frames"


def check_panel(panel: dict, board: str, endpoints: Endpoints) -> list[Result]:
    """Verify every target on one panel."""
    results: list[Result] = []
    title = panel.get("title", "<untitled>")
    for tgt in panel.get("targets", []):
        kind = (tgt.get("datasource") or {}).get("type", "prometheus")
        if kind == "prometheus":
            # Grafana runs a target as a range query unless it is marked
            # instant; the check has to make the same choice.
            ranged = bool(tgt.get("range", not tgt.get("instant", False)))
            ok, detail = check_prometheus(
                endpoints.prometheus, expand(tgt["expr"]), ranged=ranged
            )
        elif kind == "loki":
            ok, detail = check_loki(endpoints.loki, expand(tgt["expr"]))
        elif kind == "tempo":
            ok, detail = check_tempo(endpoints.tempo, expand(tgt["query"]))
        elif kind == "grafana-pyroscope-datasource":
            ok, detail = check_pyroscope(
                endpoints.pyroscope, tgt["profileTypeId"], expand(tgt["labelSelector"])
            )
        else:
            ok, detail = False, f"unknown datasource {kind}"
        results.append(Result(board, title, kind, ok, detail))
    return results


def check_dashboards(endpoints: Endpoints) -> list[Result]:
    """Verify every panel of every generated dashboard, once."""
    results: list[Result] = []
    for path in sorted(DASHBOARDS.glob("*.json")):
        board = json.loads(path.read_text(encoding="utf-8"))
        for panel in board["panels"]:
            if panel["type"] == "row":
                continue
            results.extend(check_panel(panel, board["uid"], endpoints))
    return results


def check_until(endpoints: Endpoints, timeout: float, poll: float) -> list[Result]:
    """Re-check until everything has data or *timeout* expires.

    Ingestion is asynchronous and each backend buffers on its own schedule, so
    "no data yet" and "no data ever" look identical at any single instant. A
    cold-started Tempo in particular can take longer to make a just-written
    trace searchable than Prometheus takes to expose a metric.

    Polling removes that race without inflating a fixed sleep for everyone:
    a warm stack returns on the first pass, and a cold one waits only as long
    as it actually needs.
    """
    deadline = time.monotonic() + timeout
    results = check_dashboards(endpoints)
    while any(not result.ok for result in results) and time.monotonic() < deadline:
        pending = sum(1 for result in results if not result.ok)
        print(f"  waiting for {pending} panel(s) to receive data...")
        time.sleep(poll)
        results = check_dashboards(endpoints)
    return results


def main(argv: list[str] | None = None) -> int:
    """Run the acceptance sweep and print a per-panel report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prometheus", default="http://127.0.0.1:9099")
    parser.add_argument("--loki", default="http://127.0.0.1:3100")
    parser.add_argument("--tempo", default="http://127.0.0.1:3200")
    parser.add_argument("--pyroscope", default="http://127.0.0.1:4040")
    parser.add_argument(
        "--start-stack", action="store_true", help="run scripts/lgtm/up.sh first"
    )
    parser.add_argument(
        "--smoke", action="store_true", help="run scripts/otel_smoke.py first"
    )
    parser.add_argument(
        "--settle",
        type=float,
        default=5.0,
        help="seconds to wait before the first query",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="seconds to keep re-checking panels that have no data yet",
    )
    parser.add_argument(
        "--poll",
        type=float,
        default=10.0,
        help="seconds between re-checks",
    )
    args = parser.parse_args(argv)

    if args.start_stack:
        subprocess.run([str(ROOT / "scripts" / "lgtm" / "up.sh")], check=True)
    if args.smoke:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "otel_smoke.py")], check=True
        )
    if args.start_stack or args.smoke:
        time.sleep(args.settle)

    endpoints = Endpoints(args.prometheus, args.loki, args.tempo, args.pyroscope)
    results = check_until(endpoints, args.timeout, args.poll)

    width = max((len(r.panel) for r in results), default=10)
    current = ""
    for result in results:
        if result.board != current:
            current = result.board
            print(f"\n{current}")
        mark = "ok  " if result.ok else "EMPTY"
        print(f"  {mark} {result.panel:<{width}}  {result.kind:<28} {result.detail}")

    failed = [r for r in results if not r.ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} panel queries returned data")
    if failed:
        print("panels with no data:")
        for result in failed:
            print(f"  {result.board}/{result.panel}: {result.detail}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
