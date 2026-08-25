"""Tests for the arena doctest adapter."""

from __future__ import annotations

import dataclasses
import importlib
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import typing as t

import pytest

from libtmux.server import Server

ROOT = pathlib.Path(__file__).parents[1]
TARGET = "docs/topics/workspace_setup.md"


@dataclasses.dataclass(frozen=True)
class ArenaEndpoint:
    """Retain an externally owned tmux server and its hold session."""

    server: Server
    hold_name: str
    socket_path: str
    challenge: str | None


def _external_endpoint(
    TestServer: t.Callable[..., Server],
    *,
    hold_name: str = "arena-hold",
    challenge: str | None = "arena-challenge",
) -> ArenaEndpoint:
    """Start one external tmux daemon that the adapter must not own."""
    server = TestServer()
    server.new_session(session_name=hold_name)
    socket_path = server.cmd("display-message", "-p", "#{socket_path}").stdout[0]
    if challenge is not None:
        server.cmd("set-option", "-g", "@libtmux_arena_challenge", challenge)
    return ArenaEndpoint(server, hold_name, socket_path, challenge)


def _arena_environ(endpoint: ArenaEndpoint, tmux_bin: str) -> dict[str, str]:
    """Build the complete activated environment for one external endpoint."""
    return os.environ | {
        "LIBTMUX_ARENA_DESCRIPTOR": "arena",
        "LIBTMUX_ARENA_ARTIFACT": "python-exact-binary",
        "LIBTMUX_SOCKET_PATH": endpoint.socket_path,
        "LIBTMUX_TMUX_BIN": tmux_bin,
    }


def _run_arena(
    environ: dict[str, str], *arguments: str
) -> subprocess.CompletedProcess[str]:
    """Run the native pytest entrypoint with the supplied arena selection."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--reruns=0", *arguments],
        capture_output=True,
        check=False,
        cwd=ROOT,
        env=environ,
        text=True,
    )


def _assert_only_hold(endpoint: ArenaEndpoint) -> None:
    """Assert the adapter did not own or retain the external daemon state."""
    assert endpoint.server.is_alive()
    assert [session.session_name for session in endpoint.server.sessions] == [
        endpoint.hold_name
    ]


def _remove_adapter_sessions(endpoint: ArenaEndpoint) -> None:
    """Remove only sessions that a failed adapter run could have created."""
    for session in endpoint.server.sessions:
        session_name = session.session_name
        if session_name is not None and session_name != endpoint.hold_name:
            endpoint.server.kill_session(session_name)


def _failing_tmux_wrapper(
    tmp_path: pathlib.Path,
    tmux_bin: str,
    rejected_command: str,
) -> tuple[pathlib.Path, pathlib.Path]:
    """Create a wrapper that logs every invocation and fails one subcommand."""
    wrapper = tmp_path / f"fail-{rejected_command}-tmux"
    invocation_log = tmp_path / "tmux-invocations"
    wrapper.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "import sys\n"
        f"with open({str(invocation_log)!r}, 'a', encoding='utf-8') as stream:\n"
        "    print(sys.argv[1:], file=stream)\n"
        f"if {rejected_command!r} in sys.argv:\n"
        "    raise SystemExit(1)\n"
        f"os.execv({tmux_bin!r}, [{tmux_bin!r}, *sys.argv[1:]])\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return wrapper, invocation_log


def test_descriptor_is_the_only_arena_activation_switch() -> None:
    """An alias without a descriptor preserves the ordinary doctest path."""
    arena = importlib.import_module("libtmux._arena")

    assert (
        arena.ArenaSpec.from_environ({"LIBTMUX_ARENA_ARTIFACT": "python-exact-binary"})
        is None
    )
    assert (
        arena.ArenaSpec.from_environ(
            {
                "LIBTMUX_ARENA_DESCRIPTOR": "",
                "LIBTMUX_ARENA_ARTIFACT": "python-exact-binary",
                "LIBTMUX_SOCKET_PATH": "socket",
                "LIBTMUX_TMUX_BIN": "tmux",
            }
        )
        is None
    )


@pytest.mark.parametrize(
    "environ",
    [
        {"LIBTMUX_ARENA_DESCRIPTOR": "arena"},
        {
            "LIBTMUX_ARENA_DESCRIPTOR": "arena",
            "LIBTMUX_ARENA_ARTIFACT": "",
            "LIBTMUX_SOCKET_PATH": "socket",
            "LIBTMUX_TMUX_BIN": "tmux",
        },
        {
            "LIBTMUX_ARENA_DESCRIPTOR": "arena",
            "LIBTMUX_ARENA_ARTIFACT": "python-exact-binary",
            "LIBTMUX_SOCKET_PATH": "",
            "LIBTMUX_TMUX_BIN": "tmux",
        },
        {
            "LIBTMUX_ARENA_DESCRIPTOR": "arena",
            "LIBTMUX_ARENA_ARTIFACT": "python-exact-binary",
            "LIBTMUX_SOCKET_PATH": "socket",
            "LIBTMUX_TMUX_BIN": "",
        },
        {
            "LIBTMUX_ARENA_DESCRIPTOR": "arena",
            "LIBTMUX_ARENA_ARTIFACT": "wrong-artifact",
            "LIBTMUX_SOCKET_PATH": "socket",
            "LIBTMUX_TMUX_BIN": "tmux",
        },
    ],
)
def test_activated_contract_rejects_empty_or_unknown_values(
    environ: dict[str, str],
) -> None:
    """An incomplete contract cannot fall through to ambient tmux."""
    arena = importlib.import_module("libtmux._arena")

    with pytest.raises(ValueError):
        arena.ArenaSpec.from_environ(environ)


@pytest.mark.parametrize("artifact", ["python-exact-binary", "python-workspace-setup"])
def test_artifact_requires_the_workspace_setup_source(
    artifact: str,
) -> None:
    """Both audited artifacts bind evidence to the one documented source."""
    arena = importlib.import_module("libtmux._arena")
    spec = arena.ArenaSpec.from_environ(
        {
            "LIBTMUX_ARENA_DESCRIPTOR": "arena",
            "LIBTMUX_ARENA_ARTIFACT": artifact,
            "LIBTMUX_SOCKET_PATH": "socket",
            "LIBTMUX_TMUX_BIN": "tmux",
        }
    )

    assert spec is not None
    assert spec.target_for(pathlib.Path("/repo")) == pathlib.Path(
        "/repo/docs/topics/workspace_setup.md"
    )


@pytest.mark.parametrize(
    ("artifact", "target"),
    [
        ("", "docs/topics/workspace_setup.md"),
        ("unknown", "docs/topics/workspace_setup.md"),
        ("python-exact-binary", "README.md"),
    ],
)
def test_activated_pytest_rejects_invalid_contract_before_talking_to_tmux(
    artifact: str,
    target: str,
    tmp_path: pathlib.Path,
) -> None:
    """Bad activation input cannot reach a default or external server."""
    invocation_log = tmp_path / "tmux-invocations"
    wrapper = tmp_path / "tmux"
    wrapper.write_text(
        f"#!/bin/sh\nprintf invoked >> {shlex.quote(str(invocation_log))}\nexit 1\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    environ = os.environ | {
        "LIBTMUX_ARENA_DESCRIPTOR": "arena",
        "LIBTMUX_ARENA_ARTIFACT": artifact,
        "LIBTMUX_SOCKET_PATH": "/not-a-tmux-socket",
        "LIBTMUX_TMUX_BIN": str(wrapper),
    }

    result = _run_arena(environ, "--libtmux-arena-target", target, target)

    assert result.returncode == 4
    assert not invocation_log.exists()
    assert "LIBTMUX_ARENA_EVIDENCE=" not in result.stdout


def test_arena_runs_the_exact_doctest_on_an_external_server(
    TestServer: t.Callable[..., Server],
    tmp_path: pathlib.Path,
) -> None:
    """The selected page owns sessions without taking the external daemon."""
    endpoint = _external_endpoint(TestServer)
    assert endpoint.challenge is not None
    tmux_bin = shutil.which("tmux")
    assert tmux_bin is not None
    invocation_log = tmp_path / "tmux-invocations"
    wrapper = tmp_path / "exact-tmux"
    wrapper.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$@\" >> {shlex.quote(str(invocation_log))}\n"
        f'exec {shlex.quote(tmux_bin)} "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    result = _run_arena(
        _arena_environ(endpoint, str(wrapper)),
        "--libtmux-arena-target",
        TARGET,
        TARGET,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    evidence_lines = [
        line.removeprefix("LIBTMUX_ARENA_EVIDENCE=")
        for line in result.stdout.splitlines()
        if line.startswith("LIBTMUX_ARENA_EVIDENCE=")
    ]
    assert len(evidence_lines) == 1
    evidence = json.loads(evidence_lines[0])
    assert evidence == {
        "artifact": "python-exact-binary",
        "challenge": endpoint.challenge,
        "schema": 1,
        "server_pid": int(
            endpoint.server.cmd("display-message", "-p", "#{pid}").stdout[0]
        ),
        "socket_path": endpoint.socket_path,
        "source": TARGET,
    }
    assert invocation_log.read_text(encoding="utf-8")
    _assert_only_hold(endpoint)


def test_arena_rejects_a_deselected_doctest_subset(
    TestServer: t.Callable[..., Server],
) -> None:
    """A passing subset cannot produce evidence for the complete source."""
    endpoint = _external_endpoint(TestServer)
    tmux_bin = shutil.which("tmux")
    assert tmux_bin is not None
    result = _run_arena(
        _arena_environ(endpoint, tmux_bin),
        "--libtmux-arena-target",
        TARGET,
        "-k",
        "0",
        TARGET,
    )

    assert result.returncode == 4
    assert "LIBTMUX_ARENA_EVIDENCE=" not in result.stdout
    _assert_only_hold(endpoint)


def test_arena_rejects_a_deselected_second_source(
    TestServer: t.Callable[..., Server],
) -> None:
    """A filtered second source cannot disappear from collection proof."""
    endpoint = _external_endpoint(TestServer)
    tmux_bin = shutil.which("tmux")
    assert tmux_bin is not None
    result = _run_arena(
        _arena_environ(endpoint, tmux_bin),
        "--libtmux-arena-target",
        TARGET,
        "-k",
        "workspace_setup",
        TARGET,
        "README.md",
    )

    assert result.returncode == 4
    assert "LIBTMUX_ARENA_EVIDENCE=" not in result.stdout
    _assert_only_hold(endpoint)


def test_arena_rejects_an_external_server_without_a_challenge(
    TestServer: t.Callable[..., Server],
) -> None:
    """A successful doctest run cannot publish an empty challenge."""
    endpoint = _external_endpoint(TestServer, challenge=None)
    tmux_bin = shutil.which("tmux")
    assert tmux_bin is not None
    result = _run_arena(
        _arena_environ(endpoint, tmux_bin),
        "--libtmux-arena-target",
        TARGET,
        TARGET,
    )

    assert result.returncode != 0
    assert "LIBTMUX_ARENA_EVIDENCE=" not in result.stdout
    _assert_only_hold(endpoint)


def test_arena_rejects_a_wrapper_redirected_socket(
    TestServer: t.Callable[..., Server],
    tmp_path: pathlib.Path,
) -> None:
    """Evidence cannot name a socket different from the requested endpoint."""
    expected = _external_endpoint(TestServer, hold_name="arena-expected-hold")
    alternate = _external_endpoint(TestServer, hold_name="arena-alternate-hold")
    tmux_bin = shutil.which("tmux")
    assert tmux_bin is not None
    wrapper = tmp_path / "redirect-tmux"
    wrapper.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "import sys\n"
        f"alternate_socket = {alternate.socket_path!r}\n"
        "arguments = sys.argv[1:]\n"
        "for index, argument in enumerate(arguments):\n"
        "    if argument == '-S':\n"
        "        arguments[index + 1] = alternate_socket\n"
        "    elif argument.startswith('-S'):\n"
        "        arguments[index] = '-S' + alternate_socket\n"
        f"os.execv({tmux_bin!r}, [{tmux_bin!r}, *arguments])\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    result = _run_arena(
        _arena_environ(expected, str(wrapper)),
        "--libtmux-arena-target",
        TARGET,
        TARGET,
    )

    assert result.returncode != 0
    assert "LIBTMUX_ARENA_EVIDENCE=" not in result.stdout
    _assert_only_hold(expected)
    _assert_only_hold(alternate)


def test_arena_does_not_publish_evidence_after_session_cleanup_fails(
    TestServer: t.Callable[..., Server],
    tmp_path: pathlib.Path,
) -> None:
    """A failed adapter cleanup fails the run instead of hiding a leaked session."""
    endpoint = _external_endpoint(TestServer)
    tmux_bin = shutil.which("tmux")
    assert tmux_bin is not None
    wrapper, invocation_log = _failing_tmux_wrapper(tmp_path, tmux_bin, "kill-session")
    try:
        result = _run_arena(
            _arena_environ(endpoint, str(wrapper)),
            "--libtmux-arena-target",
            TARGET,
            TARGET,
        )

        assert result.returncode != 0
        assert "LIBTMUX_ARENA_EVIDENCE=" not in result.stdout
        assert "kill-session" in invocation_log.read_text(encoding="utf-8")
    finally:
        _remove_adapter_sessions(endpoint)

    _assert_only_hold(endpoint)


def test_arena_cleanup_does_not_treat_a_failed_probe_as_an_absent_session(
    TestServer: t.Callable[..., Server],
    tmp_path: pathlib.Path,
) -> None:
    """The adapter cleans its session without a lenient existence probe."""
    endpoint = _external_endpoint(TestServer)
    tmux_bin = shutil.which("tmux")
    assert tmux_bin is not None
    wrapper, invocation_log = _failing_tmux_wrapper(tmp_path, tmux_bin, "has-session")
    try:
        result = _run_arena(
            _arena_environ(endpoint, str(wrapper)),
            "--libtmux-arena-target",
            TARGET,
            TARGET,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "LIBTMUX_ARENA_EVIDENCE=" in result.stdout
        assert "has-session" in invocation_log.read_text(encoding="utf-8")
        assert [
            session.session_name
            for session in endpoint.server.sessions
            if session.session_name != endpoint.hold_name
        ] == []
    finally:
        _remove_adapter_sessions(endpoint)

    _assert_only_hold(endpoint)
