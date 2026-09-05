"""Sphinx configuration for libtmux."""

from __future__ import annotations

import pathlib
import sys

from gp_sphinx.config import make_linkcode_resolve, merge_sphinx_config

import libtmux

# Get the project root dir, which is the parent dir of this
cwd = pathlib.Path(__file__).parent
project_root = cwd.parent
project_src = project_root / "src"

sys.path.insert(0, str(project_src))

# package data
about: dict[str, str] = {}
with (project_src / "libtmux" / "__about__.py").open() as fp:
    exec(fp.read(), about)

conf = merge_sphinx_config(
    project=about["__title__"],
    version=about["__version__"],
    copyright=about["__copyright__"],
    source_repository=f"{about['__github__']}/",
    docs_url=about["__docs__"],
    source_branch="master",
    light_logo="img/libtmux.svg",
    dark_logo="img/libtmux.svg",
    extra_extensions=[
        "sphinx_autodoc_api_style",
        "sphinx_autodoc_pytest_fixtures",
        "sphinx.ext.todo",
    ],
    intersphinx_mapping={
        "python": ("https://docs.python.org/", None),
        "pytest": ("https://docs.pytest.org/en/stable/", None),
    },
    linkcode_resolve=make_linkcode_resolve(libtmux, about["__github__"], src_dir="src"),
    # Project-specific overrides
    theme_options={
        "announcement": (
            "<em>Friendly reminder:</em> 📌 Pin the package, libtmux is"
            " pre-1.0 and APIs will be <a href='/migration.html'>changing</a>"
            " throughout 2026."
        ),
    },
    # Explicit rather than relying on gp_sphinx's own default of the same
    # value: docs/_templates/search.html overrides Furo's search page (see
    # its own header comment) to redirect to the shell's Pagefind search
    # instead of rendering a UI with no index at this path
    # (notes/status.md, "Sphinx's own search page is a dead end", in the
    # docs-site repo). A future change to gp_sphinx's own default should
    # not silently stop that override from loading.
    templates_path=["_templates"],
    html_favicon="_static/favicon.ico",
    # libtmux-org.css is the design-token adapter closing notes/status.md's
    # "Python and C++ are unskinned islands" glitch — it maps the shared
    # --lt-* tokens onto Furo's own --color-* contract (see the file's own
    # header) and must load after css/custom.css so its overrides win.
    # shell.js injects the header/footer/version-switcher chrome; both are
    # served from a stable URL (never copied) so a chrome fix reaches this
    # already-published build without a rebuild.
    html_css_files=["css/custom.css", "libtmux-org.css"],
    html_js_files=[("/_shell/shell.js", {"defer": "defer"})],
    html_extra_path=["manifest.json"],
    rediraffe_redirects="redirects.txt",
    # AGENTS.md (+ its CLAUDE.md symlink) is agent guidance, not a site
    # page; keep Sphinx from treating it as an orphan document.
    exclude_patterns=["_build", "AGENTS.md", "CLAUDE.md"],
)
globals().update(conf)
