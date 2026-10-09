"""Remote object cleanup after moves and failures inside resource scopes."""

from __future__ import annotations

import typing as t

import pytest

from libtmux import Pane, Session, Window, exc

if t.TYPE_CHECKING:
    from libtmux.common import tmux_cmd


def test_window_scope_cleans_after_move(session: Session) -> None:
    """Destroy the captured window even after another client moves its link."""
    server = session.server
    destination = server.new_session(session_name="window_destination")
    with session.new_window(window_name="move_me") as window:
        window_id = window.window_id
        result = server.cmd(
            "move-window", "-s", window_id, "-t", f"{destination.session_id}:"
        )
        assert result.returncode == 0, result.stderr
        assert window_id in [item.window_id for item in destination.windows]
    assert window_id not in [item.window_id for item in server.windows]
    assert server.has_session("window_destination")


def test_pane_scope_cleans_after_move(session: Session) -> None:
    """Destroy the captured pane after a raw join changes its parent window."""
    server = session.server
    destination = session.new_window(window_name="pane_destination")
    with session.active_window.split() as pane:
        pane_id = pane.pane_id
        result = server.cmd("join-pane", "-s", pane_id, "-t", destination.window_id)
        assert result.returncode == 0, result.stderr
        assert pane_id in [item.pane_id for item in destination.panes]
    assert pane_id not in [item.pane_id for item in server.panes]
    assert destination.window_id in [item.window_id for item in session.windows]


@pytest.mark.parametrize("kind", ["window", "pane"])
@pytest.mark.parametrize(
    "body_error", [RuntimeError("body failed"), KeyboardInterrupt(), SystemExit(3)]
)
def test_object_scope_preserves_both_failures_and_can_retry(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    body_error: BaseException,
) -> None:
    """Deny teardown at the command boundary to expose both errors and retry."""
    obj: Window | Pane = (
        session.new_window() if kind == "window" else session.active_window.split()
    )
    server = session.server
    command = server.cmd
    cleanup_error = PermissionError("cleanup denied")

    def denied(cmd: str, *args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        if cmd == "if-shell" and any(
            str(arg).startswith(f"kill-{kind} ") for arg in args
        ):
            raise cleanup_error
        return command(cmd, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(server, "cmd", denied)
        with pytest.raises(BaseExceptionGroup) as caught, obj:
            raise body_error
    assert caught.value.exceptions == (body_error, cleanup_error)
    obj.refresh()
    monkeypatch.setattr(obj._scope_owner._client, "cmd", command)
    obj.__exit__(None, None, None)
    obj.__exit__(None, None, None)
    if isinstance(obj, Window):
        assert obj.window_id not in [item.window_id for item in server.windows]
    else:
        assert obj.pane_id not in [item.pane_id for item in server.panes]


@pytest.mark.parametrize("kind", ["session", "window", "pane"])
@pytest.mark.parametrize("stderr", [[], ["permission denied"]])
def test_scope_reports_failed_command_without_disabling_retry(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    stderr: list[str],
) -> None:
    """A failed exit status is observable even when tmux emits no diagnostic."""
    server = session.server
    obj: Session | Window | Pane
    if kind == "session":
        obj = server.new_session()
    elif kind == "window":
        obj = session.new_window()
    else:
        obj = session.active_window.split()
    command = server.cmd

    def denied(cmd: str, *args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        if cmd == "if-shell" and any(
            str(arg).startswith(f"kill-{kind} ") for arg in args
        ):
            result = command("display-message", "-p", "failure probe")
            result.returncode = 64
            result.stdout = []
            result.stderr = stderr
            return result
        return command(cmd, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(server, "cmd", denied)
        with pytest.raises(exc.LibTmuxException, match=r"denied|exit status 64"), obj:
            pass
    obj.refresh()
    monkeypatch.setattr(obj._scope_owner._client, "cmd", command)
    obj.__exit__(None, None, None)
    obj.__exit__(None, None, None)
