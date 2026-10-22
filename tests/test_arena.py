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
TWO_PAGE_ARTIFACT = "python-workspace-and-location"
FIRST_PAGE = "docs/topics/workspace_setup.md"
SECOND_PAGE = "docs/topics/self_location.md"
# Must match conftest.py's ARENA_IDENTITY_FORMAT exactly -- the format string
# the between-page identity check sends to `display-message`.
ARENA_IDENTITY_PROBE = "#{pid}\t#{socket_path}\t#{@libtmux_arena_challenge}"


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


def _stop_after_first_page_wrapper(
    tmp_path: pathlib.Path,
    tmux_bin: str,
    marker: str,
) -> pathlib.Path:
    """Build a wrapper that kills the real server partway through a run.

    Trips on the *second* time it sees the between-page identity probe
    (``marker``): the first is the baseline captured before any page runs,
    the second is the check right after the first page finishes. That is
    exactly where a doctest example stopping the lent server -- as
    ``with Server()`` does in the excluded ``context_managers.md`` -- would
    land, reproduced here without needing to run that page. The probing
    command itself is then allowed to reach the now-dead socket and fail.
    """
    counter = tmp_path / "probe-count"
    wrapper = tmp_path / "stop-after-first-page-tmux"
    wrapper.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "import subprocess\n"
        "import sys\n"
        f"tmux_bin = {tmux_bin!r}\n"
        f"marker = {marker!r}\n"
        f"counter = {str(counter)!r}\n"
        "args = sys.argv[1:]\n"
        "if marker in args:\n"
        "    seen = 0\n"
        "    if os.path.exists(counter):\n"
        "        with open(counter, encoding='utf-8') as fh:\n"
        "            seen = int(fh.read())\n"
        "    seen += 1\n"
        "    with open(counter, 'w', encoding='utf-8') as fh:\n"
        "        fh.write(str(seen))\n"
        "    if seen == 2:\n"
        "        socket_arg = next(a for a in args if a.startswith('-S'))\n"
        "        subprocess.run([tmux_bin, socket_arg, 'kill-server'])\n"
        "os.execv(tmux_bin, [tmux_bin, *args])\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return wrapper


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
    assert spec.targets_for(pathlib.Path("/repo")) == (
        pathlib.Path("/repo/docs/topics/workspace_setup.md"),
    )


def test_an_artifact_may_bind_several_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One lend can audit more than one page, and every page is required.

    The supervisor takes one evidence record per declared source, so an
    artifact that names two pages and runs one is a failure rather than a
    partial pass.
    """
    arena = importlib.import_module("libtmux._arena")
    monkeypatch.setitem(
        arena.ARENA_ARTIFACT_TARGETS,
        "python-two-pages",
        ("docs/topics/workspace_setup.md", "docs/topics/traversal.md"),
    )
    spec = arena.ArenaSpec.from_environ(
        {
            "LIBTMUX_ARENA_DESCRIPTOR": "arena",
            "LIBTMUX_ARENA_ARTIFACT": "python-two-pages",
            "LIBTMUX_SOCKET_PATH": "socket",
            "LIBTMUX_TMUX_BIN": "tmux",
        }
    )

    assert spec is not None
    assert spec.targets_for(pathlib.Path("/repo")) == (
        pathlib.Path("/repo/docs/topics/workspace_setup.md"),
        pathlib.Path("/repo/docs/topics/traversal.md"),
    )


def test_wiring_an_excluded_source_to_an_artifact_is_refused() -> None:
    """The static wiring guard is a real check: it can fail, not just decorate.

    ``context_managers.md`` stops the lent server through `with Server()`
    (its `Server` name resolves to a factory pinned to the arena socket in
    arena mode, so exiting the block runs `kill-server` against the
    borrowed daemon). An artifact tuple can never bind it -- this proves
    the guard actually rejects such a mapping rather than always agreeing.
    """
    arena = importlib.import_module("libtmux._arena")
    conflicting = dict(arena.ARENA_ARTIFACT_TARGETS)
    conflicting["python-broken"] = (next(iter(arena.ARENA_EXCLUDED_SOURCES)),)

    with pytest.raises(AssertionError):
        arena._assert_no_excluded_targets(conflicting)


def test_the_committed_artifact_wiring_passes_the_same_guard() -> None:
    """Control: today's real ARENA_ARTIFACT_TARGETS never trips the guard."""
    arena = importlib.import_module("libtmux._arena")

    arena._assert_no_excluded_targets(arena.ARENA_ARTIFACT_TARGETS)


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


def test_arena_refuses_a_source_known_to_stop_the_server(
    TestServer: t.Callable[..., Server],
) -> None:
    """An excluded source is refused by name, not merely absent from a tuple.

    A generic "artifact requires {...}" mismatch would look identical to a
    typo from the outside. Requesting the excluded page proves the specific,
    named reason fires instead -- before tmux is even touched.
    """
    endpoint = _external_endpoint(TestServer)
    tmux_bin = shutil.which("tmux")
    assert tmux_bin is not None
    excluded = "docs/topics/context_managers.md"
    result = _run_arena(
        _arena_environ(endpoint, tmux_bin),
        "--libtmux-arena-target",
        excluded,
        excluded,
    )

    assert result.returncode == 4
    combined = result.stdout + result.stderr
    assert excluded in combined
    arena = importlib.import_module("libtmux._arena")
    assert arena.ARENA_EXCLUDED_SOURCES[excluded] in combined
    assert "LIBTMUX_ARENA_EVIDENCE=" not in result.stdout
    _assert_only_hold(endpoint)


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


def test_arena_runs_two_pages_and_proves_identity_between_them(
    TestServer: t.Callable[..., Server],
) -> None:
    """A real multi-page artifact reaps only what it left, one record per page.

    Passing control for the destructive test below. ``self_location.md``
    creates sessions it never kills (``elsewhere``, ``aaa-home``,
    ``zzz-guest``) -- the same kind of stray the borrowed six-page run this
    artifact is modeled on found (there: ``97``, ``foo``, ``guest``,
    ``home``). Teardown must reap them and leave the endpoint's own hold
    session untouched, and both evidence records must show the same server
    identity.
    """
    endpoint = _external_endpoint(TestServer)
    tmux_bin = shutil.which("tmux")
    assert tmux_bin is not None
    environ = os.environ | {
        "LIBTMUX_ARENA_DESCRIPTOR": "arena",
        "LIBTMUX_ARENA_ARTIFACT": TWO_PAGE_ARTIFACT,
        "LIBTMUX_SOCKET_PATH": endpoint.socket_path,
        "LIBTMUX_TMUX_BIN": tmux_bin,
    }
    result = _run_arena(
        environ,
        "--libtmux-arena-target",
        FIRST_PAGE,
        "--libtmux-arena-target",
        SECOND_PAGE,
        FIRST_PAGE,
        SECOND_PAGE,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    evidence = [
        json.loads(line.removeprefix("LIBTMUX_ARENA_EVIDENCE="))
        for line in result.stdout.splitlines()
        if line.startswith("LIBTMUX_ARENA_EVIDENCE=")
    ]
    assert {record["source"] for record in evidence} == {FIRST_PAGE, SECOND_PAGE}
    assert len({record["server_pid"] for record in evidence}) == 1
    assert len({record["challenge"] for record in evidence}) == 1
    _assert_only_hold(endpoint)


def test_arena_rejects_a_server_that_stops_between_pages(
    TestServer: t.Callable[..., Server],
    tmp_path: pathlib.Path,
) -> None:
    """A server stopped between pages is rejected and names the page.

    Negative test for the between-page identity check: without it, a run
    like this would keep going -- and publish evidence -- against whatever
    silently answered after the break, exactly the "later call silently
    started a replacement with no challenge set" failure mode the excluded
    ``context_managers.md`` produces via ``with Server()``. The wrapper
    stops the real server the moment the check runs for the first page,
    without needing to run that excluded page to prove it.
    """
    endpoint = _external_endpoint(TestServer)
    tmux_bin = shutil.which("tmux")
    assert tmux_bin is not None
    wrapper = _stop_after_first_page_wrapper(tmp_path, tmux_bin, ARENA_IDENTITY_PROBE)
    environ = os.environ | {
        "LIBTMUX_ARENA_DESCRIPTOR": "arena",
        "LIBTMUX_ARENA_ARTIFACT": TWO_PAGE_ARTIFACT,
        "LIBTMUX_SOCKET_PATH": endpoint.socket_path,
        "LIBTMUX_TMUX_BIN": str(wrapper),
    }
    result = _run_arena(
        environ,
        "--libtmux-arena-target",
        FIRST_PAGE,
        "--libtmux-arena-target",
        SECOND_PAGE,
        FIRST_PAGE,
        SECOND_PAGE,
    )

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "LIBTMUX_ARENA_EVIDENCE=" not in result.stdout
    assert FIRST_PAGE in combined
    assert "identity" in combined.lower()
    # The original endpoint (hold session included) is gone by design -- the
    # wrapper's whole point is simulating that it got stopped. What answers
    # the socket afterwards, if anything, is cleaned up by TestServer's own
    # finalizer (`_reap_test_server`), which kills by socket name regardless
    # of which daemon currently answers there.
