"""Tests for :class:`libtmux.engines.exec.ExecEngine`, through transport shims.

No docker daemon, cluster or sshd is needed. Each shim is a small script named
like the real tool that records its argv, then does what the real one does with
it: ``docker exec`` and ``kubectl exec`` run the command untouched, and ``ssh``
joins the words with spaces and has a shell re-parse them, which is the
behaviour ``shell=True`` exists for.
"""

from __future__ import annotations

import json
import os
import pathlib
import signal
import stat
import subprocess
import sys
import textwrap
import typing as t

import pytest

from libtmux import exc
from libtmux.common import get_version_str
from libtmux.engines import (
    CommandRequest,
    ExecEngine,
    ServerConnection,
    SubprocessEngine,
    SupportsCommandLine,
    SupportsConnection,
    SupportsTmuxVersion,
    TmuxEngine,
)
from libtmux.server import Server

if t.TYPE_CHECKING:
    from collections.abc import Iterator

SHIM = textwrap.dedent(
    """\
    #!{python}
    import json, os, sys
    kind = os.path.basename(sys.argv[0])
    args = sys.argv[1:]
    with open(os.environ["SHIM_LOG"], "a") as log:
        log.write(json.dumps([kind, *args]) + "\\n")
    if kind == "docker":
        assert args[:2] == ["exec", "-i"], args
        rest = args[2:]
        if rest[0] == "-u":
            rest = rest[2:]
        rest = rest[1:]
        os.execvp(rest[0], rest)
    elif kind == "kubectl":
        assert args[:2] == ["exec", "-i"], args
        rest = args[args.index("--") + 1:]
        os.execvp(rest[0], rest)
    else:
        rest = args
        while rest[0].startswith("-"):
            rest = rest[2:]
        os.execvp("sh", ["sh", "-c", " ".join(rest[1:])])
    """,
)


class Shims(t.NamedTuple):
    """The shim directory and its call log."""

    log: pathlib.Path

    def calls(self) -> list[list[str]]:
        """Return every recorded invocation."""
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]


@pytest.fixture
def shims(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> Shims:
    """Put ``docker``, ``kubectl`` and ``ssh`` shims first on ``PATH``."""
    bin_dir = tmp_path / "shims"
    bin_dir.mkdir()
    for name in ("docker", "kubectl", "ssh"):
        script = bin_dir / name
        script.write_text(SHIM.replace("{python}", sys.executable))
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("SHIM_LOG", str(log))
    return Shims(log)


def request(*args: str, **kwargs: t.Any) -> CommandRequest:
    """Build a request."""
    return CommandRequest.from_args(*args, **kwargs)


def test_engine_satisfies_the_seam_protocols() -> None:
    """Named capabilities are what ``Server`` and ``tmux_cmd`` look for."""
    engine = ExecEngine.docker("box")

    assert isinstance(engine, TmuxEngine)
    assert isinstance(engine, SupportsCommandLine)
    assert isinstance(engine, SupportsConnection)
    assert isinstance(engine, SupportsTmuxVersion)


@pytest.mark.parametrize(
    ("engine", "expected"),
    [
        (
            ExecEngine.docker("box"),
            ("docker", "exec", "-i", "box", "tmux", "-Lx", "list-sessions"),
        ),
        (
            ExecEngine.docker("box", user="root", tmux="/opt/tmux"),
            (
                "docker",
                "exec",
                "-i",
                "-u",
                "root",
                "box",
                "/opt/tmux",
                "-Lx",
                "list-sessions",
            ),
        ),
        (
            ExecEngine.kubectl("web-0"),
            ("kubectl", "exec", "-i", "web-0", "--", "tmux", "-Lx", "list-sessions"),
        ),
        (
            ExecEngine.kubectl("web-0", namespace="prod", container="app"),
            (
                "kubectl",
                "exec",
                "-i",
                "-n",
                "prod",
                "-c",
                "app",
                "web-0",
                "--",
                "tmux",
                "-Lx",
                "list-sessions",
            ),
        ),
        (
            ExecEngine.ssh("ci@host", options=("-p", "2222")),
            ("ssh", "-p", "2222", "ci@host", "tmux -Lx list-sessions"),
        ),
    ],
    ids=["docker", "docker-user", "kubectl", "kubectl-ns", "ssh"],
)
def test_command_lines(engine: ExecEngine, expected: tuple[str, ...]) -> None:
    """The transport prefix is fixed, and no engine ever adds ``-t``."""
    bound = engine.with_connection(ServerConnection.of(args=("-Lx",)))

    line = bound.command_line(request("list-sessions"))

    assert line == expected
    assert "-t" not in line


def test_the_object_api_runs_through_docker_exec(
    server: Server,
    shims: Shims,
) -> None:
    """``Server(engine=ExecEngine.docker(...))`` drives real tmux via the shim."""
    remote = Server(
        socket_name=server.socket_name,
        engine=ExecEngine.docker("box", user="ci"),
    )

    session = remote.new_session("over_exec", window_name="first")
    window = session.new_window(window_name="second", attach=False)
    pane = window.split()

    assert remote.has_session("over_exec")
    assert not remote.has_session("missing")
    assert sorted(w.window_name or "" for w in session.windows) == ["first", "second"]
    assert len(window.panes) == 2
    assert pane.pane_id is not None
    calls = shims.calls()
    assert calls
    for call in calls:
        assert call[:5] == ["docker", "exec", "-i", "-u", "ci"]
        assert "-t" not in call[:6]
        assert f"-L{server.socket_name}" in call


def test_kubectl_passes_argv_untouched(server: Server, shims: Shims) -> None:
    """A value with spaces and quotes survives ``kubectl exec -- argv``."""
    server.new_session("k8s")
    remote = Server(
        socket_name=server.socket_name,
        engine=ExecEngine.kubectl("web-0", namespace="prod"),
    )

    result = remote.cmd("display-message", "-p", "a b 'c' \"d\"")

    assert result.stdout == ["a b 'c' \"d\""]
    (call,) = shims.calls()
    assert call[:6] == ["kubectl", "exec", "-i", "-n", "prod", "web-0"]
    assert "--" in call


AWKWARD = [
    "plain",
    "with space",
    "semi;colon",
    "it's",
    'say "hi"',
    "dollar $HOME",
    "glob *",
    "tab\there",
    "back\\slash",
    "back`tick`",
    "café",
    "paren (x) & pipe |",
]


def stored(engine: TmuxEngine, value: str) -> tuple[bool, tuple[str, ...]]:
    """Store *value* as a user option and read it back through *engine*."""
    result = engine.run(request("set-option", "-g", "@rt", value))
    shown = engine.run(request("show-options", "-gqv", "@rt"))
    return result.ok, shown.stdout


def round_trip(server: Server, engine: ExecEngine, values: list[str]) -> list[str]:
    """Return the values the transport stored differently than a direct call.

    The reference is a plain local run, not the literal value, because tmux
    itself rewrites a few (3.4 doubles ``$``); only the transport's own damage
    is under test.
    """
    local = SubprocessEngine.for_server(server)
    return [value for value in values if stored(engine, value) != stored(local, value)]


def test_ssh_needs_shell_quoting_to_keep_awkward_values(
    server: Server,
    shims: Shims,
) -> None:
    """A transport that re-parses its argv corrupts values unless ``shell=True``."""
    server.new_session("quoting")
    flags = (f"-L{server.socket_name}",)

    quoted = ExecEngine.ssh("host", socket_args=flags)
    bare = ExecEngine.ssh("host", socket_args=flags, shell=False)

    assert round_trip(server, quoted, AWKWARD) == []
    assert len(round_trip(server, bare, AWKWARD)) == 10


def test_docker_needs_no_shell_quoting(server: Server, shims: Shims) -> None:
    """Passthrough transports keep every value as plain argv."""
    server.new_session("quoting_docker")
    engine = ExecEngine.docker("box", socket_args=(f"-L{server.socket_name}",))

    assert round_trip(server, engine, AWKWARD) == []


@pytest.mark.parametrize("kind", ["docker", "ssh"])
def test_stdin_payload_is_byte_exact_through_the_transport(
    server: Server,
    shims: Shims,
    tmp_path: pathlib.Path,
    kind: str,
) -> None:
    """``input`` reaches ``load-buffer -`` unchanged, 50 KB of every byte."""
    server.new_session("stdin_transport")
    flags = (f"-L{server.socket_name}",)
    engine = (
        ExecEngine.docker("box", socket_args=flags)
        if kind == "docker"
        else ExecEngine.ssh("host", socket_args=flags)
    )
    payload = bytes(range(256)) * 200
    saved = tmp_path / "out.bin"

    engine.run(
        request("load-buffer", "-b", "tb", "-", input=payload)
    ).raise_for_status()
    engine.run(request("save-buffer", "-b", "tb", str(saved))).raise_for_status()

    assert saved.read_bytes() == payload


class RecordingPopen(subprocess.Popen):  # type: ignore[type-arg]
    """A :class:`subprocess.Popen` that remembers every instance."""

    instances: t.ClassVar[list[RecordingPopen]] = []

    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
        super().__init__(*args, **kwargs)
        RecordingPopen.instances.append(self)


def test_timeout_kills_the_local_transport_process(
    server: Server,
    shims: Shims,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expiry kills and reaps the transport, then raises ``TmuxTimeout``."""
    server.new_session("slow_transport")
    engine = ExecEngine.docker("box", socket_args=(f"-L{server.socket_name}",))
    RecordingPopen.instances.clear()
    monkeypatch.setattr(subprocess, "Popen", RecordingPopen)

    with pytest.raises(exc.TmuxTimeout) as excinfo:
        engine.run(request("run-shell", "sleep 3", timeout=0.3))

    assert excinfo.value.cmd[:4] == ["docker", "exec", "-i", "box"]
    (transport,) = RecordingPopen.instances
    assert transport.returncode == -signal.SIGKILL
    with pytest.raises(ChildProcessError):
        os.waitpid(transport.pid, os.WNOHANG)


def test_a_missing_transport_is_an_engine_error() -> None:
    """The local program that carries the command must exist."""
    engine = ExecEngine(("no-such-transport-for-libtmux",))

    with pytest.raises(exc.EngineError, match="no-such-transport-for-libtmux"):
        engine.run(request("list-sessions"))


def test_a_tmux_failure_on_the_far_side_is_data(server: Server, shims: Shims) -> None:
    """The transport relays the exit status; nothing raises."""
    server.new_session("failing")
    engine = ExecEngine.docker("box", socket_args=(f"-L{server.socket_name}",))

    result = engine.run(request("kill-window", "-t", "@9999"))

    assert not result.ok
    assert result.stderr == ("can't find window: @9999",)


def test_the_far_side_version_is_probed_once(server: Server, shims: Shims) -> None:
    """``tmux -V`` runs through the transport, without socket flags."""
    engine = ExecEngine.docker("box", socket_args=(f"-L{server.socket_name}",))

    first = engine.tmux_version()
    second = engine.tmux_version()

    assert first == second == get_version_str()
    assert [call[-2:] for call in shims.calls()] == [["tmux", "-V"]]


def test_with_connection_keeps_the_transport_and_takes_the_socket() -> None:
    """Adoption changes the socket flags only."""
    engine = ExecEngine.ssh("host", options=("-p", "2222"))

    bound = engine.with_connection(ServerConnection.of(args=("-Lci",)))

    assert bound.prefix == engine.prefix
    assert bound.connection.args == ("-Lci",)
    assert bound.command_line(request("list-panes"))[-1] == "tmux -Lci list-panes"
    assert engine.connection.args == ()


@pytest.fixture(autouse=True)
def _no_leaked_popen_patch() -> Iterator[None]:
    """Keep the recording subclass from leaking between tests."""
    yield
    RecordingPopen.instances.clear()
