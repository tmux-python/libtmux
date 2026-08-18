"""Behavioral checks for the active orchestration stream service."""

from __future__ import annotations

import hashlib
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


@pytest.mark.parametrize(
    ("filename", "request_id"),
    (
        ("nested.json.json", "nested.json"),
        (".json", ".json"),
        ("space id.json", "space id"),
        ("unicode-π.json", "unicode-π"),
    ),
)
def test_request_marker_rejects_noncanonical_filename_payload_id(
    fuzzer_module: types.ModuleType,
    filename: str,
    request_id: str,
) -> None:
    """Ambiguous request filenames must not become marker or evidence paths."""
    options = fuzzer_module.WorkloadOptions(
        pathlib.Path("out"),
        "run-7",
        pathlib.Path(),
        0,
        1.0,
        1.0,
        0.0,
        "READY",
        1.0,
    )

    assert (
        fuzzer_module._request_from_marker(
            {
                "request_id": request_id,
                "requested_monotonic_ns": 7,
                "value": "READY",
            },
            pathlib.Path(filename),
            options,
            seen_request_ids=set(),
        )
        is None
    )


def test_request_marker_rejects_duplicate_payload_id(
    fuzzer_module: types.ModuleType,
) -> None:
    """A previously accepted request ID cannot be scheduled a second time."""
    options = fuzzer_module.WorkloadOptions(
        pathlib.Path("out"),
        "run-7",
        pathlib.Path(),
        0,
        1.0,
        1.0,
        0.0,
        "READY",
        1.0,
    )

    assert (
        fuzzer_module._request_from_marker(
            {
                "request_id": "sample-1",
                "requested_monotonic_ns": 7,
                "value": "READY",
            },
            pathlib.Path("sample-1.json"),
            options,
            seen_request_ids={"sample-1"},
        )
        is None
    )


def test_durable_stream_append_flushes_and_fsyncs_exact_bytes(
    fuzzer_module: types.ModuleType,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evidence publication must follow a durable exact sentinel append."""
    stream = tmp_path / "delayed-match.log"
    stream.touch()
    observed: list[bytes] = []

    def record_fsync(_file_descriptor: int) -> None:
        observed.append(stream.read_bytes())

    monkeypatch.setattr(fuzzer_module.os, "fsync", record_fsync)

    count = fuzzer_module._append_text(stream, "sentinel\n", durable=True)

    assert count == 9
    assert observed == [b"sentinel\n"]


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


def test_serve_evidence_preserves_request_delay_and_lateness(
    tmp_path: pathlib.Path,
) -> None:
    """Evidence separates requested delay from scheduling lateness."""
    output_dir = tmp_path / "evidence-output"
    process = start_serve(output_dir)

    try:
        wait_for(lambda: (output_dir / "ready.json").exists())
        write_marker(output_dir / "gate.json", {"schema_version": 1, "run_id": "run-7"})
        requested = time.monotonic_ns()
        write_marker(
            output_dir / "requests" / "sample-delay.json",
            {
                "schema_version": 1,
                "run_id": "run-7",
                "request_id": "sample-delay",
                "requested_monotonic_ns": requested,
                "value": "READY",
            },
        )
        evidence_path = output_dir / "sentinels" / "sample-delay.json"
        wait_for(evidence_path.exists)
        evidence = read_json(evidence_path)

        assert evidence["requested_monotonic_ns"] == requested
        assert evidence["configured_delay_ns"] == 20_000_000
        assert evidence["scheduled_monotonic_ns"] == requested + 20_000_000
        assert evidence["scheduling_lateness_ns"] == (
            evidence["emitted_monotonic_ns"] - evidence["scheduled_monotonic_ns"]
        )
        assert (
            evidence["sentinel_sha256"]
            == hashlib.sha256(f"{evidence['sentinel']}\n".encode()).hexdigest()
        )
    finally:
        write_marker(output_dir / "stop.json", {"schema_version": 1, "run_id": "run-7"})
        finish_process(process)


def test_serve_ignores_boolean_and_float_schema_versions(
    tmp_path: pathlib.Path,
) -> None:
    """Only an integer schema version activates gates, requests, or stops."""
    output_dir = tmp_path / "schema-output"
    process = start_serve(output_dir)

    try:
        ready = output_dir / "ready.json"
        streams = output_dir / "streams"
        requests = output_dir / "requests"
        sentinels = output_dir / "sentinels"
        wait_for(ready.exists)
        stream_paths = [
            streams / f"{mode}.log"
            for mode in (
                "editor",
                "dev-server",
                "installer",
                "delayed-match",
            )
        ]

        for invalid_version in (True, 1.0):
            write_marker(
                output_dir / "gate.json",
                {"schema_version": invalid_version, "run_id": "run-7"},
            )
            time.sleep(0.05)
            assert all(path.read_bytes() == b"" for path in stream_paths)

        write_marker(output_dir / "gate.json", {"schema_version": 1, "run_id": "run-7"})
        wait_for(lambda: all(path.read_bytes() for path in stream_paths))

        for invalid_version, request_id in (
            (True, "bool-request"),
            (1.0, "float-request"),
        ):
            write_marker(
                requests / f"{request_id}.json",
                {
                    "schema_version": invalid_version,
                    "run_id": "run-7",
                    "request_id": request_id,
                    "requested_monotonic_ns": time.monotonic_ns(),
                    "value": "READY",
                },
            )
        time.sleep(0.1)
        assert not (sentinels / "bool-request.json").exists()
        assert not (sentinels / "float-request.json").exists()

        for invalid_version in (True, 1.0):
            write_marker(
                output_dir / "stop.json",
                {"schema_version": invalid_version, "run_id": "run-7"},
            )
            time.sleep(0.05)
            assert process.poll() is None

        write_marker(output_dir / "stop.json", {"schema_version": 1, "run_id": "run-7"})
        assert process.wait(timeout=3) == 0
    finally:
        finish_process(process)


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
            assert (
                evidence["sentinel_sha256"]
                == hashlib.sha256(f"{evidence['sentinel']}\n".encode()).hexdigest()
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


def test_serve_processes_sorted_requests_sequentially_and_rejects_duplicate(
    tmp_path: pathlib.Path,
) -> None:
    """Sorted unseen IDs emit once each even when requests arrive together."""
    output_dir = tmp_path / "ordered-output"
    process = start_serve(output_dir)

    try:
        wait_for(lambda: (output_dir / "ready.json").exists())
        write_marker(output_dir / "gate.json", {"schema_version": 1, "run_id": "run-7"})
        requested = time.monotonic_ns()
        for request_id in ("z-last", "a-first"):
            write_marker(
                output_dir / "requests" / f"{request_id}.json",
                {
                    "schema_version": 1,
                    "run_id": "run-7",
                    "request_id": request_id,
                    "requested_monotonic_ns": requested,
                    "value": request_id,
                },
            )
        first_path = output_dir / "sentinels" / "a-first.json"
        last_path = output_dir / "sentinels" / "z-last.json"
        wait_for(lambda: first_path.exists() and last_path.exists())
        first = read_json(first_path)
        last = read_json(last_path)

        assert first["emitted_monotonic_ns"] <= last["emitted_monotonic_ns"]
        delayed = output_dir / "streams" / "delayed-match.log"
        original = delayed.read_text(encoding="utf-8")
        assert original.count(first["sentinel"]) == 1
        assert original.count(last["sentinel"]) == 1

        write_marker(
            output_dir / "requests" / "a-first.json",
            {
                "schema_version": 1,
                "run_id": "run-7",
                "request_id": "a-first",
                "requested_monotonic_ns": time.monotonic_ns(),
                "value": "DUPLICATE",
            },
        )
        time.sleep(0.1)

        after_duplicate = delayed.read_text(encoding="utf-8")
        assert after_duplicate.count(first["sentinel"]) == 1
        assert "value=DUPLICATE" not in after_duplicate
        assert read_json(first_path) == first
    finally:
        write_marker(output_dir / "stop.json", {"schema_version": 1, "run_id": "run-7"})
        finish_process(process)
