"""Tests for the workspace CLI (``python -m ...workspace.cli load``)."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.workspace import cli

if t.TYPE_CHECKING:
    from pathlib import Path


def test_find_workspace_file_direct_path(tmp_path: Path) -> None:
    """A direct file path is returned as-is."""
    target = tmp_path / "ws.yaml"
    target.write_text("session_name: x\n")
    assert cli._find_workspace_file(str(target)) == target


def test_find_workspace_file_in_directory(tmp_path: Path) -> None:
    """A directory is searched for .tmuxp.{yaml,yml,json}."""
    target = tmp_path / ".tmuxp.yaml"
    target.write_text("session_name: x\n")
    assert cli._find_workspace_file(str(tmp_path)) == target


def test_find_workspace_file_missing_raises(tmp_path: Path) -> None:
    """A missing file fails closed."""
    with pytest.raises(FileNotFoundError):
        cli._find_workspace_file(str(tmp_path / "nope.yaml"))


def test_expand_workspace_resolves_relative_paths(tmp_path: Path) -> None:
    """start_directory is expanded relative to the workspace file's directory."""
    raw = {
        "session_name": "x",
        "start_directory": "./root",
        "windows": [
            {
                "window_name": "w",
                "start_directory": "./win",
                "panes": [{"shell_command": ["echo hi"], "start_directory": "./pane"}],
            },
        ],
    }
    expanded = cli._expand_workspace(raw, cwd=tmp_path)
    assert expanded["start_directory"] == str(tmp_path / "root")
    assert expanded["windows"][0]["start_directory"] == str(tmp_path / "win")
    pane = expanded["windows"][0]["panes"][0]
    assert pane["start_directory"] == str(tmp_path / "pane")


def test_parser_load_arguments() -> None:
    """The load subparser captures the workspace file and the flags."""
    args = cli._build_parser().parse_args(
        ["load", "ws.yaml", "-d", "-L", "sock", "-s", "newname"],
    )
    assert args.command == "load"
    assert args.workspace_file == "ws.yaml"
    assert args.detached is True
    assert args.socket_name == "sock"
    assert args.new_session_name == "newname"
    assert args.fold is True  # builds fold by default


def test_parser_no_fold_flag() -> None:
    """``--no-fold`` opts out of dispatch chaining."""
    args = cli._build_parser().parse_args(["load", "ws.yaml", "--no-fold"])
    assert args.fold is False


def test_load_builds_and_reattaches(tmp_path: Path) -> None:
    """load() builds a real detached session; a second load attaches it (no rebuild)."""
    import libtmux

    socket = "libtmux_wscli_test"
    (tmp_path / ".tmuxp.yaml").write_text(
        "session_name: clitest\n"
        f"start_directory: {tmp_path}\n"
        "windows:\n"
        "  - window_name: editor\n"
        "    panes:\n"
        "      - echo one\n"
        "      - echo two\n"
        "  - window_name: logs\n"
        "    panes:\n"
        "      - echo log\n",
    )
    server = libtmux.Server(socket_name=socket)
    try:
        result = cli.load(str(tmp_path), socket_name=socket, detached=True)
        assert result is not None
        assert result.ok
        assert server.has_session("clitest")
        session = server.sessions.get(session_name="clitest")
        assert session is not None
        assert [window.window_name for window in session.windows] == ["editor", "logs"]

        # A second load finds the running session and attaches it (no rebuild).
        again = cli.load(str(tmp_path), socket_name=socket, detached=True)
        assert again is None
    finally:
        server.kill()


def test_dry_run_prints_commands_without_touching_tmux(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--dry-run renders the tmux commands (blank pane = no send) and runs nothing."""
    import libtmux

    socket = "libtmux_wscli_dryrun"
    (tmp_path / ".tmuxp.yaml").write_text(
        "session_name: dry\n"
        "windows:\n"
        "  - window_name: editor\n"
        "    panes:\n"
        "      - echo one\n"
        "      - blank\n",
    )
    result = cli.load(str(tmp_path), socket_name=socket, dry_run=True)
    assert result is None

    out = capsys.readouterr().out
    assert f"tmux -L {socket} new-session" in out  # socket prefix + create
    assert "split-window" in out  # the blank pane is still created
    assert "echo one" in out
    # the blank pane sends no command, so exactly one send-keys line is rendered
    assert out.count("send-keys") == 1
    # the default dry run folds: the header says so and rename + send chain
    assert "folded" in out
    assert "\\;" in out
    # nothing was executed: no tmux server exists on the dry-run socket
    assert not libtmux.Server(socket_name=socket).is_alive()


def test_dry_run_folds_split_and_send_into_one_dispatch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A split pane with a command renders as one {marked} dispatch by default."""
    (tmp_path / ".tmuxp.yaml").write_text(
        "session_name: dryfold\n"
        "windows:\n"
        "  - window_name: editor\n"
        "    panes:\n"
        "      - echo one\n"
        "      - echo two\n",
    )
    cli.load(str(tmp_path), socket_name="libtmux_wscli_fold", dry_run=True)
    out = capsys.readouterr().out

    # the second pane's split + send-keys collapse into a single {marked} chain
    marked = [line for line in out.splitlines() if "{marked}" in line]
    assert len(marked) == 1
    assert "split-window" in marked[0] and "send-keys" in marked[0]
    assert "\\;" in marked[0]


def test_dry_run_no_fold_renders_one_call_per_op(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--no-fold`` prints an unchained, one-op-per-line plan."""
    (tmp_path / ".tmuxp.yaml").write_text(
        "session_name: dryseq\n"
        "windows:\n"
        "  - window_name: editor\n"
        "    panes:\n"
        "      - echo one\n"
        "      - echo two\n",
    )
    cli.load(str(tmp_path), socket_name="libtmux_wscli_seq", dry_run=True, fold=False)
    out = capsys.readouterr().out

    assert "sequential" in out
    assert "\\;" not in out  # nothing chained
    assert "{marked}" not in out  # no marked fold
