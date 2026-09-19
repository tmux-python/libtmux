"""Test-suite-wide fixtures for libtmux's own tests."""

from __future__ import annotations

import contextlib
import os
import shlex
import signal
import typing as t

import pytest

from libtmux.common import get_version, get_version_str

if t.TYPE_CHECKING:
    import pathlib
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _clear_get_version_cache() -> None:
    """Flush the tmux-version caches before each test.

    Several tests in test_common.py and legacy_api/test_common.py
    monkey-patch libtmux.common.tmux_cmd then call get_version() to
    assert parsed-version behavior. With memoization, a prior test's
    cached result would mask the mock — this fixture guarantees a fresh
    subprocess lookup per test. get_version and get_version_str cache
    independently, so flush both.
    """
    get_version.cache_clear()
    get_version_str.cache_clear()


@pytest.fixture
def hanging_tmux(tmp_path: pathlib.Path) -> tuple[str, pathlib.Path]:
    """Return a stand-in tmux that never answers, and its pid file.

    Models the failure a real fixture cannot produce cheaply: a server
    that accepts a connection and never replies. ``-V`` is answered,
    because a wedged SERVER does not stop the local binary reporting its
    own version, and `Server.sessions` reads it on the way past.
    ``exec`` preserves the recorded pid, so a test can check the process
    afterwards instead of trusting that it was killed.
    """
    pid_file = tmp_path / "pid"
    binary = tmp_path / "tmux"
    binary.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-V" ]; then echo "tmux 3.7"; exit 0; fi\n'
        f"echo $$ > {shlex.quote(str(pid_file))}\n"
        "exec sleep 30\n"
    )
    binary.chmod(0o755)
    return str(binary), pid_file


@pytest.fixture
def hanging_tmux_with_orphan(
    tmp_path: pathlib.Path,
) -> Iterator[tuple[str, pathlib.Path, pathlib.Path]]:
    """Return a stand-in tmux whose kill leaves a pipe-holding orphan behind.

    Models a failure ``hanging_tmux`` cannot: the killed process is not the
    only one holding its inherited stdout/stderr pipes. A child backgrounded
    and ``disown``-ed before ``exec`` survives the kill and keeps writing to
    those pipes, so draining stdout/stderr for EOF after the kill blocks on
    that orphan instead of completing with the caller's own deadline.
    """
    pid_file = tmp_path / "pid"
    orphan_pid_file = tmp_path / "orphan_pid"
    binary = tmp_path / "tmux"
    binary.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-V" ]; then echo "tmux 3.7"; exit 0; fi\n'
        f"sleep 30 & echo $! > {shlex.quote(str(orphan_pid_file))}\n"
        "disown\n"
        f"echo $$ > {shlex.quote(str(pid_file))}\n"
        "exec sleep 30\n"
    )
    binary.chmod(0o755)
    yield str(binary), pid_file, orphan_pid_file
    if orphan_pid_file.exists():
        with contextlib.suppress(ProcessLookupError, ValueError):
            os.kill(int(orphan_pid_file.read_text()), signal.SIGKILL)
