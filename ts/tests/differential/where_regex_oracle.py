"""Verify the shared query corpus with Python's native regex engine."""

from __future__ import annotations

import json
import pathlib
import re
import sys
import typing as t

FIXTURE_PATH = pathlib.Path(__file__).parents[1] / "fixtures" / "where_regex.json"
PROTOCOL = "libtmux-where-regex-v1"
REQUIRED_SHARED_ADAPTATIONS = {
    "native-multiline-line-feed": (
        "All three pinned native engines recognize LF as a multiline anchor boundary."
    ),
    "native-unicode-astral-dot": (
        "ECMAScript internal Unicode mode and Python native Unicode matching consume "
        "one astral code point for dot."
    ),
}


def fail(message: str) -> t.NoReturn:
    """Exit with one diagnostic and no protocol output."""
    print(message, file=sys.stderr)
    raise SystemExit(2)


def exact_keys(value: object, expected: set[str], label: str) -> dict[str, t.Any]:
    """Require one ordinary JSON object with an exact key set."""
    if not isinstance(value, dict) or set(value) != expected:
        fail(f"{label} has invalid fields")
    return value


def load_fixture() -> dict[str, t.Any]:
    """Load and validate the shared native-regex corpus."""
    try:
        raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"regex fixture is invalid: {error}")
    fixture = exact_keys(
        raw,
        {"adaptations", "cases", "protocol", "runtimes"},
        "regex fixture",
    )
    if fixture["protocol"] != PROTOCOL:
        fail("regex fixture protocol is unsupported")
    runtimes = exact_keys(
        fixture["runtimes"], {"bun", "node", "python"}, "runtime pins"
    )
    if runtimes != {"bun": "1.3.14", "node": "22", "python": "3"}:
        fail("regex fixture runtime pins changed")
    adaptations = fixture["adaptations"]
    if not isinstance(adaptations, dict) or not adaptations:
        fail("regex fixture adaptations must be a nonempty object")
    if any(
        not isinstance(key, str) or not key or not isinstance(value, str) or not value
        for key, value in adaptations.items()
    ):
        fail("regex fixture adaptations are invalid")
    for name, description in REQUIRED_SHARED_ADAPTATIONS.items():
        if adaptations.get(name) != description:
            fail(f"regex fixture adaptation {name} changed")
    cases = fixture["cases"]
    if not isinstance(cases, list) or len(cases) != 19:
        fail("regex fixture must contain exactly 19 cases")
    return fixture


def native_flags(case: dict[str, t.Any]) -> int:
    """Translate canonical data flags into Python native flags."""
    flags = case["flags"]
    if flags not in {"", "m", "s", "ms"}:
        fail(f"case {case['id']} has invalid flags")
    value = 0
    if "m" in flags:
        value |= re.MULTILINE
    if "s" in flags:
        value |= re.DOTALL
    if case["mode"] == "insensitive":
        value |= re.IGNORECASE
    elif case["mode"] != "default":
        fail(f"case {case['id']} has invalid mode")
    return value


fixture = load_fixture()
seen_ids: set[str] = set()
seen_session_ids: set[str] = set()
used_adaptations: set[str] = set()
observations: list[dict[str, t.Any]] = []
for index, raw_case in enumerate(fixture["cases"]):
    case = exact_keys(
        raw_case,
        {
            "adaptation",
            "expected",
            "flags",
            "id",
            "input",
            "mode",
            "pattern",
            "session_id",
        },
        f"regex case {index}",
    )
    if not isinstance(case["id"], str) or not case["id"] or case["id"] in seen_ids:
        fail(f"regex case {index} has an invalid or duplicate id")
    seen_ids.add(case["id"])
    if (
        not isinstance(case["session_id"], str)
        or re.fullmatch(r"\$\d+", case["session_id"]) is None
        or case["session_id"] in seen_session_ids
    ):
        fail(f"case {case['id']} has an invalid or duplicate session_id")
    seen_session_ids.add(case["session_id"])
    if not isinstance(case["pattern"], str) or not isinstance(case["input"], str):
        fail(f"case {case['id']} pattern and input must be strings")
    expected = exact_keys(
        case["expected"], {"bun", "node", "python"}, f"case {case['id']} expected"
    )
    if any(not isinstance(value, bool) for value in expected.values()):
        fail(f"case {case['id']} expectations must be booleans")
    adaptation = case["adaptation"]
    if adaptation is not None:
        if not isinstance(adaptation, str) or adaptation not in fixture["adaptations"]:
            fail(f"case {case['id']} names an unknown adaptation")
        used_adaptations.add(adaptation)
    try:
        observed = (
            re.search(case["pattern"], case["input"], native_flags(case)) is not None
        )
    except re.error as error:
        fail(f"case {case['id']} is not valid Python regex data: {error}")
    if observed is not expected["python"]:
        fail(
            f"case {case['id']} expected Python {expected['python']!r}, "
            f"observed {observed!r}"
        )
    observations.append({"id": case["id"], "matched": observed})

required_case_adaptations = {
    "astral-dot-unicode": "native-unicode-astral-dot",
    "lf-multiline-parity": "native-multiline-line-feed",
}
for case_id, adaptation in required_case_adaptations.items():
    matching = [case for case in fixture["cases"] if case["id"] == case_id]
    if len(matching) != 1 or matching[0]["adaptation"] != adaptation:
        fail(f"case {case_id} adaptation changed")

combined = next(
    (
        case
        for case in fixture["cases"]
        if case["id"] == "multiline-dotall-open-quantifier"
    ),
    None,
)
if combined is None:
    fail("combined regex case is missing")
unsatisfied_lower_bound = combined["pattern"].replace("{2,}", "{4,}")
if unsatisfied_lower_bound == combined["pattern"]:
    fail("combined regex case lacks its open lower bound")
for label, flags, pattern in [
    ("without-dotall", "m", combined["pattern"]),
    ("without-multiline", "s", combined["pattern"]),
    ("unsatisfied-lower-bound", "ms", unsatisfied_lower_bound),
]:
    control = {**combined, "flags": flags, "pattern": pattern}
    if (
        re.search(control["pattern"], control["input"], native_flags(control))
        is not None
    ):
        fail(f"combined regex case matched negative control {label}")

if used_adaptations != set(fixture["adaptations"]):
    fail("regex fixture contains an unused adaptation")

sys.stdout.write(
    json.dumps(
        {
            "cases": observations,
            "implementation": "python-native-re",
            "protocol": PROTOCOL,
            "runtime": (
                f"{sys.version_info.major}.{sys.version_info.minor}."
                f"{sys.version_info.micro}"
            ),
            "status": "passed",
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    + "\n"
)
