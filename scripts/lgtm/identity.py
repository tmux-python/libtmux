"""Resolve who produced a telemetry run, and decide where each fact belongs.

The hard part of adding branch, commit, worktree, spike, and test identity to
telemetry is not collecting it. It is deciding which signal carries which fact,
because the three signals fail in different ways when you get it wrong.

Metrics
    Every distinct attribute combination is a stored time series forever. A
    commit SHA on a metric means a fresh set of series on every commit, growing
    without bound, and the cost lands on whoever runs Prometheus next month.
    Only dimensions you *compare across* belong here.
Traces
    Attributes are per span and stored with it. Tempo is built for high
    cardinality, so this is where the drill-down detail goes -- SHA, worktree
    path, test case -- and TraceQL can filter on any of it.
Profiles
    Pyroscope labels are per process, and a run is one process, so the full
    static identity is free here.

The dividing question for metrics is "would I ever group by this?", not "is it
interesting?". A SHA is never a comparison axis: each run has exactly one, so
grouping by SHA is grouping by run, which :data:`METRIC_KEYS` already allows
through the run id. Carrying it as well buys no query power and costs unbounded
series. That is the one place this deliberately diverges from what agentgrep's
otel-bootstrap branch does.

Names follow OpenTelemetry semantic conventions where they exist -- the ``vcs.*``
group for repository and ref, the ``test.*`` group for test identity -- so
anything already written against those conventions can read this without a
translation table.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import typing as t

# Resource attributes copied onto every metric point, and the Prometheus label
# each becomes. Keep this list short and boring: these are comparison axes.
#
# Absent on purpose: vcs.ref.head.revision (one per run, so it adds no grouping
# power over the run id while multiplying series on every commit), the
# repository URL (constant, and it can carry a private host name), the worktree
# path (a local absolute path), and test identity (one series per test case).
METRIC_KEYS: tuple[tuple[str, str], ...] = (
    ("vcs.ref.head.name", "vcs_ref_head_name"),
    ("libtmux.run_id", "libtmux_run_id"),
    ("libtmux.spike", "libtmux_spike"),
)

# Baggage keys copied onto spans by the processor in telemetry.py. These change
# within a process -- per test, per phase -- so they cannot be resource
# attributes, and they are far too high-cardinality for metrics.
BAGGAGE_KEYS: tuple[str, ...] = (
    "test.case.name",
    "test.suite.name",
    "libtmux.phase",
)

_GIT_TIMEOUT = 5.0


def _git(root: pathlib.Path, *args: str) -> list[str] | None:
    """Run one git command, returning its output lines or ``None``."""
    try:
        completed = subprocess.run(
            ("git", "-C", str(root), *args),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip().splitlines()


def vcs_attributes(root: pathlib.Path | None = None) -> dict[str, str]:
    """Resolve repository, ref, and worktree identity for *root*.

    One ``git rev-parse`` answers all of it in a couple of milliseconds, which
    matters because this runs at process start on a developer's machine. When
    the environment already names the ref -- CI usually does -- the git call is
    skipped entirely.

    Returns
    -------
    dict
        OpenTelemetry ``vcs.*`` attributes plus ``libtmux.worktree``. Empty when
        *root* is not a git repository.
    """
    root = root or pathlib.Path(__file__).resolve().parents[2]
    attributes: dict[str, str] = {}

    lines = _git(
        root,
        "rev-parse",
        "--show-toplevel",
        "--git-common-dir",
        "HEAD",
        "--abbrev-ref",
        "HEAD",
    )
    if not lines or len(lines) < 4:
        return attributes
    toplevel, common_dir, revision, ref = lines[0], lines[1], lines[2], lines[3]

    attributes["vcs.ref.head.revision"] = revision
    if ref == "HEAD":
        # Detached: prefer a tag, and fall back to the short revision so the
        # dimension is never the literal string "HEAD" for every detached run.
        described = _git(root, "describe", "--tags", "--exact-match", "HEAD")
        if described:
            attributes["vcs.ref.head.name"] = described[0]
            attributes["vcs.ref.head.type"] = "tag"
        else:
            attributes["vcs.ref.head.name"] = revision[:12]
            attributes["vcs.ref.head.type"] = "revision"
    else:
        attributes["vcs.ref.head.name"] = ref
        attributes["vcs.ref.head.type"] = "branch"

    # The repository name comes from the common git dir, which every linked
    # worktree shares, so worktrees of one repo group together rather than
    # looking like separate projects.
    attributes["vcs.repository.name"] = pathlib.Path(common_dir).resolve().parent.name

    # git-dir differs from git-common-dir only inside a linked worktree. A
    # plain clone whose directory name differs from the repository name gets
    # the label too, since that is how sibling checkouts are told apart.
    git_dir = _git(root, "rev-parse", "--git-dir")
    checkout = pathlib.Path(toplevel).name
    linked = (
        git_dir is not None
        and bool(git_dir)
        and (pathlib.Path(git_dir[0]).resolve() != pathlib.Path(common_dir).resolve())
    )
    if linked or checkout != attributes["vcs.repository.name"]:
        attributes["libtmux.worktree"] = checkout

    return attributes


def resolve(
    *,
    run_id: str,
    spike: str | None = None,
    service_name: str = "libtmux-engines",
    root: pathlib.Path | None = None,
    env: t.Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build the full resource attribute set for one telemetry run.

    Parameters
    ----------
    run_id : str
        Identifies this run; the finest comparison axis metrics carry.
    spike : str or None
        Names an experiment, so several runs can be grouped and compared.
        Falls back to ``LIBTMUX_SPIKE``.
    service_name : str
        OpenTelemetry service name.
    root : pathlib.Path or None
        Repository to inspect; defaults to this checkout.
    env : Mapping or None
        Environment to read overrides from; defaults to :data:`os.environ`.

    Returns
    -------
    dict
        Resource attributes, ready for ``Resource.create``.
    """
    environ = os.environ if env is None else env
    attributes: dict[str, str] = {
        "service.name": service_name,
        "libtmux.run_id": run_id,
    }
    attributes.update(vcs_attributes(root))

    # An explicit ref wins over the checkout's own: CI checks out a detached
    # HEAD but knows the branch the work belongs to.
    for variable, key in (
        ("LIBTMUX_VCS_REF", "vcs.ref.head.name"),
        ("LIBTMUX_VCS_REVISION", "vcs.ref.head.revision"),
        ("LIBTMUX_WORKTREE", "libtmux.worktree"),
    ):
        value = environ.get(variable)
        if value:
            attributes[key] = value

    resolved_spike = spike or environ.get("LIBTMUX_SPIKE")
    if resolved_spike:
        attributes["libtmux.spike"] = resolved_spike
    return attributes


def metric_attributes(resource: t.Mapping[str, str]) -> dict[str, str]:
    """Select the bounded subset of *resource* that metrics may carry.

    Everything not in :data:`METRIC_KEYS` is dropped rather than renamed, so a
    new resource attribute cannot silently become a new Prometheus label. That
    is the whole safety property: growing the metric surface takes an edit
    here, where the cardinality cost is written down.

    Examples
    --------
    >>> metric_attributes({"vcs.ref.head.name": "main", "vcs.ref.head.revision": "abc"})
    {'vcs_ref_head_name': 'main'}
    """
    selected: dict[str, str] = {}
    for resource_key, label in METRIC_KEYS:
        value = resource.get(resource_key)
        if value:
            selected[label] = value
    return selected


def profile_tags(resource: t.Mapping[str, str]) -> dict[str, str]:
    """Select Pyroscope tags: the static identity, minus anything path-like.

    A profile is one process, so the full identity costs nothing here. Absolute
    paths are still excluded because they carry a home directory into a stored
    label.

    Examples
    --------
    >>> tags = profile_tags({
    ...     "vcs.ref.head.name": "main",
    ...     "vcs.ref.head.revision": "abc123",
    ...     "libtmux.run_id": "r1",
    ... })
    >>> sorted(tags)
    ['libtmux_run_id', 'vcs_ref_head_name', 'vcs_ref_head_revision']
    """
    wanted = (
        "vcs.ref.head.name",
        "vcs.ref.head.revision",
        "vcs.repository.name",
        "libtmux.worktree",
        "libtmux.run_id",
        "libtmux.spike",
    )
    return {key.replace(".", "_"): resource[key] for key in wanted if resource.get(key)}
