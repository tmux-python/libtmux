"""Contracts for the shared experimental result reference."""

from __future__ import annotations

import io
import pathlib
import re
import textwrap

from sphinx.testing.util import SphinxTestApp

import libtmux.experimental.ops as ops
from libtmux.experimental.ops import Result, registry

_ROOT = pathlib.Path(__file__).parents[2]
_RESULTS_PAGE = _ROOT / "docs" / "experimental" / "results.md"
_EXPERIMENTAL_INDEX = _ROOT / "docs" / "experimental" / "index.md"
_EXTENSION_PATH = _ROOT / "docs" / "_ext"


def _result_target(result_cls: type[Result]) -> str:
    """Return the canonical Python target for a result class."""
    return f"{result_cls.__module__}.{result_cls.__qualname__}"


def _result_classes() -> set[type[Result]]:
    """Return the public base and every concrete registry result class."""
    return {Result, *(spec.result_cls for spec in registry)}


def _documented_targets() -> set[str]:
    """Return result class targets documented by the shared page."""
    assert _RESULTS_PAGE.exists(), "missing experimental results reference"
    text = _RESULTS_PAGE.read_text(encoding="utf-8")
    return set(
        re.findall(
            r"^\.\. autoclass:: (libtmux\.experimental\.ops\.results\.\w+)$",
            text,
            re.MULTILINE,
        )
    )


def _write_sphinx_project(
    tmp_path: pathlib.Path,
) -> tuple[pathlib.Path, dict[type[Result], str]]:
    """Write a focused results plus operation-card Sphinx project."""
    assert _RESULTS_PAGE.exists(), "missing experimental results reference"
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "conf.py").write_text(
        textwrap.dedent(
            f"""
            import sys

            sys.path.insert(0, {_EXTENSION_PATH.as_posix()!r})

            extensions = [
                "myst_parser",
                "sphinx.ext.linkcode",
                "sphinx_autodoc_api_style",
                "tmuxop",
            ]
            project = "result-reference-test"
            html_theme = "basic"
            api_layout_enabled = True
            autodoc_class_signature = "separated"
            autodoc_typehints = "description"
            myst_enable_extensions = {{"colon_fence"}}

            def linkcode_resolve(domain, info):
                if domain != "py":
                    return None
                return "https://example.invalid/source/" + info["fullname"]
            """
        ),
        encoding="utf-8",
    )
    (source_dir / "results.md").write_text(
        _RESULTS_PAGE.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    tutorial_dir = source_dir / "tutorials"
    tutorial_dir.mkdir()
    (tutorial_dir / "results-and-failures.md").write_text(
        "# Result paths\n",
        encoding="utf-8",
    )

    representatives: dict[type[Result], str] = {}
    for spec in registry:
        representatives.setdefault(spec.result_cls, spec.kind)

    operation_dir = source_dir / "operations"
    operation_dir.mkdir()
    for kind in representatives.values():
        (operation_dir / f"{kind}.md").write_text(
            f"# {kind}\n\n```{{tmuxop:operation}} {kind}\n```\n",
            encoding="utf-8",
        )

    toctree = "\n".join(
        [
            "results",
            "tutorials/results-and-failures",
            *(f"operations/{kind}" for kind in representatives.values()),
        ]
    )
    (source_dir / "index.md").write_text(
        f"# Result reference build\n\n```{{toctree}}\n\n{toctree}\n```\n",
        encoding="utf-8",
    )
    return source_dir, representatives


def test_results_reference_documents_exact_public_result_inventory() -> None:
    """The page owns one ordinary autodoc card per public result class."""
    result_classes = _result_classes()
    assert {result_cls.__name__ for result_cls in result_classes} <= set(ops.__all__)
    assert _documented_targets() == {
        _result_target(result_cls) for result_cls in result_classes
    }

    text = _RESULTS_PAGE.read_text(encoding="utf-8")
    for target in _documented_targets():
        assert f".. autoclass:: {target}\n   :members:" in text


def test_results_reference_documents_missing_capture_error() -> None:
    """The public eager-navigation invariant error has an API target."""
    text = _RESULTS_PAGE.read_text(encoding="utf-8")

    assert (
        ".. autoexception:: libtmux.experimental.ops.exc.MissingCreateIdError" in text
    )


def test_every_operation_result_target_is_documented() -> None:
    """Every registered operation points to a class target on the page."""
    documented = _documented_targets()

    for spec in registry:
        assert _result_target(spec.result_cls) in documented, spec.kind


def test_results_reference_has_visible_example_and_navigation() -> None:
    """The shared page is executable and reachable from the experimental root."""
    assert _RESULTS_PAGE.exists(), "missing experimental results reference"
    text = _RESULTS_PAGE.read_text(encoding="utf-8")
    index = _EXPERIMENTAL_INDEX.read_text(encoding="utf-8")

    assert text.count("```python") == 1
    assert ">>>" in text
    assert "# doctest: +SKIP" not in text
    assert "testsetup" not in text
    assert "[Results](results.md)" in index
    assert "\nresults\n" in index


def test_operation_result_links_resolve_to_autodoc_cards(
    tmp_path: pathlib.Path,
) -> None:
    """Each concrete result family links from an operation card to its API card."""
    source_dir, representatives = _write_sphinx_project(tmp_path)
    status = io.StringIO()
    warnings = io.StringIO()
    app = SphinxTestApp(
        srcdir=source_dir,
        builddir=tmp_path / "_build",
        buildername="html",
        status=status,
        warning=warnings,
        freshenv=True,
    )
    try:
        app.build()

        assert app.statuscode == 0
        assert warnings.getvalue() == ""
        python_targets = set(app.env.domains["py"].objects)
        assert {
            _result_target(result_cls) for result_cls in _result_classes()
        } <= python_targets
        assert "libtmux.experimental.ops.exc.MissingCreateIdError" in python_targets

        for result_cls, kind in representatives.items():
            html = (
                tmp_path / "_build" / "html" / "operations" / f"{kind}.html"
            ).read_text(encoding="utf-8")
            target = _result_target(result_cls)
            assert f'href="../results.html#{target}"' in html, kind
    finally:
        app.cleanup()
