"""Hold how-to pages to what they promise a reader.

A how-to guide makes two claims the harness cannot check by running code:
that the block on the page carries nothing but the reader's own code, and
that the copy button hands back exactly what is shown. Both are properties of
the *rendered* page, so both are checked here.

The cheap tests read the page source, which for this scheme is what renders —
blocks are executed where they are written, never sliced out of somewhere
else, so nothing can drift between the two. The integration test spends a
Sphinx build to confirm that, and would catch an extension that rewrote a
code block on its way to HTML.
"""

from __future__ import annotations

import html
import importlib.util
import re
import subprocess
import sys
import typing as t

import pytest

from tests.docs import howto_harness

if t.TYPE_CHECKING:
    import pathlib

PAGES = list(howto_harness.iter_pages())
PAGE_IDS = [page.name for page in PAGES]

#: Vocabulary that belongs to the test harness, never to a reader's script.
SCAFFOLDING = (
    "assert ",
    "import pytest",
    "HowtoContext",
    "retry_until",
    ">>> ",
)

#: A pygments code block in built HTML, captured with the language Sphinx
#: tagged it with.
HIGHLIGHT_RE = re.compile(
    r'<div class="highlight-(?P<language>[\w-]+) notranslate">'
    r'<div class="highlight"><pre>(?P<body>.*?)</pre>',
    re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")

#: The only two things a how-to page may render as a code block. ``python``
#: is what the harness executes; ``console`` is a command the reader runs in
#: a shell, which nothing can execute for them. Every other spelling is a
#: mistake rather than a choice: ```py`` renders as ``highlight-py`` and a
#: bare ``` renders as ``highlight-default``, both of which publish
#: copy-pasteable Python that no test ever runs.
RENDERABLE_LANGUAGES = frozenset({"python", "console"})


def _docs_config(name: str) -> t.Any:
    """Return one value from the documentation build's configuration.

    Parameters
    ----------
    name : str
        Configuration variable to read.

    Returns
    -------
    object
        Its value in ``docs/conf.py``.
    """
    spec = importlib.util.spec_from_file_location(
        "_libtmux_docs_conf_render",
        howto_harness.DOCS_CONF,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, name)


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_visible_blocks_carry_no_scaffolding(page: pathlib.Path) -> None:
    """Nothing a reader copies is an assertion or a test-suite import.

    Parameters
    ----------
    page : pathlib.Path
        A how-to page.
    """
    for block in howto_harness.parse_python_blocks(page):
        for offset, line in enumerate(block.source.splitlines()):
            found = [token for token in SCAFFOLDING if token in line]
            assert not found, (
                f"{page.name}:{block.first_line + offset} renders {found[0]!r} "
                f"to the reader: {line!r}. Hidden checks belong in "
                f"{howto_harness.sidecar_name(page)}."
            )


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_visible_blocks_copy_verbatim(page: pathlib.Path) -> None:
    """No rendered line trips sphinx-copybutton's prompt detection.

    The prompt pattern includes ``# `` and ``> ``, and copybutton strips
    prompts and copies only prompted lines. A block whose first line is a
    column-zero comment therefore copies as *only its comments* — the code
    the page is about never reaches the reader's clipboard.

    Parameters
    ----------
    page : pathlib.Path
        A how-to page.
    """
    prompt = re.compile(_docs_config("copybutton_prompt_text"))
    for block in howto_harness.parse_python_blocks(page):
        for offset, line in enumerate(block.source.splitlines()):
            assert not prompt.match(line), (
                f"{page.name}:{block.first_line + offset} renders {line!r}, "
                f"which the copy button reads as a shell prompt. Indent the "
                f"comment, or move the remark into the prose."
            )


@pytest.mark.integration
def test_rendered_blocks_match_the_page_source(tmp_path: pathlib.Path) -> None:
    """Sphinx renders each page's blocks exactly as they are written.

    Only the how-to pages are written out. Sphinx still reads every source
    into its environment, so these pages render exactly as they would in a
    full build, and skipping the rest of the site keeps this affordable
    enough to stay in the ordinary test run rather than a lane of its own.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Build destination, so the checked-in build is left alone.
    """
    source = howto_harness.REPO_ROOT / "docs"
    out = tmp_path / "html"
    # Redirects resolve against pages this build deliberately skips, and
    # rediraffe fails a build whose redirect targets are absent.
    no_redirects = tmp_path / "redirects.txt"
    no_redirects.touch()
    built = subprocess.run(
        [
            sys.executable,
            "-m",
            "sphinx",
            "-b",
            "dirhtml",
            "-q",
            "-D",
            f"rediraffe_redirects={no_redirects}",
            "-d",
            str(tmp_path / "doctrees"),
            str(source),
            str(out),
            *(str(page) for page in PAGES),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=source,
    )
    assert built.returncode == 0, f"sphinx-build failed:\n{built.stderr}"

    for page in PAGES:
        docname = page.relative_to(source).with_suffix("")
        blocks = _code_blocks(out / docname / "index.html")

        stray = sorted({lang for lang, _ in blocks} - RENDERABLE_LANGUAGES)
        assert not stray, (
            f"{page.name} renders a {stray[0]!r} code block. A how-to page "
            f"may only render ```python, which the harness runs, and "
            f"```console, which the reader runs. Anything else publishes "
            f"code that nothing tests."
        )

        rendered = [body for lang, body in blocks if lang == "python"]
        expected = [
            block.source.rstrip("\n")
            for block in howto_harness.parse_python_blocks(page)
        ]
        assert rendered == expected, (
            f"{page.name}'s rendered python blocks are not the ones the "
            f"harness ran; something between the markdown and the HTML "
            f"rewrote a block."
        )


def _code_blocks(built: pathlib.Path) -> list[tuple[str, str]]:
    """Return every code block in a built page, with its language.

    Parameters
    ----------
    built : pathlib.Path
        Path to a rendered HTML page.

    Returns
    -------
    list of tuple
        ``(language, body)`` in page order, tags stripped and entities
        decoded.
    """
    markup = built.read_text(encoding="utf-8")
    return [
        (
            match.group("language"),
            html.unescape(TAG_RE.sub("", match.group("body"))).rstrip("\n"),
        )
        for match in HIGHLIGHT_RE.finditer(markup)
    ]
