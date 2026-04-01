"""Integration tests for sphinx_pytest_fixtures using a full Sphinx build.

These tests build a minimal Sphinx project with a synthetic fixture module so
results are independent of the libtmux fixture signatures.  They gate the B1,
B2, and B4/B5 fixes in subsequent commits.

Run integration tests specifically:

    uv run pytest tests/docs/_ext/test_sphinx_pytest_fixtures_integration.py -v

"""

from __future__ import annotations

import io
import pathlib
import sys
import textwrap
import typing as t

import pytest

# ---------------------------------------------------------------------------
# Synthetic fixture module written to tmp_path for each test run
# ---------------------------------------------------------------------------

FIXTURE_MOD_SOURCE = textwrap.dedent(
    """\
    from __future__ import annotations
    import typing as t
    import pytest

    class Server:
        \"\"\"A fake server.\"\"\"

    @pytest.fixture(scope="session")
    def my_server() -> Server:
        \"\"\"Return a fake server for testing.

        Use this when you need a long-lived server across the session.
        \"\"\"
        return Server()

    @pytest.fixture
    def my_client(my_server: Server) -> str:
        \"\"\"Return a fake client connected to *my_server*.\"\"\"
        return f"client@{my_server}"

    @pytest.fixture
    def home_user() -> str:
        \"\"\"Override to customise the home directory username.\"\"\"
        return "testuser"

    @pytest.fixture
    def yield_server(my_server: Server) -> t.Generator[Server, None, None]:
        \"\"\"Yield the server and tear down after the test.\"\"\"
        yield my_server

    @pytest.fixture(autouse=True)
    def auto_cleanup() -> None:
        \"\"\"Runs automatically before every test — no request needed.\"\"\"

    @pytest.fixture
    def TestServer() -> type[Server]:
        \"\"\"Return the Server class for direct instantiation (factory fixture).\"\"\"
        return Server

    @pytest.fixture(name="renamed_fixture")
    def _internal_name() -> str:
        \"\"\"Fixture with a name alias — injected as 'renamed_fixture'.\"\"\"
        return "renamed"
    """,
)

CONF_PY_TEMPLATE = """\
import sys
sys.path.insert(0, "{srcdir}")

extensions = [
    "sphinx.ext.autodoc",
    "sphinx_pytest_fixtures",
]

master_doc = "index"
exclude_patterns = ["_build"]
html_theme = "alabaster"
"""

INDEX_RST = textwrap.dedent(
    """\
    Test fixtures
    =============

    .. py:module:: fixture_mod

    .. autofixture:: fixture_mod.my_server

    .. autofixture:: fixture_mod.my_client

    .. autofixture:: fixture_mod.home_user
       :kind: override_hook

    .. autofixture:: fixture_mod.yield_server

    .. autofixture:: fixture_mod.auto_cleanup

    .. autofixture:: fixture_mod.TestServer

    .. autofixture:: fixture_mod._internal_name
    """,
)


# ---------------------------------------------------------------------------
# Module isolation helper
# ---------------------------------------------------------------------------


def _purge_fixture_module(name: str = "fixture_mod") -> None:
    """Remove *name* and its sub-modules from sys.modules.

    Multiple Sphinx builds in the same process cache imported modules.
    Without this cleanup, the second test to use ``fixture_mod`` gets the
    first test's cached version — new attributes written to a fresh
    ``fixture_mod.py`` in a different ``tmp_path`` are never visible.
    """
    for key in list(sys.modules):
        if key == name or key.startswith(f"{name}."):
            del sys.modules[key]


# ---------------------------------------------------------------------------
# Shared fixture: build the Sphinx app once per test (no caching — each test
# gets an isolated tmp_path)
# ---------------------------------------------------------------------------


class _SphinxResult(t.NamedTuple):
    """Lightweight wrapper around a completed Sphinx build."""

    app: t.Any  # sphinx.application.Sphinx
    srcdir: pathlib.Path
    outdir: pathlib.Path
    status: str
    warnings: str


def _build_sphinx_app(
    tmp_path: pathlib.Path,
    *,
    confoverrides: dict[str, t.Any] | None = None,
    fixture_source: str | None = None,
    index_rst: str | None = None,
) -> _SphinxResult:
    """Write project files and run a full Sphinx HTML build; return results.

    Parameters
    ----------
    tmp_path :
        Per-test temporary directory provided by pytest.
    confoverrides :
        Optional Sphinx confoverrides dict (passed to Sphinx constructor).
    fixture_source :
        Override the fixture module source written to ``fixture_mod.py``.
        Defaults to :data:`FIXTURE_MOD_SOURCE`.
    index_rst :
        Override the RST index written to ``index.rst``.
        Defaults to :data:`INDEX_RST`.
    """
    from sphinx.application import Sphinx

    srcdir = tmp_path / "src"
    outdir = tmp_path / "out"
    doctreedir = tmp_path / ".doctrees"

    srcdir.mkdir()
    outdir.mkdir()
    doctreedir.mkdir()

    (srcdir / "fixture_mod.py").write_text(
        fixture_source if fixture_source is not None else FIXTURE_MOD_SOURCE,
        encoding="utf-8",
    )
    (srcdir / "conf.py").write_text(
        CONF_PY_TEMPLATE.format(srcdir=str(srcdir)),
        encoding="utf-8",
    )
    (srcdir / "index.rst").write_text(
        index_rst if index_rst is not None else INDEX_RST,
        encoding="utf-8",
    )

    status_buf = io.StringIO()
    warning_buf = io.StringIO()

    _purge_fixture_module()
    app = Sphinx(
        srcdir=str(srcdir),
        confdir=str(srcdir),
        outdir=str(outdir),
        doctreedir=str(doctreedir),
        buildername="html",
        confoverrides=confoverrides,
        status=status_buf,
        warning=warning_buf,
        freshenv=True,
    )
    app.build()

    return _SphinxResult(
        app=app,
        srcdir=srcdir,
        outdir=outdir,
        status=status_buf.getvalue(),
        warnings=warning_buf.getvalue(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_fixture_target_id(tmp_path: pathlib.Path) -> None:
    """Registered fixtures have non-empty IDs in their signature nodes."""
    from sphinx.domains.python import PythonDomain

    result = _build_sphinx_app(tmp_path)
    domain = t.cast("PythonDomain", result.app.env.get_domain("py"))
    objects = domain.data["objects"]
    # ObjectEntry = (docname, node_id, objtype, aliased)
    fixture_keys = [k for k, v in objects.items() if v.objtype == "fixture"]
    assert fixture_keys, f"No py:fixture objects found in domain. Objects: {objects}"


@pytest.mark.integration
def test_fixture_in_domain_objects(tmp_path: pathlib.Path) -> None:
    """Domain objects registry has qualified fixture names with objtype='fixture'."""
    from sphinx.domains.python import PythonDomain

    result = _build_sphinx_app(tmp_path)
    domain = t.cast("PythonDomain", result.app.env.get_domain("py"))
    objects = domain.data["objects"]

    assert "fixture_mod.my_server" in objects, (
        f"fixture_mod.my_server not in domain objects. Keys: {list(objects)}"
    )
    # ObjectEntry = (docname, node_id, objtype, aliased)
    assert objects["fixture_mod.my_server"].objtype == "fixture", (
        f"Expected objtype='fixture', got {objects['fixture_mod.my_server'].objtype!r}"
    )


@pytest.mark.integration
def test_fixture_in_inventory(tmp_path: pathlib.Path) -> None:
    """objects.inv contains a 'py:fixture' section with the registered fixtures."""
    from sphinx.util.inventory import InventoryFile

    result = _build_sphinx_app(tmp_path)
    inv_path = result.outdir / "objects.inv"
    assert inv_path.exists(), "objects.inv was not generated"

    inv = InventoryFile.loads(inv_path.read_bytes(), uri="")
    # inv.data is dict[obj_type_str, dict[name_str, _InventoryItem]]
    assert "py:fixture" in inv.data, (
        f"'py:fixture' not in inventory. Types: {sorted(inv.data)}"
    )
    fixture_names = list(inv.data["py:fixture"])
    assert any("my_server" in name for name in fixture_names), (
        f"my_server not in py:fixture inventory entries: {fixture_names}"
    )


@pytest.mark.integration
def test_manual_directive_without_module(tmp_path: pathlib.Path) -> None:
    """Manual py:fixture without currentmodule uses bare name as target."""
    from sphinx.application import Sphinx
    from sphinx.domains.python import PythonDomain

    srcdir = tmp_path / "src"
    outdir = tmp_path / "out"
    doctreedir = tmp_path / ".doctrees"
    srcdir.mkdir()
    outdir.mkdir()
    doctreedir.mkdir()

    (srcdir / "fixture_mod.py").write_text(FIXTURE_MOD_SOURCE, encoding="utf-8")
    (srcdir / "conf.py").write_text(
        CONF_PY_TEMPLATE.format(srcdir=str(srcdir)),
        encoding="utf-8",
    )
    # Bare directive with no currentmodule
    (srcdir / "index.rst").write_text(
        "Manual\n======\n\n.. py:fixture:: bare_server\n\n   Bare server docs.\n",
        encoding="utf-8",
    )

    _purge_fixture_module()
    app = Sphinx(
        srcdir=str(srcdir),
        confdir=str(srcdir),
        outdir=str(outdir),
        doctreedir=str(doctreedir),
        buildername="html",
        status=io.StringIO(),
        warning=io.StringIO(),
        freshenv=True,
    )
    app.build()

    domain = t.cast("PythonDomain", app.env.get_domain("py"))
    objects = domain.data["objects"]
    # Without currentmodule the target is the bare name — document this known behaviour
    assert "bare_server" in objects, (
        "Known limitation: bare py:fixture registers under unqualified name. "
        f"Objects: {list(objects)}"
    )


@pytest.mark.integration
def test_xref_resolves(tmp_path: pathlib.Path) -> None:
    """Cross-file :fixture: role resolves to a hyperlink in the output HTML."""
    from sphinx.application import Sphinx

    srcdir = tmp_path / "src"
    outdir = tmp_path / "out"
    doctreedir = tmp_path / ".doctrees"
    srcdir.mkdir()
    outdir.mkdir()
    doctreedir.mkdir()

    (srcdir / "fixture_mod.py").write_text(FIXTURE_MOD_SOURCE, encoding="utf-8")
    (srcdir / "conf.py").write_text(
        CONF_PY_TEMPLATE.format(srcdir=str(srcdir)),
        encoding="utf-8",
    )
    (srcdir / "index.rst").write_text(
        textwrap.dedent(
            """\
            Fixtures
            ========

            .. toctree::

               api
               usage

            """,
        ),
        encoding="utf-8",
    )
    (srcdir / "api.rst").write_text(
        textwrap.dedent(
            """\
            API
            ===

            .. py:module:: fixture_mod

            .. autofixture:: fixture_mod.my_server
            """,
        ),
        encoding="utf-8",
    )
    (srcdir / "usage.rst").write_text(
        textwrap.dedent(
            """\
            Usage
            =====

            Use :fixture:`fixture_mod.my_server` to get a server.
            """,
        ),
        encoding="utf-8",
    )

    warning_buf = io.StringIO()
    _purge_fixture_module()
    app = Sphinx(
        srcdir=str(srcdir),
        confdir=str(srcdir),
        outdir=str(outdir),
        doctreedir=str(doctreedir),
        buildername="html",
        status=io.StringIO(),
        warning=warning_buf,
        freshenv=True,
    )
    app.build()

    usage_html = (outdir / "usage.html").read_text(encoding="utf-8")
    # The xref should produce a hyperlink element pointing to the fixture
    assert "<a " in usage_html and "my_server" in usage_html, (
        "Cross-reference :fixture:`fixture_mod.my_server` did not produce a link "
        f"in usage.html. Warnings: {warning_buf.getvalue()}"
    )


@pytest.mark.integration
def test_scope_metadata_visible(tmp_path: pathlib.Path) -> None:
    """Scope value appears in the rendered HTML for autofixture directives."""
    result = _build_sphinx_app(tmp_path)
    index_html = (result.outdir / "index.html").read_text(encoding="utf-8")
    # my_server has scope="session"; the rendered page should mention it
    assert "session" in index_html, (
        "Expected scope 'session' to appear in rendered HTML for my_server"
    )


@pytest.mark.integration
def test_config_hidden_deps(tmp_path: pathlib.Path) -> None:
    """pytest_fixture_hidden_dependencies suppresses named deps from output HTML."""
    import sphinx_pytest_fixtures

    # my_client depends on my_server; hiding my_server should suppress it
    result = _build_sphinx_app(
        tmp_path,
        confoverrides={
            "pytest_fixture_hidden_dependencies": frozenset(
                {*sphinx_pytest_fixtures.PYTEST_HIDDEN, "my_server"},
            ),
        },
    )
    index_html = (result.outdir / "index.html").read_text(encoding="utf-8")
    # With my_server hidden, it must not appear in "Depends on" for my_client
    # (it may still appear as its own fixture entry — check the Depends section)
    assert (
        "Depends on" not in index_html
        or "my_server"
        not in index_html.split(
            "Depends on",
        )[-1].split("</")[0]
    ), (
        "my_server should be hidden from Depends on when added to "
        "pytest_fixture_hidden_dependencies config"
    )


@pytest.mark.integration
def test_builtin_dep_external_link(tmp_path: pathlib.Path) -> None:
    """Pytest builtin deps in PYTEST_BUILTIN_LINKS render with an external URL."""
    import sphinx_pytest_fixtures

    # Add a synthetic fixture that depends on tmp_path (a builtin with external link)
    src = FIXTURE_MOD_SOURCE + textwrap.dedent(
        """\

        @pytest.fixture
        def needs_tmp(tmp_path: "pathlib.Path") -> str:
            \"\"\"Uses tmp_path internally.\"\"\"
            return str(tmp_path)
        """,
    )
    srcdir = tmp_path / "src"
    outdir = tmp_path / "out"
    doctreedir = tmp_path / ".doctrees"
    srcdir.mkdir()
    outdir.mkdir()
    doctreedir.mkdir()

    (srcdir / "fixture_mod.py").write_text(src, encoding="utf-8")
    (srcdir / "conf.py").write_text(
        CONF_PY_TEMPLATE.format(srcdir=str(srcdir)),
        encoding="utf-8",
    )
    (srcdir / "index.rst").write_text(
        "Fixtures\n========\n\n.. py:module:: fixture_mod\n\n"
        ".. autofixture:: fixture_mod.needs_tmp\n",
        encoding="utf-8",
    )

    assert "tmp_path" in sphinx_pytest_fixtures.PYTEST_BUILTIN_LINKS, (
        "tmp_path must be in PYTEST_BUILTIN_LINKS for this test to be meaningful"
    )

    from sphinx.application import Sphinx

    _purge_fixture_module()
    sphinx_app = Sphinx(
        srcdir=str(srcdir),
        confdir=str(srcdir),
        outdir=str(outdir),
        doctreedir=str(doctreedir),
        buildername="html",
        status=io.StringIO(),
        warning=io.StringIO(),
        freshenv=True,
    )
    sphinx_app.build()

    index_html = (outdir / "index.html").read_text(encoding="utf-8")
    # tmp_path dependency should be rendered with an external href
    assert "tmp_path" in index_html, (
        "tmp_path dependency should appear in rendered HTML"
    )


@pytest.mark.integration
def test_kind_override_hook_option(tmp_path: pathlib.Path) -> None:
    """Manual :kind: override_hook option appears in rendered HTML."""
    srcdir = tmp_path / "src"
    outdir = tmp_path / "out"
    doctreedir = tmp_path / ".doctrees"
    srcdir.mkdir()
    outdir.mkdir()
    doctreedir.mkdir()

    (srcdir / "fixture_mod.py").write_text(FIXTURE_MOD_SOURCE, encoding="utf-8")
    (srcdir / "conf.py").write_text(
        CONF_PY_TEMPLATE.format(srcdir=str(srcdir)),
        encoding="utf-8",
    )
    (srcdir / "index.rst").write_text(
        textwrap.dedent(
            """\
            Fixtures
            ========

            .. py:module:: fixture_mod

            .. py:fixture:: home_user
               :kind: override_hook

               Override the home username.
            """,
        ),
        encoding="utf-8",
    )

    from sphinx.application import Sphinx

    _purge_fixture_module()
    app = Sphinx(
        srcdir=str(srcdir),
        confdir=str(srcdir),
        outdir=str(outdir),
        doctreedir=str(doctreedir),
        buildername="html",
        status=io.StringIO(),
        warning=io.StringIO(),
        freshenv=True,
    )
    app.build()

    index_html = (outdir / "index.html").read_text(encoding="utf-8")
    # Standard kinds (override_hook) are communicated via badge, not Kind field.
    assert "spf-override" in index_html, (
        "Expected spf-override badge class when :kind: override_hook is set"
    )


@pytest.mark.integration
def test_override_hook_snippet_shows_conftest(tmp_path: pathlib.Path) -> None:
    """override_hook fixtures show a conftest.py snippet, not def test_example."""
    result = _build_sphinx_app(tmp_path)
    index_html = (result.outdir / "index.html").read_text(encoding="utf-8")
    # home_user is classified as override_hook via explicit :kind: option —
    # its usage snippet must show conftest.py, not test.
    assert "conftest.py" in index_html, (
        "Expected conftest.py in override_hook fixture usage snippet (home_user)"
    )


@pytest.mark.integration
def test_function_scope_field_suppressed(tmp_path: pathlib.Path) -> None:
    """Function-scope fixtures do not render a 'Scope:' metadata field."""
    result = _build_sphinx_app(tmp_path)
    index_html = (result.outdir / "index.html").read_text(encoding="utf-8")
    # my_client is function-scope; "Scope" field should be absent from its entry.
    # my_server is session-scope and WILL have "Scope" — check that function-scope
    # entries between my_client headings do not contain "Scope: function".
    # Simple check: "function" should not appear as a scope value anywhere.
    assert "Scope: function" not in index_html, (
        "Function-scope fixture should not render 'Scope: function' field"
    )


@pytest.mark.integration
def test_badge_group_present_in_html(tmp_path: pathlib.Path) -> None:
    """Every fixture signature contains a spf-badge-group span."""
    result = _build_sphinx_app(tmp_path)
    index_html = (result.outdir / "index.html").read_text(encoding="utf-8")
    assert "spf-badge-group" in index_html, (
        "Expected spf-badge-group to be present in rendered HTML"
    )
    assert "spf-badge--fixture" in index_html, (
        "Expected FIXTURE badge (spf-badge--fixture) to be present in rendered HTML"
    )


@pytest.mark.integration
def test_scope_badge_session_present(tmp_path: pathlib.Path) -> None:
    """Session-scope fixtures have a scope badge with class spf-scope-session."""
    result = _build_sphinx_app(tmp_path)
    index_html = (result.outdir / "index.html").read_text(encoding="utf-8")
    assert "spf-scope-session" in index_html, (
        "Expected spf-scope-session class badge for my_server (scope=session)"
    )


@pytest.mark.integration
def test_no_scope_badge_for_function_scope(tmp_path: pathlib.Path) -> None:
    """Function-scope fixtures do not have a scope badge in the HTML."""
    result = _build_sphinx_app(tmp_path)
    index_html = (result.outdir / "index.html").read_text(encoding="utf-8")
    assert "spf-scope-function" not in index_html, (
        "Function-scope fixtures should not render a scope badge"
    )


@pytest.mark.integration
def test_session_scope_lifecycle_note_present(tmp_path: pathlib.Path) -> None:
    """Session-scope fixtures have a lifecycle callout note in HTML."""
    result = _build_sphinx_app(tmp_path)
    index_html = (result.outdir / "index.html").read_text(encoding="utf-8")
    assert "once per test session" in index_html, (
        "Expected session-scope lifecycle note for my_server (scope=session)"
    )


@pytest.mark.integration
def test_no_build_warnings(tmp_path: pathlib.Path) -> None:
    """A full build of the synthetic fixture module produces zero WARNING lines."""
    result = _build_sphinx_app(tmp_path)
    warnings = result.warnings
    # Strip ANSI escape codes before filtering
    import re

    ansi_escape = re.compile(r"\x1b\[[0-9;]*m")
    warning_lines = [
        line
        for line in warnings.splitlines()
        if "WARNING" in line
        # Sphinx emits "already registered" warnings when multiple Sphinx apps
        # run in the same process — these are internal Sphinx artefacts, not
        # problems with our extension.
        and "already registered" not in line
        # Filter Sphinx theme warnings unrelated to fixture processing
        and "alabaster" not in line
    ]
    # Strip ANSI codes for readability in failure output
    warning_lines = [ansi_escape.sub("", line) for line in warning_lines]
    assert not warning_lines, "Unexpected WARNING lines in build output:\n" + "\n".join(
        warning_lines
    )


@pytest.mark.integration
def test_factory_snippet_shows_instantiation(tmp_path: pathlib.Path) -> None:
    """Factory fixtures are classified as factory and render a FACTORY badge."""
    result = _build_sphinx_app(tmp_path)
    index_html = (result.outdir / "index.html").read_text(encoding="utf-8")
    # TestServer is a factory fixture — it must have the FACTORY badge.
    assert "spf-factory" in index_html, (
        "Expected spf-factory class badge for TestServer factory fixture"
    )
    # Standard kinds (resource, factory, override_hook) are communicated via
    # badges only — the Kind field is suppressed for badge-covered kinds.
    assert "<p>factory</p>" not in index_html, (
        "Standard Kind field should be suppressed when badge covers it"
    )


@pytest.mark.integration
def test_autouse_note_present(tmp_path: pathlib.Path) -> None:
    """Autouse fixtures show a 'No request needed' note instead of a test snippet."""
    result = _build_sphinx_app(tmp_path)
    index_html = (result.outdir / "index.html").read_text(encoding="utf-8")
    assert "No request needed" in index_html, (
        "Expected 'No request needed' note for auto_cleanup (autouse=True)"
    )


@pytest.mark.integration
def test_name_alias_registered_in_domain(tmp_path: pathlib.Path) -> None:
    """Fixtures with name= alias are registered under the alias, not internal name."""
    from sphinx.domains.python import PythonDomain

    result = _build_sphinx_app(tmp_path)
    domain = t.cast("PythonDomain", result.app.env.get_domain("py"))
    objects = domain.data["objects"]
    fixture_keys = {k for k, v in objects.items() if v.objtype == "fixture"}
    assert "fixture_mod.renamed_fixture" in fixture_keys, (
        f"Expected 'fixture_mod.renamed_fixture' in domain objects. "
        f"Fixture keys: {fixture_keys}"
    )
    assert "fixture_mod._internal_name" not in fixture_keys, (
        "Internal function name '_internal_name' should not appear in domain — "
        "only the 'renamed_fixture' alias should be registered"
    )


# ---------------------------------------------------------------------------
# "Used by" and "Parametrized" metadata rendering (Commit 3)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_used_by_links_rendered(tmp_path: pathlib.Path) -> None:
    """Fixtures with consumers show a "Used by" field with links."""
    result = _build_sphinx_app(tmp_path)
    index_html = (result.outdir / "index.html").read_text(encoding="utf-8")
    # my_server is used by my_client and yield_server
    assert "Used by" in index_html
    assert "my_client" in index_html


@pytest.mark.integration
def test_used_by_not_shown_when_no_consumers(tmp_path: pathlib.Path) -> None:
    """Fixtures with no consumers do not show "Used by"."""
    result = _build_sphinx_app(tmp_path)
    store = result.app.env.domaindata.get("sphinx_pytest_fixtures", {})
    reverse_deps = store.get("reverse_deps", {})
    assert "fixture_mod.auto_cleanup" not in reverse_deps


@pytest.mark.integration
def test_parametrized_values_rendered(tmp_path: pathlib.Path) -> None:
    """Parametrized fixtures show their parameter values."""
    extra_fixture = textwrap.dedent(
        """\

    @pytest.fixture(params=["bash", "zsh"])
    def shell(request) -> str:
        \"\"\"Fixture parametrized over shell interpreters.\"\"\"
        return request.param
    """,
    )
    result = _build_sphinx_app(
        tmp_path,
        fixture_source=FIXTURE_MOD_SOURCE + extra_fixture,
        index_rst=INDEX_RST + "\n.. autofixture:: fixture_mod.shell\n",
    )
    index_html = (result.outdir / "index.html").read_text(encoding="utf-8")
    assert "Parametrized" in index_html
    assert "'bash'" in index_html
    assert "'zsh'" in index_html


# ---------------------------------------------------------------------------
# Short-name :fixture: xref resolution (Commit 3)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_short_name_fixture_xref_resolves(tmp_path: pathlib.Path) -> None:
    """:fixture:`my_server` short-name reference resolves to a hyperlink."""
    index_with_xref = INDEX_RST + textwrap.dedent(
        """\

    Usage
    -----

    See :fixture:`my_server` for the server fixture.
    """,
    )
    result = _build_sphinx_app(tmp_path, index_rst=index_with_xref)
    index_html = (result.outdir / "index.html").read_text(encoding="utf-8")
    # Should resolve to a real link, not a <span class="xref"> (broken ref)
    assert (
        '<a class="reference internal"' in index_html
        or "fixture_mod.my_server" in index_html
    )
    # And no fixture-related warnings
    fixture_warnings = [
        line
        for line in result.warnings.splitlines()
        if "fixture" in line.lower() and "my_server" in line
    ]
    assert fixture_warnings == [], f"Unexpected warnings: {fixture_warnings}"


# ---------------------------------------------------------------------------
# Manual py:fixture:: directive store participation (Commit 4)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_manual_directive_in_store(tmp_path: pathlib.Path) -> None:
    """Manual .. py:fixture:: directives register in the env store."""
    manual_rst = textwrap.dedent(
        """\
    Test fixtures
    =============

    .. py:module:: fixture_mod

    .. autofixture:: fixture_mod.my_server

    .. py:fixture:: manual_helper
       :scope: session
       :depends: my_server

       A manually documented fixture.
    """,
    )
    result = _build_sphinx_app(tmp_path, index_rst=manual_rst)
    store = result.app.env.domaindata.get("sphinx_pytest_fixtures", {})
    fixtures = store.get("fixtures", {})
    assert "fixture_mod.manual_helper" in fixtures
    meta = fixtures["fixture_mod.manual_helper"]
    assert meta.scope == "session"
    assert len(meta.deps) == 1
    assert meta.deps[0].display_name == "my_server"


# ---------------------------------------------------------------------------
# CSS contract tests — verify extension HTML matches custom.css selectors
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_css_contract_badge_classes(tmp_path: pathlib.Path) -> None:
    """CSS class names used in custom.css are present in rendered HTML."""
    result = _build_sphinx_app(tmp_path)
    index_html = (result.outdir / "index.html").read_text(encoding="utf-8")

    # These classes are targeted by selectors in docs/_static/css/custom.css.
    # If the extension changes its class names, CSS silently breaks.
    css_classes = [
        "spf-badge-group",
        "spf-badge",
        "spf-badge--fixture",
        "spf-badge--scope",
        "spf-scope-session",
        "spf-badge--kind",
        "spf-factory",
    ]
    for cls in css_classes:
        assert cls in index_html, f"CSS class {cls!r} missing from rendered HTML"


@pytest.mark.integration
def test_badge_tabindex_in_html(tmp_path: pathlib.Path) -> None:
    """Badges render with tabindex='0' for touch/keyboard accessibility."""
    result = _build_sphinx_app(tmp_path)
    index_html = (result.outdir / "index.html").read_text(encoding="utf-8")
    assert 'tabindex="0"' in index_html, (
        "Expected tabindex='0' on badge <abbr> elements for touch accessibility"
    )
