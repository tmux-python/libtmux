"""Fixture detection and classification helpers for sphinx_pytest_fixtures."""

from __future__ import annotations

import collections.abc
import inspect
import typing as t

from sphinx.util import logging as sphinx_logging
from sphinx.util.typing import stringify_annotation

from sphinx_pytest_fixtures._constants import (
    _CONFIG_BUILTIN_LINKS,
    _CONFIG_EXTERNAL_LINKS,
    _CONFIG_HIDDEN_DEPS,
    _DEFAULTS,
    PYTEST_BUILTIN_LINKS,
    PYTEST_HIDDEN,
)
from sphinx_pytest_fixtures._models import (
    _FixtureFunctionDefinitionAdapter,
    _FixtureMarker,
)

if t.TYPE_CHECKING:
    pass

logger = sphinx_logging.getLogger(__name__)


def _is_pytest_fixture(obj: t.Any) -> bool:
    """Return True if *obj* is a pytest fixture callable.

    Parameters
    ----------
    obj : Any
        The object to inspect.

    Returns
    -------
    bool
        True for pytest 9+ ``FixtureFunctionDefinition`` instances and older
        pytest fixtures marked with ``_fixture_function_marker``.
    """
    try:
        from _pytest.fixtures import FixtureFunctionDefinition

        if isinstance(obj, FixtureFunctionDefinition):
            return True
    except ImportError:
        pass
    return hasattr(obj, "_fixture_function_marker")


def _get_fixture_fn(obj: t.Any) -> t.Callable[..., t.Any]:
    """Return the raw underlying function from a fixture wrapper.

    Parameters
    ----------
    obj : Any
        A pytest fixture wrapper object.

    Returns
    -------
    Callable
        The unwrapped fixture function with original annotations and docstring.
    """
    if hasattr(obj, "_get_wrapped_function"):
        return obj._get_wrapped_function()  # type: ignore[no-any-return]
    if hasattr(obj, "_fixture_function"):
        return obj._fixture_function  # type: ignore[no-any-return]
    if hasattr(obj, "__wrapped__"):
        return obj.__wrapped__  # type: ignore[no-any-return]
    return t.cast("t.Callable[..., t.Any]", obj)


def _get_fixture_marker(obj: t.Any) -> _FixtureMarker:
    """Return normalised fixture metadata for *obj*.

    Handles pytest 9+ FixtureFunctionDefinition (scope is Scope enum) and
    older pytest fixtures (_fixture_function_marker attribute).

    Parameters
    ----------
    obj : Any
        A pytest fixture wrapper object.

    Returns
    -------
    _FixtureMarker
        Normalised marker object exposing ``scope`` (always a str),
        ``autouse``, ``params``, and ``name``.
    """
    try:
        from _pytest.fixtures import FixtureFunctionDefinition

        if isinstance(obj, FixtureFunctionDefinition):
            # FixtureFunctionDefinition wraps a FixtureFunctionMarker;
            # access the marker to get scope/autouse/params/name.
            marker = obj._fixture_function_marker
            return _FixtureFunctionDefinitionAdapter(marker)
    except ImportError:
        pass
    old_marker = getattr(obj, "_fixture_function_marker", None)
    if old_marker is not None:
        return _FixtureFunctionDefinitionAdapter(old_marker)
    msg = f"pytest fixture marker metadata not found on {type(obj).__name__!r}"
    raise AttributeError(msg)


def _iter_injectable_params(
    obj: t.Any,
) -> t.Iterator[tuple[str, inspect.Parameter]]:
    """Yield (name, param) for injectable (non-variadic) fixture parameters.

    Pytest injects all POSITIONAL_OR_KEYWORD and KEYWORD_ONLY params by name.
    POSITIONAL_ONLY parameters (before ``/``) cannot be injected by name — skip.
    VAR_POSITIONAL (*args) and VAR_KEYWORD (**kwargs) are also skipped.

    Parameters
    ----------
    obj : Any
        A pytest fixture wrapper object.

    Yields
    ------
    tuple[str, inspect.Parameter]
        ``(name, param)`` pairs for injectable fixture parameters only.
    """
    sig = inspect.signature(_get_fixture_fn(obj))
    for name, param in sig.parameters.items():
        if param.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        yield name, param


def _get_user_deps(
    obj: t.Any,
    hidden: frozenset[str] | None = None,
) -> list[tuple[str, t.Any]]:
    """Return ``(name, annotation)`` pairs for user-visible fixture dependencies.

    Parameters
    ----------
    obj : Any
        A pytest fixture wrapper object.
    hidden : frozenset[str] | None
        Names to exclude from the dependency list.  When ``None``, falls back
        to the module-level :data:`PYTEST_HIDDEN` constant.

    Returns
    -------
    list[tuple[str, Any]]
        Parameters of the wrapped function that are not pytest built-in fixtures.
        These are the fixtures users need to provide (or that are auto-provided
        by other project fixtures).
    """
    if hidden is None:
        hidden = PYTEST_HIDDEN
    return [
        (name, param.annotation)
        for name, param in _iter_injectable_params(obj)
        if name not in hidden
    ]


def _classify_deps(
    obj: t.Any,
    app: t.Any,
) -> tuple[list[str], dict[str, str], list[str]]:
    """Classify fixture dependencies into three buckets.

    Parameters
    ----------
    obj : Any
        A pytest fixture wrapper object.
    app : Any
        The Sphinx application (may be ``None`` in unit-test contexts).

    Returns
    -------
    tuple[list[str], dict[str, str], list[str]]
        ``(project_deps, builtin_deps, hidden_deps)`` where:

        * *project_deps* — dep names to render as ``:fixture:`` cross-refs
        * *builtin_deps* — dict mapping dep name → external URL
        * *hidden_deps* — dep names suppressed entirely
    """
    if app is not None:
        hidden: frozenset[str] = getattr(
            app.config,
            _CONFIG_HIDDEN_DEPS,
            PYTEST_HIDDEN,
        )
        builtin_links: dict[str, str] = getattr(
            app.config,
            _CONFIG_BUILTIN_LINKS,
            PYTEST_BUILTIN_LINKS,
        )
        external_links: dict[str, str] = getattr(
            app.config,
            _CONFIG_EXTERNAL_LINKS,
            {},
        )
        all_links = {**builtin_links, **external_links}
    else:
        hidden = PYTEST_HIDDEN
        all_links = PYTEST_BUILTIN_LINKS

    project: list[str] = []
    builtin: dict[str, str] = {}
    hidden_list: list[str] = []

    for name, _param in _iter_injectable_params(obj):
        if name in hidden:
            hidden_list.append(name)
        elif name in all_links:
            builtin[name] = all_links[name]
        else:
            project.append(name)

    return project, builtin, hidden_list


def _get_return_annotation(obj: t.Any) -> t.Any:
    """Return the injected type of the fixture's underlying function.

    For ``yield`` fixtures annotated as ``Generator[T, None, None]`` or
    ``Iterator[T]``, returns the yield type ``T`` — the value the test function
    actually receives. This matches how pytest users think about the fixture's
    return contract.

    Parameters
    ----------
    obj : Any
        A pytest fixture wrapper object.

    Returns
    -------
    Any
        The resolved return/yield type annotation, or ``inspect.Parameter.empty``
        when the annotation cannot be resolved (e.g. forward references under
        ``TYPE_CHECKING`` guards not importable at doc-build time).
    """
    fn = _get_fixture_fn(obj)
    try:
        hints = t.get_type_hints(fn)
    except (NameError, AttributeError, TypeError, RecursionError):
        # Forward references (TYPE_CHECKING guards), parameterized generics
        # (TypeError in some Python versions), circular imports (RecursionError),
        # or other resolution failures.  Fall back to the raw annotation string.
        ann = inspect.signature(fn).return_annotation
        return inspect.Parameter.empty if ann is inspect.Parameter.empty else ann
    ret = hints.get("return", inspect.Parameter.empty)
    if ret is inspect.Parameter.empty:
        return ret
    # Unwrap Generator/Iterator and their async counterparts so that
    # yield-based fixtures show the injected type, not the generator type.
    origin = t.get_origin(ret)
    if origin in (
        collections.abc.Generator,
        collections.abc.Iterator,
        collections.abc.AsyncGenerator,
        collections.abc.AsyncIterator,
    ):
        args = t.get_args(ret)
        return args[0] if args else inspect.Parameter.empty
    return ret


def _format_type_short(annotation: t.Any) -> str:
    """Format *annotation* to a short display string for docs.

    Parameters
    ----------
    annotation : Any
        A type annotation, possibly ``inspect.Parameter.empty``.

    Returns
    -------
    str
        A human-readable type string, or ``"..."`` when annotation is absent.
    """
    if annotation is inspect.Parameter.empty:
        return "..."
    try:
        return stringify_annotation(annotation)
    except Exception:
        return str(annotation)


def _is_factory(obj: t.Any) -> bool:
    """Return True if *obj* is a factory fixture.

    Parameters
    ----------
    obj : Any
        A pytest fixture wrapper object.

    Returns
    -------
    bool
        True when the return annotation is ``type[X]`` or ``Callable[..., X]``.
        Returns False when no annotation (or ``t.Any``) is present — use
        the explicit ``:kind: factory`` option to override.
    """
    ret = _get_return_annotation(obj)
    # t.Any / unannotated: no type information — default to resource.
    if ret is inspect.Parameter.empty or ret is t.Any:
        return False
    origin = t.get_origin(ret)
    if origin is type or origin is collections.abc.Callable:
        return True
    ret_str = str(ret)
    return ret_str.startswith("type[") or "Callable" in ret_str


def _infer_kind(obj: t.Any, explicit_kind: str | None = None) -> str:
    """Return the fixture kind, honouring an explicit override.

    Priority chain:

    1. *explicit_kind* — set via ``:kind:`` directive option by the author.
    2. Type annotation — ``type[X]`` / ``Callable`` → ``"factory"``.
    3. Default → ``"resource"``.

    Parameters
    ----------
    obj : Any
        A pytest fixture wrapper object.
    explicit_kind : str | None
        Value from the ``:kind:`` directive option, if provided.

    Returns
    -------
    str
        One of ``"resource"``, ``"factory"``, or ``"override_hook"`` (or any
        custom string passed via ``:kind:``).
    """
    if explicit_kind:
        return explicit_kind
    if _is_factory(obj):
        return "factory"
    return str(_DEFAULTS["kind"])
