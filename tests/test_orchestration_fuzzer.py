"""Behavioral checks for the active orchestration stream service."""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import time
import types
import typing as t

import pytest


@pytest.fixture()
def fuzzer_module() -> types.ModuleType:
    """Load the standalone fuzzer script without requiring Rich."""
    script = pathlib.Path(__file__).parents[1] / "scripts" / "orchestration_fuzzer.py"
    spec = importlib.util.spec_from_file_location("orchestration_fuzzer", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_stream_for_pane_reserves_only_selected_ordinal(
    fuzzer_module: types.ModuleType,
) -> None:
    """Only the chosen pane ordinal receives the delayed-match stream."""
    observed = [
        fuzzer_module.stream_for_pane(ordinal, delayed_ordinal=2).value
        for ordinal in range(8)
    ]

    assert observed == [
        "editor",
        "dev-server",
        "delayed-match",
        "installer",
        "editor",
        "dev-server",
        "installer",
        "editor",
    ]


def test_sentinel_text_is_unique_to_run_and_request(
    fuzzer_module: types.ModuleType,
) -> None:
    """A delayed match cannot be confused with another run or request."""
    assert (
        fuzzer_module.sentinel_text("run-7", "sample-03", "READY")
        == "LIBTMUX_SENTINEL run=run-7 request=sample-03 value=READY"
    )


def test_source_lines_uses_sorted_paths_and_a_private_seeded_shuffle(
    fuzzer_module: types.ModuleType,
    tmp_path: pathlib.Path,
) -> None:
    """Corpus ordering is repeatable even when the filesystem order differs."""
    source_root = tmp_path / "project"
    source = source_root / "src" / "libtmux"
    source.mkdir(parents=True)
    (source / "zeta.py").write_bytes(b"zeta one\nzeta two\n")
    (source / "alpha.py").write_bytes(b"alpha one\n")

    assert fuzzer_module.source_lines(source_root, seed=7) == (
        "src/libtmux/zeta.py:2: zeta two",
        "src/libtmux/alpha.py:1: alpha one",
        "src/libtmux/zeta.py:1: zeta one",
    )


def test_render_frame_uses_only_its_mode_epoch_and_seeded_corpus(
    fuzzer_module: types.ModuleType,
) -> None:
    """Frame rendering has stable mode-specific output for a fixed input."""
    corpus = ("src/libtmux/alpha.py:1: alpha", "src/libtmux/zeta.py:2: zeta")

    editor = fuzzer_module.render_frame(
        fuzzer_module.StreamMode.EDITOR,
        epoch=4,
        corpus=corpus,
        seed=11,
    )
    installer = fuzzer_module.render_frame(
        fuzzer_module.StreamMode.INSTALLER,
        epoch=4,
        corpus=corpus,
        seed=11,
    )

    assert editor.text == "[editor epoch=4] src/libtmux/zeta.py:2: zeta\n"
    assert installer.text == "[installer epoch=4] install phase=install unit=5/8\n"


def write_marker(path: pathlib.Path, data: dict[str, t.Any]) -> None:
    """Publish one complete marker without exposing a partial JSON document."""
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(data), encoding="utf-8")
    temporary.replace(path)


def wait_for(predicate: t.Callable[[], bool], timeout_s: float = 3.0) -> None:
    """Wait for an observable external condition or fail with a useful timeout."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    pytest.fail("timed out waiting for fuzzer marker state")


def read_json(path: pathlib.Path) -> dict[str, t.Any]:
    """Read one completed JSON marker."""
    return t.cast(dict[str, t.Any], json.loads(path.read_text(encoding="utf-8")))


def start_serve(output_dir: pathlib.Path) -> subprocess.Popen[str]:
    """Start the standalone fuzzer with a short deterministic service cadence."""
    root = pathlib.Path(__file__).parents[1]
    environment = os.environ.copy()
    environment.pop("VIRTUAL_ENV", None)
    return subprocess.Popen(
        (
            sys.executable,
            str(root / "scripts" / "orchestration_fuzzer.py"),
            "serve",
            "--output-dir",
            str(output_dir),
            "--run-id",
            "run-7",
            "--source-root",
            str(root),
            "--seed",
            "11",
            "--frame-rate",
            "100",
            "--duration",
            "10",
            "--delayed-match-after",
            "0.02",
            "--sentinel-prefix",
            "READY",
            "--heartbeat-interval",
            "0.01",
        ),
        cwd=root,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def finish_process(process: subprocess.Popen[str]) -> None:
    """Ensure a failed service assertion cannot leak a fuzzer process."""
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=3)


def test_serve_pauses_until_a_matching_gate_and_handles_repeated_requests(
    tmp_path: pathlib.Path,
) -> None:
    """A gated service emits each request sentinel once and exits on matching stop."""
    output_dir = tmp_path / "fuzzer-output"
    process = start_serve(output_dir)

    try:
        ready = output_dir / "ready.json"
        streams = output_dir / "streams"
        requests = output_dir / "requests"
        sentinels = output_dir / "sentinels"
        wait_for(ready.exists)

        assert read_json(ready) == {"schema_version": 1, "run_id": "run-7"}
        stream_paths = [
            streams / f"{mode}.log"
            for mode in (
                "editor",
                "dev-server",
                "installer",
                "delayed-match",
            )
        ]
        assert all(path.read_bytes() == b"" for path in stream_paths)

        write_marker(output_dir / "gate.json", {"schema_version": 1, "run_id": "other"})
        time.sleep(0.05)
        assert all(path.read_bytes() == b"" for path in stream_paths)

        (output_dir / "gate.json").write_text("{not-json", encoding="utf-8")
        time.sleep(0.05)
        assert all(path.read_bytes() == b"" for path in stream_paths)

        write_marker(output_dir / "gate.json", {"schema_version": 1, "run_id": "run-7"})
        wait_for(lambda: all(path.read_bytes() for path in stream_paths))

        write_marker(
            requests / "wrong-run.json",
            {
                "schema_version": 1,
                "run_id": "other",
                "request_id": "wrong-run",
                "requested_monotonic_ns": time.monotonic_ns(),
                "value": "READY",
            },
        )
        (requests / "malformed.json").write_text("[", encoding="utf-8")
        time.sleep(0.05)
        assert not (sentinels / "wrong-run.json").exists()
        assert not (sentinels / "malformed.json").exists()

        request_ids = ("sample-00", "sample-01")
        for request_id in request_ids:
            requested = time.monotonic_ns()
            write_marker(
                requests / f"{request_id}.json",
                {
                    "schema_version": 1,
                    "run_id": "run-7",
                    "request_id": request_id,
                    "requested_monotonic_ns": requested,
                    "value": "READY",
                },
            )
            evidence_path = sentinels / f"{request_id}.json"
            wait_for(evidence_path.exists)
            evidence = read_json(evidence_path)
            assert evidence["schema_version"] == 1
            assert evidence["run_id"] == "run-7"
            assert evidence["request_id"] == request_id
            assert evidence["scheduled_monotonic_ns"] >= requested
            assert (
                evidence["emitted_monotonic_ns"] >= evidence["scheduled_monotonic_ns"]
            )
            assert evidence["sentinel"] == (
                f"LIBTMUX_SENTINEL run=run-7 request={request_id} value=READY"
            )
            delayed_stream = (streams / "delayed-match.log").read_text(encoding="utf-8")
            assert delayed_stream.count(evidence["sentinel"]) == 1

            def ordinary_frame_follows(sentinel: str = evidence["sentinel"]) -> bool:
                """Check that the service resumed normal delayed-stream output."""
                return (streams / "delayed-match.log").read_text(
                    encoding="utf-8"
                ).rstrip().splitlines()[-1] != sentinel

            wait_for(ordinary_frame_follows)

        write_marker(output_dir / "stop.json", {"schema_version": 1, "run_id": "run-7"})
        assert process.wait(timeout=3) == 0
        heartbeat = read_json(output_dir / "heartbeat.json")
        assert heartbeat["schema_version"] == 1
        assert heartbeat["run_id"] == "run-7"
        assert heartbeat["state"] == "stopped"
    finally:
        finish_process(process)
