"""Conftest.py (root-level).

We keep this in root pytest fixtures in pytest's doctest plugin to be available, as well
as avoiding conftest.py from being included in the wheel, in addition to pytest_plugin
for pytester only being available via the root directory.

See "pytest_plugins in non-top-level conftest files" in
https://docs.pytest.org/en/stable/deprecations.html
"""

from __future__ import annotations

import contextlib
import pathlib
import shutil
import subprocess
import typing as t
import uuid

import pytest
from _pytest.doctest import DoctestItem

from libtmux._internal.engines.control_protocol import CommandContext, ControlProtocol
from libtmux.pane import Pane
from libtmux.pytest_plugin import USING_ZSH
from libtmux.server import Server
from libtmux.session import Session
from libtmux.window import Window

if t.TYPE_CHECKING:
    import pathlib

pytest_plugins = ["pytester"]


@pytest.fixture(autouse=True)
def add_doctest_fixtures(
    request: pytest.FixtureRequest,
    doctest_namespace: dict[str, t.Any],
) -> None:
    """Configure doctest fixtures for pytest-doctest."""
    if isinstance(request._pyfuncitem, DoctestItem) and shutil.which("tmux"):
        request.getfixturevalue("set_home")
        doctest_namespace["Server"] = Server
        doctest_namespace["Session"] = Session
        doctest_namespace["Window"] = Window
        doctest_namespace["Pane"] = Pane
        doctest_namespace["server"] = request.getfixturevalue("server")
        doctest_namespace["Server"] = request.getfixturevalue("TestServer")
        session: Session = request.getfixturevalue("session")
        doctest_namespace["session"] = session
        doctest_namespace["window"] = session.active_window
        doctest_namespace["pane"] = session.active_pane
        doctest_namespace["request"] = request


@pytest.fixture(autouse=True)
def set_home(
    monkeypatch: pytest.MonkeyPatch,
    user_path: pathlib.Path,
) -> None:
    """Configure home directory for pytest tests."""
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


# ---------------------------------------------------------------------------
# Control-mode sandbox helper
# ---------------------------------------------------------------------------


@pytest.fixture
@contextlib.contextmanager
def control_sandbox(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> t.Iterator[Server]:
    """Provide an isolated control-mode server for a test.

    - Creates a unique tmux socket name per invocation
    - Isolates HOME and TMUX_TMPDIR under a per-test temp directory
    - Clears TMUX env var to avoid inheriting user sessions
    - Uses ControlModeEngine; on exit, kills the server best-effort
    """
    socket_name = f"libtmux_test_{uuid.uuid4().hex[:8]}"
    base = tmp_path_factory.mktemp("ctrl_sandbox")
    home = base / "home"
    tmux_tmpdir = base / "tmux"
    home.mkdir()
    tmux_tmpdir.mkdir()

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("TMUX_TMPDIR", str(tmux_tmpdir))
    monkeypatch.delenv("TMUX", raising=False)

    from libtmux._internal.engines.control_mode import ControlModeEngine

    server = Server(socket_name=socket_name, engine=ControlModeEngine())

    try:
        yield server
    finally:
        with contextlib.suppress(Exception):
            server.kill()
        with contextlib.suppress(Exception):
            server.engine.close()


@pytest.fixture
def control_client_logs(
    control_sandbox: t.ContextManager[Server],
    tmp_path_factory: pytest.TempPathFactory,
) -> t.Iterator[tuple[subprocess.Popen[str], ControlProtocol, pathlib.Path]]:
    """Spawn a raw tmux -C client against the sandbox and log stdout/stderr."""
    base = tmp_path_factory.mktemp("ctrl_logs")
    stdout_path = base / "control_stdout.log"
    stderr_path = base / "control_stderr.log"

    with control_sandbox as server:
        cmd = [
            "tmux",
            "-L",
            server.socket_name or "",
            "-C",
            "attach-session",
            "-t",
            "ctrltest",
        ]
        # Ensure ctrltest exists
        server.cmd("new-session", "-d", "-s", "ctrltest")
        stdout_f = stdout_path.open("w+", buffering=1)
        stderr_f = stderr_path.open("w+", buffering=1)
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=stdout_f,
            stderr=stderr_f,
            text=True,
            bufsize=1,
        )
        proto = ControlProtocol()
        # tmux -C will emit a %begin/%end pair for this initial attach-session;
        # queue a matching context so the parser has a pending command.
        proto.register_command(CommandContext(argv=list(cmd)))
        try:
            yield proc, proto, stdout_path
        finally:
            with contextlib.suppress(Exception):
                if proc.stdin:
                    proc.stdin.write("kill-session -t ctrltest\n")
                    proc.stdin.flush()
            proc.terminate()
            proc.wait(timeout=2)
            with contextlib.suppress(Exception):
                stdout_f.close()
            with contextlib.suppress(Exception):
                stderr_f.close()


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add CLI options for selecting tmux engine."""
    parser.addoption(
        "--engine",
        action="store",
        default="subprocess",
        choices=["subprocess", "control"],
        help="Select tmux engine for fixtures (default: subprocess).",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        (
            "engines(names): run the test once for each engine in 'names' "
            "(e.g. ['control', 'subprocess'])."
        ),
    )


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize engine_name when requested by tests."""
    if "engine_name" in metafunc.fixturenames:
        marker = metafunc.definition.get_closest_marker("engines")
        if marker:
            params = list(marker.args[0])
        else:
            params = [metafunc.config.getoption("--engine")]
        metafunc.parametrize("engine_name", params, indirect=True)


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Filter out doctests when running with control engine.

    Remove doctests from collection to avoid pytest's _use_item_location
    bug: DoctestItem.reportinfo() returns None lineno for fixture doctests,
    which triggers assertion failure in _pytest/reports.py:420 when skipped.
    """
    engine_opt = config.getoption("--engine", default="subprocess")
    if engine_opt != "control":
        return

    # Filter out DoctestItems - can't use skip markers due to pytest bug
    items[:] = [item for item in items if not isinstance(item, DoctestItem)]
