"""Regression tests for executable documentation isolation."""

from __future__ import annotations

import os
import pathlib

import pytest

_ROOT_CONFTEST = pathlib.Path(__file__).parents[2] / "conftest.py"


def _install_root_conftest(pytester: pytest.Pytester) -> None:
    """Give an isolated pytest run the repository's doctest fixtures."""
    pytester.makeconftest(_ROOT_CONFTEST.read_text(encoding="utf-8"))


def test_docs_doctest_sandbox_configures_private_tmux_environment(
    docs_doctest_sandbox: pathlib.Path,
) -> None:
    """The fixture provides a private home, socket base, and tmux config."""
    home = docs_doctest_sandbox / "home"
    tmux_tmpdir = docs_doctest_sandbox / "tmux"

    assert pathlib.Path(os.environ["HOME"]) == home
    assert pathlib.Path(os.environ["TMUX_TMPDIR"]) == tmux_tmpdir
    assert "TMUX" not in os.environ
    assert "TMUX_PANE" not in os.environ
    assert (home / ".tmux.conf").read_text(encoding="utf-8") == (
        "set -g base-index 1\n"
    )
    assert (home / ".zshrc").read_text(encoding="utf-8") == ""
    assert tmux_tmpdir.stat().st_mode & 0o777 == 0o700


def test_markdown_blocks_do_not_share_home_state(
    pytester: pytest.Pytester,
) -> None:
    """Each Markdown block executes in a fresh documentation sandbox."""
    _install_root_conftest(pytester)
    pytester.makefile(
        ".md",
        isolated="""
        # Isolated examples

        ```python
        >>> import os
        >>> import pathlib
        >>> marker = pathlib.Path(os.environ["HOME"]) / "marker"
        >>> marker.write_text("first", encoding="utf-8")
        5
        ```

        ```python
        >>> import os
        >>> import pathlib
        >>> marker = pathlib.Path(os.environ["HOME"]) / "marker"
        >>> marker.exists()
        False
        ```
        """,
    )

    result = pytester.runpytest(
        "-q",
        "--reruns",
        "0",
        "--doctest-docutils-modules",
        "isolated.md",
    )

    result.assert_outcomes(passed=2)


def test_markdown_failure_reports_document_location(
    pytester: pytest.Pytester,
) -> None:
    """A failed prompt points authors back to the Markdown source."""
    _install_root_conftest(pytester)
    pytester.makefile(
        ".md",
        failure="""
        # Visible failure

        ```python
        >>> 2 + 2
        5
        ```
        """,
    )

    result = pytester.runpytest(
        "-q",
        "--reruns",
        "0",
        "--doctest-docutils-modules",
        "failure.md",
    )

    result.assert_outcomes(failed=1)
    result.stdout.re_match_lines([r".*failure\.md.*"])
