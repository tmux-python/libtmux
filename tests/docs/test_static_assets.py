"""Contracts for documentation assets emitted into HTML pages."""

from __future__ import annotations

import pathlib
import textwrap

from sphinx.testing.util import SphinxTestApp

_ROOT = pathlib.Path(__file__).parents[2]


def test_docs_setup_omits_deleted_inline_tabs_script_from_html(
    tmp_path: pathlib.Path,
) -> None:
    """Rendered tabs work without referencing gp-sphinx's deleted script."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "conf.py").write_text(
        textwrap.dedent(
            f"""
            import runpy

            _site = runpy.run_path({str(_ROOT / "docs" / "conf.py")!r})
            extensions = [
                name
                for name in _site["extensions"]
                if name == "sphinx_inline_tabs"
            ]
            html_theme = "basic"
            project = "asset-test"
            setup = _site["setup"]
            """
        ),
        encoding="utf-8",
    )
    (source / "index.rst").write_text(
        textwrap.dedent(
            """
            Asset test
            ==========

            .. tab:: Python plan

               Typed operation

            .. tab:: Compiled tmux sequence

               Rendered command
            """
        ),
        encoding="utf-8",
    )

    app = SphinxTestApp(
        srcdir=source,
        builddir=tmp_path / "_build",
        buildername="html",
        freshenv=True,
    )
    try:
        app.build()
        output = tmp_path / "_build" / "html"
        html = (output / "index.html").read_text(encoding="utf-8")
    finally:
        app.cleanup()

    assert 'class="tab-set' in html
    assert "_static/tabs.css" in html
    assert "_static/tabs.js" not in html
