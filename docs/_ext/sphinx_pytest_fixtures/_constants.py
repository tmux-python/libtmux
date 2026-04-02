from __future__ import annotations

import re
import typing as t


class SetupDict(t.TypedDict):
    """Return type for Sphinx extension setup()."""

    version: str
    env_version: int
    parallel_read_safe: bool
    parallel_write_safe: bool


# ---------------------------------------------------------------------------
# Extension identity and version
# ---------------------------------------------------------------------------

_EXTENSION_KEY = "sphinx_pytest_fixtures"
"""Domaindata namespace key used in ``env.domaindata``."""

_EXTENSION_VERSION = "1.0"
"""Reported in ``setup()`` return dict."""

# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, str] = {
    "scope": "function",
    "kind": "resource",
    "usage": "auto",
}

# ---------------------------------------------------------------------------
# Field labels for rendered metadata
# ---------------------------------------------------------------------------

_FIELD_LABELS: dict[str, str] = {
    "scope": "Scope",
    "depends": "Depends on",
    "autouse": "Autouse",
    "kind": "Kind",
    "used_by": "Used by",
    "parametrized": "Parametrized",
}

# ---------------------------------------------------------------------------
# Callout messages for fixture cards
# ---------------------------------------------------------------------------

_CALLOUT_MESSAGES: dict[str, str] = {
    "autouse": (
        "No request needed \u2014 this fixture runs automatically for every test."
    ),
    "session_scope": (
        "Created once per test session and shared across all tests. "
        "Requesting this fixture does not create a new instance per test."
    ),
    "override_hook": (
        "This is an override hook. Override it in your project\u2019s "
        "conftest.py to customise behaviour for your test suite."
    ),
    "yield_fixture": (
        "This is a yield fixture \u2014 it runs setup code before yielding "
        "the value to the test, then teardown code after the test completes."
    ),
    "async_fixture": "This is an async fixture. Use it in async test functions.",
}

# ---------------------------------------------------------------------------
# Fixture index table structure
# ---------------------------------------------------------------------------

_INDEX_TABLE_COLUMNS: tuple[tuple[str, int], ...] = (
    ("Fixture", 20),
    ("Flags", 22),
    ("Returns", 12),
    ("Description", 46),
)

# ---------------------------------------------------------------------------
# Config attribute names (registered via app.add_config_value)
# ---------------------------------------------------------------------------

_CONFIG_HIDDEN_DEPS = "pytest_fixture_hidden_dependencies"
_CONFIG_BUILTIN_LINKS = "pytest_fixture_builtin_links"
_CONFIG_EXTERNAL_LINKS = "pytest_external_fixture_links"
_CONFIG_LINT_LEVEL = "pytest_fixture_lint_level"

# ---------------------------------------------------------------------------
# Intersphinx resolution keys
# ---------------------------------------------------------------------------

_INTERSPHINX_PROJECT = "pytest"
_INTERSPHINX_FIXTURE_ROLE = "std:fixture"

# ---------------------------------------------------------------------------
# Scopes that suppress the scope badge (function scope = no badge)
# ---------------------------------------------------------------------------

_SUPPRESSED_SCOPES: frozenset[str] = frozenset({"function"})

# ---------------------------------------------------------------------------
# Compiled regex patterns
# ---------------------------------------------------------------------------

_RST_INLINE_PATTERN = re.compile(
    r":(\w+):`([^`]+)`"  # :role:`content`
    r"|``([^`]+)``"  # ``literal``
    r"|`([^`]+)`"  # `interpreted text`
)
_IDENTIFIER_PATTERN = re.compile(r"(\b[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*\b)")

# ---------------------------------------------------------------------------
# Fixture metadata models — env-safe (all fields are pickle-safe primitives)
# ---------------------------------------------------------------------------

FixtureKind = t.Literal["resource", "factory", "override_hook"]
_KNOWN_KINDS: frozenset[str] = frozenset(t.get_args(FixtureKind))

_STORE_VERSION = 5
"""Bump whenever ``FixtureMeta`` or the store schema changes.

Used both as the Sphinx ``env_version`` (triggers full cache invalidation) and
as a runtime sentinel inside the store dict (guards against stale pickles on
incremental builds when ``env_version`` was not bumped).
"""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Fixtures hidden from "Depends on" entirely (low-value noise for readers).
# Does NOT include fixtures that have entries in PYTEST_BUILTIN_LINKS —
# those are shown with external hyperlinks instead of being hidden.
PYTEST_HIDDEN: frozenset[str] = frozenset(
    {
        "pytestconfig",
        "capfd",
        "capsysbinary",
        "capfdbinary",
        "recwarn",
        "tmpdir",
        "pytester",
        "testdir",
        "record_property",
        "record_xml_attribute",
        "record_testsuite_property",
        "cache",
    },
)

# External links for pytest built-in fixtures shown in "Depends on" blocks.
# Used as offline fallback when intersphinx inventory is unavailable.
PYTEST_BUILTIN_LINKS: dict[str, str] = {
    "tmp_path_factory": (
        "https://docs.pytest.org/en/stable/reference/fixtures.html#tmp_path_factory"
    ),
    "tmp_path": "https://docs.pytest.org/en/stable/reference/fixtures.html#tmp_path",
    "monkeypatch": (
        "https://docs.pytest.org/en/stable/reference/fixtures.html#monkeypatch"
    ),
    "request": "https://docs.pytest.org/en/stable/reference/fixtures.html#request",
    "capsys": "https://docs.pytest.org/en/stable/reference/fixtures.html#capsys",
    "caplog": "https://docs.pytest.org/en/stable/reference/fixtures.html#caplog",
}
