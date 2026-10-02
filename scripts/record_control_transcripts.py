r"""Record tmux control-mode transcripts from real tmux binaries.

Usage::

    TMUX_TMPDIR=/tmp/lt-en python scripts/record_control_transcripts.py \\
        --out tests/fixtures/control_mode 3.2a=/path/to/tmux 3.7c=/path/to/tmux

Each ``LABEL=BIN`` writes ``LABEL.ctl`` (the exact bytes the control client read
from tmux's stdout) and ``LABEL-kill.ctl`` (the same for a server that dies
under the client), plus ``manifest.json`` mapping each label to its ``tmux -V``
output and the command lines sent. A private socket per run keeps the default
server out of it; the caller sets ``TMUX_TMPDIR`` to a short private directory.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import pathlib
import subprocess
import time
import typing as t

MARKER = "café"
#: Lines sent over the control connection, with seconds to wait after each.
SCENARIO: tuple[tuple[str, float], ...] = (
    ("rename-window foo", 0.2),
    ("display-message -p 'a;b' ; display-message -p second", 0.2),
    ("bogus", 0.2),
    ("set-hook -g after-rename-window 'rename-session hooked'", 0.1),
    ("rename-window bar", 0.3),
    ("send-keys -t %0 -l 'printf \"caf\\303\\251\\t\\\\\\\\z\\n\"'", 0.1),
    ("send-keys -t %0 Enter", 0.4),
    ("refresh-client -B 'sub:%*:#{pane_current_command}'", 1.6),
    ("new-window", 0.3),
    ("split-window", 0.3),
    ("kill-pane", 0.3),
    ("rename-session renamed", 0.2),
    ("refresh-client -f pause-after=1", 0.2),
    ("send-keys -t %0 'seq 1 30000' Enter", 0.1),
    ("refresh-client -A '%0:continue'", 0.3),
    ("kill-window", 0.3),
    ("", 0.3),
)


def _tmux(tmux_bin: str, socket: str, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [tmux_bin, "-L", socket, *args],
        capture_output=True,
        check=False,
    )


def _record(
    tmux_bin: str,
    socket: str,
    steps: t.Sequence[tuple[str, float]],
    *,
    stall: float = 0.0,
    kill_server: bool = False,
) -> bytes:
    _tmux(tmux_bin, socket, "-f/dev/null", "new-session", "-d", "-s", "w", "sh")
    _tmux(tmux_bin, socket, "set-option", "-g", "default-shell", "/bin/sh")
    _tmux(tmux_bin, socket, "set-option", "-g", "status-interval", "1")
    proc = subprocess.Popen(
        [tmux_bin, "-L", socket, "-u", "-C", "attach-session", "-E", "-t", "w"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None
    os.set_blocking(proc.stdout.fileno(), False)
    chunks: list[bytes] = []

    def drain() -> None:
        with contextlib.suppress(BlockingIOError):
            while data := proc.stdout.read(65536):  # type: ignore[union-attr]
                chunks.append(data)

    try:
        time.sleep(0.3)
        for line, wait in steps:
            proc.stdin.write(line.encode() + b"\n")
            proc.stdin.flush()
            # A stalled reader is what makes tmux emit %pause: skip draining
            # while the flood is in flight, then catch up.
            if "seq 1" in line and stall:
                time.sleep(stall)
            else:
                time.sleep(wait)
            drain()
        if kill_server:
            _tmux(tmux_bin, socket, "kill-server")
            time.sleep(0.3)
        drain()
        with contextlib.suppress(OSError):
            proc.stdin.close()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=3)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        drain()
        _tmux(tmux_bin, socket, "kill-server")
    return b"".join(chunks)


def main() -> None:
    """Record one pair of transcripts per ``LABEL=BIN`` argument."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("builds", nargs="+", metavar="LABEL=BIN")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict[str, t.Any]] = {}
    for item in args.builds:
        label, _, tmux_bin = item.partition("=")
        version = subprocess.run(
            [tmux_bin, "-V"], capture_output=True, text=True, check=True
        ).stdout.strip()
        socket = f"ctlrec{os.getpid()}"
        main_bytes = _record(tmux_bin, socket, SCENARIO, stall=2.5)
        (args.out / f"{label}.ctl").write_bytes(main_bytes)
        kill_steps = (("display-message -p before", 0.2),)
        kill_bytes = _record(tmux_bin, socket, kill_steps, kill_server=True)
        (args.out / f"{label}-kill.ctl").write_bytes(kill_bytes)
        manifest[label] = {
            "version": version,
            "marker": MARKER,
            "sent": [line for line, _ in SCENARIO],
        }
        print(label, version, len(main_bytes), len(kill_bytes))
    manifest_path = args.out / "manifest.json"
    existing = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    existing.update(manifest)
    manifest_path.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
