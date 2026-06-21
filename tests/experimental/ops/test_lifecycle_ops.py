"""Tests for server/session lifecycle, option, and environment operations."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.ops import (
    KillServer,
    RunShell,
    SetEnvironment,
    SetHook,
    SetOption,
    SetWindowOption,
    ShowOptions,
    SourceFile,
    StartServer,
    SuspendClient,
    operation_from_dict,
    operation_to_dict,
    result_from_dict,
    result_to_dict,
    run,
)
from libtmux.experimental.ops._types import ClientName, SessionId, WindowId

if t.TYPE_CHECKING:
    import pathlib

    from libtmux.experimental.ops.operation import Operation
    from libtmux.session import Session


class RenderCase(t.NamedTuple):
    """An op and the exact argv it renders."""

    test_id: str
    op: Operation[t.Any]
    expected: tuple[str, ...]


RENDER_CASES = (
    RenderCase(
        test_id="start_server",
        op=StartServer(),
        expected=("start-server",),
    ),
    RenderCase(
        test_id="kill_server",
        op=KillServer(),
        expected=("kill-server",),
    ),
    RenderCase(
        test_id="run_shell",
        op=RunShell(command_line="echo hi"),
        expected=("run-shell", "echo hi"),
    ),
    RenderCase(
        test_id="run_shell_background",
        op=RunShell(command_line="x", background=True),
        expected=("run-shell", "-b", "x"),
    ),
    RenderCase(
        test_id="source_file",
        op=SourceFile(path="~/.tmux.conf"),
        expected=("source-file", "~/.tmux.conf"),
    ),
    RenderCase(
        test_id="suspend_client",
        op=SuspendClient(target=ClientName("/dev/pts/1")),
        expected=("suspend-client", "-t", "/dev/pts/1"),
    ),
    RenderCase(
        test_id="set_option",
        op=SetOption(option="status", value="on"),
        expected=("set-option", "status", "on"),
    ),
    RenderCase(
        test_id="set_option_global",
        op=SetOption(global_=True, option="status", value="on"),
        expected=("set-option", "-g", "status", "on"),
    ),
    RenderCase(
        test_id="set_option_unset",
        op=SetOption(option="status", unset=True),
        expected=("set-option", "-u", "status"),
    ),
    RenderCase(
        test_id="set_window_option",
        op=SetWindowOption(option="mode-keys", value="vi"),
        expected=("set-window-option", "mode-keys", "vi"),
    ),
    RenderCase(
        test_id="set_environment",
        op=SetEnvironment(name="FOO", value="bar"),
        expected=("set-environment", "FOO", "bar"),
    ),
    RenderCase(
        test_id="set_environment_unset",
        op=SetEnvironment(global_=True, name="FOO", unset=True),
        expected=("set-environment", "-g", "-u", "FOO"),
    ),
    RenderCase(
        test_id="set_hook",
        op=SetHook(name="after-new-window", hook_command="display hi"),
        expected=("set-hook", "after-new-window", "display hi"),
    ),
)


@pytest.mark.parametrize(
    list(RenderCase._fields),
    RENDER_CASES,
    ids=[c.test_id for c in RENDER_CASES],
)
def test_lifecycle_op_render(
    test_id: str,
    op: Operation[t.Any],
    expected: tuple[str, ...],
) -> None:
    """Each op renders the exact tmux argv."""
    assert op.render() == expected


@pytest.mark.parametrize(
    list(RenderCase._fields),
    RENDER_CASES,
    ids=[c.test_id for c in RENDER_CASES],
)
def test_lifecycle_op_round_trips(
    test_id: str,
    op: Operation[t.Any],
    expected: tuple[str, ...],
) -> None:
    """Each op and its result round-trip via dicts."""
    assert operation_from_dict(operation_to_dict(op)) == op
    result = op.build_result(returncode=0)
    assert result_from_dict(result_to_dict(result)) == result


def test_set_and_show_option_live(session: Session) -> None:
    """set-option writes a session option that show-options reads back."""
    from libtmux.experimental.engines import SubprocessEngine

    engine = SubprocessEngine.for_server(session.server)
    sid = session.session_id
    assert sid is not None

    run(
        SetOption(target=SessionId(sid), option="@ops_var", value="hello"),
        engine,
    ).raise_for_status()
    shown = run(ShowOptions(target=SessionId(sid)), engine)
    assert shown.ok
    assert shown.options.get("@ops_var") == "hello"


def test_set_window_option_and_environment_live(session: Session) -> None:
    """set-window-option and set-environment succeed against real objects."""
    from libtmux.experimental.engines import SubprocessEngine

    engine = SubprocessEngine.for_server(session.server)
    sid = session.session_id
    window = session.active_window
    assert sid is not None and window.window_id is not None

    assert run(
        SetWindowOption(target=WindowId(window.window_id), option="@w", value="x"),
        engine,
    ).ok
    assert run(
        SetEnvironment(target=SessionId(sid), name="OPS_ENV", value="1"),
        engine,
    ).ok
    assert run(
        SetHook(
            target=SessionId(sid),
            name="after-new-window",
            hook_command="display-message ok",
        ),
        engine,
    ).ok


def test_run_shell_source_file_start_server_live(
    session: Session,
    tmp_path: pathlib.Path,
) -> None:
    """run-shell, source-file, and start-server all succeed."""
    from libtmux.experimental.engines import SubprocessEngine

    engine = SubprocessEngine.for_server(session.server)

    assert run(RunShell(command_line="true"), engine).ok
    assert run(StartServer(), engine).ok

    conf = tmp_path / "snippet.conf"
    conf.write_text("set-option -g @sourced yes\n")
    assert run(SourceFile(path=str(conf)), engine).ok
