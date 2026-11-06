"""Create and find a named window. Requires tmux 3.2a+ and libtmux.

Run from the checkout: ``python examples/create_window.py``.
"""

from __future__ import annotations

import os
import pathlib
import tempfile

from libtmux import Server


def main() -> None:
    """Create a window on a private server and verify its identity and name."""
    os.environ.pop("TMUX", None)
    os.environ.pop("TMUX_PANE", None)
    with tempfile.TemporaryDirectory(prefix="lt-create-window-") as directory:
        server = Server(
            socket_path=pathlib.Path(directory) / "tmux.sock",
            config_file="/dev/null",
        )
        try:
            session = server.new_session(
                session_name="example", window_name="main", window_command="cat"
            )
            first = session.active_window
            window = session.new_window(window_name="logs", window_shell="cat")
            found = session.windows.get(window_id=window.window_id)
            assert found is not None
            assert found.window_id != first.window_id
            assert found.window_name == "logs"
            assert len(session.windows) == 2
        finally:
            server.kill()
        assert not server.is_alive()
    print("created window: logs")


if __name__ == "__main__":
    main()
