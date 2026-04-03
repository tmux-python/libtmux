"""Tests for sphinx_pytest_fixtures Sphinx extension."""

from __future__ import annotations

import collections.abc
import types
import typing as t

import pytest
import sphinx_pytest_fixtures
import sphinx_pytest_fixtures._store
from docutils import nodes

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
    """_is_factory returns False for unannotated (t.Any) fixtures; no name heuristic."""

    @pytest.fixture
    def CapitalFactory() -> t.Any:
        return lambda: None

    assert not sphinx_pytest_fixtures._is_factory(CapitalFactory)


def test_is_factory_camelcase_unannotated_defaults_to_resource() -> None:
    """Unannotated CamelCase fixture must NOT be silently classified as factory."""

    @pytest.fixture
    def Session() -> t.Any:
        return "string value"

    assert not sphinx_pytest_fixtures._is_factory(Session)


def test_factory_detection_negative() -> None:
    """_is_factory returns False for plain resource fixtures."""

    @pytest.fixture
    def plain_fixture() -> str:
        return "hello"

    assert not sphinx_pytest_fixtures._is_factory(plain_fixture)


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
# setup()
# ---------------------------------------------------------------------------


def test_setup_return_value() -> None:
    """setup() returns correct extension metadata."""
    connections: list[tuple[str, t.Any]] = []

    app = types.SimpleNamespace(
        setup_extension=lambda ext: None,
        add_config_value=lambda name, default, rebuild, **kw: None,
        add_crossref_type=lambda *a, **kw: None,
        add_directive_to_domain=lambda d, n, cls: None,
        add_role_to_domain=lambda d, n, role: None,
        add_autodocumenter=lambda cls: None,
        add_directive=lambda name, cls: None,
        add_node=lambda *a, **kw: None,
        add_css_file=lambda *a, **kw: None,
        connect=lambda event, handler: connections.append((event, handler)),
    )

    result = sphinx_pytest_fixtures.setup(app)
    assert result["version"] == "1.0"
    assert result["parallel_read_safe"] is True
    assert result["parallel_write_safe"] is True


def test_setup_event_connections() -> None:
    """setup() connects required event handlers."""
    connections: list[tuple[str, t.Any]] = []

    app = types.SimpleNamespace(
        setup_extension=lambda ext: None,
        add_config_value=lambda name, default, rebuild, **kw: None,
        add_crossref_type=lambda *a, **kw: None,
        add_directive_to_domain=lambda d, n, cls: None,
        add_role_to_domain=lambda d, n, role: None,
        add_autodocumenter=lambda cls: None,
        add_directive=lambda name, cls: None,
        add_node=lambda *a, **kw: None,
        add_css_file=lambda *a, **kw: None,
        connect=lambda event, handler: connections.append((event, handler)),
    )

    sphinx_pytest_fixtures.setup(app)
    event_names = [e for e, _ in connections]
    assert "missing-reference" in event_names
    assert "doctree-resolved" in event_names
    assert "env-purge-doc" in event_names
    assert "env-merge-info" in event_names
    assert "env-updated" in event_names

    handlers = dict(connections)
    assert handlers["missing-reference"] is sphinx_pytest_fixtures._on_missing_reference


def test_setup_registers_autodocumenter() -> None:
    """setup() registers FixtureDocumenter."""
    registered: list[t.Any] = []

    app = types.SimpleNamespace(
        setup_extension=lambda ext: None,
        add_config_value=lambda name, default, rebuild, **kw: None,
        add_crossref_type=lambda *a, **kw: None,
        add_directive_to_domain=lambda d, n, cls: None,
        add_role_to_domain=lambda d, n, role: None,
        add_autodocumenter=lambda cls: registered.append(cls),
        add_directive=lambda name, cls: None,
        add_node=lambda *a, **kw: None,
        add_css_file=lambda *a, **kw: None,
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


def test_iter_injectable_params_keeps_keyword_only() -> None:
    """_iter_injectable_params includes KEYWORD_ONLY params — pytest can inject them."""

    @pytest.fixture
    def fx(*, server: t.Any) -> None:
        pass

    names = [n for n, _ in sphinx_pytest_fixtures._iter_injectable_params(fx)]
    assert "server" in names


def test_iter_injectable_params_skips_positional_only() -> None:
    """_iter_injectable_params skips POSITIONAL_ONLY params (before /).

    Positional-only parameters cannot be injected by name, so they are
    correctly excluded from the fixture dependency list.
    """
    import textwrap

    code = textwrap.dedent("""
        import pytest
        import typing as t

        @pytest.fixture
        def fx(server: t.Any, /, *, session: t.Any) -> None:
            pass
    """)
    ns: dict[str, t.Any] = {}
    exec(compile(code, "<test>", "exec"), ns)
    names = [n for n, _ in sphinx_pytest_fixtures._iter_injectable_params(ns["fx"])]
    assert names == ["session"]
    assert "server" not in names


# ---------------------------------------------------------------------------
# _build_badge_group_node — portable inline badge nodes (Commit 4)
# ---------------------------------------------------------------------------


def test_build_badge_group_node_fixture_always_present() -> None:
    """_build_badge_group_node always includes a FIXTURE badge child."""
    node = sphinx_pytest_fixtures._build_badge_group_node("function", "resource", False)
    texts = [child.astext() for child in node.children]
    assert "fixture" in texts


def test_build_badge_group_node_no_scope_for_function() -> None:
    """Function-scope produces no scope badge (absence = function-scope)."""
    node = sphinx_pytest_fixtures._build_badge_group_node("function", "resource", False)
    classes_all = [
        c
        for child in node.children
        if hasattr(child, "get")
        for c in child.get("classes", [])
    ]
    assert sphinx_pytest_fixtures._CSS.BADGE_SCOPE not in classes_all


def test_build_badge_group_node_session_scope_badge() -> None:
    """Session-scope produces a scope badge with class spf-scope-session."""
    node = sphinx_pytest_fixtures._build_badge_group_node("session", "resource", False)
    classes_all = [
        c
        for child in node.children
        if hasattr(child, "get")
        for c in child.get("classes", [])
    ]
    assert sphinx_pytest_fixtures._CSS.scope("session") in classes_all


def test_build_badge_group_node_override_kind() -> None:
    """override_hook produces a badge with class spf-override."""
    node = sphinx_pytest_fixtures._build_badge_group_node(
        "function", "override_hook", False
    )
    texts = [child.astext() for child in node.children]
    classes_all = [
        c
        for child in node.children
        if hasattr(child, "get")
        for c in child.get("classes", [])
    ]
    assert "override" in texts
    assert sphinx_pytest_fixtures._CSS.OVERRIDE in classes_all


def test_build_badge_group_node_autouse_replaces_kind() -> None:
    """autouse=True shows AUTO badge with spf-autouse class, no kind badge."""
    node = sphinx_pytest_fixtures._build_badge_group_node("function", "resource", True)
    texts = [child.astext() for child in node.children]
    classes_all = [
        c
        for child in node.children
        if hasattr(child, "get")
        for c in child.get("classes", [])
    ]
    assert "auto" in texts
    assert sphinx_pytest_fixtures._CSS.AUTOUSE in classes_all
    assert sphinx_pytest_fixtures._CSS.BADGE_KIND not in classes_all


def test_build_badge_group_node_factory_session() -> None:
    """Factory + session scope produces both scope and factory badges."""
    node = sphinx_pytest_fixtures._build_badge_group_node("session", "factory", False)
    texts = [child.astext() for child in node.children]
    classes_all = [
        c
        for child in node.children
        if hasattr(child, "get")
        for c in child.get("classes", [])
    ]
    assert "factory" in texts
    assert sphinx_pytest_fixtures._CSS.FACTORY in classes_all
    assert sphinx_pytest_fixtures._CSS.scope("session") in classes_all


def test_build_badge_group_node_has_tabindex() -> None:
    """All badge abbreviation nodes have tabindex='0' for touch accessibility."""
    from docutils import nodes

    node = sphinx_pytest_fixtures._build_badge_group_node("session", "factory", True)
    abbreviations = [
        child for child in node.children if isinstance(child, nodes.abbreviation)
    ]
    assert len(abbreviations) > 0
    for abbr in abbreviations:
        assert abbr.get("tabindex") == "0", (
            f"Badge {abbr.astext()!r} missing tabindex='0'"
        )


# ---------------------------------------------------------------------------
# _get_spf_store — store version guard
# ---------------------------------------------------------------------------


def test_store_version_guard_resets_stale() -> None:
    """_get_spf_store resets a store with an outdated _store_version."""
    env = types.SimpleNamespace(
        domaindata={
            "sphinx_pytest_fixtures": {
                "fixtures": {"old.fixture": "stale"},
                "public_to_canon": {"old": "old.fixture"},
                "reverse_deps": {},
                "_store_version": 1,
            }
        }
    )
    store = sphinx_pytest_fixtures._get_spf_store(env)
    assert store["fixtures"] == {}
    assert store["public_to_canon"] == {}
    assert store["_store_version"] == sphinx_pytest_fixtures._STORE_VERSION


def test_store_version_guard_preserves_current() -> None:
    """_get_spf_store preserves a store with the current _store_version."""
    sentinel_meta = types.SimpleNamespace(docname="api", public_name="srv")
    env = types.SimpleNamespace(
        domaindata={
            "sphinx_pytest_fixtures": {
                "fixtures": {"mod.srv": sentinel_meta},
                "public_to_canon": {"srv": "mod.srv"},
                "reverse_deps": {},
                "_store_version": sphinx_pytest_fixtures._STORE_VERSION,
            }
        }
    )
    store = sphinx_pytest_fixtures._get_spf_store(env)
    assert store["fixtures"]["mod.srv"] is sentinel_meta


# ---------------------------------------------------------------------------
# public_to_canon registration logic
# ---------------------------------------------------------------------------


def test_public_to_canon_first_registration() -> None:
    """First registration stores canonical name for a public name."""
    env = types.SimpleNamespace(domaindata={})
    store = sphinx_pytest_fixtures._get_spf_store(env)

    store["public_to_canon"]["server"] = "mod_a.server"
    assert store["public_to_canon"]["server"] == "mod_a.server"


def test_public_to_canon_ambiguous() -> None:
    """Two fixtures with the same public name mark the mapping as None."""
    env = types.SimpleNamespace(domaindata={})
    store = sphinx_pytest_fixtures._get_spf_store(env)

    # Simulate what _register_fixture_meta does (corrected logic):
    public_name = "server"

    # First registration
    if public_name not in store["public_to_canon"]:
        store["public_to_canon"][public_name] = "mod_a.server"
    elif store["public_to_canon"][public_name] != "mod_a.server":
        store["public_to_canon"][public_name] = None

    # Second registration with different canonical name
    if public_name not in store["public_to_canon"]:
        store["public_to_canon"][public_name] = "mod_b.server"
    elif store["public_to_canon"][public_name] != "mod_b.server":
        store["public_to_canon"][public_name] = None

    assert store["public_to_canon"]["server"] is None


def test_public_to_canon_idempotent() -> None:
    """Registering the same fixture twice preserves the canonical name."""
    env = types.SimpleNamespace(domaindata={})
    store = sphinx_pytest_fixtures._get_spf_store(env)

    public_name = "server"

    # First registration
    if public_name not in store["public_to_canon"]:
        store["public_to_canon"][public_name] = "mod.server"
    elif store["public_to_canon"][public_name] != "mod.server":
        store["public_to_canon"][public_name] = None

    # Same fixture registered again
    if public_name not in store["public_to_canon"]:
        store["public_to_canon"][public_name] = "mod.server"
    elif store["public_to_canon"][public_name] != "mod.server":
        store["public_to_canon"][public_name] = None

    assert store["public_to_canon"]["server"] == "mod.server"


# ---------------------------------------------------------------------------
# _finalize_store — store finalization
# ---------------------------------------------------------------------------


def _make_meta(
    canonical: str,
    public: str,
    deps: tuple[sphinx_pytest_fixtures.FixtureDep, ...] = (),
    docname: str = "api",
) -> sphinx_pytest_fixtures.FixtureMeta:
    """Build a minimal FixtureMeta for unit tests."""
    return sphinx_pytest_fixtures.FixtureMeta(
        docname=docname,
        canonical_name=canonical,
        public_name=public,
        source_name=public,
        scope="function",
        autouse=False,
        kind="resource",
        return_display="str",
        return_xref_target=None,
        deps=deps,
        param_reprs=(),
        has_teardown=False,
        is_async=False,
        summary="Test fixture.",
    )


def test_finalize_store_forward_reference() -> None:
    """_finalize_store resolves forward-reference dep targets."""
    env = types.SimpleNamespace(domaindata={})
    store = sphinx_pytest_fixtures._get_spf_store(env)

    # consumer registered before provider → dep.target is None
    consumer_dep = sphinx_pytest_fixtures.FixtureDep(
        display_name="provider", kind="fixture", target=None
    )
    store["fixtures"]["mod.consumer"] = _make_meta(
        "mod.consumer", "consumer", deps=(consumer_dep,)
    )
    store["fixtures"]["mod.provider"] = _make_meta("mod.provider", "provider")

    sphinx_pytest_fixtures._finalize_store(store)

    resolved_dep = store["fixtures"]["mod.consumer"].deps[0]
    assert resolved_dep.target == "mod.provider"


def test_finalize_store_empty_store() -> None:
    """_finalize_store on an empty store completes without error."""
    env = types.SimpleNamespace(domaindata={})
    store = sphinx_pytest_fixtures._get_spf_store(env)
    sphinx_pytest_fixtures._finalize_store(store)
    assert store["fixtures"] == {}
    assert store["public_to_canon"] == {}
    assert store["reverse_deps"] == {}


def test_finalize_store_self_dependency() -> None:
    """_finalize_store skips self-edges in reverse_deps."""
    env = types.SimpleNamespace(domaindata={})
    store = sphinx_pytest_fixtures._get_spf_store(env)

    self_dep = sphinx_pytest_fixtures.FixtureDep(
        display_name="self_ref", kind="fixture", target=None
    )
    store["fixtures"]["mod.self_ref"] = _make_meta(
        "mod.self_ref", "self_ref", deps=(self_dep,)
    )

    sphinx_pytest_fixtures._finalize_store(store)

    # dep.target resolves to itself, but reverse_deps should not contain self-edge
    assert "mod.self_ref" not in store["reverse_deps"].get("mod.self_ref", [])


def test_finalize_store_ambiguous_public_name() -> None:
    """_finalize_store marks ambiguous public names as None in public_to_canon."""
    env = types.SimpleNamespace(domaindata={})
    store = sphinx_pytest_fixtures._get_spf_store(env)

    store["fixtures"]["mod_a.server"] = _make_meta("mod_a.server", "server")
    store["fixtures"]["mod_b.server"] = _make_meta("mod_b.server", "server")

    sphinx_pytest_fixtures._finalize_store(store)

    assert store["public_to_canon"]["server"] is None


def test_finalize_store_reverse_deps() -> None:
    """_finalize_store populates reverse_deps from fixture deps."""
    env = types.SimpleNamespace(domaindata={})
    store = sphinx_pytest_fixtures._get_spf_store(env)

    dep_on_server = sphinx_pytest_fixtures.FixtureDep(
        display_name="server", kind="fixture", target="mod.server"
    )
    store["fixtures"]["mod.server"] = _make_meta("mod.server", "server")
    store["fixtures"]["mod.client"] = _make_meta(
        "mod.client", "client", deps=(dep_on_server,)
    )

    sphinx_pytest_fixtures._finalize_store(store)

    assert "mod.client" in store["reverse_deps"]["mod.server"]


def test_finalize_store_parallel_merge() -> None:
    """_finalize_store resolves deps after parallel worker merge."""
    # Simulate primary env with consumer, sub-env with provider
    primary_env = types.SimpleNamespace(domaindata={})
    primary_store = sphinx_pytest_fixtures._get_spf_store(primary_env)

    consumer_dep = sphinx_pytest_fixtures.FixtureDep(
        display_name="provider", kind="fixture", target=None
    )
    primary_store["fixtures"]["mod.consumer"] = _make_meta(
        "mod.consumer", "consumer", deps=(consumer_dep,)
    )

    # Simulate sub-env merge
    sub_env = types.SimpleNamespace(domaindata={})
    sub_store = sphinx_pytest_fixtures._get_spf_store(sub_env)
    sub_store["fixtures"]["mod.provider"] = _make_meta(
        "mod.provider", "provider", docname="other"
    )

    # Merge (what _on_env_merge_info does)
    primary_store["fixtures"].update(sub_store["fixtures"])

    # Finalize
    sphinx_pytest_fixtures._finalize_store(primary_store)

    resolved_dep = primary_store["fixtures"]["mod.consumer"].deps[0]
    assert resolved_dep.target == "mod.provider"
    assert "mod.consumer" in primary_store["reverse_deps"]["mod.provider"]


def test_finalize_store_stale_target_after_purge() -> None:
    """_finalize_store clears stale dep targets after provider is purged."""
    env = types.SimpleNamespace(domaindata={})
    store = sphinx_pytest_fixtures._get_spf_store(env)

    dep_on_provider = sphinx_pytest_fixtures.FixtureDep(
        display_name="provider", kind="fixture", target="mod.provider"
    )
    store["fixtures"]["mod.consumer"] = _make_meta(
        "mod.consumer", "consumer", deps=(dep_on_provider,)
    )
    store["fixtures"]["mod.provider"] = _make_meta("mod.provider", "provider")

    # Simulate purge of provider
    del store["fixtures"]["mod.provider"]

    sphinx_pytest_fixtures._finalize_store(store)

    resolved_dep = store["fixtures"]["mod.consumer"].deps[0]
    assert resolved_dep.target is None
    assert "mod.provider" not in store["reverse_deps"]


# ---------------------------------------------------------------------------
# Badge group text separators (Commit 4)
# ---------------------------------------------------------------------------


def test_badge_group_node_has_text_separators() -> None:
    """Badge group nodes have Text(' ') separators between badge children."""
    from docutils import nodes as docnodes

    node = sphinx_pytest_fixtures._build_badge_group_node("session", "factory", False)
    # Should have: scope badge, Text(" "), factory badge, Text(" "), FIXTURE badge
    text_nodes = [child for child in node.children if isinstance(child, docnodes.Text)]
    assert len(text_nodes) >= 2, f"Expected >=2 Text separators, got {len(text_nodes)}"
    for t_node in text_nodes:
        assert t_node.astext() == " "


# ---------------------------------------------------------------------------
# FixtureKind validation (Commit 4)
# ---------------------------------------------------------------------------


def test_infer_kind_custom_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Unknown :kind: values produce a warning during registration."""
    import logging

    env = types.SimpleNamespace(
        domaindata={},
        app=types.SimpleNamespace(
            config=types.SimpleNamespace(
                pytest_fixture_hidden_dependencies=frozenset(),
                pytest_fixture_builtin_links={},
                pytest_external_fixture_links={},
            ),
        ),
    )

    @pytest.fixture
    def my_fixture() -> str:
        """Return a test value."""
        return "hello"

    with caplog.at_level(logging.WARNING, logger="sphinx_pytest_fixtures"):
        sphinx_pytest_fixtures._register_fixture_meta(
            env=env,
            docname="api",
            obj=my_fixture,
            public_name="my_fixture",
            source_name="my_fixture",
            modname="mod",
            kind="custom_weird_kind",
            app=env.app,
        )

    assert any("custom_weird_kind" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# _classify_deps
# ---------------------------------------------------------------------------


def test_classify_deps_project_fixture() -> None:
    """Non-builtin, non-hidden dep is classified as a project fixture."""

    @pytest.fixture
    def my_fixture(server: t.Any) -> str:
        return "hello"

    project, builtin, hidden = sphinx_pytest_fixtures._classify_deps(my_fixture, None)
    assert "server" in project
    assert "server" not in builtin
    assert "server" not in hidden


def test_classify_deps_hidden_fixture() -> None:
    """Fixture depending on pytestconfig has it classified as hidden."""

    @pytest.fixture
    def my_fixture(pytestconfig: t.Any) -> str:
        return "hello"

    project, _builtin, hidden = sphinx_pytest_fixtures._classify_deps(my_fixture, None)
    assert "pytestconfig" in hidden
    assert "pytestconfig" not in project


# ---------------------------------------------------------------------------
# _has_authored_example
# ---------------------------------------------------------------------------


def test_has_authored_example_with_rubric() -> None:
    """Authored Example rubric suppresses auto-generated snippets."""
    from docutils import nodes

    content = nodes.container()
    content += nodes.paragraph("", "Some intro text.")
    content += nodes.rubric("", "Example")
    content += nodes.literal_block("", "def test(): pass")
    assert sphinx_pytest_fixtures._has_authored_example(content)


def test_has_authored_example_with_doctest() -> None:
    """Doctest blocks count as authored examples."""
    from docutils import nodes

    content = nodes.container()
    content += nodes.doctest_block("", ">>> 1 + 1\n2")
    assert sphinx_pytest_fixtures._has_authored_example(content)


def test_has_authored_example_without() -> None:
    """No authored examples — auto-snippet should still be generated."""
    from docutils import nodes

    content = nodes.container()
    content += nodes.paragraph("", "Just a description.")
    assert not sphinx_pytest_fixtures._has_authored_example(content)


def test_has_authored_example_nested_not_detected() -> None:
    """Nested rubrics inside admonitions are not detected (non-recursive)."""
    from docutils import nodes

    content = nodes.container()
    admonition = nodes.note()
    admonition += nodes.rubric("", "Example")
    content += admonition
    assert not sphinx_pytest_fixtures._has_authored_example(content)


# ---------------------------------------------------------------------------
# _build_usage_snippet
# ---------------------------------------------------------------------------


def test_build_usage_snippet_resource_returns_none() -> None:
    """Resource fixtures return None (generic snippet suppressed)."""
    result = sphinx_pytest_fixtures._build_usage_snippet(
        "server", "Server", "resource", "function", autouse=False
    )
    assert result is None


def test_build_usage_snippet_autouse_returns_note() -> None:
    """Autouse fixtures return a nodes.note admonition."""
    from docutils import nodes

    result = sphinx_pytest_fixtures._build_usage_snippet(
        "auto_cleanup", None, "resource", "function", autouse=True
    )
    assert isinstance(result, nodes.note)
    assert "No request needed" in result.astext()


def test_build_usage_snippet_factory_returns_literal_block() -> None:
    """Factory fixtures produce a literal_block with instantiation pattern."""
    from docutils import nodes

    result = sphinx_pytest_fixtures._build_usage_snippet(
        "TestServer", "Server", "factory", "function", autouse=False
    )
    assert isinstance(result, nodes.literal_block)
    text = result.astext()
    assert "test_example" in text
    assert "TestServer()" in text
    assert ": Server" in text


def test_build_usage_snippet_override_hook_returns_conftest() -> None:
    """Override hook fixtures produce a conftest.py snippet."""
    from docutils import nodes

    result = sphinx_pytest_fixtures._build_usage_snippet(
        "home_user", "str", "override_hook", "function", autouse=False
    )
    assert isinstance(result, nodes.literal_block)
    text = result.astext()
    assert "conftest.py" in text
    assert "@pytest.fixture\n" in text


def test_build_usage_snippet_override_hook_session_scope() -> None:
    """Override hook with session scope includes scope in decorator."""
    result = sphinx_pytest_fixtures._build_usage_snippet(
        "home_user", "str", "override_hook", "session", autouse=False
    )
    assert result is not None
    text = result.astext()
    assert 'scope="session"' in text


def test_build_usage_snippet_override_hook_no_return_type() -> None:
    """Override hook without return type omits the arrow annotation."""
    result = sphinx_pytest_fixtures._build_usage_snippet(
        "home_user", None, "override_hook", "function", autouse=False
    )
    assert result is not None
    text = result.astext()
    assert " -> " not in text


# ---------------------------------------------------------------------------
# _on_env_purge_doc
# ---------------------------------------------------------------------------


def test_env_purge_doc_removes_only_target() -> None:
    """Purging a doc removes only that doc's fixtures from the store."""
    env = types.SimpleNamespace(
        domaindata={
            "sphinx_pytest_fixtures": {
                "fixtures": {
                    "mod.fixture_a": sphinx_pytest_fixtures.FixtureMeta(
                        docname="page_a",
                        canonical_name="mod.fixture_a",
                        public_name="fixture_a",
                        source_name="fixture_a",
                        scope="function",
                        autouse=False,
                        kind="resource",
                        return_display="str",
                        return_xref_target=None,
                        deps=(),
                        param_reprs=(),
                        has_teardown=False,
                        is_async=False,
                        summary="",
                    ),
                    "mod.fixture_b": sphinx_pytest_fixtures.FixtureMeta(
                        docname="page_b",
                        canonical_name="mod.fixture_b",
                        public_name="fixture_b",
                        source_name="fixture_b",
                        scope="function",
                        autouse=False,
                        kind="resource",
                        return_display="str",
                        return_xref_target=None,
                        deps=(),
                        param_reprs=(),
                        has_teardown=False,
                        is_async=False,
                        summary="",
                    ),
                },
                "public_to_canon": {},
                "reverse_deps": {},
                "_store_version": sphinx_pytest_fixtures._STORE_VERSION,
            },
        },
    )
    app = types.SimpleNamespace()
    sphinx_pytest_fixtures._on_env_purge_doc(app, env, "page_a")
    store = env.domaindata["sphinx_pytest_fixtures"]
    assert "mod.fixture_a" not in store["fixtures"]
    assert "mod.fixture_b" in store["fixtures"]


# ---------------------------------------------------------------------------
# FixtureMeta schema evolution — deprecated/replacement/teardown_summary
# ---------------------------------------------------------------------------


def test_fixture_meta_new_fields_default_to_none() -> None:
    """New optional fields default to None when not provided."""
    meta = _make_meta("mod.server", "server")
    assert meta.deprecated is None
    assert meta.replacement is None
    assert meta.teardown_summary is None


def test_fixture_meta_new_fields_accept_values() -> None:
    """New optional fields accept explicit values."""
    meta = sphinx_pytest_fixtures.FixtureMeta(
        docname="api",
        canonical_name="mod.old_server",
        public_name="old_server",
        source_name="old_server",
        scope="function",
        autouse=False,
        kind="resource",
        return_display="Server",
        return_xref_target=None,
        deps=(),
        param_reprs=(),
        has_teardown=True,
        is_async=False,
        summary="Deprecated server fixture.",
        deprecated="2.0",
        replacement="mod.new_server",
        teardown_summary="Kills the tmux server process.",
    )
    assert meta.deprecated == "2.0"
    assert meta.replacement == "mod.new_server"
    assert meta.teardown_summary == "Kills the tmux server process."


# ---------------------------------------------------------------------------
# Deprecation badge rendering
# ---------------------------------------------------------------------------


def test_deprecated_badge_renders_at_slot_zero() -> None:
    """Deprecated badge appears as leftmost badge (slot 0)."""
    node = sphinx_pytest_fixtures._build_badge_group_node(
        "session", "resource", False, deprecated=True
    )
    badges = [c for c in node.children if isinstance(c, nodes.abbreviation)]
    assert len(badges) >= 2
    # First badge should be "deprecated"
    assert badges[0].astext() == "deprecated"
    classes_first: list[str] = badges[0].get("classes", [])
    assert sphinx_pytest_fixtures._CSS.DEPRECATED in classes_first


def test_deprecated_badge_absent_when_not_deprecated() -> None:
    """No deprecated badge when deprecated=False (default)."""
    node = sphinx_pytest_fixtures._build_badge_group_node("session", "resource", False)
    badges = [c for c in node.children if isinstance(c, nodes.abbreviation)]
    texts = [b.astext() for b in badges]
    assert "deprecated" not in texts


# ---------------------------------------------------------------------------
# Build-time validation (SPF001-SPF006)
# ---------------------------------------------------------------------------


def test_spf001_missing_docstring(caplog: pytest.LogCaptureFixture) -> None:
    """SPF001 fires for fixtures with empty summary."""
    import logging

    from sphinx_pytest_fixtures._validation import _validate_store

    store: sphinx_pytest_fixtures._store.FixtureStoreDict = {
        "fixtures": {
            "mod.bare": _make_meta("mod.bare", "bare"),
        },
        "public_to_canon": {"bare": "mod.bare"},
        "reverse_deps": {},
        "_store_version": sphinx_pytest_fixtures._STORE_VERSION,
    }
    # Override summary to empty
    import dataclasses

    store["fixtures"]["mod.bare"] = dataclasses.replace(
        store["fixtures"]["mod.bare"], summary=""
    )

    app = types.SimpleNamespace(
        config=types.SimpleNamespace(pytest_fixture_lint_level="warning")
    )
    with caplog.at_level(logging.WARNING, logger="sphinx_pytest_fixtures._validation"):
        _validate_store(store, app)

    spf001 = [r for r in caplog.records if getattr(r, "spf_code", None) == "SPF001"]
    assert len(spf001) == 1


def test_spf005_deprecated_without_replacement(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SPF005 fires for deprecated fixtures without replacement."""
    import dataclasses
    import logging

    from sphinx_pytest_fixtures._validation import _validate_store

    meta = dataclasses.replace(
        _make_meta("mod.old", "old"), deprecated="2.0", replacement=None
    )
    store: sphinx_pytest_fixtures._store.FixtureStoreDict = {
        "fixtures": {"mod.old": meta},
        "public_to_canon": {"old": "mod.old"},
        "reverse_deps": {},
        "_store_version": sphinx_pytest_fixtures._STORE_VERSION,
    }
    app = types.SimpleNamespace(
        config=types.SimpleNamespace(pytest_fixture_lint_level="warning")
    )
    with caplog.at_level(logging.WARNING, logger="sphinx_pytest_fixtures._validation"):
        _validate_store(store, app)

    spf005 = [r for r in caplog.records if getattr(r, "spf_code", None) == "SPF005"]
    assert len(spf005) == 1


def test_validation_silent_when_lint_level_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """lint_level='none' suppresses all validation warnings."""
    import dataclasses
    import logging

    from sphinx_pytest_fixtures._validation import _validate_store

    meta = dataclasses.replace(_make_meta("mod.bare", "bare"), summary="")
    store: sphinx_pytest_fixtures._store.FixtureStoreDict = {
        "fixtures": {"mod.bare": meta},
        "public_to_canon": {"bare": "mod.bare"},
        "reverse_deps": {},
        "_store_version": sphinx_pytest_fixtures._STORE_VERSION,
    }
    app = types.SimpleNamespace(
        config=types.SimpleNamespace(pytest_fixture_lint_level="none")
    )
    with caplog.at_level(logging.WARNING, logger="sphinx_pytest_fixtures._validation"):
        _validate_store(store, app)

    assert len(caplog.records) == 0


def test_lint_level_error_uses_logger_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """lint_level='error' emits ERROR-level records and sets statuscode=1."""
    import dataclasses
    import logging

    from sphinx_pytest_fixtures._validation import _validate_store

    meta = dataclasses.replace(_make_meta("mod.bare", "bare"), summary="")
    store: sphinx_pytest_fixtures._store.FixtureStoreDict = {
        "fixtures": {"mod.bare": meta},
        "public_to_canon": {"bare": "mod.bare"},
        "reverse_deps": {},
        "_store_version": sphinx_pytest_fixtures._STORE_VERSION,
    }
    app = types.SimpleNamespace(
        config=types.SimpleNamespace(pytest_fixture_lint_level="error"),
        statuscode=0,
    )
    with caplog.at_level(logging.DEBUG, logger="sphinx_pytest_fixtures._validation"):
        _validate_store(store, app)

    spf001 = [r for r in caplog.records if getattr(r, "spf_code", None) == "SPF001"]
    assert len(spf001) == 1
    assert spf001[0].levelno == logging.ERROR
    assert app.statuscode == 1


def test_spf002_missing_return_annotation(caplog: pytest.LogCaptureFixture) -> None:
    """SPF002 fires for fixtures with empty return annotation."""
    import dataclasses
    import logging

    from sphinx_pytest_fixtures._validation import _validate_store

    meta = dataclasses.replace(_make_meta("mod.bare", "bare"), return_display="...")
    store: sphinx_pytest_fixtures._store.FixtureStoreDict = {
        "fixtures": {"mod.bare": meta},
        "public_to_canon": {"bare": "mod.bare"},
        "reverse_deps": {},
        "_store_version": sphinx_pytest_fixtures._STORE_VERSION,
    }
    app = types.SimpleNamespace(
        config=types.SimpleNamespace(pytest_fixture_lint_level="warning")
    )
    with caplog.at_level(logging.WARNING, logger="sphinx_pytest_fixtures._validation"):
        _validate_store(store, app)

    spf002 = [r for r in caplog.records if getattr(r, "spf_code", None) == "SPF002"]
    assert len(spf002) == 1


def test_spf003_yield_missing_teardown(caplog: pytest.LogCaptureFixture) -> None:
    """SPF003 fires for yield fixtures without teardown documentation."""
    import dataclasses
    import logging

    from sphinx_pytest_fixtures._validation import _validate_store

    meta = dataclasses.replace(
        _make_meta("mod.gen", "gen"),
        has_teardown=True,
        teardown_summary=None,
    )
    store: sphinx_pytest_fixtures._store.FixtureStoreDict = {
        "fixtures": {"mod.gen": meta},
        "public_to_canon": {"gen": "mod.gen"},
        "reverse_deps": {},
        "_store_version": sphinx_pytest_fixtures._STORE_VERSION,
    }
    app = types.SimpleNamespace(
        config=types.SimpleNamespace(pytest_fixture_lint_level="warning")
    )
    with caplog.at_level(logging.WARNING, logger="sphinx_pytest_fixtures._validation"):
        _validate_store(store, app)

    spf003 = [r for r in caplog.records if getattr(r, "spf_code", None) == "SPF003"]
    assert len(spf003) == 1


def test_spf006_ambiguous_public_name(caplog: pytest.LogCaptureFixture) -> None:
    """SPF006 fires when a public name maps to multiple canonical names."""
    import logging

    from sphinx_pytest_fixtures._validation import _validate_store

    store: sphinx_pytest_fixtures._store.FixtureStoreDict = {
        "fixtures": {
            "mod_a.server": _make_meta("mod_a.server", "server"),
            "mod_b.server": _make_meta("mod_b.server", "server"),
        },
        "public_to_canon": {"server": None},  # ambiguous
        "reverse_deps": {},
        "_store_version": sphinx_pytest_fixtures._STORE_VERSION,
    }
    app = types.SimpleNamespace(
        config=types.SimpleNamespace(pytest_fixture_lint_level="warning")
    )
    with caplog.at_level(logging.WARNING, logger="sphinx_pytest_fixtures._validation"):
        _validate_store(store, app)

    spf006 = [r for r in caplog.records if getattr(r, "spf_code", None) == "SPF006"]
    assert len(spf006) == 1


# ---------------------------------------------------------------------------
# _qualify_forward_ref — TYPE_CHECKING forward-reference resolution
# ---------------------------------------------------------------------------


def test_qualify_forward_ref_resolves_type_checking_import() -> None:
    """_qualify_forward_ref resolves TYPE_CHECKING imports via AST parsing."""
    from sphinx_pytest_fixtures._metadata import _qualify_forward_ref

    from libtmux.pytest_plugin import session

    fn = sphinx_pytest_fixtures._get_fixture_fn(session)
    result = _qualify_forward_ref("Session", fn)
    assert result == "libtmux.session.Session"


def test_qualify_forward_ref_returns_none_for_unknown() -> None:
    """_qualify_forward_ref returns None for names not found in module imports."""
    from sphinx_pytest_fixtures._metadata import _qualify_forward_ref

    from libtmux.pytest_plugin import server

    fn = sphinx_pytest_fixtures._get_fixture_fn(server)
    result = _qualify_forward_ref("NonexistentClass", fn)
    assert result is None
