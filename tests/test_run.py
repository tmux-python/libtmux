"""Tests for :meth:`libtmux.Pane.run`."""

from __future__ import annotations

import inspect
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import textwrap
import threading
import time
import typing as t

import pytest

from libtmux import exc, run as run_module
from libtmux.pane import Pane
from libtmux.server import Server

if t.TYPE_CHECKING:
    from libtmux.session import Session

#: Interactive shells under test, started without the user's rc files.
SHELLS: dict[str, str] = {
    "sh": "sh",
    "bash": "env HISTFILE=/dev/null bash --norc",
    "zsh": "zsh -f",
}


def _shell_pane(session: Session, shell: str) -> Pane:
    """Return a fresh pane running *shell*, skipping when it is missing."""
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} not installed")
    window = session.new_window(attach=False, window_shell=SHELLS[shell])
    pane = window.active_pane
    assert pane is not None
    return pane


@pytest.fixture
def pane(session: Session) -> Pane:
    """Return the session's first pane, at a shell prompt."""
    pane = session.active_window.active_pane
    assert pane is not None
    return pane


@pytest.fixture(params=sorted(SHELLS))
def shell_pane(session: Session, request: pytest.FixtureRequest) -> Pane:
    """Return a pane for each of sh, bash and zsh."""
    return _shell_pane(session, request.param)


class RunFixture(t.NamedTuple):
    """One command and what it must report."""

    test_id: str
    command: str
    returncode: int
    stdout: list[str]


RUN_FIXTURES: list[RunFixture] = [
    RunFixture("true", "true", 0, []),
    RunFixture("false", "false", 1, []),
    RunFixture("exit_status", "sh -c 'exit 7'", 7, []),
    RunFixture("one_line", "echo hello", 0, ["hello"]),
    RunFixture("two_lines", "printf 'a\\nb\\n'", 0, ["a", "b"]),
    RunFixture("no_trailing_newline", "printf partial", 0, ["partial"]),
    RunFixture("blank_line_kept", "printf 'a\\n\\nb\\n'", 0, ["a", "", "b"]),
    RunFixture("stderr_included", "echo oops >&2; false", 1, ["oops"]),
    RunFixture("compound", "echo a; echo b; sh -c 'exit 3'", 3, ["a", "b"]),
    RunFixture("single_quote", 'echo "it\'s"', 0, ["it's"]),
    RunFixture("trailing_semicolon", "echo a;", 0, ["a"]),
    RunFixture("quoted_semicolon", "echo ';' ';'", 0, ["; ;"]),
]


@pytest.mark.parametrize(
    list(RunFixture._fields),
    RUN_FIXTURES,
    ids=[f.test_id for f in RUN_FIXTURES],
)
def test_run_reports_status_and_output(
    pane: Pane,
    test_id: str,
    command: str,
    returncode: int,
    stdout: list[str],
) -> None:
    """Pane.run() returns the exit status and only the command's output."""
    result = pane.run(command, timeout=10)

    assert result.returncode == returncode
    assert result.stdout == stdout
    assert result.args == command


def test_run_output_excludes_echoed_command(pane: Pane) -> None:
    """The typed command line is not part of the output, even when it matches."""
    result = pane.run("echo echo", timeout=10)

    assert result.stdout == ["echo"]


@pytest.mark.parametrize("shell", sorted(SHELLS))
def test_run_on_a_shell_that_starts_late_returns_clean_output(
    session: Session, shell: str
) -> None:
    """A line typed before the shell reads input does not leak into stdout.

    The pane's tty echoes a line that arrives before the shell has set it up,
    and the shell's prompt then shares a row with the begin marker. dash, which
    never leaves cooked mode, did this on 4 of 15 fresh panes; the late start
    is forced here instead of waiting for load to cause it.
    """
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} not installed")
    window = session.new_window(
        attach=False,
        window_shell=f"sh -c 'sleep 0.2; exec {SHELLS[shell]}'",
    )
    pane = window.active_pane
    assert pane is not None
    result = pane.run("echo hi", timeout=10)
    assert result.stdout == ["hi"]
    assert result.returncode == 0
    assert not result.truncated


def test_run_twice_does_not_mix_output(pane: Pane) -> None:
    """A second call reports only its own output, not the first call's."""
    assert pane.run("echo first", timeout=10).stdout == ["first"]
    assert pane.run("echo second", timeout=10).stdout == ["second"]


def test_run_uses_fresh_channel_each_call(
    pane: Pane,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each call waits on channels no earlier call used."""
    channels: list[str] = []
    real_popen = subprocess.Popen

    def spy(args: t.Any, *a: t.Any, **kw: t.Any) -> t.Any:
        if "wait-for" in args and "-S" not in args:
            channels.append(args[-1])
        return real_popen(args, *a, **kw)

    monkeypatch.setattr(subprocess, "Popen", spy)
    pane.run("true", timeout=10)
    pane.run("true", timeout=10)

    assert len(channels) == 4
    assert len(set(channels)) == 4


def test_run_leaves_no_option_behind(pane: Pane) -> None:
    """The exit-status option is removed once the result is read."""
    pane.run("true", timeout=10)

    shown = pane.cmd("show-options", "-p").stdout
    assert not [line for line in shown if line.startswith("@libtmux_run")]


def test_run_timeout_raises_with_partial_output(pane: Pane) -> None:
    """A command that outlives *timeout* raises and reports what it printed."""
    started = time.monotonic()
    with pytest.raises(exc.PaneRunTimeout) as excinfo:
        pane.run("echo before; sleep 30", timeout=0.5)
    elapsed = time.monotonic() - started

    assert elapsed < 5
    assert excinfo.value.timeout == 0.5
    assert excinfo.value.stdout == ["before"]
    assert excinfo.value.started is True


def test_run_timeout_is_both_a_wait_and_a_bounded_call(pane: Pane) -> None:
    """``except TmuxTimeout`` and ``except WaitTimeout`` each cover Pane.run."""
    with pytest.raises(exc.TmuxTimeout) as excinfo:
        pane.run("sleep 30", timeout=0.5)

    assert isinstance(excinfo.value, exc.PaneRunTimeout)
    assert isinstance(excinfo.value, exc.WaitTimeout)
    assert isinstance(excinfo.value, exc.LibTmuxException)


def test_run_default_timeout_is_finite() -> None:
    """A call that names no timeout still ends."""
    default = inspect.signature(Pane.run).parameters["timeout"].default

    assert isinstance(default, float)
    assert 0 < default < float("inf")


@pytest.mark.parametrize("timeout", [0, -1])
def test_run_rejects_non_positive_timeout(pane: Pane, timeout: float) -> None:
    """A zero or negative bound is a programming error, not an instant timeout."""
    with pytest.raises(ValueError, match="positive"):
        pane.run("true", timeout=timeout)


def test_run_works_after_a_timeout(pane: Pane) -> None:
    """Interrupting the timed-out command lets the pane run the next one."""
    with pytest.raises(exc.PaneRunTimeout):
        pane.run("sleep 30", timeout=0.5)
    pane.send_keys("C-c", enter=False, literal=False)

    assert pane.run("echo again", timeout=10).stdout == ["again"]


def test_run_server_gone_raises(pane: Pane) -> None:
    """A server that dies mid-wait is reported as gone, not as finished."""
    server = pane.server

    threading.Timer(0.5, lambda: server.cmd("kill-server")).start()
    started = time.monotonic()
    with pytest.raises(exc.TmuxServerGone):
        pane.run("sleep 30", timeout=20)

    assert time.monotonic() - started < 10


def test_run_pane_closed_raises_promptly(session: Session) -> None:
    """A pane that exits before reporting raises PaneNotFound without waiting."""
    window = session.new_window(attach=False)
    pane = window.split()

    started = time.monotonic()
    with pytest.raises(exc.PaneNotFound):
        pane.run("exit", timeout=30)

    assert time.monotonic() - started < 5


def test_run_dead_pane_raises_promptly(session: Session) -> None:
    """With ``remain-on-exit`` the pane stays, dead; the call still ends at once."""
    window = session.new_window(attach=False)
    pane = window.split()
    pane.cmd("set-option", "-p", "remain-on-exit", "on")

    started = time.monotonic()
    with pytest.raises(exc.PaneNotFound):
        pane.run("exit 3", timeout=30)

    assert time.monotonic() - started < 5


def test_run_other_pane_closing_does_not_end_the_call(session: Session) -> None:
    """The hook filters on the pane: a sibling closing wakes nobody."""
    window = session.new_window(attach=False)
    pane = window.split()
    sibling = window.split()
    assert pane.pane_id != sibling.pane_id

    threading.Timer(0.3, lambda: sibling.send_keys("exit")).start()
    result = pane.run("sleep 1; echo done", timeout=20)

    assert (result.returncode, result.stdout) == (0, ["done"])


def _gone_hooks(session: Session) -> list[str]:
    shown = session.server.cmd("show-hooks", "-gw").stdout
    return [line for line in shown if line.startswith(("pane-exited[", "pane-died["))]


def test_run_removes_its_hooks_on_every_path(session: Session) -> None:
    """No hook outlives the call: result, timeout, or closed pane."""
    window = session.new_window(attach=False)
    pane = window.split()
    pane.run("true", timeout=10)
    assert _gone_hooks(session) == []

    with pytest.raises(exc.PaneRunTimeout):
        pane.run("sleep 30", timeout=0.5)
    assert _gone_hooks(session) == []
    pane.send_keys("C-c", enter=False, literal=False)

    with pytest.raises(exc.PaneNotFound):
        pane.run("exit", timeout=10)
    assert _gone_hooks(session) == []


def test_run_leaves_the_callers_hooks_alone(session: Session) -> None:
    """A ``pane-exited`` hook the caller already set survives a call."""
    server = session.server
    server.cmd("set-hook", "-g", "pane-exited", "set-option -g @mine 1")
    window = session.new_window(attach=False)
    pane = window.split()
    pane.run("true", timeout=10)

    assert any("@mine" in line for line in server.cmd("show-hooks", "-gw").stdout)


class AbortFixture(t.NamedTuple):
    """A command the shell cannot run to completion."""

    test_id: str
    command: str


ABORT_FIXTURES: list[AbortFixture] = [
    AbortFixture("unterminated_single_quote", "echo 'unterminated"),
    AbortFixture("unterminated_double_quote", 'echo "unterminated'),
    AbortFixture("unclosed_paren", "("),
    AbortFixture("stray_fi", "fi"),
]


@pytest.mark.parametrize(
    list(AbortFixture._fields),
    ABORT_FIXTURES,
    ids=[f.test_id for f in ABORT_FIXTURES],
)
def test_run_releases_waiter_when_the_line_aborts(
    shell_pane: Pane,
    test_id: str,
    command: str,
) -> None:
    """A command the shell rejects is a nonzero status, not a hung waiter."""
    started = time.monotonic()
    result = shell_pane.run(command, timeout=20)

    assert time.monotonic() - started < 10
    assert result.returncode != 0
    assert shell_pane.run("echo usable", timeout=10).stdout == ["usable"]


def test_run_releases_waiter_on_interrupt(shell_pane: Pane) -> None:
    """Ctrl-C on a running command ends the call with status 130."""
    threading.Timer(
        0.5,
        lambda: shell_pane.send_keys("C-c", enter=False, literal=False),
    ).start()
    started = time.monotonic()
    result = shell_pane.run("sleep 30", timeout=20)

    assert time.monotonic() - started < 10
    assert result.returncode == 130
    assert shell_pane.run("echo usable", timeout=10).stdout == ["usable"]


def test_run_trailing_comment_does_not_leak(shell_pane: Pane) -> None:
    """A trailing ``#`` comment is the command's, in zsh as in bash and sh.

    zsh ignores ``#`` comments at an interactive prompt unless
    ``interactive_comments`` is set, so a comment typed in the line would
    print as arguments.
    """
    result = shell_pane.run("echo hi  # trailing comment", timeout=10)

    assert (result.returncode, result.stdout) == (0, ["hi"])


def test_run_shell_state_persists(shell_pane: Pane) -> None:
    """The command runs in the pane's own shell: ``cd`` and ``export`` stick."""
    shell_pane.run("cd /tmp; export LT_RUN_X=5", timeout=10)

    result = shell_pane.run('echo "$PWD $LT_RUN_X"', timeout=10)

    assert result.stdout == ["/tmp 5"]


def _lines_with_begin_marker(lines: list[str]) -> int:
    return len([line for line in lines if run_module._BEGIN in line])


def test_run_bash_history_keeps_no_entry(session: Session) -> None:
    """After a call, bash's history holds none of the typed lines."""
    pane = _shell_pane(session, "bash")
    pane.run("true", timeout=10)
    pane.run("true", timeout=10)

    # The listing still holds the line that is running it.
    listing = pane.run("history", timeout=10).stdout

    assert _lines_with_begin_marker(listing) == 1


def test_run_zsh_history_honours_leading_space(session: Session) -> None:
    """Zsh with ``hist_ignore_space`` drops the typed lines from history."""
    pane = _shell_pane(session, "zsh")
    pane.send_keys("setopt histignorespace")
    pane.run("true", timeout=10)
    pane.run("true", timeout=10)

    listing = pane.run("fc -l 1", timeout=10).stdout

    assert _lines_with_begin_marker(listing) <= 1


def test_run_fails_fast_when_the_shell_cannot_reach_the_server(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """A pane whose shell cannot signal this server fails at the start bound.

    The wrapper shell has its own, empty ``TMUX_TMPDIR``, so the ``tmux`` it
    runs looks for the socket elsewhere, as a shell behind ``ssh`` or
    ``docker exec`` does. The directory must exist: tmux falls back to
    ``/tmp`` for one that does not.
    """
    monkeypatch.setattr(run_module, "_START_TIMEOUT", 0.5)
    window = session.new_window(
        attach=False,
        window_shell=f"env TMUX_TMPDIR={tmp_path} sh",
    )
    pane = window.active_pane
    assert pane is not None

    started = time.monotonic()
    with pytest.raises(exc.PaneRunTimeout) as excinfo:
        pane.run("echo hi", timeout=60)

    assert time.monotonic() - started < 10
    assert excinfo.value.started is False
    assert "cannot reach this tmux server" in str(excinfo.value)


def test_run_concurrent_calls_on_one_pane_do_not_mix(pane: Pane) -> None:
    """Threads calling run() on one pane each get their own output."""
    results: dict[int, run_module.PaneRunResult] = {}
    errors: list[Exception] = []

    def worker(i: int) -> None:
        try:
            results[i] = pane.run(f"echo out-{i}; sh -c 'exit {i}'", timeout=30)
        except (exc.LibTmuxException, exc.TmuxTimeout) as err:
            errors.append(err)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert {i: (r.returncode, r.stdout, r.truncated) for i, r in results.items()} == {
        i: (i, [f"out-{i}"], False) for i in range(6)
    }


def test_run_waiting_for_the_pane_times_out_without_typing(pane: Pane) -> None:
    """A call that cannot get the pane's lock in time types nothing."""
    holder = threading.Thread(target=lambda: pane.run("sleep 1", timeout=30))
    holder.start()
    try:
        # The holder owns the lock once its count shows.
        pane_id = pane.pane_id
        assert pane_id is not None
        for _ in range(500):
            if run_module._drive_lock_count(pane.server, pane_id):
                break
            time.sleep(0.01)
        with pytest.raises(exc.PaneRunTimeout) as excinfo:
            pane.run("echo never-typed", timeout=0.2)
    finally:
        holder.join()
    assert excinfo.value.started is False
    assert excinfo.value.stdout == []
    assert all("never-typed" not in line for line in pane.capture_pane(start="-"))
    assert pane.run("echo after", timeout=10).stdout == ["after"]


def test_run_on_different_panes_does_not_serialize(
    session: Session,
    tmp_path: pathlib.Path,
) -> None:
    """Each command waits for a file the other writes: only parallel calls finish."""
    first = _shell_pane(session, "sh")
    second = _shell_pane(session, "sh")
    a, b = tmp_path / "a", tmp_path / "b"
    wait = "until [ -e {} ]; do sleep 0.02; done"
    errors: list[Exception] = []

    def worker(pane: Pane, mine: pathlib.Path, theirs: pathlib.Path) -> None:
        try:
            pane.run(f"touch {mine}; " + wait.format(theirs), timeout=10)
        except (exc.LibTmuxException, exc.TmuxTimeout) as err:
            errors.append(err)

    threads = [
        threading.Thread(target=worker, args=(first, a, b)),
        threading.Thread(target=worker, args=(second, b, a)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors


def test_run_drive_lock_leaves_no_entry_behind(pane: Pane) -> None:
    """The lock table is empty after every path out, error or not."""
    pane_id = pane.pane_id
    assert pane_id is not None
    pane.run("true", timeout=10)
    assert not [k for k in run_module._DRIVE_LOCKS if k[2] == pane_id]
    with pytest.raises(exc.PaneRunTimeout):
        pane.run("sleep 30", timeout=0.3)
    assert not [k for k in run_module._DRIVE_LOCKS if k[2] == pane_id]
    pane.send_keys("C-c", enter=False)


def test_run_costs_at_most_eight_tmux_calls(
    server: Server,
    session: Session,
    tmp_path: pathlib.Path,
) -> None:
    """One call is eight tmux invocations, in the pane and out of it.

    Setup and teardown commands travel as one ``;``-chained invocation each,
    so a change that unchains them (it was sixteen calls) turns this red. The
    count comes from a wrapper binary that logs every exec, which sees the
    calls the pane's shell makes as well as the library's.
    """
    real = shutil.which("tmux")
    assert real is not None
    log = tmp_path / "execs"
    wrapper = tmp_path / "tmux"
    wrapper.write_text(f'#!/bin/sh\necho x >> {log}\nexec {real} "$@"\n')
    wrapper.chmod(0o755)
    counted = Server(socket_name=server.socket_name, tmux_bin=str(wrapper))
    counted_session = counted.sessions.get(session_id=session.session_id)
    assert counted_session is not None
    pane = counted_session.active_window.active_pane
    assert pane is not None
    pane.run("true", timeout=10)  # first call may do one-time work
    log.write_text("")
    pane.run("true", timeout=10)
    assert len(log.read_text().split()) <= 8


needs_proc = pytest.mark.skipif(
    not pathlib.Path("/proc/self/cmdline").exists(),
    reason="finds tmux clients by reading /proc",
)


def _wait_for_clients(
    socket_name: str | None,
    *,
    done_only: bool = False,
) -> list[int]:
    """Return pids of tmux ``wait-for`` waiters talking to *socket_name*.

    *done_only* leaves out the short-lived waiter for the ``started``
    acknowledgement, so a hit means the call is waiting for its command.
    """
    found = []
    for entry in pathlib.Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        words = [a.decode(errors="replace") for a in argv]
        if (
            "wait-for" in words
            and "-S" not in words
            and any(socket_name and socket_name in w for w in words)
            and not (done_only and any(w.endswith("-started") for w in words))
        ):
            found.append(int(entry.name))
    return found


def _until(condition: t.Callable[[], bool], what: str, seconds: float = 10) -> None:
    """Poll *condition* for a bounded time; fail naming *what*."""
    deadline = time.monotonic() + seconds
    while not condition():
        if time.monotonic() > deadline:
            pytest.fail(f"timed out waiting for {what}")
        time.sleep(0.01)


@needs_proc
def test_run_cancel_wakes_the_call_and_leaves_no_waiter(pane: Pane) -> None:
    """cancel() ends a blocked call at once and takes its tmux waiter with it."""
    cancel = run_module.PaneRunCancel()
    caught: list[exc.PaneRunCancelled] = []

    def worker() -> None:
        try:
            pane.run("echo before; sleep 30", timeout=60, cancel=cancel)
        except exc.PaneRunCancelled as err:
            caught.append(err)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    socket_name = pane.server.socket_name
    _until(lambda: "before" in pane.capture_pane(), "the command's first output")
    started = time.monotonic()
    cancel.cancel()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert time.monotonic() - started < 3
    assert len(caught) == 1
    assert caught[0].started is True
    assert caught[0].stdout == ["before"]
    assert _wait_for_clients(socket_name) == []
    assert run_module._drive_lock_count(pane.server, str(pane.pane_id)) == 0
    hooks = pane.server.cmd("show-hooks", "-g").stdout
    assert not [h for h in hooks if "pane-exited[" in h or "pane-died[" in h]
    pane.send_keys("C-c", enter=False)
    assert pane.run("echo after", timeout=10).stdout == ["after"]


@needs_proc
def test_run_cancel_before_the_shell_starts_reports_no_output(
    session: Session,
) -> None:
    """A call cancelled before its line ran reports the pane's rows as no output."""
    window = session.new_window(
        attach=False,
        window_shell="sh -c 'sleep 1; exec sh'",
    )
    pane = window.active_pane
    assert pane is not None
    cancel = run_module.PaneRunCancel()
    caught: list[exc.PaneRunCancelled] = []

    def worker() -> None:
        try:
            pane.run("echo hi", timeout=60, cancel=cancel)
        except exc.PaneRunCancelled as err:
            caught.append(err)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    socket_name = pane.server.socket_name
    _until(lambda: bool(_wait_for_clients(socket_name)), "the start waiter")
    # The tty has echoed the typed line by now; the shell has not run it.
    _until(lambda: any("LTRUN" in row for row in pane.capture_pane()), "the echo")
    cancel.cancel()
    thread.join(timeout=10)
    assert [(e.started, e.stdout) for e in caught] == [(False, [])]


def test_run_cancel_while_queued_types_nothing(pane: Pane) -> None:
    """A call waiting for the pane's lock leaves the queue when cancelled."""
    holder = threading.Thread(
        target=lambda: pane.run("sleep 1", timeout=30), daemon=True
    )
    holder.start()
    pane_id = str(pane.pane_id)
    _until(lambda: run_module._drive_lock_count(pane.server, pane_id) > 0, "the lock")
    cancel = run_module.PaneRunCancel()
    caught: list[exc.PaneRunCancelled] = []

    def queued() -> None:
        try:
            pane.run("echo never-typed", timeout=30, cancel=cancel)
        except exc.PaneRunCancelled as err:
            caught.append(err)

    waiter = threading.Thread(target=queued, daemon=True)
    waiter.start()
    _until(
        lambda: run_module._drive_lock_count(pane.server, pane_id) == 2,
        "the second call to queue",
    )
    started = time.monotonic()
    cancel.cancel()
    waiter.join(timeout=10)
    assert time.monotonic() - started < 0.9, "cancel should not wait for the holder"
    holder.join()
    assert [e.started for e in caught] == [False]
    assert all("never-typed" not in line for line in pane.capture_pane(start="-"))
    assert pane.run("echo after", timeout=10).stdout == ["after"]


def test_run_already_cancelled_types_nothing(pane: Pane) -> None:
    """A cancelled token ends the call before anything reaches the pane."""
    cancel = run_module.PaneRunCancel()
    cancel.cancel()
    with pytest.raises(exc.PaneRunCancelled) as excinfo:
        pane.run("echo never-typed", timeout=10, cancel=cancel)
    assert excinfo.value.started is False
    assert all("never-typed" not in line for line in pane.capture_pane(start="-"))


_ABANDON_CHILD = textwrap.dedent(
    """
    import pathlib, sys, threading, time
    import libtmux

    mode, socket_name, pane_id, tmux_bin = sys.argv[1:5]
    server = libtmux.Server(socket_name=socket_name, tmux_bin=tmux_bin)
    pane = next(p for p in server.panes if p.pane_id == pane_id)

    def waiters(done_only=False):
        n = 0
        for entry in pathlib.Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                words = (entry / "cmdline").read_bytes().split(b"\\0")
            except OSError:
                continue
            if (
                b"wait-for" in words
                and b"-S" not in words
                and any(socket_name.encode() in w for w in words)
                and not (done_only and any(w.endswith(b"-started") for w in words))
            ):
                n += 1
        return n

    def until_waiting():
        deadline = time.monotonic() + 10
        while not waiters(done_only=True):
            assert time.monotonic() < deadline
            time.sleep(0.01)

    if mode == "interrupt":
        print("ready", flush=True)
        try:
            pane.run("sleep 30", timeout=60)
        except KeyboardInterrupt:
            print("waiters", waiters(), flush=True)
    else:
        threading.Thread(
            target=lambda: pane.run("sleep 30", timeout=60), daemon=True
        ).start()
        until_waiting()
        print("exiting", flush=True)
    """
)


@needs_proc
@pytest.mark.parametrize("mode", ["interrupt", "exit"])
def test_run_abandoned_call_leaves_no_waiter(
    session: Session,
    mode: str,
) -> None:
    """KeyboardInterrupt and interpreter exit do not orphan the tmux waiter.

    The command (``sleep 30``) outlives the child, so a waiter left behind
    would still be there when the child is gone.
    """
    socket_name = session.server.socket_name
    pane = session.active_window.active_pane
    assert pane is not None and socket_name is not None
    tmux_bin = shutil.which("tmux")
    assert tmux_bin is not None
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _ABANDON_CHILD,
            mode,
            socket_name,
            str(pane.pane_id),
            tmux_bin,
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert child.stdout is not None
    try:
        assert child.stdout.readline().strip() in {"ready", "exiting"}
        if mode == "interrupt":
            _until(
                lambda: bool(_wait_for_clients(socket_name, done_only=True)),
                "the done waiter",
            )
            os.kill(child.pid, signal.SIGINT)
            assert child.stdout.readline().strip() == "waiters 0"
        child.wait(timeout=20)
    finally:
        child.kill()
        child.wait()
    assert _wait_for_clients(socket_name) == []
    pane.send_keys("C-c", enter=False)


def test_pane_run_timeout_keeps_both_parents() -> None:
    """``PaneRunTimeout`` is a wait that gave up and a bounded tmux command."""
    err = exc.PaneRunTimeout("sleep 9", 1.0, [], cmd=[], started=True)

    assert isinstance(err, exc.WaitTimeout)
    assert isinstance(err, exc.TmuxTimeout)
    assert isinstance(err, exc.TmuxError)


def test_pane_run_goes_through_the_engine_seam(server: Server) -> None:
    """``Pane.run``'s tmux calls are dispatched by the server's engine.

    Only its long-lived ``wait-for`` client is forked directly.
    """
    from libtmux.engines import CommandRequest, SubprocessEngine

    seen: list[str] = []

    class Counting(SubprocessEngine):
        def run(self, request: CommandRequest) -> t.Any:
            seen.append(request.args[0])
            return super().run(request)

    session = server.new_session(session_name="seam_run")
    counted = Server(socket_name=server.socket_name, engine=Counting())
    pane = counted.sessions.get(session_name="seam_run").active_pane
    assert pane is not None
    seen.clear()

    result = pane.run("true", timeout=30)

    assert result.returncode == 0
    assert "set-hook" in seen
    assert "send-keys" in seen
    session.kill()
