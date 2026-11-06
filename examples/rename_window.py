"""Rename an existing window. Requires tmux 3.2a+ and libtmux.

Run from the checkout: ``python examples/rename_window.py``.
"""

from __future__ import annotations

import os
import pathlib
import tempfile

from libtmux import Server


def main() -> None:
    """Rename a private window and verify that its identity is unchanged."""
    os.environ.pop("TMUX", None)
    os.environ.pop("TMUX_PANE", None)
    with tempfile.TemporaryDirectory(prefix="lt-rename-window-") as directory:
        server = Server(
            socket_path=pathlib.Path(directory) / "tmux.sock",
            config_file="/dev/null",
        )
        try:
            session = server.new_session(
                session_name="example", window_name="main", window_command="cat"
            )
            window = session.active_window
            original_id = window.window_id
            renamed = window.rename_window("logs")
            found = session.windows.get(window_id=original_id)
            assert found is not None
            assert renamed.window_id == found.window_id == original_id
            assert found.window_name == "logs"
            assert len(session.windows) == 1
        finally:
            server.kill()
        assert not server.is_alive()
    print("renamed window: logs")


if __name__ == "__main__":
    main()
