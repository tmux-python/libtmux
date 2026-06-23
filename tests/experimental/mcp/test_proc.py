"""The Linux ``/proc`` readers for caller discovery: byte parsing + fail-closed."""

from __future__ import annotations

import os

from libtmux.experimental.mcp.vocabulary._proc import (
    _ppid_from_stat,
    read_proc_environ,
    read_proc_ppid,
    read_proc_uid,
)


def test_ppid_from_stat_survives_parens_in_comm() -> None:
    """The ppid parse anchors on the last ')', so a paren-laden comm is fine."""
    assert _ppid_from_stat(b"1234 (tmux: serv (x)) S 99 1234 1234 0 -1") == 99


def test_ppid_from_stat_garbage_is_none() -> None:
    """Unparseable stat bytes yield None, never an exception."""
    assert _ppid_from_stat(b"nonsense") is None


def test_real_readers_match_os() -> None:
    """The real /proc readers agree with os.getppid()/os.getuid() for self."""
    assert read_proc_ppid(os.getpid()) == os.getppid()
    assert read_proc_uid(os.getpid()) == os.getuid()


def test_environ_reader_minimises_keys() -> None:
    """The environ reader exposes only TMUX/TMUX_PANE (never other secrets)."""
    env = read_proc_environ(os.getpid())
    assert env is not None
    assert set(env) <= {"TMUX", "TMUX_PANE"}


def test_readers_fail_closed_on_bad_pid() -> None:
    """An unreadable pid yields None from every reader (never raises)."""
    bad = -1
    assert read_proc_environ(bad) is None
    assert read_proc_ppid(bad) is None
    assert read_proc_uid(bad) is None
