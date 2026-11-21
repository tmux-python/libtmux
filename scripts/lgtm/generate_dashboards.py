"""Generate the libtmux Grafana dashboard suite.

Dashboards are generated rather than hand-edited JSON. A Grafana board is a few
hundred lines of deeply nested objects in which a panel's position is manual
arithmetic, so hand-maintaining six of them guarantees drift. Here a board is a
list of panel calls and :class:`Board` does the grid math.

The generated JSON is committed. ``scripts/lgtm/up.sh`` regenerates it on every
start and ``tests/scripts/lgtm/test_dashboards.py`` fails if the committed copy differs,
so the two cannot silently diverge.

Every panel must be backed by telemetry ``scripts/lgtm/smoke.py`` actually
emits. ``scripts/lgtm/acceptance.py`` executes each panel's own queries and
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
# Every panel's selector, so filtering is uniform and adding a dimension here
# reaches all of them at once. Branch is in the default scope because the usual
# question is "did this branch change anything", and leaving it out silently
# mixes two branches into one line.
SCOPE = 'tmux_lane=~"$lane", vcs_ref_head_name=~"$branch"'
TAGS = ["libtmux", "generated"]

BUCKET = "tmux_command_duration_seconds_bucket"


def rate_by(label: str, metric: str) -> str:
    """Per-second rate of *metric*, grouped by *label*."""
    return f"sum by ({label}) (rate({metric}{{{SCOPE}}}[$__rate_interval]))"


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
    inner = f"increase({metric}{{{SCOPE}}}[$__range])"
    return f"sum by ({label}) ({inner})" if label else f"sum({inner})"


def window_quantile(quantile: float, label: str) -> str:
    """Latency *quantile* across the whole window, for summary tables."""
    return (
        f"histogram_quantile({quantile}, sum by (le, {label}) "
        f"(rate({BUCKET}{{{SCOPE}}}[$__range])))"
    )


def quantile_by(quantile: float, label: str) -> str:
    """Latency *quantile* from the duration histogram, grouped by *label*."""
    return (
        f"histogram_quantile({quantile}, sum by (le, {label}) "
        f"(rate({BUCKET}{{{SCOPE}}}[$__rate_interval])))"
    )


ERR_THRESHOLDS: list[dict[str, t.Any]] = [
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
        refresh: str = "1m",
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

    def add(
        self,
        panel: dict[str, t.Any],
        *,
        w: int = 12,
        h: int = 8,
        links: list[dict[str, t.Any]] | None = None,
    ) -> None:
        """Place a panel at the current grid cursor."""
        panel["id"] = self._next_id()
        panel["gridPos"] = self._place(w, h)
        if links:
            panel["links"] = links
        self._panels.append(panel)

    def variable(self, name: str, label: str, metric_label: str) -> None:
        """Add a multi-select variable populated from a metric's label values."""
        self._templates.append(
            {
                "name": name,
                "label": label,
                "type": "query",
                "datasource": PROM,
                "query": {
                    "qryType": 1,
                    "query": f"label_values(tmux_requests_total, {metric_label})",
                    "refId": f"var-{name}",
                },
                "refresh": 2,
                "sort": 1,
                "includeAll": True,
                "allValue": ".*",
                "multi": True,
                "current": {"text": "All", "value": "$__all"},
            }
        )

    def scope_variables(self) -> None:
        """Add the selectors every board shares: transport and branch."""
        self.variable("lane", "Transport", "tmux_lane")
        self.variable("branch", "Branch", "vcs_ref_head_name")

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


def text(title: str, markdown: str) -> dict[str, t.Any]:
    """Build a documentation panel.

    Grafana's guidance is that a dashboard should answer a question, and that
    the question should be written down rather than inferred from the panels.
    """
    return {
        "type": "text",
        "title": title,
        "datasource": None,
        "options": {"mode": "markdown", "content": markdown},
        "transparent": True,
    }


def drill(title: str, uid: str) -> dict[str, t.Any]:
    """Build a panel link that opens *uid* keeping time range and variables.

    Directed browsing is what separates a set of dashboards from a pile of
    them: from a symptom, one click reaches the board that explains it, still
    scoped to what you were looking at.
    """
    return {
        "title": title,
        "url": (
            f"/d/{uid}?$" + "{__url_time_range}"
            "&var-lane=${lane:queryparam}&var-branch=${branch:queryparam}"
        ),
        "targetBlank": False,
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
    board.scope_variables()

    board.add(
        text(
            "",
            "**Rate, Errors, Duration** for the tmux engines. RED is the right "
            "frame here because an engine is a service: the caller cares how "
            "much work goes through, how much of it fails, and how long it "
            "takes.\n\n"
            "Panels link to the board that explains them. Use **Transports** "
            "for which transport is responsible, **Commands** for which tmux "
            "command, and **Compare** for whether a branch or run changed "
            "anything.",
        ),
        w=24,
        h=4,
    )

    board.row("Rate")
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
    board.row("Errors")
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

    board.row("Rate over time")
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
        ),
        links=[drill("Break down by transport", "libtmux-transports")],
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
        ),
        links=[drill("Break down by command", "libtmux-commands")],
    )

    board.row("Streaming")
    board.add(
        stat(
            "Notifications received",
            [
                target(
                    f"max_over_time(sum(tmux_notifications_total{{{SCOPE}}})[$__range:])",
                    instant=True,
                )
            ],
            description=(
                "Control-mode notifications consumed by a subscriber. Counted "
                "once per run, so this reads the last value in the window "
                "rather than an increase over it."
            ),
        ),
        w=12,
        h=5,
    )
    board.add(
        stat(
            "Notifications dropped",
            [
                target(
                    f"max_over_time(sum(tmux_notifications_dropped_total{{{SCOPE}}})[$__range:])",
                    instant=True,
                )
            ],
            thresholds=ERR_THRESHOLDS,
            description=(
                "Notifications discarded because a subscriber fell behind. "
                "Above zero means the stream is outrunning its consumer."
            ),
        ),
        w=12,
        h=5,
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
    board.scope_variables()

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
    board.scope_variables()

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


def build_compare() -> Board:
    """Build the board for comparing runs, branches, and spikes.

    The other boards answer "what is happening". This one answers "is this
    different from that", which is the question the identity attributes exist
    to serve: same panels, grouped by whichever axis is being compared.
    """
    board = Board(
        "libtmux-compare",
        "libtmux / Compare",
        description=(
            "One run against another, one branch against another. Pick a spike "
            "to scope the comparison to a single experiment."
        ),
        time_from="now-6h",
    )
    board.scope_variables()
    board.variable("spike", "Spike", "libtmux_spike")

    scoped = f'{SCOPE}, libtmux_spike=~"$spike"'

    def by(label: str, metric: str) -> str:
        return f"sum by ({label}) (increase({metric}{{{scoped}}}[$__range]))"

    def quantile(quantile_value: float, label: str) -> str:
        return (
            f"histogram_quantile({quantile_value}, sum by (le, {label}) "
            f"(rate({BUCKET}{{{scoped}}}[$__range])))"
        )

    board.row("By run")
    board.add(
        table(
            "Runs in range",
            [
                target(
                    by("libtmux_run_id", "tmux_requests_total"),
                    "requests",
                    fmt="table",
                    instant=True,
                    ref="A",
                ),
                target(
                    by("libtmux_run_id", "tmux_commands_total"),
                    "commands",
                    fmt="table",
                    instant=True,
                    ref="B",
                ),
                target(
                    by("libtmux_run_id", "tmux_failures_total"),
                    "failures",
                    fmt="table",
                    instant=True,
                    ref="C",
                ),
                target(
                    quantile(0.95, "libtmux_run_id"),
                    "p95",
                    fmt="table",
                    instant=True,
                    ref="D",
                ),
            ],
            description="Every run in the window, side by side.",
        ),
        w=24,
        h=9,
    )
    board.add(
        timeseries(
            "p95 by run",
            [target(quantile(0.95, "libtmux_run_id"), "{{libtmux_run_id}}")],
            unit="s",
            description="Did a run get slower than the one before it?",
        ),
        w=12,
        h=8,
    )
    board.add(
        timeseries(
            "Request rate by run",
            [
                target(
                    f"sum by (libtmux_run_id) "
                    f"(rate(tmux_requests_total{{{scoped}}}[$__rate_interval]))",
                    "{{libtmux_run_id}}",
                )
            ],
            unit="reqps",
        ),
        w=12,
        h=8,
    )

    board.row("By branch")
    board.add(
        timeseries(
            "p95 by branch",
            [target(quantile(0.95, "vcs_ref_head_name"), "{{vcs_ref_head_name}}")],
            unit="s",
            description="The regression check: one branch against another.",
        ),
        w=12,
        h=8,
    )
    board.add(
        piechart(
            "Requests by branch",
            [
                target(
                    by("vcs_ref_head_name", "tmux_requests_total"),
                    "{{vcs_ref_head_name}}",
                    instant=True,
                )
            ],
        ),
        w=12,
        h=8,
    )
    board.add(
        table(
            "Branch summary",
            [
                target(
                    by("vcs_ref_head_name", "tmux_requests_total"),
                    "requests",
                    fmt="table",
                    instant=True,
                    ref="A",
                ),
                target(
                    by("vcs_ref_head_name", "tmux_inlined_total"),
                    "inlined",
                    fmt="table",
                    instant=True,
                    ref="B",
                ),
                target(
                    quantile(0.95, "vcs_ref_head_name"),
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


def build_home() -> Board:
    """Build the entry point that says which board answers which question.

    Grafana's maturity model calls this directed browsing: without it, finding
    the right dashboard is guesswork and the answer is to duplicate one.
    """
    board = Board(
        "libtmux-home",
        "libtmux / Home",
        description="Start here. Which board answers which question.",
        refresh="",
    )
    board.scope_variables()
    board.add(
        text(
            "",
            "# libtmux engine observability\n\n"
            "Telemetry comes from the engine instrumentation seam, so the "
            "exporters are ordinary sinks and the engines are untouched.\n\n"
            "| Board | Answers |\n"
            "| --- | --- |\n"
            "| [Overview](/d/libtmux-overview) | Is work flowing, and is it healthy? "
            "Rate, errors, duration, plus traces, logs and profiles. |\n"
            "| [Transports](/d/libtmux-transports) | Which transport is responsible? "
            "Subprocess against control mode, sync against async. |\n"
            "| [Commands](/d/libtmux-commands) | Which tmux command is responsible? |\n"
            "| [Compare](/d/libtmux-compare) | "
            "Did this run or branch change anything? |\n\n"
            "**Producing data**: `just otel-smoke` for a steady workload, "
            "`just otel-load` for a ramping arrival rate that exposes "
            "saturation. `just otel-acceptance` checks every panel still has "
            "data.\n\n"
            "Every board is generated by `scripts/lgtm/generate_dashboards.py`; "
            "edits made in this UI are overwritten on the next `just otel-up`.",
        ),
        w=24,
        h=13,
    )
    board.row("Health right now")
    board.add(
        stat(
            "Requests in range",
            [target(window_total("tmux_requests_total"), instant=True)],
            description="Across every transport in the selected window.",
        ),
        w=8,
        h=5,
        links=[drill("Open Overview", "libtmux-overview")],
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
        w=8,
        h=5,
        links=[drill("Open Commands", "libtmux-commands")],
    )
    board.add(
        stat(
            "Branches reporting",
            [
                target(
                    "count(count by (vcs_ref_head_name) ("
                    + window_total("tmux_requests_total", "vcs_ref_head_name")
                    + "))",
                    instant=True,
                )
            ],
            description="How many branches have data in this window.",
        ),
        w=8,
        h=5,
        links=[drill("Open Compare", "libtmux-compare")],
    )
    return board


BUILDERS = (build_home, build_overview, build_transports, build_commands, build_compare)


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
