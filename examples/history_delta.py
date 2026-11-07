"""Read repeated retained rows. Requires tmux 3.8+, libtmux, and POSIX cat.

Run: ``python examples/history_delta.py``.
The empty pane accepts deterministic native input; no program-exit claim is made.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile

from libtmux import Pane, Server


def main() -> None:
    """Distinguish ordinary history eviction from an unread collection gap."""
    os.environ.pop("TMUX", None)
    os.environ.pop("TMUX_PANE", None)
    binary = shutil.which("tmux")
    assert binary is not None, "tmux must be on PATH"
    with tempfile.TemporaryDirectory(prefix="lt-history-") as directory:
        socket = pathlib.Path(directory) / "tmux.sock"
        server = Server(socket_path=socket, config_file="/dev/null", tmux_bin=binary)
        try:
            session = server.new_session(session_name="history", window_command="cat")
            session.set_option("history-limit", 5)
            pane_id = session.cmd("new-window", "-d", "-P", "-F#{pane_id}", "").stdout[
                0
            ]
            pane = Pane.from_pane_id(server, pane_id)
            pane.window.resize(width=20, height=5)

            def write(count: int) -> None:
                subprocess.run(
                    [binary, "-S", str(socket), "display-message", "-I", "-t", pane_id],
                    input="same\r\n" * count,
                    text=True,
                    capture_output=True,
                    check=True,
                    timeout=0.5,
                )

            write(64)
            first = pane.capture_since()
            assert (first.status, first.reason) == ("reset", "initial")
            write(2)
            second = pane.capture_since(first.cursor)
            assert second.status == "continuous"
            assert second.lines == ("same", "same")
            write(64)
            third = pane.capture_since(second.cursor)
            assert third.status == "gap"
            assert third.lines == ("same",) * 5
        finally:
            server.kill()
        assert not server.is_alive()
    print("continuous: 2 rows; gap: 5 retained rows")


if __name__ == "__main__":
    main()
