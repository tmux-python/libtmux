"""Structural contracts for the querying topic guides."""

from __future__ import annotations

import pathlib

_ROOT = pathlib.Path(__file__).parents[2]
_QUERYING = _ROOT / "docs" / "topics" / "querying"
_GUIDES = {
    "hierarchy.md",
    "query-list.md",
    "tmux-formats.md",
    "neo.md",
    "snapshot.md",
}


def test_querying_guides_cover_each_query_style() -> None:
    """The topic owns exactly one page for every supported query style."""
    pages = {path.name for path in _QUERYING.glob("*.md")}

    assert pages == _GUIDES | {"index.md"}


def test_every_query_guide_has_tutorial_failures_and_api() -> None:
    """Each query style documents its decision, success, failure, and API."""
    for name in _GUIDES:
        text = (_QUERYING / name).read_text(encoding="utf-8")
        assert "## When to use it" in text, name
        assert "## Tutorial" in text, name
        assert "### Happy path" in text, name
        assert "### Sad path" in text, name
        assert "## API reference" in text, name
        assert "## Related topics" in text, name
        assert text.count("```python") >= 2, name
        assert text.count("```{eval-rst}") == 1, name
        assert ".. auto" in text, name
        assert "doctest: +SKIP" not in text, name


def test_querying_index_is_a_decision_guide_and_navigation_root() -> None:
    """The landing helps users choose and owns all five guide pages."""
    text = (_QUERYING / "index.md").read_text(encoding="utf-8")

    for name in _GUIDES:
        assert f"]({name})" in text
        assert name.removesuffix(".md") in text
    assert "Freshness" in text
    assert "Failure signal" in text
    assert "```{toctree}" in text


def test_topics_navigation_points_to_querying_root() -> None:
    """The topics landing exposes querying as one coherent topic group."""
    text = (_ROOT / "docs" / "topics" / "index.md").read_text(encoding="utf-8")

    assert ":link: querying/index" in text
    assert "\nquerying/index\n" in text


def test_legacy_query_topic_urls_redirect_to_new_guides() -> None:
    """Existing traversal and filtering URLs remain valid after the split."""
    redirects = (_ROOT / "docs" / "redirects.txt").read_text(encoding="utf-8")

    assert (
        '"topics/traversal.md" "topics/querying/hierarchy.md"' in redirects
    )
    assert (
        '"topics/filtering.md" "topics/querying/query-list.md"' in redirects
    )
    assert not (_ROOT / "docs" / "topics" / "traversal.md").exists()
    assert not (_ROOT / "docs" / "topics" / "filtering.md").exists()
