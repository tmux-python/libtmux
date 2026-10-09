"""Captured endpoint selection and client environment contracts."""

from __future__ import annotations

import os
import pathlib
import subprocess
import typing as t

import pytest

from libtmux import Server, exc
from libtmux._internal.control_mode import ControlMode
from libtmux.pytest_plugin import _reap_test_server

if t.TYPE_CHECKING:
    from libtmux.common import tmux_cmd


def endpoint_environment(**overrides: str) -> dict[str, str]:
    """Clear selectors in the child copy without touching the host."""
    return {
        "LIBTMUX_SOCKET_PATH": "",
        "LIBTMUX_SOCKET_NAME": "",
        "TMUX": "",
        "TMUX_PANE": "",
        "TMUX_TMPDIR": "",
        **overrides,
    }


@pytest.mark.parametrize(
    ("kwargs", "environment", "expected"),
    [
        ({}, {}, f"/tmp/tmux-{os.getuid()}/default"),
        ({}, {"TMUX_TMPDIR": "/tmp/root"}, f"/tmp/root/tmux-{os.getuid()}/default"),
        ({}, {"TMUX": "/tmp/with, commas /socket,12,$3"}, "/tmp/with, commas /socket"),
        ({}, {"TMUX": "/tmp/job,12,-1"}, "/tmp/job"),
        (
            {},
            {
                "LIBTMUX_SOCKET_PATH": "/tmp/env-path",
                "LIBTMUX_SOCKET_NAME": "bad/name",
                "TMUX": "bad",
                "TMUX_TMPDIR": "bad",
            },
            "/tmp/env-path",
        ),
        (
            {},
            {"LIBTMUX_SOCKET_NAME": "env-name", "TMUX": "bad"},
            f"/tmp/tmux-{os.getuid()}/env-name",
        ),
        (
            {"socket_path": "/tmp/explicit"},
            {"LIBTMUX_SOCKET_PATH": "bad", "TMUX": "bad", "TMUX_TMPDIR": "bad"},
            "/tmp/explicit",
        ),
        (
            {"socket_name": "explicit"},
            {"LIBTMUX_SOCKET_PATH": "bad", "TMUX": "bad"},
            f"/tmp/tmux-{os.getuid()}/explicit",
        ),
        ({}, {"LIBTMUX_SOCKET_PATH": "/tmp/ spaced "}, "/tmp/ spaced "),
    ],
)
def test_endpoint_precedence(
    kwargs: dict[str, str],
    environment: dict[str, str],
    expected: str,
) -> None:
    """Resolve defaults and shadowed invalid inputs without launching tmux."""
    server = Server(
        socket_path=kwargs.get("socket_path"),
        socket_name=kwargs.get("socket_name"),
        child_environment=endpoint_environment(**environment),
    )
    assert server.socket_path == expected


@pytest.mark.parametrize(
    "kwargs",
    [
        {"socket_path": "/tmp/path", "socket_name": "name"},
        {"socket_path": "relative"},
        {"socket_path": ""},
        {"socket_path": "/tmp/bad\0path"},
        *({"socket_name": name} for name in ("", ".", "..", "a/b", "a\\b", "a\0b")),
    ],
)
def test_invalid_explicit_selectors(kwargs: dict[str, str]) -> None:
    """Reject invalid explicit inputs even when an environment fallback exists."""
    with pytest.raises(ValueError):
        Server(
            socket_path=kwargs.get("socket_path"),
            socket_name=kwargs.get("socket_name"),
            child_environment=endpoint_environment(LIBTMUX_SOCKET_PATH="/tmp/fallback"),
        )


@pytest.mark.parametrize(
    "environment",
    [
        {"LIBTMUX_SOCKET_PATH": "relative", "LIBTMUX_SOCKET_NAME": "fallback"},
        {"LIBTMUX_SOCKET_NAME": "../bad", "TMUX": "/tmp/fallback,1,0"},
        {"TMUX_TMPDIR": "relative"},
        {"TMUX_TMPDIR": "/tmp/bad\0root"},
    ],
)
def test_invalid_selected_environment(environment: dict[str, str]) -> None:
    """Report the selected invalid value instead of trying a weaker selector."""
    with pytest.raises(ValueError):
        Server(child_environment=endpoint_environment(**environment))


@pytest.mark.parametrize(
    "value",
    [
        "/tmp/sock",
        ",1,0",
        "/tmp/sock,,0",
        "/tmp/sock,0,0",
        "/tmp/sock,-1,0",
        "/tmp/sock,+1,0",
        "/tmp/sock, 1,0",
        "/tmp/sock,\uff11\uff12,0",
        "/tmp/sock,1,",
        "/tmp/sock,1,$",
        "/tmp/sock,1,$$2",
        "/tmp/sock,1,-2",
        "/tmp/sock,1,+2",
        "/tmp/sock,1, 2",
        "/tmp/sock,1,2x",
        "/tmp/sock,1,$-1",
    ],
)
def test_malformed_tmux_context(value: str) -> None:
    """Validate the selected context's numeric fields and shape."""
    with pytest.raises(exc.NotInsideTmux):
        Server(child_environment=endpoint_environment(TMUX=value))


def test_relative_tmux_path() -> None:
    """Reject a relative path even inside a shaped TMUX context."""
    with pytest.raises(ValueError):
        Server(child_environment=endpoint_environment(TMUX="relative,1,0"))


@pytest.mark.parametrize("remove_after_capture", [False, True])
def test_missing_named_root_never_falls_back(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    remove_after_capture: bool,
) -> None:
    """Block launch before tmux can choose an ambient fallback root."""
    root = tmp_path / "missing"
    if remove_after_capture:
        root.mkdir()
    server = Server(
        socket_name="libtmux_test_missing_root",
        child_environment={"TMUX_TMPDIR": str(root)},
    )
    if remove_after_capture:
        root.rmdir()

    def forbidden_launch(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        pytest.fail("missing root reached a subprocess launch")

    monkeypatch.setattr(subprocess, "Popen", forbidden_launch)
    with pytest.raises(FileNotFoundError):
        server.new_session(session_name="must_not_start")
    assert not root.exists()


def test_explicit_path_does_not_create_parent(tmp_path: pathlib.Path) -> None:
    """Leave caller-managed parents untouched for an explicit socket path."""
    parent = tmp_path / "missing"
    server = Server(socket_path=parent / "libtmux_test_explicit")
    with pytest.raises(exc.LibTmuxException):
        server.new_session(session_name="must_not_start")
    assert not parent.exists()


@pytest.mark.parametrize("mode", [0o700, 0o770, 0o775])
def test_named_directory_permissions(tmp_path: pathlib.Path, mode: int) -> None:
    """Accept tmux's group permissions while rejecting access for other users."""
    directory = tmp_path / f"tmux-{os.getuid()}"
    directory.mkdir(mode=mode)
    directory.chmod(mode)
    server = Server(
        socket_name="libtmux_test_permissions",
        child_environment={"TMUX_TMPDIR": str(tmp_path)},
    )
    if mode & 0o007:
        with pytest.raises(PermissionError):
            server._prepare_socket_directory()
    else:
        server._prepare_socket_directory()


def test_named_directory_rejects_symlink(tmp_path: pathlib.Path) -> None:
    """Keep the UID directory itself from redirecting a captured endpoint."""
    target = tmp_path / "target"
    target.mkdir()
    (tmp_path / f"tmux-{os.getuid()}").symlink_to(target)
    server = Server(
        socket_name="libtmux_test_symlink",
        child_environment={"TMUX_TMPDIR": str(tmp_path)},
    )
    with pytest.raises(PermissionError):
        server._prepare_socket_directory()


def test_endpoint_and_environment_are_captured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retain the selected path and environment after callers edit either input."""
    overrides = endpoint_environment(
        LIBTMUX_SOCKET_NAME="captured",
        TMUX_TMPDIR="/tmp/one",
        LIBTMUX_TEST_VALUE="before",
    )
    server = Server(child_environment=overrides)
    overrides["TMUX_TMPDIR"] = "/tmp/two"
    monkeypatch.setenv("TMUX_TMPDIR", "/tmp/three")
    monkeypatch.setenv("LIBTMUX_TEST_VALUE", "after")
    assert server.socket_path == f"/tmp/one/tmux-{os.getuid()}/captured"
    assert server.child_environment["TMUX_TMPDIR"] == "/tmp/one"
    assert server.child_environment["LIBTMUX_TEST_VALUE"] == "before"
    with pytest.raises(TypeError):
        t.cast("dict[str, str]", server.child_environment)["TMUX_TMPDIR"] = "/tmp/four"


def test_commands_do_not_mutate_host_environment(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Observe host and child environments at real launches, including control mode."""
    monkeypatch.setenv("TMUX", "/tmp/unrelated,42,0")
    monkeypatch.setenv("TMUX_PANE", "%42")
    before = dict(os.environ)
    actual_popen = subprocess.Popen
    launches: list[dict[str, str]] = []

    def observed_popen(*args: t.Any, **kwargs: t.Any) -> subprocess.Popen[str]:
        assert dict(os.environ) == before
        child = dict(kwargs["env"])
        assert "TMUX" not in child
        assert "TMUX_PANE" not in child
        launches.append(child)
        return actual_popen(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "Popen", observed_popen)
        with server.new_session(session_name="client_environment") as session:
            server.raise_if_dead()
            with ControlMode(server, session):
                assert server.is_alive()
    assert launches
    assert dict(os.environ) == before


def test_session_scope_cleans_renamed_id(server: Server) -> None:
    """Destroy the session after a raw rename leaves its cached name stale."""
    anchor = server.new_session(session_name="anchor")
    with server.new_session(session_name="before") as session:
        server.cmd("rename-session", "after", target=session.session_id)
    assert [item.session_id for item in server.sessions] == [anchor.session_id]


def test_session_scope_tolerates_prior_destruction(server: Server) -> None:
    """Permit repeated cleanup while another session keeps the server alive."""
    server.new_session(session_name="anchor")
    with server.new_session(session_name="discard") as session:
        session.kill()
    session.__exit__(None, None, None)


@pytest.mark.parametrize(
    "body_error", [RuntimeError("body failed"), KeyboardInterrupt(), SystemExit(3)]
)
def test_scope_preserves_body_and_cleanup_failure(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
    body_error: BaseException,
) -> None:
    """Inject a teardown failure because a healthy private daemon cannot cause it."""
    session = server.new_session(session_name="dual_failure")
    cleanup_error = PermissionError("cleanup denied")

    command = server.cmd

    def failed_cleanup(cmd: str, *args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        if cmd == "if-shell" and any(
            str(arg).startswith("kill-session ") for arg in args
        ):
            raise cleanup_error
        return command(cmd, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(server, "cmd", failed_cleanup)
        with pytest.raises(BaseExceptionGroup) as caught, session:
            raise body_error
    assert caught.value.exceptions == (body_error, cleanup_error)
    monkeypatch.setattr(session._scope_owner._client, "cmd", command)
    session.__exit__(None, None, None)


def test_factory_custom_path_finalizer(
    request: pytest.FixtureRequest,
    tmp_path: pathlib.Path,
) -> None:
    """Verify the factory cleans its custom path after the test body exits."""
    path = tmp_path / "libtmux_test_factory"

    def check_finalization() -> None:
        assert not path.exists()
        assert not Server(socket_path=path).is_alive()

    request.addfinalizer(check_finalization)
    factory = request.getfixturevalue("TestServer")
    server = factory(socket_path=path, config_file="/dev/null")
    server.new_session(session_name="owned")
    assert server.is_alive()


def test_reaper_retains_exact_endpoint(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep finalization at the original root after a host environment change."""
    server = Server(
        socket_name="libtmux_test_capture",
        config_file="/dev/null",
        child_environment={"TMUX_TMPDIR": str(tmp_path)},
    )
    server.new_session(session_name="owned")
    try:
        monkeypatch.setenv("TMUX_TMPDIR", str(tmp_path / "other"))
        _reap_test_server(server)
        assert not pathlib.Path(server.socket_path).exists()
        assert not server.is_alive()
    finally:
        server.kill()


def test_reaper_exposes_cleanup_failure(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expose a failed cleanup instead of suppressing or unlinking its socket."""
    server = Server(socket_path=tmp_path / "libtmux_test_denied")

    def fail(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        message = "cleanup denied"
        raise PermissionError(message)

    monkeypatch.setattr(subprocess, "Popen", fail)
    with pytest.raises(PermissionError, match="cleanup denied"):
        _reap_test_server(server)
