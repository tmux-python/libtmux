"""Guard the wiring between ``docs/howto/`` and its sidecars.

:mod:`tests.docs.howto_harness` fails loudly when a page's contract is broken,
but only for pages it is actually asked to run. These tests cover the failure
modes it cannot see from the inside: the harness being unplugged — the plugin
dropped from ``conftest.py``, the collect hook deleted, a page renamed out from
under its sidecar — and the page being unreachable, which Sphinx reports as a
warning nobody reads because the build does not run with ``-W``.
"""

from __future__ import annotations

import re
import typing as t

import pytest

from tests.docs import howto_harness

if t.TYPE_CHECKING:
    from pathlib import Path

PAGES = list(howto_harness.iter_pages())
PAGE_IDS = [page.name for page in PAGES]

#: A ``{toctree}`` block and its body, in a backtick-fenced MyST directive.
TOCTREE_RE = re.compile(
    r"^```\{toctree\}\n(?P<body>.*?)^```$",
    re.DOTALL | re.MULTILINE,
)


def test_there_are_howto_pages() -> None:
    """The how-to tree is not empty, so the checks below are not vacuous."""
    assert PAGES


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_page_contract_holds(page: Path) -> None:
    """Each page has runnable blocks and a sidecar that matches them.

    Parameters
    ----------
    page : pathlib.Path
        A how-to page.
    """
    blocks = howto_harness.parse_python_blocks(page)
    assert blocks, f"{page.name} has no backtick-fenced ```python block"

    sidecar = howto_harness._load_sidecar(page)
    checks = howto_harness.resolve_checks(sidecar, len(blocks))
    assert len(checks) == len(blocks)


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_page_anchor_matches_its_filename(page: Path) -> None:
    """Each page opens with the anchor its filename implies.

    Cross-references reach a how-to by ``{ref}`howto-<stem>```. Deriving the
    anchor from the filename means renaming a page breaks here, loudly, rather
    than leaving inbound references pointing at a target that no longer
    exists — which Sphinx reports without failing the build.

    Parameters
    ----------
    page : pathlib.Path
        A how-to page.
    """
    first = page.read_text(encoding="utf-8").lstrip().splitlines()[0]
    assert first == f"(howto-{page.stem})="


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_page_is_reachable_from_an_index(page: Path) -> None:
    """Each page is listed in the toctree of the index beside it.

    A page absent from every toctree still builds — as an orphan, behind a
    ``toc.not_included`` warning that ``just build-docs`` does not turn into
    a failure. The reader simply never finds the page.

    Parameters
    ----------
    page : pathlib.Path
        A how-to page.
    """
    index = page.parent / "index.md"
    assert index.exists(), f"{page.parent} has no index.md to list {page.name} in"

    listed = {
        entry
        for match in TOCTREE_RE.finditer(index.read_text(encoding="utf-8"))
        for line in match.group("body").splitlines()
        if (entry := line.strip()) and not entry.startswith(":")
    }
    assert page.stem in listed, (
        f"{page.name} is not in the toctree of {index.relative_to(index.parents[1])}"
    )


def test_pages_in_scope_are_collected_by_the_harness(
    request: pytest.FixtureRequest,
) -> None:
    """Every how-to page the run was pointed at produced a harness item.

    A page that is in scope but produced no
    :class:`~tests.docs.howto_harness.HowtoPageItem` is a page nothing
    executes: gp-libs' doctest collector ignores a fence without ``>>>``
    silently, so the run would stay green.

    Parameters
    ----------
    request : pytest.FixtureRequest
        Used to reach the collected session items.
    """
    session = request.session
    collected = {
        item.path
        for item in session.items
        if isinstance(item, howto_harness.HowtoPageItem)
    }
    in_scope = [page for page in PAGES if _is_in_collection_scope(page, session)]

    if not in_scope:
        pytest.skip("no how-to page is inside this run's collection roots")

    assert set(in_scope) <= collected


def _is_in_collection_scope(page: Path, session: pytest.Session) -> bool:
    """Return whether ``page`` sits under one of the run's collection roots.

    Parameters
    ----------
    page : pathlib.Path
        A how-to page.
    session : pytest.Session
        The running session.

    Returns
    -------
    bool
        True when pytest was pointed at the page or a directory above it.
    """
    for arg in session.config.args:
        root = session.config.invocation_params.dir / arg.split("::")[0]
        if page == root or root in page.parents:
            return True
    return False
