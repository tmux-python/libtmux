"""Conftest.py (root-level).

We keep this in root pytest fixtures in pytest's doctest plugin to be available, as well
as avoiding conftest.py from being included in the wheel, in addition to pytest_plugin
for pytester only being available via the root directory.

See "pytest_plugins in non-top-level conftest files" in
https://docs.pytest.org/en/stable/deprecations.html
"""

from __future__ import annotations

import functools
import json
import os
import pathlib
import shutil
import typing as t
import uuid

import pytest
from _pytest.doctest import DoctestItem

from libtmux._arena import ARENA_EXCLUDED_SOURCES, ArenaSpec
from libtmux._internal.control_mode import ControlMode
from libtmux.client import Client
from libtmux.pane import Pane
from libtmux.pytest_plugin import USING_ZSH
from libtmux.server import Server
from libtmux.session import Session
from libtmux.window import Window

pytest_plugins = ["pytester"]

ARENA_EVIDENCE_PREFIX = "LIBTMUX_ARENA_EVIDENCE="
# One round-trip answers identity and the challenge together: pid and
# socket_path prove *which* server answered, @libtmux_arena_challenge proves
# it is still configured as the one that was lent (a silently spawned
# replacement starts with no such option set).
ARENA_IDENTITY_FORMAT = "#{pid}\t#{socket_path}\t#{@libtmux_arena_challenge}"
ARENA_SPEC_KEY: pytest.StashKey[ArenaSpec] = pytest.StashKey()
# A set rather than one path: an artifact may audit several pages, and the
# supervisor then expects one evidence record per page.
ARENA_TARGETS_KEY: pytest.StashKey[frozenset[pathlib.Path]] = pytest.StashKey()
ARENA_DISCOVERED_PATHS_KEY: pytest.StashKey[frozenset[pathlib.Path]] = pytest.StashKey()
# Node ids per source rather than one flat set, so a record can name the page
# that produced it, and a page that collected nothing is caught.
ARENA_DISCOVERED_KEY: pytest.StashKey[dict[pathlib.Path, frozenset[str]]] = (
    pytest.StashKey()
)
ARENA_COLLECTED_KEY: pytest.StashKey[dict[pathlib.Path, frozenset[str]]] = (
    pytest.StashKey()
)
ARENA_PASSED_KEY: pytest.StashKey[dict[pathlib.Path, frozenset[str]]] = (
    pytest.StashKey()
)
# The identity captured once, before any page runs, so every later query has
# something fixed to compare against rather than just "looks fine to itself".
ARENA_IDENTITY_KEY: pytest.StashKey[tuple[int, str, str]] = pytest.StashKey()
# Session names already on the lend before this run touched it, so teardown
# can reap exactly what the run's own examples left behind and nothing else.
ARENA_BASELINE_SESSIONS_KEY: pytest.StashKey[frozenset[str]] = pytest.StashKey()
# The last node id collected per source, in the order pytest will actually
# run them -- how the per-page identity check knows a page has finished
# without guessing at item counts.
ARENA_LAST_NODEID_KEY: pytest.StashKey[dict[pathlib.Path, str]] = pytest.StashKey()


def _arena_spec(config: pytest.Config) -> ArenaSpec | None:
    """Return the validated arena contract for this pytest invocation."""
    return config.stash.get(ARENA_SPEC_KEY, None)


def _arena_targets(config: pytest.Config) -> frozenset[pathlib.Path] | None:
    """Return the validated arena sources for this pytest invocation."""
    return config.stash.get(ARENA_TARGETS_KEY, None)


def _query_arena_identity(spec: ArenaSpec) -> tuple[int, str, str]:
    """Return (pid, socket_path, challenge) for the endpoint ``spec`` names.

    ``display-message`` only ever answers a server already listening on the
    requested socket -- unlike ``new-session``, tmux does not spawn one to
    service it (verified: a `list-sessions`/`display-message` against a
    socket with nothing listening just errors, it never creates the socket
    file). So this query itself can never be what silently starts the
    replacement server a stopped lend produces.
    """
    server = Server(socket_path=spec.socket_path, tmux_bin=spec.tmux_bin)
    result = server.cmd("display-message", "-p", ARENA_IDENTITY_FORMAT).stdout
    if len(result) != 1:
        msg = "arena server identity query returned an unexpected result"
        raise RuntimeError(msg)
    parts = result[0].split("\t", 2)
    if len(parts) != 3 or parts[1] != spec.socket_path or not parts[2]:
        msg = "arena server identity does not match the requested endpoint"
        raise RuntimeError(msg)
    return int(parts[0]), parts[1], parts[2]


def _verify_arena_identity(
    spec: ArenaSpec,
    baseline: tuple[int, str, str],
    where: str,
) -> None:
    """Raise, naming ``where``, if the lent server's identity has moved on.

    ``where`` is the source whose examples just finished running, or "the
    run" for the check just before evidence is published -- so a break is
    attributed to the page after which it was detected, rather than only
    discovered once every requested page has already run against whatever
    answered next.
    """
    try:
        observed = _query_arena_identity(spec)
    except RuntimeError as exc_info:
        msg = f"arena server identity check failed after {where!r}: {exc_info}"
        raise RuntimeError(msg) from exc_info
    if observed != baseline:
        msg = (
            f"arena server identity changed after {where!r}: expected "
            f"pid/socket/challenge {baseline!r}, got {observed!r}"
        )
        raise RuntimeError(msg)


def _reap_arena_sessions(spec: ArenaSpec, baseline_sessions: frozenset[str]) -> None:
    """Kill every session this run's own examples left behind.

    Idempotent: a session already gone (already reaped, or never existed)
    is not an error. Scoped to the diff against ``baseline_sessions`` -- the
    lend's own sessions from before this run touched it -- so a session that
    predates the run, such as its hold session, is never a candidate.
    """
    server = Server(socket_path=spec.socket_path, tmux_bin=spec.tmux_bin)
    current = {s.session_name for s in server.sessions if s.session_name is not None}
    for name in sorted(current - baseline_sessions):
        cleanup = server.cmd("kill-session", target=name)
        already_gone = cleanup.returncode != 0 and any(
            "can't find session" in line or "session not found" in line
            for line in cleanup.stderr
        )
        if cleanup.returncode != 0 and not already_gone:
            msg = f"arena teardown could not reap leaked session {name!r}"
            raise RuntimeError(msg)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the source(s) selected by the arena adapter.

    Repeatable: one flag per audited page. The adapter passes exactly the
    pages its artifact declares, and nothing else may be collected.
    """
    parser.addoption(
        "--libtmux-arena-target",
        metavar="PATH",
        action="append",
        help="Run one audited doctest source against an external tmux server "
        "(repeatable)",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Validate the arena contract before pytest initializes fixtures."""
    try:
        spec = ArenaSpec.from_environ(os.environ)
    except ValueError as exc_info:
        raise pytest.UsageError(str(exc_info)) from exc_info
    if spec is None:
        return

    raw_targets = frozenset(config.getoption("libtmux_arena_target") or [])
    excluded = {
        source: ARENA_EXCLUDED_SOURCES[source]
        for source in raw_targets
        if source in ARENA_EXCLUDED_SOURCES
    }
    if excluded:
        # Checked before the artifact's own tuple is even consulted: a
        # source like this must be refused by name, not merely absent from
        # ARENA_ARTIFACT_TARGETS -- the two look identical from outside a
        # mismatch error otherwise.
        reasons = "; ".join(
            f"{source!r} ({reason})" for source, reason in sorted(excluded.items())
        )
        msg = f"arena refuses excluded source(s): {reasons}"
        raise pytest.UsageError(msg)

    expected_relative = frozenset(
        p.as_posix() for p in spec.targets_for(pathlib.Path())
    )
    if raw_targets != expected_relative:
        msg = f"arena artifact {spec.artifact!r} requires {sorted(expected_relative)!r}"
        raise pytest.UsageError(msg)
    root = pathlib.Path(config.rootpath).resolve()
    targets = frozenset(p.resolve(strict=True) for p in spec.targets_for(root))
    config.stash[ARENA_SPEC_KEY] = spec
    config.stash[ARENA_TARGETS_KEY] = targets

    # Baseline, captured before any page runs: what "the lent server" and
    # "its sessions" mean for the rest of this run. Every later identity
    # check compares against this rather than against its own last query, so
    # a slow drift across several pages cannot pass by always comparing
    # favorably to the most recent (possibly already-wrong) reading.
    try:
        config.stash[ARENA_IDENTITY_KEY] = _query_arena_identity(spec)
    except RuntimeError as exc_info:
        raise pytest.UsageError(str(exc_info)) from exc_info
    baseline_server = Server(socket_path=spec.socket_path, tmux_bin=spec.tmux_bin)
    config.stash[ARENA_BASELINE_SESSIONS_KEY] = frozenset(
        s.session_name for s in baseline_server.sessions if s.session_name is not None
    )


def pytest_collection_finish(session: pytest.Session) -> None:
    """Reject selections that include anything besides the audited sources."""
    targets = _arena_targets(session.config)
    if targets is None:
        return
    paths = {item.path.resolve() for item in session.items}
    selected = frozenset(item.nodeid for item in session.items)
    discovered_paths = session.config.stash.get(ARENA_DISCOVERED_PATHS_KEY, frozenset())
    discovered = session.config.stash.get(ARENA_DISCOVERED_KEY, {})
    discovered_all = (
        frozenset().union(*discovered.values()) if discovered else frozenset()
    )
    if (
        paths != targets
        or discovered_paths != targets
        or discovered.keys() != targets
        or any(not nodeids for nodeids in discovered.values())
        or selected != discovered_all
    ):
        msg = "arena requires collection of exactly the audited doctest sources"
        raise pytest.UsageError(msg)
    session.config.stash[ARENA_COLLECTED_KEY] = dict(discovered)

    # The last node id per source, in the order pytest is actually about to
    # run them (not the order they happened to be discovered in). This is
    # how the per-page identity check recognizes "a page just finished"
    # without hard-coding how many items any given page collects.
    last_nodeid_by_path: dict[pathlib.Path, str] = {}
    for item in session.items:
        item_path = item.path.resolve()
        if item_path in targets:
            last_nodeid_by_path[item_path] = item.nodeid
    session.config.stash[ARENA_LAST_NODEID_KEY] = last_nodeid_by_path


def pytest_itemcollected(item: pytest.Item) -> None:
    """Record every arena item before pytest applies filters."""
    targets = _arena_targets(item.config)
    if targets is None:
        return
    path = item.path.resolve()
    discovered_paths = item.config.stash.get(ARENA_DISCOVERED_PATHS_KEY, frozenset())
    item.config.stash[ARENA_DISCOVERED_PATHS_KEY] = discovered_paths | {path}
    if path in targets:
        discovered = item.config.stash.get(ARENA_DISCOVERED_KEY, {})
        discovered = dict(discovered)
        discovered[path] = discovered.get(path, frozenset()) | {item.nodeid}
        item.config.stash[ARENA_DISCOVERED_KEY] = discovered


def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[t.Any]) -> None:
    """Record successful arena doctest calls for evidence publication."""
    targets = _arena_targets(item.config)
    path = item.path.resolve()
    if targets is None or path not in targets:
        return
    if call.when == "call" and call.excinfo is None:
        passed = item.config.stash.get(ARENA_PASSED_KEY, {})
        passed = dict(passed)
        passed[path] = passed.get(path, frozenset()) | {item.nodeid}
        item.config.stash[ARENA_PASSED_KEY] = passed


@pytest.fixture(autouse=True)
def add_doctest_fixtures(
    request: pytest.FixtureRequest,
    doctest_namespace: dict[str, t.Any],
) -> t.Generator[None]:
    """Configure doctest fixtures for pytest-doctest."""
    if not isinstance(request._pyfuncitem, DoctestItem):
        yield
        return

    spec = _arena_spec(request.config)
    if spec is None and not shutil.which("tmux"):
        yield
        return

    if spec is None:
        request.getfixturevalue("set_home")
        server = request.getfixturevalue("server")
        test_server = request.getfixturevalue("TestServer")
        session: Session = request.getfixturevalue("session")
    else:
        server = Server(socket_path=spec.socket_path, tmux_bin=spec.tmux_bin)
        session_name = f"libtmux_arena_{uuid.uuid4().hex}"
        session = server.new_session(session_name=session_name)
        test_server = functools.partial(
            Server,
            socket_path=spec.socket_path,
            tmux_bin=spec.tmux_bin,
        )

    doctest_namespace["Server"] = Server
    doctest_namespace["Session"] = Session
    doctest_namespace["Window"] = Window
    doctest_namespace["Pane"] = Pane
    doctest_namespace["Client"] = Client
    doctest_namespace["server"] = server
    doctest_namespace["Server"] = test_server
    doctest_namespace["session"] = session
    doctest_namespace["window"] = session.active_window
    doctest_namespace["pane"] = session.active_pane
    doctest_namespace["request"] = request
    doctest_namespace["ControlMode"] = ControlMode
    doctest_namespace["control_mode"] = functools.partial(
        ControlMode,
        server=session.server,
        session=session,
    )
    doctest_namespace["monkeypatch"] = request.getfixturevalue("monkeypatch")
    try:
        yield
    finally:
        if spec is not None:
            cleanup = server.cmd("kill-session", target=session_name)
            # idempotent teardown. A doctest that kills its own
            # last pane/window (tmux: last window dies -> session dies) has
            # already achieved this fixture's goal -- "our session is gone"
            # -- by the time we get here. Only a session that is *not* gone
            # and *failed* to go is a real cleanup failure; do not conflate
            # "already torn down" with "could not tear down" (see
            # pane_interaction.md:467,477 in borrowed.md finding 2).
            already_gone = cleanup.returncode != 0 and any(
                "can't find session" in line or "session not found" in line
                for line in cleanup.stderr
            )
            if cleanup.returncode != 0 and not already_gone:
                msg = "arena session cleanup failed"
                raise RuntimeError(msg)

            # Prove identity survived this page before the next one starts
            # to run against whatever answers next. Only the item that is
            # last (in run order) for its source checks -- an earlier item
            # in the same page would just repeat a check its own page
            # hasn't finished yet, and the page boundary is exactly where a
            # doctest-content break (like the excluded context_managers.md's
            # `with Server()`) would land.
            last_nodeid_by_path = request.config.stash.get(
                ARENA_LAST_NODEID_KEY,
                {},
            )
            item_path = request._pyfuncitem.path.resolve()
            if last_nodeid_by_path.get(item_path) == request._pyfuncitem.nodeid:
                baseline = request.config.stash.get(ARENA_IDENTITY_KEY, None)
                if baseline is not None:
                    source = item_path.relative_to(
                        request.config.rootpath,
                    ).as_posix()
                    _verify_arena_identity(spec, baseline, source)


@pytest.fixture(autouse=True)
def set_home(
    monkeypatch: pytest.MonkeyPatch,
    user_path: pathlib.Path,
    request: pytest.FixtureRequest,
) -> None:
    """Configure home directory for pytest tests."""
    if _arena_spec(request.config) is None:
        monkeypatch.setenv("HOME", str(user_path))


@pytest.fixture(autouse=True)
def setup_fn(
    clear_env: None,
) -> None:
    """Function-level test configuration fixtures for pytest."""


@pytest.fixture(autouse=True, scope="session")
def setup_session(
    request: pytest.FixtureRequest,
    config_file: pathlib.Path,
) -> None:
    """Session-level test configuration for pytest."""
    if USING_ZSH:
        request.getfixturevalue("zshrc")


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Reap the run's stray sessions, then publish evidence once all pass.

    Reaping runs whenever the identity captured at ``pytest_configure`` still
    matches -- regardless of ``exitstatus`` -- so a run that fails for an
    unrelated reason does not leave the lend dirtier than it found it.
    It is skipped, not attempted against a guess, the moment identity no
    longer matches: after a break (or a silent replacement) the socket may
    not even be answering for the server this run was lent, and teardown
    does not touch a tmux server it cannot first prove is that one.

    fail-closed is preserved for evidence because ``exitstatus`` is only
    ``pytest.ExitCode.OK`` when every collected item passed; since collection
    already required every target to contribute at least one item
    (``pytest_collection_finish``), ``collected_by_target`` and
    ``passed_by_target`` are equal for every target by construction once we
    reach this point. No partial-source evidence is possible: either every
    requested page gets a record, or (on any failure/error) none do.
    """
    spec = _arena_spec(session.config)
    targets = _arena_targets(session.config)
    if spec is None or targets is None:
        return

    baseline_identity = session.config.stash.get(ARENA_IDENTITY_KEY, None)
    baseline_sessions = session.config.stash.get(ARENA_BASELINE_SESSIONS_KEY, None)
    try:
        observed_identity = _query_arena_identity(spec)
    except RuntimeError:
        observed_identity = None
    identity_intact = (
        baseline_identity is not None and observed_identity == baseline_identity
    )
    if identity_intact and baseline_sessions is not None:
        _reap_arena_sessions(spec, baseline_sessions)

    collected_by_target = session.config.stash.get(ARENA_COLLECTED_KEY, {})
    passed_by_target = session.config.stash.get(ARENA_PASSED_KEY, {})
    if (
        exitstatus != pytest.ExitCode.OK
        or not collected_by_target
        or collected_by_target.keys() != targets
        or passed_by_target != collected_by_target
        or session.config.getoption("collectonly")
    ):
        return

    if baseline_identity is None or not identity_intact:
        msg = "arena server identity does not match the requested endpoint"
        raise RuntimeError(msg)
    for target in sorted(targets, key=lambda p: p.as_posix()):
        evidence = {
            "artifact": spec.artifact,
            "challenge": baseline_identity[2],
            "schema": 1,
            "server_pid": baseline_identity[0],
            "socket_path": baseline_identity[1],
            "source": target.relative_to(session.config.rootpath).as_posix(),
        }
        print(
            "\n" + ARENA_EVIDENCE_PREFIX + json.dumps(evidence, sort_keys=True),
            flush=True,
        )
