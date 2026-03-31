"""Tests for sphinx_pytest_fixtures Sphinx extension."""

from __future__ import annotations

import collections.abc
import pathlib
import types
import typing as t

import pytest
import sphinx_pytest_fixtures

from libtmux.server import Server

# ---------------------------------------------------------------------------
# _is_pytest_fixture
# ---------------------------------------------------------------------------


def test_is_pytest_fixture_positive() -> None:
    """_is_pytest_fixture returns True for decorated fixtures."""

    @pytest.fixture(scope="session")
    def my_fixture(tmp_path_factory: pytest.TempPathFactory) -> str:
        return "hello"

    assert sphinx_pytest_fixtures._is_pytest_fixture(my_fixture)


def test_is_pytest_fixture_negative() -> None:
    """_is_pytest_fixture returns False for plain functions."""

    def not_a_fixture() -> str:
        return "hello"

    assert not sphinx_pytest_fixtures._is_pytest_fixture(not_a_fixture)


# ---------------------------------------------------------------------------
# _get_user_deps
# ---------------------------------------------------------------------------


def test_user_deps_filters_pytest_hidden() -> None:
    """_get_user_deps excludes fixtures in PYTEST_HIDDEN (low-value noise).

    Fixtures in PYTEST_BUILTIN_LINKS (request, monkeypatch, etc.) are NOT
    filtered by _get_user_deps — they are rendered with external hyperlinks
    by transform_content instead.
    """

    @pytest.fixture
    def my_fixture(
        pytestconfig: pytest.Config,
        monkeypatch: pytest.MonkeyPatch,
        server: t.Any,
    ) -> str:
        return "hello"

    deps = sphinx_pytest_fixtures._get_user_deps(my_fixture)
    names = [name for name, _ in deps]
    # pytestconfig is in PYTEST_HIDDEN → filtered
    assert "pytestconfig" not in names
    # monkeypatch is in PYTEST_BUILTIN_LINKS (not PYTEST_HIDDEN) → appears
    assert "monkeypatch" in names
    # project fixture → appears
    assert "server" in names


def test_user_deps_empty_for_only_hidden_params() -> None:
    """_get_user_deps returns empty list when all params are in PYTEST_HIDDEN."""

    @pytest.fixture
    def my_fixture(pytestconfig: pytest.Config) -> str:
        return "hello"

    assert sphinx_pytest_fixtures._get_user_deps(my_fixture) == []


# ---------------------------------------------------------------------------
# _get_return_annotation — including Generator/yield unwrapping
# ---------------------------------------------------------------------------


def test_get_return_annotation_resolved() -> None:
    """_get_return_annotation returns the resolved return type."""

    @pytest.fixture
    def my_fixture() -> str:
        return "hello"

    ann = sphinx_pytest_fixtures._get_return_annotation(my_fixture)
    assert ann is str


def test_get_return_annotation_forward_ref_fallback() -> None:
    """_get_return_annotation falls back gracefully on unresolvable forward refs."""

    @pytest.fixture
    def my_fixture() -> UnresolvableForwardRef:  # type: ignore[name-defined]  # noqa: F821
        return None

    # Should not raise; returns the annotation string or Parameter.empty
    ann = sphinx_pytest_fixtures._get_return_annotation(my_fixture)
    assert ann is not None


def test_get_return_annotation_unwraps_generator() -> None:
    """_get_return_annotation extracts yield type from Generator[T, None, None]."""

    @pytest.fixture
    def server_fixture() -> collections.abc.Generator[Server, None, None]:
        srv = Server()
        yield srv
        srv.kill()

    ann = sphinx_pytest_fixtures._get_return_annotation(server_fixture)
    assert ann is Server


def test_get_return_annotation_unwraps_iterator() -> None:
    """_get_return_annotation extracts yield type from Iterator[T]."""

    @pytest.fixture
    def server_fixture() -> collections.abc.Iterator[Server]:
        yield Server()

    ann = sphinx_pytest_fixtures._get_return_annotation(server_fixture)
    assert ann is Server


# ---------------------------------------------------------------------------
# _is_factory
# ---------------------------------------------------------------------------


def test_factory_detection_from_type_annotation() -> None:
    """_is_factory returns True for type[X] return annotation."""

    @pytest.fixture
    def test_factory(request: pytest.FixtureRequest) -> type[Server]:
        return Server

    assert sphinx_pytest_fixtures._is_factory(test_factory)


def test_factory_detection_from_callable_annotation() -> None:
    """_is_factory returns True for Callable return annotation."""

    @pytest.fixture
    def make_thing() -> collections.abc.Callable[[], str]:
        return lambda: "x"

    assert sphinx_pytest_fixtures._is_factory(make_thing)


def test_factory_detection_from_name_convention() -> None:
    """_is_factory falls back to uppercase-first name heuristic when no annotation."""

    @pytest.fixture
    def CapitalFactory() -> t.Any:
        return lambda: None

    assert sphinx_pytest_fixtures._is_factory(CapitalFactory)


def test_factory_detection_negative() -> None:
    """_is_factory returns False for plain resource fixtures."""

    @pytest.fixture
    def plain_fixture() -> str:
        return "hello"

    assert not sphinx_pytest_fixtures._is_factory(plain_fixture)


# ---------------------------------------------------------------------------
# _is_overridable
# ---------------------------------------------------------------------------


def test_overridable_detection_positive() -> None:
    """_is_overridable returns True for zero-dep plain-return override fixtures."""

    @pytest.fixture
    def session_params() -> dict:  # type: ignore[type-arg]
        """Override in conftest to customize session creation."""
        return {}

    assert sphinx_pytest_fixtures._is_overridable(session_params)


def test_overridable_detection_negative_has_deps() -> None:
    """_is_overridable returns False when fixture has user-visible dependencies."""

    @pytest.fixture
    def session_params(server: t.Any) -> dict:  # type: ignore[type-arg]
        """Override in conftest to customize session creation."""
        return {}

    assert not sphinx_pytest_fixtures._is_overridable(session_params)


def test_overridable_detection_negative_complex_return() -> None:
    """_is_overridable returns False for fixtures returning domain objects."""

    @pytest.fixture
    def my_server() -> Server:
        """Override in conftest."""
        return Server()

    assert not sphinx_pytest_fixtures._is_overridable(my_server)


def test_overridable_detection_negative_no_docstring_keyword() -> None:
    """_is_overridable returns False without override/conftest in docstring."""

    @pytest.fixture
    def session_params() -> dict:  # type: ignore[type-arg]
        """Return default session parameters."""
        return {}

    assert not sphinx_pytest_fixtures._is_overridable(session_params)


# ---------------------------------------------------------------------------
# format_name (via getattr pattern used in FixtureDocumenter.format_name)
# ---------------------------------------------------------------------------


def test_format_name_uses_function_name_when_not_renamed() -> None:
    """format_name returns the function name when no name alias is set."""

    @pytest.fixture
    def server_fixture() -> str:
        return "hello"

    fixture_name = (
        getattr(
            server_fixture,
            "name",
            None,
        )
        or sphinx_pytest_fixtures._get_fixture_fn(server_fixture).__name__
    )
    assert fixture_name == "server_fixture"


def test_format_name_honours_fixture_name_alias() -> None:
    """format_name returns the alias when @pytest.fixture(name=...) is used."""

    @pytest.fixture(name="server")
    def _server_fixture() -> str:
        return "hello"

    fixture_name = (
        getattr(
            _server_fixture,
            "name",
            None,
        )
        or sphinx_pytest_fixtures._get_fixture_fn(_server_fixture).__name__
    )
    assert fixture_name == "server"


# ---------------------------------------------------------------------------
# _on_process_fixture_docstring
# ---------------------------------------------------------------------------


def test_process_docstring_does_not_modify_fixture_lines() -> None:
    """_on_process_fixture_docstring no longer injects RST for fixtures.

    Metadata rendering moved to PyFixtureDirective.transform_content.
    """

    @pytest.fixture
    def my_fixture() -> str:
        """Existing docstring."""
        return "hello"

    lines: list[str] = ["Existing docstring."]
    sphinx_pytest_fixtures._on_process_fixture_docstring(
        app=None,
        what="function",
        name="my_fixture",
        obj=my_fixture,
        options={},
        lines=lines,
    )

    assert lines == ["Existing docstring."]


def test_process_docstring_skips_non_fixture() -> None:
    """_on_process_fixture_docstring does not modify non-fixture objects."""

    def plain_fn() -> str:
        return "hello"

    lines: list[str] = ["Original."]
    sphinx_pytest_fixtures._on_process_fixture_docstring(
        app=None,
        what="function",
        name="plain_fn",
        obj=plain_fn,
        options={},
        lines=lines,
    )

    assert lines == ["Original."]


def test_process_docstring_does_not_inject_depends_on() -> None:
    """_on_process_fixture_docstring no longer injects Depends-on RST.

    Depends-on rendering moved to PyFixtureDirective.transform_content.
    """

    @pytest.fixture
    def my_fixture(config_file: pathlib.Path) -> str:
        return "hello"

    lines: list[str] = ["docstring"]
    sphinx_pytest_fixtures._on_process_fixture_docstring(
        app=None,
        what="function",
        name="my_fixture",
        obj=my_fixture,
        options={},
        lines=lines,
    )

    assert lines == ["docstring"]


def test_process_docstring_no_depends_on_when_no_user_deps() -> None:
    """_on_process_fixture_docstring omits Depends-on when all deps are internal."""

    @pytest.fixture
    def my_fixture(request: pytest.FixtureRequest) -> str:
        return "hello"

    lines: list[str] = []
    sphinx_pytest_fixtures._on_process_fixture_docstring(
        app=None,
        what="function",
        name="my_fixture",
        obj=my_fixture,
        options={},
        lines=lines,
    )

    joined = "\n".join(lines)
    assert "Depends on" not in joined


def test_process_docstring_does_not_modify_yield_fixture() -> None:
    """_on_process_fixture_docstring does not modify yield fixture lines.

    Return-type rendering (Server vs Generator) is now handled by
    transform_content via the :return-type: directive option.
    """

    @pytest.fixture
    def server_fixture() -> collections.abc.Generator[Server, None, None]:
        yield Server()

    lines: list[str] = []
    sphinx_pytest_fixtures._on_process_fixture_docstring(
        app=None,
        what="fixture",
        name="server_fixture",
        obj=server_fixture,
        options={},
        lines=lines,
    )

    assert lines == []


# ---------------------------------------------------------------------------
# setup()
# ---------------------------------------------------------------------------


def test_setup_return_value() -> None:
    """setup() returns correct extension metadata."""
    connections: list[tuple[str, t.Any]] = []

    app = types.SimpleNamespace(
        setup_extension=lambda ext: None,
        add_config_value=lambda name, default, rebuild, **kw: None,
        add_directive_to_domain=lambda d, n, cls: None,
        add_role_to_domain=lambda d, n, role: None,
        add_autodocumenter=lambda cls: None,
        connect=lambda event, handler: connections.append((event, handler)),
    )

    result = sphinx_pytest_fixtures.setup(app)
    assert result["version"] == "1.0"
    assert result["parallel_read_safe"] is True
    assert result["parallel_write_safe"] is True


def test_setup_event_connections() -> None:
    """setup() connects autodoc-process-docstring and missing-reference handlers."""
    connections: list[tuple[str, t.Any]] = []

    app = types.SimpleNamespace(
        setup_extension=lambda ext: None,
        add_config_value=lambda name, default, rebuild, **kw: None,
        add_directive_to_domain=lambda d, n, cls: None,
        add_role_to_domain=lambda d, n, role: None,
        add_autodocumenter=lambda cls: None,
        connect=lambda event, handler: connections.append((event, handler)),
    )

    sphinx_pytest_fixtures.setup(app)
    event_names = [e for e, _ in connections]
    assert "autodoc-process-docstring" in event_names
    assert "missing-reference" in event_names

    handlers = dict(connections)
    assert (
        handlers["autodoc-process-docstring"]
        is sphinx_pytest_fixtures._on_process_fixture_docstring
    )
    assert handlers["missing-reference"] is sphinx_pytest_fixtures._on_missing_reference


def test_setup_registers_autodocumenter() -> None:
    """setup() registers FixtureDocumenter."""
    registered: list[t.Any] = []

    app = types.SimpleNamespace(
        setup_extension=lambda ext: None,
        add_config_value=lambda name, default, rebuild, **kw: None,
        add_directive_to_domain=lambda d, n, cls: None,
        add_role_to_domain=lambda d, n, role: None,
        add_autodocumenter=lambda cls: registered.append(cls),
        connect=lambda event, handler: None,
    )

    sphinx_pytest_fixtures.setup(app)
    assert sphinx_pytest_fixtures.FixtureDocumenter in registered


# ---------------------------------------------------------------------------
# _get_fixture_marker — scope normalisation (Commit 1)
# ---------------------------------------------------------------------------


def test_get_fixture_marker_scope_is_str_for_session() -> None:
    """_get_fixture_marker always returns str scope, never enum or None."""

    @pytest.fixture(scope="session")
    def my_fixture() -> str:
        return "hello"

    marker = sphinx_pytest_fixtures._get_fixture_marker(my_fixture)
    assert isinstance(marker.scope, str)
    assert marker.scope == "session"


def test_get_fixture_marker_function_scope_is_str() -> None:
    """Function-scope (default) fixture returns 'function', not None."""

    @pytest.fixture
    def fn_fixture() -> str:
        return "x"

    marker = sphinx_pytest_fixtures._get_fixture_marker(fn_fixture)
    assert isinstance(marker.scope, str)
    assert marker.scope == "function"


# ---------------------------------------------------------------------------
# _iter_injectable_params — variadic filter (Commit 1)
# ---------------------------------------------------------------------------


def test_iter_injectable_params_skips_kwargs() -> None:
    """_iter_injectable_params skips *args and **kwargs."""

    @pytest.fixture
    def fx(server: t.Any, *args: t.Any, **kwargs: t.Any) -> None:
        pass

    names = [n for n, _ in sphinx_pytest_fixtures._iter_injectable_params(fx)]
    assert names == ["server"]
    assert "args" not in names
    assert "kwargs" not in names


# ---------------------------------------------------------------------------
# _build_badge_html — badge group HTML (Commit 4)
# ---------------------------------------------------------------------------


def test_build_badge_html_fixture_only() -> None:
    """Function-scope resource fixture has only FIXTURE badge."""
    html = sphinx_pytest_fixtures._build_badge_html("function", "resource", False)
    assert "spf-badge--fixture" in html
    assert "spf-badge--scope" not in html
    assert "spf-badge--kind" not in html


def test_build_badge_html_session_scope() -> None:
    """Session-scope shows scope badge with data-scope=session."""
    html = sphinx_pytest_fixtures._build_badge_html("session", "resource", False)
    assert 'data-scope="session"' in html
    assert "spf-badge--scope" in html


def test_build_badge_html_override_kind() -> None:
    """override_hook fixtures show OVERRIDE badge."""
    html = sphinx_pytest_fixtures._build_badge_html("function", "override_hook", False)
    assert 'data-kind="override_hook"' in html
    assert "OVERRIDE" in html
    assert "spf-badge--kind" in html


def test_build_badge_html_autouse_replaces_kind() -> None:
    """autouse=True shows AUTO state badge instead of kind badge."""
    html = sphinx_pytest_fixtures._build_badge_html("function", "resource", True)
    assert 'data-state="autouse"' in html
    assert "AUTO" in html
    assert "spf-badge--kind" not in html


def test_build_badge_html_factory_session() -> None:
    """Factory fixture with session scope shows both scope and kind badges."""
    html = sphinx_pytest_fixtures._build_badge_html("session", "factory", False)
    assert 'data-scope="session"' in html
    assert 'data-kind="factory"' in html
    assert "FACTORY" in html
