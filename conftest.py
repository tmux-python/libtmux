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
ARENA_TARGET_KEY: pytest.StashKey[pathlib.Path] = pytest.StashKey()
ARENA_DISCOVERED_PATHS_KEY: pytest.StashKey[frozenset[pathlib.Path]] = pytest.StashKey()
ARENA_DISCOVERED_KEY: pytest.StashKey[frozenset[str]] = pytest.StashKey()
ARENA_COLLECTED_KEY: pytest.StashKey[frozenset[str]] = pytest.StashKey()
ARENA_PASSED_KEY: pytest.StashKey[frozenset[str]] = pytest.StashKey()


def _arena_spec(config: pytest.Config) -> ArenaSpec | None:
    """Return the validated arena contract for this pytest invocation."""
    return config.stash.get(ARENA_SPEC_KEY, None)


def _arena_target(config: pytest.Config) -> pathlib.Path | None:
    """Return the validated arena source for this pytest invocation."""
    return config.stash.get(ARENA_TARGET_KEY, None)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the source selected by the arena adapter."""
    parser.addoption(
        "--libtmux-arena-target",
        metavar="PATH",
        help="Run one audited doctest source against an external tmux server",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Validate the arena contract before pytest initializes fixtures."""
    try:
        spec = ArenaSpec.from_environ(os.environ)
    except ValueError as exc_info:
        raise pytest.UsageError(str(exc_info)) from exc_info
    if spec is None:
        return

    raw_target = config.getoption("libtmux_arena_target")
    expected_relative = ArenaSpec.target_for(spec, pathlib.Path()).as_posix()
    if raw_target != expected_relative:
        msg = f"arena artifact {spec.artifact!r} requires {expected_relative!r}"
        raise pytest.UsageError(msg)
    root = pathlib.Path(config.rootpath).resolve()
    target = spec.target_for(root).resolve(strict=True)
    config.stash[ARENA_SPEC_KEY] = spec
    config.stash[ARENA_TARGET_KEY] = target


def pytest_collection_finish(session: pytest.Session) -> None:
    """Reject selections that include anything besides the audited source."""
    target = _arena_target(session.config)
    if target is None:
        return
    paths = {item.path.resolve() for item in session.items}
    selected = frozenset(item.nodeid for item in session.items)
    discovered_paths = session.config.stash.get(ARENA_DISCOVERED_PATHS_KEY, frozenset())
    discovered = session.config.stash.get(ARENA_DISCOVERED_KEY, frozenset())
    if (
        paths != {target}
        or discovered_paths != {target}
        or not discovered
        or selected != discovered
    ):
        msg = "arena requires collection of exactly one audited doctest source"
        raise pytest.UsageError(msg)
    session.config.stash[ARENA_COLLECTED_KEY] = selected


def pytest_itemcollected(item: pytest.Item) -> None:
    """Record every arena item before pytest applies filters."""
    target = _arena_target(item.config)
    if target is None:
        return
    path = item.path.resolve()
    discovered_paths = item.config.stash.get(ARENA_DISCOVERED_PATHS_KEY, frozenset())
    item.config.stash[ARENA_DISCOVERED_PATHS_KEY] = discovered_paths | {path}
    if path == target:
        discovered = item.config.stash.get(ARENA_DISCOVERED_KEY, frozenset())
        item.config.stash[ARENA_DISCOVERED_KEY] = discovered | {item.nodeid}


def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[t.Any]) -> None:
    """Record successful arena doctest calls for evidence publication."""
    target = _arena_target(item.config)
    if target is None or item.path.resolve() != target:
        return
    if call.when == "call" and call.excinfo is None:
        passed = item.config.stash.get(ARENA_PASSED_KEY, frozenset())
        item.config.stash[ARENA_PASSED_KEY] = passed | {item.nodeid}


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
            if cleanup.returncode != 0:
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
    """Publish evidence only after the selected doctests pass."""
    spec = _arena_spec(session.config)
    target = _arena_target(session.config)
    if spec is None or target is None or exitstatus != pytest.ExitCode.OK:
        return
    collected = session.config.stash.get(ARENA_COLLECTED_KEY, frozenset())
    passed = session.config.stash.get(ARENA_PASSED_KEY, frozenset())
    if not collected or passed != collected or session.config.getoption("collectonly"):
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
    evidence = {
        "artifact": spec.artifact,
        "challenge": parts[2],
        "schema": 1,
        "server_pid": int(parts[0]),
        "socket_path": parts[1],
        "source": target.relative_to(session.config.rootpath).as_posix(),
    }
    print(
        "\n" + ARENA_EVIDENCE_PREFIX + json.dumps(evidence, sort_keys=True), flush=True
    )
