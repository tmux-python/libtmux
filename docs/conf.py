"""Sphinx configuration for libtmux."""

from __future__ import annotations

import os
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

# The shell integration — libtmux.org's chrome and its site-wide search — is
# correct only where this build is served *under* the assembled site, at
# /py/<version>/api/. Two consumers do that: libtmux.org's assembler and a
# local preview of it. A third does not: .github/workflows/docs.yml publishes
# this same tree to the bucket behind libtmux.git-pull.com, at the root, where
# /_shell/shell.js is nothing and /search/ is this build's own search page.
#
# So the integration is on by default, for the two that nest it, and that
# workflow sets LIBTMUX_DOCS_STANDALONE=1 to opt out. Standalone keeps Furo's
# own search page and loads no chrome, which is what that host serves today.
#
# The design-token adapter stays on in both: it degrades to stock Furo by
# itself when the shared stylesheet is unreachable (see its own header).
shell_integration = os.environ.get("LIBTMUX_DOCS_STANDALONE", "") != "1"

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
    # _templates_shell holds only the search override, kept out of _templates
    # so dropping it from this list is all it takes to fall back to Furo's own
    # search page. Sphinx searches the list in order, and the value gp_sphinx
    # would otherwise supply on its own is spelled out here so a change to its
    # default cannot silently drop either directory.
    templates_path=(
        ["_templates_shell", "_templates"] if shell_integration else ["_templates"]
    ),
    html_favicon="_static/favicon.ico",
    # libtmux-org.css maps the site's shared --lt-* design tokens onto Furo's
    # own --color-* contract (see the file's own header) and must load after
    # css/custom.css so its overrides win.
    html_css_files=["css/custom.css", "libtmux-org.css"],
    # shell.js injects the header, footer and version switcher. Referenced,
    # never copied, so a chrome fix reaches an already-published build without
    # a rebuild here.
    html_js_files=(
        [("/_shell/shell.js", {"defer": "defer"})] if shell_integration else []
    ),
    html_extra_path=["manifest.json"],
    rediraffe_redirects="redirects.txt",
    # AGENTS.md (+ its CLAUDE.md symlink) is agent guidance, not a site
    # page; keep Sphinx from treating it as an orphan document.
    exclude_patterns=["_build", "AGENTS.md", "CLAUDE.md"],
)
globals().update(conf)
