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

from libtmux._arena import ArenaSpec
from libtmux._internal.control_mode import ControlMode
from libtmux.client import Client
from libtmux.pane import Pane
from libtmux.pytest_plugin import USING_ZSH
from libtmux.server import Server
from libtmux.session import Session
from libtmux.window import Window

pytest_plugins = ["pytester"]

ARENA_EVIDENCE_PREFIX = "LIBTMUX_ARENA_EVIDENCE="
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


def _arena_spec(config: pytest.Config) -> ArenaSpec | None:
    """Return the validated arena contract for this pytest invocation."""
    return config.stash.get(ARENA_SPEC_KEY, None)


def _arena_targets(config: pytest.Config) -> frozenset[pathlib.Path] | None:
    """Return the validated arena sources for this pytest invocation."""
    return config.stash.get(ARENA_TARGETS_KEY, None)


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
    """Publish one evidence record per audited source, after all of them pass.

    fail-closed is preserved because ``exitstatus`` is only
    ``pytest.ExitCode.OK`` when every collected item passed; since collection
    already required every target to contribute at least one item
    (``pytest_collection_finish``), ``collected_by_target`` and
    ``passed_by_target`` are equal for every target by construction once we
    reach this point. No partial-source evidence is possible: either every
    requested page gets a record, or (on any failure/error) none do.
    """
    spec = _arena_spec(session.config)
    targets = _arena_targets(session.config)
    if spec is None or targets is None or exitstatus != pytest.ExitCode.OK:
        return
    collected_by_target = session.config.stash.get(ARENA_COLLECTED_KEY, {})
    passed_by_target = session.config.stash.get(ARENA_PASSED_KEY, {})
    if (
        not collected_by_target
        or collected_by_target.keys() != targets
        or passed_by_target != collected_by_target
        or session.config.getoption("collectonly")
    ):
        return

    server = Server(socket_path=spec.socket_path, tmux_bin=spec.tmux_bin)
    result = server.cmd(
        "display-message",
        "-p",
        "#{pid}\t#{socket_path}\t#{@libtmux_arena_challenge}",
    ).stdout
    if len(result) != 1:
        msg = "arena server identity query returned an unexpected result"
        raise RuntimeError(msg)
    parts = result[0].split("\t", 2)
    if len(parts) != 3 or parts[1] != spec.socket_path or not parts[2]:
        msg = "arena server identity does not match the requested endpoint"
        raise RuntimeError(msg)
    for target in sorted(targets, key=lambda p: p.as_posix()):
        evidence = {
            "artifact": spec.artifact,
            "challenge": parts[2],
            "schema": 1,
            "server_pid": int(parts[0]),
            "socket_path": parts[1],
            "source": target.relative_to(session.config.rootpath).as_posix(),
        }
        print(
            "\n" + ARENA_EVIDENCE_PREFIX + json.dumps(evidence, sort_keys=True),
            flush=True,
        )
