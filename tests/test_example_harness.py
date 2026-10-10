"""Run the ordinary example unchanged with an external private endpoint."""

from __future__ import annotations

import os
import pathlib
import select
import subprocess
import sys

import pytest

from libtmux import Server
from libtmux.pytest_plugin import _reap_test_server
from libtmux.test.retry import retry_until


@pytest.mark.parametrize("selector", ["path", "name"])
@pytest.mark.parametrize("server_state", ["absent", "running"])
@pytest.mark.parametrize("fail_body", [False, True])
def test_ordinary_workspace_uses_external_defaults_and_leaves_its_objects(
    tmp_path: pathlib.Path,
    selector: str,
    server_state: str,
    fail_body: bool,
) -> None:
    """Run the displayed program with either daemon state and retain its work."""
    before = dict(os.environ)
    child = dict(
        before,
        TMUX_TMPDIR=str(tmp_path),
        LIBTMUX_SOCKET_PATH="",
        LIBTMUX_SOCKET_NAME="",
        TMUX="/tmp/ignored,42,0",
        TMUX_PANE="%42",
    )
    child["LIBTMUX_SOCKET_" + selector.upper()] = (
        str(tmp_path / "libtmux_test_workspace.sock")
        if selector == "path"
        else "libtmux_test_workspace"
    )
    server = Server(child_environment=child)
    example = pathlib.Path(__file__).parents[1] / "examples" / "workspace.py"
    readme = pathlib.Path(__file__).parents[1] / "README.md"
    assert f"```python\n{example.read_text()}```" in readme.read_text()
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    pid_fd = None
    pid = None
    anchor = None
    try:
        if server_state == "running":
            anchor = server.new_session("harness_anchor", window_command="sleep 60")
            server.cmd("set-option", "-s", "exit-empty", "on")
            server.cmd("set-option", "-g", "status", "off")
            server.cmd("set-option", "-s", "@existing-work", "preserve-this")
            initial_pid = server.cmd("display-message", "-p", "#{pid}").stdout[0]
        else:
            assert not server.is_alive()
            assert not pathlib.Path(server.socket_path).exists()
        output = None
        for _ in range(1 if fail_body else 2):
            result = subprocess.run(
                [sys.executable, str(example)],
                env=child,
                text=True,
                check=False,
                timeout=20,
                stdout=write_fd if fail_body else subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if fail_body:
                assert result.returncode != 0
                assert "BrokenPipeError" in result.stderr
            else:
                assert result.returncode == 0, result.stderr
                assert result.stdout.strip().startswith("libtmux-example work %")
                if output is not None:
                    assert result.stdout == output
                output = result.stdout
        pid = int(server.cmd("display-message", "-p", "#{pid}").stdout[0])
        if hasattr(os, "pidfd_open"):
            pid_fd = os.pidfd_open(pid)
        session = server.sessions.get(session_name="libtmux-example")
        assert session is not None
        assert session.windows.get(window_name="work") is not None
        if anchor is not None:
            assert str(pid) == initial_pid
            assert anchor.session_id is not None
            assert server.has_session(anchor.session_id)
            assert server.cmd("show-options", "-sqv", "exit-empty").stdout == ["on"]
            assert server.cmd("show-options", "-gqv", "status").stdout == ["off"]
            assert server.cmd("show-options", "-sqv", "@existing-work").stdout == [
                "preserve-this"
            ]
        assert dict(os.environ) == before
    finally:
        os.close(write_fd)
        try:
            _reap_test_server(server)
            if pid_fd is not None:
                poller = select.poll()
                poller.register(pid_fd, select.POLLIN)
                assert any(events & select.POLLIN for _, events in poller.poll(5000))
            elif pid is not None:

                def process_exited() -> bool:
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        return True
                    return False

                retry_until(process_exited, seconds=5)
                assert process_exited()
            assert not pathlib.Path(server.socket_path).exists()
        finally:
            if pid_fd is not None:
                os.close(pid_fd)


@pytest.mark.parametrize(
    ("example_name", "document", "id_prefix"),
    [
        ("session_scope.py", "README.md", "$"),
        ("find_or_create.py", "docs/topics/context_managers.md", "%"),
    ],
)
@pytest.mark.parametrize("selector", ["path", "name"])
@pytest.mark.parametrize("fail_body", [False, True])
def test_unchanged_session_example(
    tmp_path: pathlib.Path,
    selector: str,
    fail_body: bool,
    example_name: str,
    document: str,
    id_prefix: str,
) -> None:
    """Redirect the same program and force body failure through a closed pipe."""
    before = dict(os.environ)
    child = dict(
        before,
        TMUX_TMPDIR=str(tmp_path),
        LIBTMUX_SOCKET_PATH="",
        LIBTMUX_SOCKET_NAME="",
    )
    if selector == "path":
        child["LIBTMUX_SOCKET_PATH"] = str(tmp_path / "libtmux_test_example.sock")
    else:
        child["LIBTMUX_SOCKET_NAME"] = "libtmux_test_example"
    child["TMUX"] = "/tmp/ignored,42,0"
    child["TMUX_PANE"] = "%42"
    server = Server(config_file="/dev/null", child_environment=child)
    example = pathlib.Path(__file__).parents[1] / "examples" / example_name
    readme = pathlib.Path(__file__).parents[1] / document
    assert f"```python\n{example.read_text()}```" in readme.read_text()
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    pid_fd = None
    pid = None
    try:
        anchor = server.new_session(
            session_name="harness_anchor", window_command="sleep 60"
        )
        pid = int(server.cmd("display-message", "-p", "#{pid}").stdout[0])
        if hasattr(os, "pidfd_open"):
            pid_fd = os.pidfd_open(pid)
        command = [sys.executable, str(example)]
        result = subprocess.run(
            command,
            env=child,
            text=True,
            check=False,
            timeout=20,
            stdout=write_fd if fail_body else subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if fail_body:
            assert result.returncode != 0
            assert "BrokenPipeError" in result.stderr
        else:
            assert result.returncode == 0, result.stderr
            assert result.stdout.strip().startswith(id_prefix)
            assert result.stdout.strip() != anchor.session_id
        assert [session.session_id for session in server.sessions] == [
            anchor.session_id
        ]
        assert dict(os.environ) == before
    finally:
        os.close(write_fd)
        try:
            _reap_test_server(server)
            if pid_fd is not None:
                poller = select.poll()
                poller.register(pid_fd, select.POLLIN)
                assert any(events & select.POLLIN for _, events in poller.poll(5000))
            elif pid is not None:

                def process_exited() -> bool:
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        return True
                    return False

                retry_until(process_exited, seconds=5)
                assert process_exited()
            result_after = server.cmd("list-sessions")
            assert result_after.returncode != 0
            assert any(
                "No such file or directory" in line or "no server running" in line
                for line in result_after.stderr
            )
            assert not pathlib.Path(server.socket_path).exists()
        finally:
            if pid_fd is not None:
                os.close(pid_fd)
