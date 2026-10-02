"""Tests for :meth:`libtmux.Pane.run`."""

from __future__ import annotations

import inspect
import pathlib
import shutil
import subprocess
import threading
import time
import typing as t

import pytest

from libtmux import exc, run as run_module
from libtmux.pane import Pane

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


def test_run_timeout_joins_the_one_timeout_hierarchy(pane: Pane) -> None:
    """One ``except TmuxTimeout`` covers Pane.run, Server.wait_for and cmd()."""
    with pytest.raises(exc.TmuxTimeout) as excinfo:
        pane.run("sleep 30", timeout=0.5)

    assert isinstance(excinfo.value, exc.PaneRunTimeout)
    assert not isinstance(excinfo.value, exc.LibTmuxException)


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
