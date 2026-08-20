"""Generate the libtmux Grafana dashboard suite.

Dashboards are generated rather than hand-edited JSON. A Grafana board is a few
hundred lines of deeply nested objects in which a panel's position is manual
arithmetic, so hand-maintaining six of them guarantees drift. Here a board is a
list of panel calls and :class:`Board` does the grid math.

The generated JSON is committed. ``scripts/lgtm/up.sh`` regenerates it on every
start and ``tests/test_lgtm_dashboards.py`` fails if the committed copy differs,
so the two cannot silently diverge.

Every panel must be backed by telemetry ``scripts/otel_smoke.py`` actually
emits. ``scripts/otel_acceptance.py`` executes each panel's own queries and
fails on any that returns nothing, which is what keeps a board honest.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import typing as t

PROM: dict[str, str] = {"type": "prometheus", "uid": "prometheus"}
LOKI: dict[str, str] = {"type": "loki", "uid": "loki"}
TEMPO: dict[str, str] = {"type": "tempo", "uid": "tempo"}
PYROSCOPE: dict[str, str] = {"type": "grafana-pyroscope-datasource", "uid": "pyroscope"}

SERVICE = "libtmux-engines"
# Every panel filters by the lane template variable, so one board serves both
# "all transports together" and "this transport alone".
LANE = 'tmux_lane=~"$lane"'
TAGS = ["libtmux", "generated"]

BUCKET = "tmux_command_duration_seconds_bucket"


def rate_by(label: str, metric: str) -> str:
    """Per-second rate of *metric*, grouped by *label*."""
    return f"sum by ({label}) (rate({metric}{{{LANE}}}[$__rate_interval]))"


def window_total(metric: str, label: str | None = None) -> str:
    """Total increase of *metric* across the dashboard's time range.

    Deliberately windowed rather than a bare counter read. The workload is
    short-lived, so a few minutes after it exits Prometheus marks its series
    stale and an instant query at ``now`` returns nothing at all -- a stat
    panel reading the counter directly goes blank while the timeseries beside
    it still shows the run. ``increase`` over ``$__range`` asks what happened
    in the window the viewer selected, which is both what they meant and
    immune to staleness.
    """
    inner = f"increase({metric}{{{LANE}}}[$__range])"
    return f"sum by ({label}) ({inner})" if label else f"sum({inner})"


def window_quantile(quantile: float, label: str) -> str:
    """Latency *quantile* across the whole window, for summary tables."""
    return (
        f"histogram_quantile({quantile}, sum by (le, {label}) "
        f"(rate({BUCKET}{{{LANE}}}[$__range])))"
    )


def quantile_by(quantile: float, label: str) -> str:
    """Latency *quantile* from the duration histogram, grouped by *label*."""
    return (
        f"histogram_quantile({quantile}, sum by (le, {label}) "
        f"(rate({BUCKET}{{{LANE}}}[$__rate_interval])))"
    )


ERR_THRESHOLDS = [
    {"color": "green", "value": None},
    {"color": "orange", "value": 1},
    {"color": "red", "value": 5},
]


def target(
    expr: str,
    legend: str = "",
    *,
    exemplar: bool = False,
    fmt: str = "time_series",
    instant: bool = False,
    ref: str = "A",
    datasource: dict[str, str] | None = None,
) -> dict[str, t.Any]:
    """Build one query target.

    Parameters
    ----------
    expr : str
        The query, in the datasource's own language.
    legend : str
        Legend format; Grafana expands ``{{label}}``.
    exemplar : bool
        Overlay exemplars, giving the metric-to-trace pivot.
    fmt : str
        ``time_series``, ``heatmap``, or ``table``.
    instant : bool
        Ask for a single point instead of a range.
    ref : str
        Query id, unique within a panel.
    datasource : dict or None
        Defaults to Prometheus.

    Returns
    -------
    dict
        A Grafana target object.
    """
    tgt: dict[str, t.Any] = {
        "datasource": datasource or PROM,
        "editorMode": "code",
        "expr": expr,
        "legendFormat": legend or "__auto",
        "range": not instant,
        "instant": instant,
        "refId": ref,
    }
    if exemplar:
        tgt["exemplar"] = True
    if fmt != "time_series":
        tgt["format"] = fmt
    return tgt


class Board:
    """A dashboard that lays itself out on Grafana's 24-column grid."""

    def __init__(
        self,
        uid: str,
        title: str,
        *,
        description: str = "",
        refresh: str = "30s",
        time_from: str = "now-1h",
    ) -> None:
        self.uid = uid
        self.title = title
        self.description = description
        self.refresh = refresh
        self.time_from = time_from
        self._panels: list[dict[str, t.Any]] = []
        self._templates: list[dict[str, t.Any]] = []
        self._id = 0
        self._x = 0
        self._y = 0
        self._row_h = 0

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _place(self, w: int, h: int) -> dict[str, int]:
        if self._x + w > 24:
            self._x = 0
            self._y += self._row_h
            self._row_h = 0
        pos = {"x": self._x, "y": self._y, "w": w, "h": h}
        self._x += w
        self._row_h = max(self._row_h, h)
        return pos

    def row(self, title: str) -> None:
        """Start a labelled row, flushing the current one."""
        if self._x != 0:
            self._x = 0
            self._y += self._row_h
            self._row_h = 0
        self._panels.append(
            {
                "type": "row",
                "title": title,
                "collapsed": False,
                "id": self._next_id(),
                "gridPos": {"x": 0, "y": self._y, "w": 24, "h": 1},
                "panels": [],
            }
        )
        self._y += 1

    def add(self, panel: dict[str, t.Any], *, w: int = 12, h: int = 8) -> None:
        """Place a panel at the current grid cursor."""
        panel["id"] = self._next_id()
        panel["gridPos"] = self._place(w, h)
        self._panels.append(panel)

    def lane_variable(self) -> None:
        """Add the transport selector every board filters on."""
        self._templates.append(
            {
                "name": "lane",
                "label": "Transport",
                "type": "query",
                "datasource": PROM,
                "query": {
                    "qryType": 1,
                    "query": "label_values(tmux_requests_total, tmux_lane)",
                    "refId": "var-lane",
                },
                "refresh": 2,
                "sort": 1,
                "includeAll": True,
                "allValue": ".*",
                "multi": True,
                "current": {"text": "All", "value": "$__all"},
            }
        )

    def to_dict(self) -> dict[str, t.Any]:
        """Render the dashboard envelope."""
        return {
            "uid": self.uid,
            "title": self.title,
            "description": self.description,
            "tags": TAGS,
            "timezone": "browser",
            "schemaVersion": 39,
            "version": 1,
            "editable": True,
            "graphTooltip": 1,
            "refresh": self.refresh,
            "time": {"from": self.time_from, "to": "now"},
            "templating": {"list": self._templates},
            "links": [
                {
                    "title": "libtmux dashboards",
                    "type": "dashboards",
                    "tags": ["libtmux"],
                    "asDropdown": True,
                    "includeVars": True,
                    "keepTime": True,
                    "icon": "external link",
                }
            ],
            "annotations": {"list": []},
            "panels": self._panels,
        }


# ---------------------------------------------------------------------------
# Panel builders.
# ---------------------------------------------------------------------------
def timeseries(
    title: str,
    targets: list[dict[str, t.Any]],
    *,
    unit: str = "short",
    description: str = "",
    stacking: bool = False,
) -> dict[str, t.Any]:
    """Build a timeseries panel."""
    custom: dict[str, t.Any] = {
        "fillOpacity": 18 if stacking else 10,
        "showPoints": "never",
        "lineWidth": 2,
    }
    if stacking:
        custom["stacking"] = {"mode": "normal", "group": "A"}
    return {
        "type": "timeseries",
        "title": title,
        "description": description,
        "datasource": PROM,
        "targets": targets,
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "palette-classic"},
                "unit": unit,
                "custom": custom,
            },
            "overrides": [],
        },
        "options": {
            "legend": {
                "displayMode": "table",
                "placement": "bottom",
                "calcs": ["lastNotNull", "max"],
            },
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
    }


def stat(
    title: str,
    targets: list[dict[str, t.Any]],
    *,
    unit: str = "short",
    description: str = "",
    thresholds: list[dict[str, t.Any]] | None = None,
) -> dict[str, t.Any]:
    """Build a single-value stat panel."""
    field: dict[str, t.Any] = {"unit": unit}
    if thresholds is not None:
        field["color"] = {"mode": "thresholds"}
        field["thresholds"] = {"mode": "absolute", "steps": thresholds}
    else:
        field["color"] = {"mode": "palette-classic"}
    return {
        "type": "stat",
        "title": title,
        "description": description,
        "datasource": PROM,
        "targets": targets,
        "fieldConfig": {"defaults": field, "overrides": []},
        "options": {
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
            "textMode": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        },
    }


def heatmap(title: str, expr: str, *, description: str = "") -> dict[str, t.Any]:
    """Build a latency heatmap from histogram buckets."""
    return {
        "type": "heatmap",
        "title": title,
        "description": description,
        "datasource": PROM,
        "targets": [target(expr, "{{le}}", fmt="heatmap")],
        "options": {
            "calculate": False,
            "cellGap": 1,
            "color": {"mode": "scheme", "scheme": "Spectral", "steps": 64},
            "yAxis": {"unit": "s"},
            "legend": {"show": True},
            "tooltip": {"show": True, "yHistogram": True},
        },
        "fieldConfig": {"defaults": {"custom": {"hideFrom": {}}}, "overrides": []},
    }


def piechart(
    title: str, targets: list[dict[str, t.Any]], *, description: str = ""
) -> dict[str, t.Any]:
    """Build a pie chart of proportions."""
    return {
        "type": "piechart",
        "title": title,
        "description": description,
        "datasource": PROM,
        "targets": targets,
        "fieldConfig": {
            "defaults": {"color": {"mode": "palette-classic"}, "unit": "short"},
            "overrides": [],
        },
        "options": {
            "displayLabels": ["percent"],
            "legend": {
                "displayMode": "table",
                "placement": "right",
                "values": ["value"],
            },
            "pieType": "donut",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        },
    }


def table(
    title: str, targets: list[dict[str, t.Any]], *, description: str = ""
) -> dict[str, t.Any]:
    """Build a table panel from instant queries."""
    return {
        "type": "table",
        "title": title,
        "description": description,
        "datasource": PROM,
        "targets": targets,
        "transformations": [
            {"id": "merge", "options": {}},
            {
                "id": "organize",
                "options": {
                    "excludeByName": {"Time": True, "job": True, "instance": True}
                },
            },
        ],
        "fieldConfig": {
            "defaults": {"color": {"mode": "thresholds"}, "custom": {"align": "auto"}},
            "overrides": [],
        },
        "options": {"showHeader": True, "footer": {"show": False}},
    }


def logs(title: str, expr: str, *, description: str = "") -> dict[str, t.Any]:
    """Build a Loki logs panel."""
    return {
        "type": "logs",
        "title": title,
        "description": description,
        "datasource": LOKI,
        "targets": [target(expr, datasource=LOKI, ref="A")],
        "options": {
            "showTime": True,
            "sortOrder": "Descending",
            "wrapLogMessage": True,
            "enableLogDetails": True,
        },
    }


def flamegraph(title: str, *, description: str = "") -> dict[str, t.Any]:
    """Build a Pyroscope flame graph of the profiled process."""
    return {
        "type": "flamegraph",
        "title": title,
        "description": description,
        "datasource": PYROSCOPE,
        "targets": [
            {
                "datasource": PYROSCOPE,
                "queryType": "profile",
                "profileTypeId": "process_cpu:cpu:nanoseconds:cpu:nanoseconds",
                "labelSelector": f'{{service_name="{SERVICE}"}}',
                "groupBy": [],
                "refId": "A",
            }
        ],
        "options": {},
    }


def traces(title: str, query: str, *, description: str = "") -> dict[str, t.Any]:
    """Build a Tempo search panel."""
    return {
        "type": "table",
        "title": title,
        "description": description,
        "datasource": TEMPO,
        "targets": [
            {
                "datasource": TEMPO,
                "queryType": "traceql",
                "query": query,
                "limit": 20,
                "tableType": "spans",
                "refId": "A",
            }
        ],
        "options": {"showHeader": True},
    }


# ---------------------------------------------------------------------------
# Boards.
# ---------------------------------------------------------------------------
def build_overview() -> Board:
    """Build the board answering whether tmux work is flowing and healthy."""
    board = Board(
        "libtmux-overview",
        "libtmux / Overview",
        description=(
            "Throughput, latency, and failures across every engine transport. "
            "Metric panels carry exemplars, so a latency spike links to the "
            "trace behind it."
        ),
    )
    board.lane_variable()

    board.row("Totals")
    board.add(
        stat(
            "Requests",
            [target(window_total("tmux_requests_total"), instant=True)],
            description="Requests dispatched to an engine.",
        ),
        w=6,
        h=5,
    )
    board.add(
        stat(
            "tmux commands",
            [target(window_total("tmux_commands_total"), instant=True)],
            description="Commands tmux was told to run; a group counts as its members.",
        ),
        w=6,
        h=5,
    )
    board.add(
        stat(
            "Inlined share",
            [
                target(
                    f"100 * {window_total('tmux_inlined_total')} "
                    f"/ clamp_min({window_total('tmux_commands_total')}, 1)",
                    instant=True,
                )
            ],
            unit="percent",
            description="Commands that rode inside another request's argv.",
        ),
        w=6,
        h=5,
    )
    board.add(
        stat(
            "Failure share",
            [
                target(
                    f"100 * {window_total('tmux_failures_total')} "
                    f"/ clamp_min({window_total('tmux_requests_total')}, 1)",
                    instant=True,
                )
            ],
            unit="percent",
            thresholds=ERR_THRESHOLDS,
            description="Requests tmux rejected.",
        ),
        w=6,
        h=5,
    )

    board.row("Throughput and latency")
    board.add(
        timeseries(
            "Request rate by transport",
            [
                target(
                    rate_by("tmux_lane", "tmux_requests_total"),
                    "{{tmux_lane}}",
                )
            ],
            unit="reqps",
            description="How much each transport is carrying.",
        )
    )
    board.add(
        timeseries(
            "p95 latency by transport",
            [
                target(
                    quantile_by(0.95, "tmux_lane"),
                    "{{tmux_lane}}",
                    exemplar=True,
                )
            ],
            unit="s",
            description=(
                "Per-request time inside the engine. "
                "Click an exemplar to open its trace."
            ),
        )
    )
    board.add(
        heatmap(
            "Latency distribution",
            rate_by("le", BUCKET),
            description="Where requests actually land, not just the tail.",
        )
    )
    board.add(
        timeseries(
            "Failures by transport",
            [
                target(
                    rate_by("tmux_lane", "tmux_failures_total"),
                    "{{tmux_lane}}",
                )
            ],
            unit="reqps",
            description="tmux rejections; the smoke workload issues these on purpose.",
        )
    )

    board.row("Traces, logs, and profiles")
    board.add(
        traces(
            "Requests that batched commands",
            '{ resource.service.name="libtmux-engines" && span.tmux.inlined > 0 }',
            description="Spans carrying more than one tmux command.",
        )
    )
    board.add(
        logs(
            "Engine logs",
            '{service_name="libtmux-engines"} | json',
            description="Application logs, correlated to traces by trace_id.",
        )
    )
    board.add(
        flamegraph(
            "CPU profile",
            description="Where Python time went while the workload ran.",
        ),
        w=24,
        h=11,
    )
    return board


def build_transports() -> Board:
    """Build the board comparing transports against each other."""
    board = Board(
        "libtmux-transports",
        "libtmux / Transports",
        description=(
            "Subprocess against control mode, sync against async. Same "
            "operations, different dispatch cost."
        ),
    )
    board.lane_variable()

    board.row("Share of work")
    board.add(
        piechart(
            "Requests by transport",
            [
                target(
                    window_total("tmux_requests_total", "tmux_lane"),
                    "{{tmux_lane}}",
                    instant=True,
                )
            ],
            description="Which transport carried the run.",
        ),
        w=8,
        h=8,
    )
    board.add(
        timeseries(
            "Commands per request",
            [
                target(
                    f"{window_total('tmux_commands_total', 'tmux_lane')} "
                    f"/ clamp_min("
                    f"{window_total('tmux_requests_total', 'tmux_lane')}, 1)",
                    "{{tmux_lane}}",
                )
            ],
            description="Above 1 means requests are carrying command groups.",
        ),
        w=8,
        h=8,
    )
    board.add(
        timeseries(
            "Inlined commands",
            [
                target(
                    rate_by("tmux_lane", "tmux_inlined_total"),
                    "{{tmux_lane}}",
                )
            ],
            unit="reqps",
            description="Commands that cost no dispatch of their own.",
        ),
        w=8,
        h=8,
    )

    board.row("Latency percentiles")
    for quantile, label in ((0.5, "p50"), (0.95, "p95"), (0.99, "p99")):
        board.add(
            timeseries(
                f"{label} by transport",
                [
                    target(
                        quantile_by(quantile, "tmux_lane"),
                        "{{tmux_lane}}",
                        exemplar=quantile == 0.99,
                    )
                ],
                unit="s",
            ),
            w=8,
            h=8,
        )

    board.row("Per-transport detail")
    board.add(
        table(
            "Transport summary",
            [
                target(
                    window_total("tmux_requests_total", "tmux_lane"),
                    "requests",
                    fmt="table",
                    instant=True,
                    ref="A",
                ),
                target(
                    window_total("tmux_commands_total", "tmux_lane"),
                    "commands",
                    fmt="table",
                    instant=True,
                    ref="B",
                ),
                target(
                    window_total("tmux_inlined_total", "tmux_lane"),
                    "inlined",
                    fmt="table",
                    instant=True,
                    ref="C",
                ),
            ],
            description="Totals for the selected window, per transport.",
        ),
        w=24,
        h=8,
    )
    return board


def build_commands() -> Board:
    """Build the board breaking work down by tmux command."""
    board = Board(
        "libtmux-commands",
        "libtmux / Commands",
        description="Which tmux commands the workload issues, and what they cost.",
    )
    board.lane_variable()

    board.row("Command mix")
    board.add(
        piechart(
            "Requests by command",
            [
                target(
                    window_total("tmux_requests_total", "tmux_command"),
                    "{{tmux_command}}",
                    instant=True,
                )
            ],
        ),
        w=8,
        h=9,
    )
    board.add(
        timeseries(
            "Request rate by command",
            [
                target(
                    rate_by("tmux_command", "tmux_requests_total"),
                    "{{tmux_command}}",
                )
            ],
            unit="reqps",
            stacking=True,
        ),
        w=16,
        h=9,
    )

    board.row("Cost and failures")
    board.add(
        timeseries(
            "p95 by command",
            [
                target(
                    quantile_by(0.95, "tmux_command"),
                    "{{tmux_command}}",
                )
            ],
            unit="s",
        )
    )
    board.add(
        timeseries(
            "Failures by command",
            [
                target(
                    rate_by("tmux_command", "tmux_failures_total"),
                    "{{tmux_command}}",
                )
            ],
            unit="reqps",
        )
    )
    board.add(
        table(
            "Command summary",
            [
                target(
                    window_total("tmux_requests_total", "tmux_command"),
                    "requests",
                    fmt="table",
                    instant=True,
                    ref="A",
                ),
                target(
                    window_total("tmux_commands_total", "tmux_command"),
                    "commands",
                    fmt="table",
                    instant=True,
                    ref="B",
                ),
                target(
                    window_quantile(0.95, "tmux_command"),
                    "p95",
                    fmt="table",
                    instant=True,
                    ref="C",
                ),
            ],
        ),
        w=24,
        h=8,
    )
    return board


BUILDERS = (build_overview, build_transports, build_commands)


def write_dashboards(out_dir: pathlib.Path) -> list[pathlib.Path]:
    """Write every board to *out_dir*, returning the paths written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for builder in BUILDERS:
        board = builder()
        path = out_dir / f"{board.uid}.json"
        path.write_text(json.dumps(board.to_dict(), indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    """Regenerate the dashboard suite."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=pathlib.Path(__file__).parent / "dashboards",
    )
    args = parser.parse_args(argv)
    for path in write_dashboards(args.output):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
