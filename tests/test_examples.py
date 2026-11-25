"""Run standalone examples unchanged and preserve an unrelated session."""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import typing as t

import pytest

from libtmux import Server

if t.TYPE_CHECKING:
    from libtmux.session import Session

EXAMPLES = pathlib.Path(__file__).parent.parent / "examples"


@pytest.mark.parametrize(
    ("script_name", "expected"),
    [
        ("create_window.py", "created window: logs"),
        ("rename_window.py", "renamed window: logs"),
        ("send_keys.py", "received: hello from libtmux"),
    ],
)
def test_standalone_example(
    script_name: str,
    expected: str,
    session: Session,
) -> None:
    """Run the same file twice, check its result, and retain another program."""
    pane = session.active_window.active_pane
    assert pane is not None
    original_pid = pane.pane_pid
    assert original_pid
    assert session.session_id is not None
    env = os.environ.copy()
    env.pop("TMUX", None)
    env.pop("TMUX_PANE", None)

    with tempfile.TemporaryDirectory(prefix="lt-examples-test-") as directory:
        root = pathlib.Path(directory)
        env["TMPDIR"] = directory
        for _ in range(2):
            try:
                result = subprocess.run(
                    [sys.executable, str(EXAMPLES / script_name)],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=1,
                    check=False,
                )
                assert result.returncode == 0, result.stdout + result.stderr
                assert result.stdout.splitlines() == [expected]
                assert not list(root.iterdir()), "example left its private directory"
                assert session.server.has_session(session.session_id)
                pane.refresh()
                assert pane.pane_pid == original_pid
                os.kill(int(original_pid), 0)
            finally:
                for socket_path in root.glob("*/tmux.sock"):
                    Server(socket_path=socket_path).kill()
