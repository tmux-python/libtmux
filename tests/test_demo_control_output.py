"""Behavioral checks for the bounded async control-output demo."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import typing as t

import pytest


def _write_source_corpus(root: pathlib.Path) -> dict[str, bytes]:
    """Write a small, deterministic Python corpus and return its contents."""
    files = {
        "alpha.py": b"from __future__ import annotations\n\nALPHA = 1\n",
        "bravo.py": b"def bravo() -> str:\n    return 'bravo'\n",
        "charlie.py": b"class Charlie:\n    value = 3\n",
        "delta.py": b"async def delta() -> int:\n    return 4\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (root / "ignored.txt").write_text("not Python\n")
    return files


def _run_demo(
    tmp_path: pathlib.Path,
    *args: str,
) -> tuple[subprocess.CompletedProcess[str], dict[str, t.Any]]:
    """Run the real CLI in an isolated temporary directory and read its report."""
    root = pathlib.Path(__file__).parents[1]
    output = tmp_path / f"report-{len(list(tmp_path.glob('report-*.json')))}.json"
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    env["TMPDIR"] = str(tmp_path)
    completed = subprocess.run(
        (
            "uv",
            "run",
            "scripts/demo_control_output.py",
            *args,
            "--json-out",
            str(output),
            "--quiet",
        ),
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=45,
    )
    report = json.loads(output.read_text()) if output.exists() else {}
    return completed, report


def test_scroll_selects_stable_sources_and_verifies_live_wxp_output(
    tmp_path: pathlib.Path,
) -> None:
    """The lossless demo routes and verifies all panes in a 2x2 topology."""
    corpus = tmp_path / "corpus"
    files = _write_source_corpus(corpus)

    completed, report = _run_demo(
        tmp_path,
        "scroll",
        "--source-root",
        str(corpus),
        "--seed",
        "13",
        "--windows",
        "2",
        "--panes",
        "2",
        "--lines",
        "4",
        "--delay",
        "0",
    )

    assert completed.returncode == 0, completed.stderr
    assert report["mode"] == "scroll"
    assert report["topology"] == {
        "windows": 2,
        "panes_per_window": 2,
        "total_panes": 4,
    }
    assert [pane["source"] for pane in report["panes"]] == [
        "alpha.py",
        "bravo.py",
        "delta.py",
        "charlie.py",
    ]
    assert all(pane["verified"] for pane in report["panes"])
    assert all(pane["frames"] == 4 for pane in report["panes"])
    assert all(pane["first_sequence"] == 0 for pane in report["panes"])
    assert all(pane["last_sequence"] == 3 for pane in report["panes"])
    assert all(
        pane["source_sha256"] == hashlib.sha256(files[pane["source"]]).hexdigest()
        for pane in report["panes"]
    )
    assert all(len(pane["stream_sha256"]) == 64 for pane in report["panes"])
    assert report["dropped_frames"] == 0
    assert report["responsive"] is True


def test_overload_reports_drops_and_keeps_engine_responsive(
    tmp_path: pathlib.Path,
) -> None:
    """A deliberately stalled size-one subscriber drops frames, then recovers."""
    corpus = tmp_path / "corpus"
    _write_source_corpus(corpus)

    completed, report = _run_demo(
        tmp_path,
        "overload",
        "--source-root",
        str(corpus),
        "--seed",
        "21",
        "--windows",
        "2",
        "--panes",
        "2",
        "--lines",
        "512",
    )

    assert completed.returncode == 0, completed.stderr
    assert report["mode"] == "overload"
    assert report["dropped_frames"] > 0
    assert report["observed_frames"] > 0
    assert report["responsive"] is True
    assert report["lossless"] is False


def test_demo_removes_server_and_scratch_state(tmp_path: pathlib.Path) -> None:
    """A completed demo leaves neither its tmux server nor scratch directory."""
    corpus = tmp_path / "corpus"
    _write_source_corpus(corpus)

    completed, report = _run_demo(
        tmp_path,
        "scroll",
        "--source-root",
        str(corpus),
        "--windows",
        "1",
        "--panes",
        "1",
        "--lines",
        "2",
        "--delay",
        "0",
    )

    assert completed.returncode == 0, completed.stderr
    assert report["cleanup"] == {
        "scratch_removed": True,
        "server_stopped": True,
    }
    assert list(tmp_path.glob("ltout-*")) == []


def test_scroll_rebalances_an_eight_pane_window(tmp_path: pathlib.Path) -> None:
    """A large pane demo retiles while splitting instead of exhausting geometry."""
    corpus = tmp_path / "corpus"
    _write_source_corpus(corpus)

    completed, report = _run_demo(
        tmp_path,
        "scroll",
        "--source-root",
        str(corpus),
        "--windows",
        "1",
        "--panes",
        "8",
        "--lines",
        "1",
        "--delay",
        "0",
    )

    assert completed.returncode == 0, completed.stderr
    assert report["topology"]["total_panes"] == 8
    assert report["dropped_frames"] == 0


def test_demo_ignores_a_hostile_user_tmux_config(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user after-new-session hook cannot kill the isolated demo server."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".tmux.conf").write_text("set-hook -g after-new-session 'kill-server'\n")
    monkeypatch.setenv("HOME", str(home))
    corpus = tmp_path / "corpus"
    _write_source_corpus(corpus)

    completed, report = _run_demo(
        tmp_path,
        "scroll",
        "--source-root",
        str(corpus),
        "--windows",
        "1",
        "--panes",
        "1",
        "--lines",
        "1",
        "--delay",
        "0",
    )

    assert completed.returncode == 0, completed.stderr
    assert report["responsive"] is True
