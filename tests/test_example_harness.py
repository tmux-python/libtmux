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
@pytest.mark.parametrize("fail_body", [False, True])
def test_unchanged_session_example(
    tmp_path: pathlib.Path,
    selector: str,
    fail_body: bool,
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
    example = pathlib.Path(__file__).parents[1] / "examples" / "session_scope.py"
    readme = pathlib.Path(__file__).parents[1] / "README.md"
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
            assert result.stdout.strip().startswith("$")
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
