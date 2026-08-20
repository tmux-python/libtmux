"""Structural contracts for the generated Grafana dashboards.

These run offline. They cannot tell whether a panel has data -- that is
``scripts/otel_acceptance.py`` against a live stack -- but they do keep the
committed JSON honest about its generator and about the datasources it binds
to, which is where a board rots silently.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import typing as t

import pytest

_ROOT = pathlib.Path(__file__).parents[1]
_LGTM = _ROOT / "scripts" / "lgtm"
_DASHBOARDS = _LGTM / "dashboards"

# The uids provisioned by scripts/lgtm/grafana-datasources.yaml. A panel bound
# to anything else renders an error instead of data.
_DATASOURCE_UIDS = {"prometheus", "loki", "tempo", "pyroscope"}


def _generator() -> t.Any:
    """Import the dashboard generator from ``scripts/`` by path."""
    spec = importlib.util.spec_from_file_location(
        "generate_dashboards", _LGTM / "generate_dashboards.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _boards() -> list[dict[str, t.Any]]:
    """Load every committed dashboard."""
    loaded: list[dict[str, t.Any]] = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(_DASHBOARDS.glob("*.json"))
    ]
    assert loaded, "no dashboards committed"
    return loaded


def _panels(board: dict[str, t.Any]) -> list[dict[str, t.Any]]:
    """Return a board's real panels, skipping row headers."""
    return [panel for panel in board["panels"] if panel["type"] != "row"]


def test_committed_dashboards_match_their_generator(tmp_path: pathlib.Path) -> None:
    """The JSON in the repo is what the generator produces right now.

    ``up.sh`` regenerates on every start, so a stale committed copy would be
    silently replaced at runtime and the diff would show up in someone else's
    working tree.
    """
    module = _generator()
    module.write_dashboards(tmp_path)

    regenerated = {
        path.name: path.read_text(encoding="utf-8") for path in tmp_path.glob("*.json")
    }
    committed = {
        path.name: path.read_text(encoding="utf-8")
        for path in _DASHBOARDS.glob("*.json")
    }

    assert set(regenerated) == set(committed)
    for name, text in regenerated.items():
        assert committed[name] == text, f"{name} is stale; run `just otel-dashboards`"


def test_every_panel_queries_something() -> None:
    """A panel with no target can never show data."""
    for board in _boards():
        for panel in _panels(board):
            assert panel.get("targets"), (
                f"{board['uid']}/{panel['title']} has no targets"
            )


def test_every_target_binds_a_provisioned_datasource() -> None:
    """Panels reference datasources by uid, so the uid has to exist."""
    for board in _boards():
        for panel in _panels(board):
            for target in panel["targets"]:
                uid = (target.get("datasource") or {}).get("uid")
                assert uid in _DATASOURCE_UIDS, (
                    f"{board['uid']}/{panel['title']} binds unknown datasource {uid!r}"
                )


def test_lane_variable_is_defined_wherever_it_is_used() -> None:
    """A query filtering on ``$lane`` needs the board to define ``$lane``.

    An undefined variable is not an error in Grafana; it interpolates to an
    empty string and the panel quietly returns nothing.
    """
    for board in _boards():
        names = {var["name"] for var in board["templating"]["list"]}
        serialized = json.dumps(board["panels"])
        if "$lane" in serialized:
            assert "lane" in names, f"{board['uid']} uses $lane without defining it"


def test_dashboard_uid_matches_its_filename() -> None:
    """Provisioning keys on uid; a mismatch makes boards hard to find."""
    for path in sorted(_DASHBOARDS.glob("*.json")):
        board = json.loads(path.read_text(encoding="utf-8"))
        assert board["uid"] == path.stem


def test_acceptance_expands_every_template_variable() -> None:
    """No ``$`` may survive expansion, or a query filters on a literal.

    Grafana substitutes variables before sending a query. The acceptance script
    has to do the same, and a variable it does not know about would be sent
    through as text and match nothing.
    """
    spec = importlib.util.spec_from_file_location(
        "otel_acceptance", _ROOT / "scripts" / "otel_acceptance.py"
    )
    assert spec is not None
    assert spec.loader is not None
    acceptance = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(acceptance)

    for board in _boards():
        for panel in _panels(board):
            for target in panel["targets"]:
                query = (
                    target.get("expr")
                    or target.get("query")
                    or target.get("labelSelector")
                )
                if query is None:
                    continue
                assert "$" not in acceptance.expand(query), (
                    f"{board['uid']}/{panel['title']} keeps a variable after expansion"
                )


@pytest.mark.parametrize(
    "required", ["libtmux-overview", "libtmux-transports", "libtmux-commands"]
)
def test_expected_boards_are_committed(required: str) -> None:
    """The suite the README and acceptance script assume exists."""
    assert (_DASHBOARDS / f"{required}.json").is_file()


def test_no_panel_reads_a_counter_without_a_window() -> None:
    """Every Prometheus query must span a range, never read a counter at a point.

    The workloads that feed these boards are short-lived. A few minutes after
    one exits, Prometheus marks its series stale and an instant query at
    ``now`` returns nothing, so a panel reading ``sum(tmux_requests_total)``
    renders "No data" while the timeseries beside it still shows the run.

    Windowing the query -- ``increase(...[$__range])``, ``rate(...[...])`` --
    asks what happened during the selected window instead, which is both what
    the viewer meant and immune to staleness. This test is the cheap offline
    guard for that: a live check only catches it if it runs late enough for
    the series to have gone stale, which is exactly when nobody is looking.
    """
    for board in _boards():
        for panel in _panels(board):
            for target in panel["targets"]:
                if (target.get("datasource") or {}).get("type") != "prometheus":
                    continue
                expr = target["expr"]
                assert "[" in expr, (
                    f"{board['uid']}/{panel['title']} reads a counter with no "
                    f"range window and will blank out once the series goes "
                    f"stale: {expr}"
                )
