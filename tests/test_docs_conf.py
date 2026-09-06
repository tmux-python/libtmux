"""Tests for the docs build's shell integration.

``docs/conf.py`` serves two deployment shapes. libtmux.org's assembler nests
this tree under ``/py/<version>/api/``, where the site's chrome and its
site-wide search sit at the root and root-relative paths reach them.
``.github/workflows/docs.yml`` publishes the same tree to a bucket root,
where ``/_shell/`` holds nothing and ``/search/`` is this build's own search
page — so the integration must be off there, or that host loses its search
to a page that redirects to itself.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import typing as t

import pytest

DOCS = pathlib.Path(__file__).parent.parent / "docs"
STANDALONE = "LIBTMUX_DOCS_STANDALONE"

#: Read the config the way Sphinx does — by executing it — rather than
#: importing, which would leave ``docs`` on ``sys.path`` for later tests.
#: The path must be absolute: ``conf.py`` locates the project from its own
#: ``__file__``, and a relative one puts the root at ``docs/``.
_DUMP = (
    "import json, runpy, sys;"
    "g = runpy.run_path(sys.argv[1]);"
    "print(json.dumps({k: g[k] for k in ('templates_path', 'html_js_files')}))"
)


def _conf(standalone: str | None) -> dict[str, t.Any]:
    """Return ``docs/conf.py``'s resolved values under one env setting."""
    env = os.environ.copy()
    env.pop(STANDALONE, None)
    if standalone is not None:
        env[STANDALONE] = standalone
    proc = subprocess.run(
        [sys.executable, "-c", _DUMP, str(DOCS / "conf.py")],
        cwd=DOCS,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    parsed: dict[str, t.Any] = json.loads(proc.stdout)
    return parsed


def _js_paths(conf: dict[str, t.Any]) -> list[str]:
    """Flatten ``html_js_files``, whose entries are paths or (path, attrs)."""
    entries: list[t.Any] = conf["html_js_files"]
    return [str(e[0]) if isinstance(e, list) else str(e) for e in entries]


@pytest.mark.parametrize("standalone", [None, "", "0"])
def test_shell_integration_is_on_by_default(standalone: str | None) -> None:
    """Anything but ``1`` nests the build: chrome and the search override."""
    conf = _conf(standalone)
    assert "_templates_shell" in conf["templates_path"]
    assert "/_shell/shell.js" in _js_paths(conf)


def test_standalone_keeps_sphinx_search_and_loads_no_chrome() -> None:
    """``LIBTMUX_DOCS_STANDALONE=1`` is the bucket-root deploy.

    Dropping ``_templates_shell`` restores Furo's own search page, and no
    chrome is requested from a ``/_shell/`` that is not there.
    """
    conf = _conf("1")
    assert conf["templates_path"] == ["_templates"]
    assert _js_paths(conf) == []


def test_search_override_lives_outside_the_shared_templates_dir() -> None:
    """The gate drops the override by dropping one directory.

    ``_templates`` holds templates gp_sphinx expects on every build, so the
    search override cannot live there or standalone would inherit it.
    """
    assert (DOCS / "_templates_shell" / "search.html").is_file()
    assert not (DOCS / "_templates" / "search.html").exists()


def test_search_redirect_cannot_target_itself() -> None:
    """The redirect is guarded on the page's own path.

    Served at a root the stub *is* ``/search/``, and a bare ``<meta
    refresh>`` there reloads the page for ever.
    """
    stub = (DOCS / "_templates_shell" / "search.html").read_text()
    assert "http-equiv" not in stub
    assert "window.location.pathname" in stub
    assert "if (here !== '/search/')" in stub
