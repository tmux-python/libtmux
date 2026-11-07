"""Executable selection and metadata probes use the captured client environment."""

from __future__ import annotations

import json
import os
import pathlib
import shutil

import pytest

from libtmux import Server, exc
from libtmux._internal.control_mode import ControlMode
from libtmux.common import get_version


def _recording_executable(path: pathlib.Path, log: pathlib.Path, binary: str) -> None:
    path.write_text(
        "#!/usr/bin/python3\n"
        "import json, os, sys\n"
        f"with open({str(log)!r}, 'a') as output:\n"
        "    output.write(json.dumps({'executable': sys.argv[0], "
        "'args': sys.argv[1:], 'marker': os.getenv('LIBTMUX_CLIENT_MARKER')})"
        " + '\\n')\n"
        f"os.execv({binary!r}, [{binary!r}, *sys.argv[1:]])\n",
    )
    path.chmod(0o700)


@pytest.mark.parametrize("selector", [None, "custom-tmux"])
def test_server_freezes_executable_before_first_command(
    server: Server,
    tmp_path: pathlib.Path,
    selector: str | None,
) -> None:
    """Adding an earlier PATH candidate must not change an existing handle."""
    binary = shutil.which("tmux")
    assert binary is not None
    early, selected = tmp_path / "early", tmp_path / "selected"
    early.mkdir()
    selected.mkdir()
    name = selector or "tmux"
    log = tmp_path / "launches.jsonl"
    _recording_executable(selected / name, log, binary)
    captured = Server(
        socket_path=server.socket_path,
        tmux_bin=selector,
        child_environment={"PATH": f"{early}:{selected}"},
    )
    _recording_executable(early / name, log, binary)
    result = captured.cmd("-V")
    assert result.returncode == 0
    launches = [json.loads(line) for line in log.read_text().splitlines()]
    assert {item["executable"] for item in launches} == {str(selected / name)}


def test_version_and_control_launches_keep_captured_environment(
    server: Server,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Observe real version, query, control and cleanup launches through a shim."""
    binary = shutil.which("tmux")
    assert binary is not None
    log = tmp_path / "launches.jsonl"
    _recording_executable(tmp_path / "tmux", log, binary)
    captured = Server(
        socket_path=server.socket_path,
        config_file="/dev/null",
        child_environment={"PATH": str(tmp_path), "LIBTMUX_CLIENT_MARKER": "captured"},
    )
    monkeypatch.setenv("LIBTMUX_CLIENT_MARKER", "changed")
    get_version.cache_clear()
    with captured.new_session(session_name="captured_environment") as session:
        with ControlMode(captured, session):
            assert len(session.windows) == 1
        captured.raise_if_dead()
    launches = [json.loads(line) for line in log.read_text().splitlines()]
    assert any(item["args"] == ["-V"] for item in launches)
    assert any("-C" in item["args"] for item in launches)
    assert all(item["marker"] == "captured" for item in launches)
    assert os.environ["LIBTMUX_CLIENT_MARKER"] == "changed"


def test_relative_executable_path_retains_construction_directory(
    server: Server,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing cwd cannot redirect an explicit relative executable path."""
    binary = shutil.which("tmux")
    assert binary is not None
    log = tmp_path / "launches.jsonl"
    _recording_executable(tmp_path / "tmux", log, binary)
    monkeypatch.chdir(tmp_path)
    captured = Server(socket_path=server.socket_path, tmux_bin="./tmux")
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    assert captured.cmd("-V").returncode == 0
    assert pathlib.Path(json.loads(log.read_text())["executable"]) == tmp_path / "tmux"


def test_missing_captured_executable_does_not_use_later_path(
    server: Server,
    tmp_path: pathlib.Path,
) -> None:
    """Failure to resolve an executable remains a failure after construction."""
    binary = shutil.which("tmux")
    assert binary is not None
    captured = Server(
        socket_path=server.socket_path, child_environment={"PATH": str(tmp_path)}
    )
    _recording_executable(tmp_path / "tmux", tmp_path / "unexpected.jsonl", binary)
    with pytest.raises(exc.TmuxCommandNotFound):
        captured.cmd("-V")
    assert not (tmp_path / "unexpected.jsonl").exists()
