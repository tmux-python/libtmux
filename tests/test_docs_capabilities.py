"""Tests for the ``tmux-capabilities`` Sphinx extension."""

from __future__ import annotations

import io
import typing as t

import pytest
from sphinx.application import Sphinx

from docs._ext import tmux_capabilities
from libtmux._internal.support import capabilities

if t.TYPE_CHECKING:
    import pathlib

_CONF_PY = """\
extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "docs._ext.tmux_capabilities",
]
master_doc = "index"
"""


class BuildResult(t.NamedTuple):
    """Completed synthetic Sphinx build output and captured warnings.

    Attributes
    ----------
    outdir : pathlib.Path
        Rendered builder output directory.
    warnings : str
        Captured Sphinx warning stream text.
    """

    outdir: pathlib.Path
    warnings: str


def _build_sphinx(
    tmp_path: pathlib.Path,
    index_md: str,
    *,
    buildername: str = "html",
    nitpicky: bool = False,
    manifest: dict[str, t.Any] | None = None,
    extra_files: dict[str, str] | None = None,
) -> BuildResult:
    srcdir = tmp_path / "src"
    outdir = tmp_path / "out"
    doctreedir = tmp_path / "doctrees"
    srcdir.mkdir(parents=True, exist_ok=True)

    (srcdir / "conf.py").write_text(_CONF_PY, encoding="utf-8")
    (srcdir / "index.md").write_text(index_md, encoding="utf-8")
    if extra_files:
        for rel_path, content in extra_files.items():
            target = srcdir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    overrides: dict[str, t.Any] = {}
    if nitpicky:
        overrides["nitpicky"] = True
    if manifest is not None:
        overrides["tmux_capabilities_manifest"] = manifest

    status = io.StringIO()
    warning = io.StringIO()
    app = Sphinx(
        srcdir=str(srcdir),
        confdir=str(srcdir),
        outdir=str(outdir),
        doctreedir=str(doctreedir),
        buildername=buildername,
        confoverrides=overrides,
        status=status,
        warning=warning,
        freshenv=True,
    )
    app.build()
    return BuildResult(outdir=outdir, warnings=warning.getvalue())


def test_version_ordering_and_validation() -> None:
    """Order tmux release keys as next-X.Y < X.Y-rc < X.Y-rcN < X.Y < X.Ya."""
    releases = ["3.8a", "3.8", "3.8-rc2", "3.8-rc", "next-3.8", "3.2a", "3.2"]

    assert sorted(releases, key=tmux_capabilities.tmux_version_key) == [
        "3.2",
        "3.2a",
        "next-3.8",
        "3.8-rc",
        "3.8-rc2",
        "3.8",
        "3.8a",
    ]

    for invalid in ("", "master", "03.4", "3.7a-rc1", "3.7.1"):
        with pytest.raises(ValueError, match=r"tmux release|patch letter"):
            tmux_capabilities.tmux_version_key(invalid)


def test_capability_and_workaround_states() -> None:
    """Evaluate capability intervals and release-specific workarounds."""
    cap = {
        "since": "3.4",
        "except": ["3.6"],
        "until": "3.8",
        "handling": "refuse",
    }
    assert tmux_capabilities.capability_state(cap, "3.3a") == "refused"
    assert tmux_capabilities.capability_state(cap, "3.4") == "supported"
    assert tmux_capabilities.capability_state(cap, "3.6") == "refused"
    assert tmux_capabilities.capability_state(cap, "3.7a") == "supported"
    assert tmux_capabilities.capability_state(cap, "3.8") == "refused"

    repaired = {"since": "3.6", "handling": "repair"}
    assert tmux_capabilities.capability_state(repaired, "3.5") == "repaired"

    fallback = {"since": "3.4", "handling": "fallback"}
    assert tmux_capabilities.capability_state(fallback, "3.3a") == "fallback"
    assert tmux_capabilities.capability_state(fallback, "3.4") == "supported"

    workaround = {"releases": ["3.7"], "handling": "repair"}
    assert tmux_capabilities.workaround_state(workaround, "3.6") == "supported"
    assert tmux_capabilities.workaround_state(workaround, "3.7") == "workaround"


def test_html_matrix_links_documented_sphinx_apis(
    tmp_path: pathlib.Path,
) -> None:
    """Link every capability's Python APIs and refusal error cleanly."""
    api_page = (
        "# API\n\n"
        "```{eval-rst}\n"
        ".. py:class:: libtmux.Server\n\n"
        "   .. py:method:: run_shell()\n"
        "   .. py:method:: list_keys()\n\n"
        ".. py:class:: libtmux.Pane\n\n"
        "   .. py:method:: capture_pane()\n"
        "   .. py:method:: paste_buffer()\n"
        "   .. py:method:: new_pane()\n\n"
        ".. py:exception:: libtmux.exc.LibTmuxException\n"
        ".. py:exception:: libtmux.exc.VersionTooLow\n"
        "```\n"
    )
    index_md = (
        "# Compatibility\n\n"
        "```{tmux-capabilities}\n"
        "```\n\n"
        "```{toctree}\n"
        ":hidden:\n"
        "api\n"
        "```\n"
    )

    result = _build_sphinx(
        tmp_path,
        index_md,
        nitpicky=True,
        extra_files={"api.md": api_page},
    )

    assert result.warnings == ""
    html = (result.outdir / "index.html").read_text(encoding="utf-8")

    for entry in capabilities.CAPABILITIES:
        assert f'id="cap-{entry.id}"' in html
        assert entry.name in html
        for api in entry.apis:
            short = tmux_capabilities.short_py_name(api)
            assert f"api.html#{api}" in html
            assert short in html

    assert "api.html#libtmux.exc.LibTmuxException" in html
    assert "run-shell working directory, tmux 3.3a: Warns and falls back" in html
    assert "run-shell working directory, tmux 3.4: Works" in html
    assert (
        "Floating panes, tmux 3.6: Refused with an error (exc.LibTmuxException)" in html
    )
    assert "Floating panes, tmux 3.7: Works" in html
    manifest = capabilities.manifest()
    shown = tmux_capabilities.resolve_versions(
        manifest["floor"]["minimum"], manifest["capabilities"]
    )
    for release in shown:
        assert f"<p>{release}</p>" in html


def test_default_build_warns_on_unresolved_api_target(
    tmp_path: pathlib.Path,
) -> None:
    """Warn on an undocumented API target even without nitpicky mode."""
    bad_manifest = {
        "schema": "libtmux-capabilities/1",
        "port": "py",
        "floor": {"minimum": "3.2a"},
        "capabilities": [
            {
                "id": "missing-api",
                "name": "Missing API",
                "summary": "Points at an undocumented method.",
                "since": "3.7",
                "handling": "fallback",
                "apis": ["libtmux.Pane.does_not_exist"],
                "commands": [{"command": "capture-pane", "flags": ["-T"]}],
            },
        ],
        "workarounds": [],
    }
    result = _build_sphinx(
        tmp_path,
        "# Test\n\n```{tmux-capabilities}\n```\n",
        nitpicky=False,
        manifest=bad_manifest,
    )

    assert "libtmux.Pane.does_not_exist" in result.warnings


def test_directive_options_workarounds_and_text_builder(
    tmp_path: pathlib.Path,
) -> None:
    """Filter by API, collapse release ranges, hide legend, and render text."""
    manifest = {
        "schema": "libtmux-capabilities/1",
        "port": "py",
        "floor": {"minimum": "3.2a"},
        "capabilities": [
            {
                "id": "pane-cap",
                "name": "Pane capture flag",
                "summary": "Trim trailing blank cells.",
                "since": "3.4",
                "handling": "fallback",
                "apis": ["libtmux.Pane.capture_pane"],
                "commands": [{"command": "capture-pane", "flags": ["-T"]}],
            },
            {
                "id": "server-cap",
                "name": "Server shell directory",
                "summary": "Run shell in a directory.",
                "since": "3.4",
                "handling": "fallback",
                "apis": ["libtmux.Server.run_shell"],
                "commands": [{"command": "run-shell", "flags": ["-c"]}],
            },
        ],
        "workarounds": [
            {
                "id": "pane-workaround",
                "name": "break-pane naming",
                "summary": "Repairs window name on 3.7.",
                "releases": ["3.7"],
                "handling": "repair",
                "apis": ["libtmux.Pane.break_pane"],
                "commands": [{"command": "break-pane"}],
            },
        ],
    }
    index_md = (
        "# Filtered\n\n"
        "```{tmux-capabilities}\n"
        ":api: libtmux.Pane\n"
        ":versions: 3.2a, 3.3a, 3.4, 3.7, 3.8\n"
        ":group-releases:\n"
        ":no-legend:\n"
        "```\n"
    )

    html_res = _build_sphinx(tmp_path / "html", index_md, manifest=manifest)
    html = (html_res.outdir / "index.html").read_text(encoding="utf-8")
    assert "Pane capture flag" in html
    assert "break-pane naming" in html
    assert "Server shell directory" not in html
    assert "3.2a-3.3a" in html
    assert "tmux-capabilities-legend" not in html

    text_res = _build_sphinx(
        tmp_path / "text",
        index_md,
        buildername="text",
        manifest=manifest,
    )
    rendered_text = (text_res.outdir / "index.txt").read_text(encoding="utf-8")
    assert "Pane capture flag" in rendered_text
    assert "Pane.capture_pane" in rendered_text

    bad_api_res = _build_sphinx(
        tmp_path / "bad_api",
        "# Bad\n\n```{tmux-capabilities}\n:api: libtmux.NoSuchClass\n```\n",
        manifest=manifest,
    )
    assert "matched no capability entries" in bad_api_res.warnings

    bad_ver_res = _build_sphinx(
        tmp_path / "bad_ver",
        "# Bad\n\n```{tmux-capabilities}\n:versions: invalid\n```\n",
        manifest=manifest,
    )
    assert "Not a tmux release string" in bad_ver_res.warnings
