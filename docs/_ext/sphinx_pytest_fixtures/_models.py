"""Data models, dataclasses, protocols, and node types for sphinx_pytest_fixtures."""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from docutils import nodes

from sphinx_pytest_fixtures._constants import _DEFAULTS


@dataclass(frozen=True)
class FixtureDep:
    """A classified fixture dependency.

    All fields are primitive types so that ``FixtureDep`` can be pickled
    safely when stored in the Sphinx build environment.
    """

    display_name: str
    """Short display name, e.g. ``"config_file"``."""

    kind: t.Literal["fixture", "builtin", "external", "unresolved"]
    """Classification of the dependency."""

    target: str | None = None
    """Canonical name for project fixtures (used for reverse deps)."""

    url: str | None = None
    """External URL for builtin/external deps."""


@dataclass(frozen=True)
class FixtureMeta:
    """Env-safe fixture metadata stored per fixture in the build environment.

    All fields must be pickle-safe primitives — never store raw annotation
    objects (``type``, generics) here as they are not reliably picklable.

    Stored at ``env.domaindata["sphinx_pytest_fixtures"]["fixtures"][canonical_name]``.
    """

    docname: str
    """Sphinx docname of the page where this fixture is documented."""

    canonical_name: str
    """Fully-qualified name, e.g. ``"libtmux.pytest_plugin.server"``."""

    public_name: str
    """Pytest injection name, e.g. ``"server"`` (alias or function name)."""

    source_name: str
    """Real module attribute name, e.g. ``"_server"``."""

    scope: str
    """Fixture scope: ``"function"``, ``"session"``, ``"module"``, or ``"class"``."""

    autouse: bool
    """Whether the fixture runs automatically for every test."""

    kind: str
    """Fixture kind: one of :data:`FixtureKind` values, or a custom string."""

    return_display: str
    """Short type label, e.g. ``"Server"``."""

    return_xref_target: str | None
    """Simple class name for cross-referencing, or ``None`` for complex types."""

    deps: tuple[FixtureDep, ...]
    """Classified fixture dependencies."""

    param_reprs: tuple[str, ...]
    """``repr()`` of each parametrize value from the fixture marker."""

    has_teardown: bool
    """True when the fixture is a generator (yield-based) fixture."""

    is_async: bool
    """True when the fixture is an async function or async generator."""

    summary: str
    """First sentence of the fixture docstring (raw RST markup preserved)."""

    deprecated: str | None = None
    """Version string when the fixture is deprecated, or ``None``."""

    replacement: str | None = None
    """Canonical name of the replacement fixture, or ``None``."""

    teardown_summary: str | None = None
    """Short description of teardown/cleanup behavior, or ``None``."""


class autofixture_index_node(nodes.General, nodes.Element):
    """Placeholder replaced during ``doctree-resolved`` with a fixture index table."""


# ---------------------------------------------------------------------------
# Protocol for fixture marker (structural type for mypy safety)
# ---------------------------------------------------------------------------


class _FixtureMarker(t.Protocol):
    """Normalised fixture metadata — scope is ALWAYS a plain str."""

    @property
    def scope(self) -> str: ...  # never None, never Scope enum

    @property
    def autouse(self) -> bool: ...

    @property
    def params(self) -> t.Sequence[t.Any] | None: ...

    @property
    def name(self) -> str | None: ...


class _FixtureFunctionDefinitionAdapter:
    """Adapter: normalises pytest 9+ FixtureFunctionDefinition to _FixtureMarker.

    pytest 9+: .scope is a _pytest.scope.Scope enum — .value is the lowercase str.
    pytest <9: .scope may be str or None (None means function-scope).
    """

    __slots__ = ("_obj",)

    def __init__(self, obj: t.Any) -> None:
        self._obj = obj

    @property
    def scope(self) -> str:
        raw = self._obj.scope
        if hasattr(raw, "value"):  # pytest 9+: _pytest.scope.Scope enum
            return str(raw.value)
        return str(raw) if raw else _DEFAULTS["scope"]

    @property
    def autouse(self) -> bool:
        return bool(self._obj.autouse)

    @property
    def params(self) -> t.Sequence[t.Any] | None:
        return self._obj.params  # type: ignore[no-any-return]

    @property
    def name(self) -> str | None:
        return self._obj.name  # type: ignore[no-any-return]
