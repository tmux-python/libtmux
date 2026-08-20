"""Structural contracts for the generated Grafana dashboards.

These run offline. They cannot tell whether a panel has data -- that is
``scripts/otel_acceptance.py`` against a live stack -- but they do keep the
committed JSON honest about its generator and about the datasources it binds
to, which is where a board rots silently.
"""

from __future__ import annotations

import functools
import importlib.util
import json
import pathlib
import subprocess
import sys
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


def _query_panels(board: dict[str, t.Any]) -> list[dict[str, t.Any]]:
    """Return only the panels that are supposed to query a datasource.

    Text panels are documentation. Grafana's guidance is to write the question
    a board answers onto the board itself, so a panel with no query is
    expected here rather than a defect.
    """
    return [panel for panel in _panels(board) if panel["type"] != "text"]


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
        for panel in _query_panels(board):
            assert panel.get("targets"), (
                f"{board['uid']}/{panel['title']} has no targets"
            )


def test_every_target_binds_a_provisioned_datasource() -> None:
    """Panels reference datasources by uid, so the uid has to exist."""
    for board in _boards():
        for panel in _query_panels(board):
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
        for panel in _query_panels(board):
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
        for panel in _query_panels(board):
            for target in panel["targets"]:
                if (target.get("datasource") or {}).get("type") != "prometheus":
                    continue
                expr = target["expr"]
                assert "[" in expr, (
                    f"{board['uid']}/{panel['title']} reads a counter with no "
                    f"range window and will blank out once the series goes "
                    f"stale: {expr}"
                )


def test_metric_labels_stay_a_closed_low_cardinality_set() -> None:
    """Metrics may carry only the dimensions worth grouping by.

    Every distinct label combination is a Prometheus series kept forever, so
    this set is a budget, not a convenience. A commit SHA is the tempting
    mistake: each run has exactly one, so grouping by SHA is grouping by run,
    which the run id already allows -- it would buy no query power while
    adding a fresh set of series on every commit.

    Detail like the SHA, the worktree path, and test identity is not lost; it
    rides on spans and profiles, where high cardinality is expected and the
    drill-down actually happens.
    """
    spec = importlib.util.spec_from_file_location("identity", _LGTM / "identity.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert {label for _key, label in module.METRIC_KEYS} == {
        "vcs_ref_head_name",
        "libtmux_run_id",
        "libtmux_spike",
    }

    resource = {
        "vcs.ref.head.name": "main",
        "vcs.ref.head.revision": "deadbeef",
        "vcs.repository.name": "libtmux",
        "libtmux.worktree": "/home/someone/checkout",
        "libtmux.run_id": "r1",
    }
    labels = module.metric_attributes(resource)
    assert "vcs_ref_head_revision" not in labels
    assert "libtmux_worktree" not in labels
    assert labels["vcs_ref_head_name"] == "main"

    # The same facts must still reach profiles, where they are affordable.
    tags = module.profile_tags(resource)
    assert "vcs_ref_head_revision" in tags


def test_every_scope_variable_used_is_defined() -> None:
    """A panel filtering on an undefined variable silently returns nothing."""
    for board in _boards():
        names = {var["name"] for var in board["templating"]["list"]}
        serialized = json.dumps(board["panels"])
        for variable in ("lane", "branch", "spike", "run"):
            if f"${variable}" in serialized:
                assert variable in names, (
                    f"{board['uid']} filters on ${variable} without defining it"
                )


def test_identity_doctests_execute() -> None:
    """The doctests documenting the metric/profile split actually run.

    ``scripts`` is not in pytest's testpaths, so nothing else executes them.
    A doctest that never runs is a comment that looks like a test, and this
    module's examples carry the load-bearing decision: which facts a metric
    may keep and which belong on a profile.
    """
    import doctest

    spec = importlib.util.spec_from_file_location("identity", _LGTM / "identity.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    results = doctest.testmod(module, verbose=False)
    assert results.attempted > 0, "identity.py has no doctests to run"
    assert results.failed == 0, f"{results.failed} doctest(s) failed"


def test_telemetry_doctests_execute() -> None:
    """The same, for the exporter module, when its dependency is installed.

    telemetry.py needs OpenTelemetry, which lives in the ``otel`` dependency
    group rather than ``dev`` so the ordinary gates stay lean. Skipping is
    honest here; asserting would make the default test run demand a dependency
    libtmux itself never imports.
    """
    import doctest

    pytest.importorskip("opentelemetry", reason="otel dependency group not installed")

    spec = importlib.util.spec_from_file_location("telemetry", _LGTM / "telemetry.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["telemetry"] = module
    spec.loader.exec_module(module)

    results = doctest.testmod(module, verbose=False)
    assert results.failed == 0, f"{results.failed} doctest(s) failed"


def test_readme_only_shows_commands_that_exist() -> None:
    """Every ``just`` command the README demonstrates is a real recipe.

    A renamed recipe is the likeliest way this documentation rots, and the
    failure is silent: the prose still reads correctly and the command simply
    does not work. Checking is cheap because both sides are in the repo.
    """
    import re

    readme = (_LGTM / "README.md").read_text(encoding="utf-8")
    justfile = (_ROOT / "justfile").read_text(encoding="utf-8")

    shown = set(re.findall(r"^\$ just ([a-z][a-z-]*)", readme, re.MULTILINE))
    assert shown, "the README stopped showing any just commands"
    defined = set(
        re.findall(r"^([a-z][a-z-]*)(?: \*?[a-z_]+)?:", justfile, re.MULTILINE)
    )
    missing = shown - defined
    assert not missing, f"README shows recipes that do not exist: {sorted(missing)}"


def test_readme_names_every_dashboard_it_ships() -> None:
    """The README's board list matches the boards actually generated.

    Adding a board and forgetting to mention it leaves it undiscoverable,
    which for a dashboard is the same as not shipping it.
    """
    readme = (_LGTM / "README.md").read_text(encoding="utf-8")
    for path in sorted(_DASHBOARDS.glob("*.json")):
        board = json.loads(path.read_text(encoding="utf-8"))
        assert board["title"] in readme, (
            f"{board['title']} is generated but never mentioned in the README"
        )


def _identity() -> t.Any:
    """Import the identity resolver from ``scripts/``."""
    spec = importlib.util.spec_from_file_location("identity", _LGTM / "identity.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git_repo(root: pathlib.Path) -> None:
    """Create a one-commit git repository at *root*."""
    run = functools.partial(subprocess.run, cwd=root, check=True, capture_output=True)
    run(["git", "init", "-q", "-b", "trunk"])
    run(["git", "config", "user.email", "t@example.invalid"])
    run(["git", "config", "user.name", "Test"])
    (root / "f.txt").write_text("x", encoding="utf-8")
    run(["git", "add", "f.txt"])
    run(["git", "commit", "-qm", "first"])


def test_an_explicit_ref_beats_the_checkout(tmp_path: pathlib.Path) -> None:
    """CI checks out a detached HEAD but knows the branch the work belongs to.

    Without the override every CI run would be labelled by its revision, and
    comparing a branch against another would be impossible in exactly the
    place it matters most.
    """
    identity = _identity()
    _git_repo(tmp_path)

    resolved = identity.resolve(
        run_id="r",
        root=tmp_path,
        env={"LIBTMUX_VCS_REF": "release/1.2", "LIBTMUX_WORKTREE": "ci-runner"},
    )

    assert resolved["vcs.ref.head.name"] == "release/1.2"
    assert resolved["libtmux.worktree"] == "ci-runner"
    assert identity.metric_attributes(resolved)["vcs_ref_head_name"] == "release/1.2"


def test_a_detached_head_never_labels_itself_head(tmp_path: pathlib.Path) -> None:
    """Detached checkouts must not collapse onto one meaningless label.

    ``git rev-parse --abbrev-ref HEAD`` answers the literal string ``HEAD``
    when detached. Used directly, every detached run on every branch would
    share one dimension value and could not be told apart.
    """
    identity = _identity()
    _git_repo(tmp_path)
    subprocess.run(
        ["git", "checkout", "-q", "--detach"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    attributes = identity.vcs_attributes(tmp_path)

    assert attributes["vcs.ref.head.name"] != "HEAD"
    assert attributes["vcs.ref.head.type"] in {"tag", "revision"}
    assert attributes["vcs.ref.head.revision"].startswith(
        attributes["vcs.ref.head.name"]
    )


def test_a_tagged_detached_head_reports_the_tag(tmp_path: pathlib.Path) -> None:
    """A tag is more meaningful than a revision, so it wins when present."""
    identity = _identity()
    _git_repo(tmp_path)
    subprocess.run(
        ["git", "tag", "v9.9.9"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "checkout", "-q", "--detach"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    attributes = identity.vcs_attributes(tmp_path)

    assert attributes["vcs.ref.head.name"] == "v9.9.9"
    assert attributes["vcs.ref.head.type"] == "tag"


def test_a_directory_outside_git_yields_no_vcs_attributes(
    tmp_path: pathlib.Path,
) -> None:
    """Telemetry must still run where there is no repository to describe."""
    identity = _identity()

    assert identity.vcs_attributes(tmp_path) == {}
    resolved = identity.resolve(run_id="r", root=tmp_path, env={})
    assert resolved["libtmux.run_id"] == "r"
    assert "vcs.ref.head.name" not in resolved


def test_a_failing_load_setup_is_attempted_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setup that cannot succeed must not be retried by every iteration.

    rampa isolates a failing iteration and runs the next one, which is what a
    load tool should do. That makes it the scenario's job not to rebuild
    expensive state on a path that always fails: building it costs a tmux
    server and three exporter threads, so retrying per iteration turns one bad
    input into thousands of servers and enough threads to saturate the machine.
    It did exactly that once, which is why this is pinned.
    """
    pytest.importorskip("opentelemetry", reason="otel dependency group not installed")

    monkeypatch.syspath_prepend(str(_LGTM))
    spec = importlib.util.spec_from_file_location("load_tmux", _LGTM / "load_tmux.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["load_tmux"] = module
    spec.loader.exec_module(module)

    attempts = 0

    def refuse() -> t.NoReturn:
        nonlocal attempts
        attempts += 1
        message = "tmux unavailable"
        raise RuntimeError(message)

    monkeypatch.setattr(module, "_server", refuse)

    raised = []
    for _ in range(50):
        with pytest.raises(RuntimeError, match="tmux unavailable") as caught:
            module._engine()
        raised.append(caught.value)

    assert attempts == 1, f"setup was retried {attempts} times"
    assert all(error is raised[0] for error in raised)


def test_an_unknown_load_lane_is_rejected_before_anything_is_built() -> None:
    """A typo must fail at import, not once per iteration.

    Validating late means the tmux server is already created by the time the
    lane is looked up, and the failure repeats for the whole run.
    """
    source = (_LGTM / "load_tmux.py").read_text(encoding="utf-8")

    validation = source.index("if LANE not in LANES:")
    creation = source.index("def _server(")
    assert validation < creation, "the lane must be validated before _server is defined"
    assert "raise SystemExit(message)" in source


def test_the_mcp_config_and_the_stack_agree_on_grafana_port() -> None:
    """An agent's config must point where the stack actually puts Grafana.

    The image ships an MCP config assuming Grafana's default port. This stack
    moves it, so the shipped copy connects to nothing -- and the failure is
    quiet in the worst way: the agent authenticates against nothing, finds no
    data, and reports an empty stack rather than a misconfigured one. Keeping
    the two defaults in step is the whole point of shipping our own.
    """
    import re

    up = (_LGTM / "up.sh").read_text(encoding="utf-8")
    mcp = (_LGTM / "mcp-config.sh").read_text(encoding="utf-8")

    def default_port(text: str) -> str:
        match = re.search(
            r'GRAFANA_PORT="\$\{LIBTMUX_LGTM_GRAFANA_PORT:-(\d+)\}"', text
        )
        assert match, "no Grafana port default found"
        return match.group(1)

    assert default_port(up) == default_port(mcp)
    # The token belongs to the running container, never to the repository.
    assert "glsa_" not in mcp
