"""Send text to a pane reader. Requires tmux 3.2a+, a POSIX shell, and libtmux.

Run from the checkout: ``python examples/send_keys.py``.
The reader acknowledges input; this does not demonstrate process exit.
"""

from __future__ import annotations

import os
import pathlib
import shlex
import shutil
import tempfile
import threading

from libtmux import Server


def _wait_for_signal(server: Server, channel: str) -> None:
    """Bound this example's ordinary channel wait using its private server."""
    errors: list[BaseException] = []

    def wait() -> None:
        try:
            server.wait_for(channel)
        except BaseException as error:  # noqa: BLE001 - re-raised in the calling thread
            errors.append(error)

    waiter = threading.Thread(target=wait)
    waiter.start()
    waiter.join(timeout=1)
    if waiter.is_alive():
        server.kill()
        waiter.join(timeout=1)
        msg = f"Reader did not signal {channel!r}"
        raise TimeoutError(msg)
    if errors:
        raise errors[0]


def main() -> None:
    """Wait for the reader, send a line, and verify its captured response."""
    os.environ.pop("TMUX", None)
    os.environ.pop("TMUX_PANE", None)
    tmux_bin = shutil.which("tmux")
    assert tmux_bin is not None, "tmux must be installed on PATH"
    with tempfile.TemporaryDirectory(prefix="lt-send-keys-") as directory:
        socket_path = pathlib.Path(directory) / "tmux.sock"
        server = Server(
            socket_path=socket_path, config_file="/dev/null", tmux_bin=tmux_bin
        )
        tmux = shlex.join([tmux_bin, "-S", str(socket_path)])
        reader = (
            "stty -echo && "
            f"{tmux} wait-for -S input-ready && "
            "while IFS= read -r line; do "
            "printf 'received: %s\\n' \"$line\"; "
            f"{tmux} wait-for -S input-received; "
            "done"
        )
        try:
            session = server.new_session(
                session_name="example", window_command=f"sh -c {shlex.quote(reader)}"
            )
            pane = session.active_window.active_pane
            assert pane is not None
            _wait_for_signal(server, "input-ready")
            pane.send_keys("hello from libtmux", literal=True)
            _wait_for_signal(server, "input-received")
            assert "received: hello from libtmux" in pane.capture_pane()
        finally:
            server.kill()
        assert not server.is_alive()
    print("received: hello from libtmux")


if __name__ == "__main__":
    main()
