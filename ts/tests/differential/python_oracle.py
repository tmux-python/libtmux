"""Regex oracle for the TypeScript port's differential corpus.

Evaluates the shared corpus with Python's :mod:`re` so the Bun and Node
engines can be compared against the semantics libtmux already ships.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import pathlib
import sys
import typing as t

BASELINE_COMMIT = "38e368c11117fb4aeb2f082d552cd4f210eae06a"
PROTOCOL = "libtmux-differential-v1"
BASELINE_LISTING_DIGEST = (
    "24be5e548a27374719ceb4a628dfda280946881f0320a92247105842974059e5"
)


def fail(message: str) -> t.NoReturn:
    """Exit with one diagnostic and no protocol output."""
    print(message, file=sys.stderr)
    raise SystemExit(2)


def load_pinned_libtmux() -> t.Any:
    """Load libtmux only from the materialized baseline commit."""
    raw_root = os.environ.get("LIBTMUX_ORACLE_ROOT")
    if not raw_root:
        fail("isolated Python 0.62.0 source root is required")
    root = pathlib.Path(raw_root).resolve(strict=True)
    marker_path = root / ".libtmux-oracle.json"
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"isolated Python provenance marker is invalid: {error}")
    if not isinstance(marker, dict) or set(marker) != {
        "commit",
        "listingBase64",
        "listingDigest",
        "protocol",
    }:
        fail("isolated Python provenance marker has invalid fields")
    if (
        marker["commit"] != BASELINE_COMMIT
        or marker["protocol"] != "libtmux-python-oracle-root-v1"
        or marker["listingDigest"] != BASELINE_LISTING_DIGEST
        or not isinstance(marker["listingBase64"], str)
    ):
        fail("isolated Python provenance marker does not match v0.62.0")
    try:
        listing = base64.b64decode(marker["listingBase64"], validate=True)
    except (ValueError, TypeError) as error:
        fail(f"isolated Python provenance listing is invalid: {error}")
    if hashlib.sha256(listing).hexdigest() != BASELINE_LISTING_DIGEST:
        fail("isolated Python provenance listing digest does not match v0.62.0")

    expected: dict[str, str] = {}
    for raw_line in listing.decode("utf-8").splitlines():
        metadata, path = raw_line.split("\t", 1)
        mode, kind, oid = metadata.split(" ")
        if mode != "100644" or kind != "blob" or not path.startswith("src/libtmux/"):
            fail("isolated Python provenance listing has an unsupported entry")
        expected[path.removeprefix("src/")] = oid

    source_package = root / "src" / "libtmux"
    observed: dict[str, str] = {}
    for path in source_package.rglob("*"):
        if path.is_symlink() or not path.is_file():
            if path.is_symlink():
                fail("isolated Python provenance tree contains a symlink")
            continue
        relative = path.relative_to(root / "src").as_posix()
        content = path.read_bytes()
        framed = b"blob " + str(len(content)).encode("ascii") + b"\0" + content
        observed[relative] = hashlib.sha1(framed).hexdigest()
    if observed != expected:
        fail("isolated Python provenance tree content does not match v0.62.0")

    source = (root / "src").resolve(strict=True)
    sys.path.insert(0, str(source))
    import libtmux

    imported = pathlib.Path(libtmux.__file__).resolve(strict=True)
    try:
        imported.relative_to(source)
    except ValueError:
        fail("Python oracle imported libtmux outside the pinned source root")
    if libtmux.__version__ != "0.62.0":
        fail(f"Python oracle expected 0.62.0, received {libtmux.__version__}")
    return libtmux


def read_request() -> dict[str, t.Any]:
    """Read exactly one strictly framed request."""
    first = sys.stdin.buffer.readline()
    trailing = sys.stdin.buffer.read()
    if not first.endswith(b"\n") or trailing != b"":
        fail("differential request must be exactly one newline-terminated frame")
    try:
        request = json.loads(first)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"differential request is invalid JSON: {error}")
    if not isinstance(request, dict) or set(request) != {
        "operation",
        "protocol",
        "requestId",
        "socketPath",
    }:
        fail("differential request has invalid fields")
    if request["protocol"] != PROTOCOL or request["operation"] != "list-sessions":
        fail("differential request has an unsupported protocol or operation")
    if not isinstance(request["requestId"], str) or request["requestId"] == "":
        fail("differential requestId must not be empty")
    if not isinstance(request["socketPath"], str) or request["socketPath"] == "":
        fail("differential socketPath must not be empty")
    return request


libtmux = load_pinned_libtmux()
request = read_request()
server = libtmux.Server(socket_path=request["socketPath"])
raw = server.cmd("list-sessions", "-F", "#{session_name}")
stdout_bytes = ("\n".join(raw.stdout) + ("\n" if raw.stdout else "")).encode()
stderr_bytes = ("\n".join(raw.stderr) + ("\n" if raw.stderr else "")).encode()
sessions = sorted(
    session.session_name
    for session in server.sessions
    if session.session_name is not None
)
response = {
    "diagnostics": [],
    "implementation": "python-0.62.0",
    "protocol": PROTOCOL,
    "requestId": request["requestId"],
    "returncode": raw.returncode,
    "semantics": {"sessions": sessions},
    "stderrBase64": base64.b64encode(stderr_bytes).decode("ascii"),
    "stdoutBase64": base64.b64encode(stdout_bytes).decode("ascii"),
}
sys.stdout.write(json.dumps(response, separators=(",", ":"), sort_keys=True) + "\n")
