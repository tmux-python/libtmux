"""Sphinx integration tests for tmux operation reference rendering."""

from __future__ import annotations

import io
import pathlib
import subprocess
import sys
import textwrap
import typing as t

import pytest
from sphinx.errors import SphinxError
from sphinx.testing.util import SphinxTestApp
from sphinx.util.inventory import InventoryFile

from libtmux.experimental.ops import catalog

_REPO_ROOT = pathlib.Path(__file__).parents[2]
_EXTENSION_PATH = _REPO_ROOT / "docs" / "_ext"


def _write_project(
    root: pathlib.Path,
    sources: dict[str, str],
) -> pathlib.Path:
    """Write one isolated Sphinx source tree."""
    source_dir = root / "source"
    source_dir.mkdir(parents=True)
    (source_dir / "conf.py").write_text(
        textwrap.dedent(
            f"""
            import sys

            sys.path.insert(0, {_EXTENSION_PATH.as_posix()!r})

            extensions = ["sphinx.ext.linkcode", "tmuxop"]
            project = "tmuxop-test"
            html_theme = "basic"

            def linkcode_resolve(domain, info):
                if domain != "py":
                    return None
                return "https://example.invalid/source/" + info["fullname"]
            """
        ),
        encoding="utf-8",
    )
    for relative_path, content in sources.items():
        destination = source_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(textwrap.dedent(content), encoding="utf-8")
    return source_dir


def _build(
    source_dir: pathlib.Path,
    *,
    parallel: int = 0,
    freshenv: bool = True,
    filenames: t.Sequence[pathlib.Path] = (),
) -> tuple[SphinxTestApp, str, str]:
    """Build one synthetic project and return captured streams."""
    root = source_dir.parent
    status = io.StringIO()
    warnings = io.StringIO()
    app = SphinxTestApp(
        srcdir=source_dir,
        builddir=root,
        buildername="html",
        status=status,
        warning=warnings,
        freshenv=freshenv,
        parallel=parallel,
    )
    try:
        app.build(filenames=filenames)
        return app, status.getvalue(), warnings.getvalue()
    finally:
        app.cleanup()


def _operation_sources() -> dict[str, str]:
    pane_kinds = [entry.kind for entry in catalog() if entry.scope == "pane"]
    sources = {
        "index.rst": (
            "Operation reference\n"
            "===================\n\n"
            ".. toctree::\n\n"
            + "\n".join(f"   {kind}" for kind in pane_kinds)
            + "\n\n.. tmuxop:catalog::\n   :scope: pane\n"
        )
    }
    for kind in pane_kinds:
        title = kind.replace("_", " ").title()
        sources[f"{kind}.rst"] = (
            f"{title}\n{'=' * len(title)}\n\n.. tmuxop:operation:: {kind}\n"
        )
    return sources


def test_operation_card_and_catalog_render_semantic_html(
    tmp_path: pathlib.Path,
) -> None:
    """A serial build renders a styled card and linked catalog."""
    source_dir = _write_project(tmp_path, _operation_sources())

    app, _, warnings = _build(source_dir)

    assert app.statuscode == 0
    assert warnings == ""
    operation_html = (tmp_path / "html" / "send_keys.html").read_text(encoding="utf-8")
    catalog_html = (tmp_path / "html" / "index.html").read_text(encoding="utf-8")
    assert "gp-sphinx-api-card-entry" in operation_html
    assert "SendKeys" in operation_html
    assert "send-keys" in operation_html
    assert "mutating" in operation_html
    assert "primitive" in operation_html
    assert "AckResult" in operation_html
    assert "Link to this operation" in operation_html
    assert "https://example.invalid/source/SendKeys" in operation_html
    assert 'href="send_keys.html#tmuxop-operation-send-keys"' in catalog_html


def test_parallel_build_exports_operation_inventory(tmp_path: pathlib.Path) -> None:
    """Parallel reading preserves operation targets and inventory entries."""
    source_dir = _write_project(tmp_path, _operation_sources())

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "sphinx",
            "-b",
            "html",
            "-j",
            "2",
            str(source_dir),
            str(tmp_path / "html"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    with (tmp_path / "html" / "objects.inv").open("rb") as inventory_file:
        inventory = InventoryFile.load(
            inventory_file,
            "",
            posixpath_join,
        )
    assert "send_keys" in inventory["tmuxop:operation"]


def posixpath_join(uri: str, location: str) -> str:
    """Join an inventory URI without platform-specific separators."""
    return f"{uri.rstrip('/')}/{location.lstrip('/')}"


def test_incremental_build_retains_unchanged_operation_targets(
    tmp_path: pathlib.Path,
) -> None:
    """Re-reading a catalog does not erase operation pages from the domain."""
    sources = {
        "index.rst": """
            Operation reference
            ===================

            .. toctree::

               send_keys
               split_window
        """,
        "send_keys.rst": """
            Send keys
            =========

            .. tmuxop:operation:: send_keys
        """,
        "split_window.rst": """
            Split window
            ============

            .. tmuxop:operation:: split_window
        """,
    }
    source_dir = _write_project(tmp_path, sources)
    _build(source_dir)
    index_path = source_dir / "index.rst"
    index_path.write_text(
        index_path.read_text(encoding="utf-8") + "\nUpdated.\n",
        encoding="utf-8",
    )

    app, _, warnings = _build(
        source_dir,
        freshenv=False,
        filenames=[index_path],
    )

    assert app.statuscode == 0
    assert warnings == ""
    domain = app.env.domains["tmuxop"]
    assert set(domain.operations) == {"send_keys", "split_window"}


@pytest.mark.parametrize(
    ("sources", "message"),
    [
        (
            {
                "index.rst": """
                    Unknown
                    =======

                    .. tmuxop:operation:: no_such_operation
                """
            },
            "no_such_operation",
        ),
        (
            {
                "index.rst": """
                    Duplicate
                    =========

                    .. toctree::

                       duplicate

                    .. tmuxop:operation:: send_keys
                """,
                "duplicate.rst": """
                    Duplicate
                    =========

                    .. tmuxop:operation:: send_keys
                """,
            },
            "already documented",
        ),
    ],
)
def test_invalid_operation_pages_fail_the_build(
    tmp_path: pathlib.Path,
    sources: dict[str, str],
    message: str,
) -> None:
    """Unknown or duplicate operation pages are fatal author errors."""
    source_dir = _write_project(tmp_path, sources)

    with pytest.raises(SphinxError, match=message):
        _build(source_dir)
