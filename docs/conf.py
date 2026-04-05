"""Sphinx configuration for libtmux."""

from __future__ import annotations

import pathlib
import sys

import libtmux

from gp_sphinx.config import make_linkcode_resolve, merge_sphinx_config

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
    extra_extensions=["sphinx_pytest_fixtures", "sphinx.ext.todo"],
    intersphinx_mapping={
        "python": ("https://docs.python.org/", None),
        "pytest": ("https://docs.pytest.org/en/stable/", None),
    },
    linkcode_resolve=make_linkcode_resolve(
        libtmux, about["__github__"], src_dir="src"
    ),
    # Project-specific overrides
    theme_options={
        "announcement": (
            "<em>Friendly reminder:</em> 📌 Pin the package, libtmux is"
            " pre-1.0 and APIs will be <a href='/migration.html'>changing</a>"
            " throughout 2026."
        ),
    },
    html_favicon="_static/favicon.ico",
    html_css_files=["css/custom.css"],
    html_extra_path=["manifest.json"],
    rediraffe_redirects="redirects.txt",
)
globals().update(conf)
